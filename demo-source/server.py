#!/usr/bin/env python3
"""独立演示客流源：分页快照协议 + 故障演练。

协议：
  GET /records?limit=N                        开启新快照并返回第一页
  GET /records?limit=N&snapshot=S&cursor=C    返回同一快照内的后续页
  响应 {snapshot, records, next_cursor, total}；游标失效/未知返回 410 {detail: cursor_expired}

语义：快照在开启时冻结；翻页期间对“线上数据”的新增、更正、撤除只影响下一次快照。
演练（POST /control，JSON 体）：
  mutate_per_page   每翻一页对线上数据做的变异次数（新增/更正/撤除，默认 1）
  drop_rate         直接断开连接的概率（0–1，模拟断连，默认 0）
  snapshot_ttl      快照有效期秒数，过期后游标失效（默认 120）
  page_delay        每页响应前的人工延迟秒数（模拟慢速来源，默认 0）
  corrupt_next      为 true 时下一个快照混入非法记录（演示整份校验失败）
  reset             为 true 时重置线上数据与全部快照
查询：GET /control/state 返回当前模式、线上行数与各快照校验和。
运行：python server.py（环境变量 PORT、DEMO_DAYS、DEMO_SEED、MUTATE_PER_PAGE、DROP_RATE、SNAPSHOT_TTL、PAGE_DELAY）
"""
import copy
import hashlib
import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.getenv('PORT', '8100'))
DAYS = int(os.getenv('DEMO_DAYS', '26'))
SEED = int(os.getenv('DEMO_SEED', '2026'))
ZONES = [('星空厅', .42, .10), ('水世界', .63, .025), ('机械坊', .31, -.015)]

def gen_records():
    rng = random.Random(SEED)
    rows = []
    for zone, base, uplift in ZONES:
        for day in range(DAYS):
            for arm in ('A', 'B'):
                visitors = rng.randint(55, 100)
                p = base + (uplift if arm == 'B' else 0)
                completed = sum(rng.random() < p for _ in range(visitors))
                rows.append({'record': f'{zone}-{day + 1:02}-{arm}', 'zone': zone, 'arm': arm,
                             'visitors': visitors, 'completed': completed})
    return rows

def digest(rows):
    # 与后端整份校验后的指纹口径一致：数值列统一转为 float 再计算 SHA256
    norm = []
    for r in rows:
        row = dict(r)
        for k in ('visitors', 'completed'):
            try:
                row[k] = float(row[k])
            except (TypeError, ValueError):
                pass
        norm.append(row)
    return hashlib.sha256(json.dumps(norm, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

state = {
    'live': gen_records(),
    'snapshots': {},   # id -> {records, expires, checksum}
    'seq': 0,
    'day_seq': 0,
    'served_pages': 0,
    'mode': {
        'mutate_per_page': int(os.getenv('MUTATE_PER_PAGE', '1')),
        'drop_rate': float(os.getenv('DROP_RATE', '0')),
        'snapshot_ttl': float(os.getenv('SNAPSHOT_TTL', '120')),
        'page_delay': float(os.getenv('PAGE_DELAY', '0')),
        'corrupt_next': False,
    },
    'rng': random.Random(SEED + 7),
    'lock': threading.Lock(),
}

def mutate_live(n):
    with state['lock']:
        rng, live = state['rng'], state['live']
        for _ in range(n):
            kind = rng.choice(['add', 'correct', 'remove'])
            if kind == 'add':
                state['day_seq'] += 1
                zone, _, _ = rng.choice(ZONES)
                arm = rng.choice(['A', 'B'])
                v = rng.randint(55, 100)
                live.append({'record': f"{zone}-N{state['day_seq']:03}-{arm}", 'zone': zone, 'arm': arm,
                             'visitors': v, 'completed': rng.randint(0, v)})
            elif kind == 'correct' and live:
                row = rng.choice(live)
                row['visitors'] = max(1, int(row['visitors']) + rng.randint(-8, 8))
                row['completed'] = min(int(row['completed']), row['visitors'])
            elif kind == 'remove' and len(live) > 120:
                live.pop(rng.randrange(len(live)))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[demo-source] {self.address_string()} {fmt % args}', flush=True)

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health':
            return self._send(200, {'status': 'healthy'})
        if path == '/records':
            return self.records(parse_qs(urlparse(self.path).query))
        if path == '/control/state':
            with state['lock']:
                return self._send(200, {'mode': state['mode'], 'live_rows': len(state['live']),
                                        'served_pages': state['served_pages'],
                                        'snapshots': {k: {'rows': len(v['records']), 'checksum': v['checksum'],
                                                          'expires_in': round(v['expires'] - time.time(), 1)}
                                                      for k, v in state['snapshots'].items()}})
        return self._send(404, {'detail': 'not_found'})

    def do_POST(self):
        if urlparse(self.path).path != '/control':
            return self._send(404, {'detail': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {'detail': 'bad_json'})
        with state['lock']:
            if body.get('reset'):
                state['live'] = gen_records()
                state['snapshots'] = {}
                state['seq'] = 0
            for key in ('mutate_per_page', 'drop_rate', 'snapshot_ttl', 'page_delay'):
                if key in body:
                    state['mode'][key] = body[key]
            if 'corrupt_next' in body:
                state['mode']['corrupt_next'] = bool(body['corrupt_next'])
            mode = dict(state['mode'])
        return self._send(200, {'mode': mode})

    def records(self, q):
        mode = state['mode']
        # 断连演练：不写任何字节直接关闭连接
        if state['rng'].random() < float(mode.get('drop_rate') or 0):
            self.close_connection = True
            return
        delay = float(mode.get('page_delay') or 0)
        if delay:
            time.sleep(delay)  # 慢速来源演练：配合短快照 TTL 触发游标过期
        try:
            limit = max(1, min(int(q.get('limit', ['100'])[0]), 500))
        except ValueError:
            limit = 100
        snap = q.get('snapshot', [''])[0]
        cursor = q.get('cursor', [''])[0]
        with state['lock']:
            if not snap:
                state['seq'] += 1
                snap = f"snap-{state['seq']:04d}"
                frozen = copy.deepcopy(state['live'])
                if state['mode'].get('corrupt_next'):
                    state['mode']['corrupt_next'] = False
                    frozen[len(frozen) // 2]['visitors'] = 'NaN'  # 注入非法记录，演示整份校验失败
                ttl = state['mode'].get('snapshot_ttl')
                state['snapshots'][snap] = {'records': frozen, 'checksum': digest(frozen),
                                            'expires': time.time() + (float(ttl) if ttl is not None else 120)}
                offset = 0
            else:
                entry = state['snapshots'].get(snap)
                if not entry or time.time() > entry['expires'] or not cursor.startswith(snap + ':'):
                    return self._send(410, {'detail': 'cursor_expired'})
                try:
                    offset = int(cursor.split(':', 1)[1])
                except (IndexError, ValueError):
                    return self._send(410, {'detail': 'cursor_expired'})
            entry = state['snapshots'][snap]
            rows = entry['records']
            page = rows[offset:offset + limit]
            nxt = offset + limit
            payload = {'snapshot': snap, 'records': page,
                       'next_cursor': f'{snap}:{nxt}' if nxt < len(rows) else None,
                       'total': len(rows)}
            state['served_pages'] += 1
            mutations = int(mode.get('mutate_per_page') or 0)
        if mutations:
            mutate_live(mutations)  # 翻页期间改数：只影响下一次快照
        self._send(200, payload)

if __name__ == '__main__':
    print(f'[demo-source] listening on :{PORT}, days={DAYS}, seed={SEED}, mode={state["mode"]}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
