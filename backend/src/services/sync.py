"""远端客流源分页同步：固定快照翻页、断点续传、整份校验后一次性切换版本。

协议（来源侧）：
  GET {base_url}/records?limit=N                       → 开启新快照并返回第一页
  GET {base_url}/records?limit=N&snapshot=S&cursor=C   → 同一快照内的后续页
  响应 {snapshot, records, next_cursor, total}；游标失效返回 410。
本模块保证：一次运行只消费一个快照；游标失效即作废暂存重新取整份，绝不拼接两次快照。
"""
import json, time, logging, http.client, urllib.request, urllib.error, urllib.parse
from sqlalchemy import select, func
from src.config.database import Session
from src.models import RemoteSource, SourceVersion, SyncRun, Dataset
from src.services.datasets import validate_records
from src.services.audit import record
from src.utils.serialization import checksum

class CursorExpired(Exception): pass
class SourceUnavailable(Exception): pass

MAX_RESTARTS = 5          # 一次运行允许的快照重取次数上限
MAX_ROWS = 5000           # 与整份校验口径一致，提前截断失控来源
ATTEMPTS_PER_CALL = 25    # 单次执行最多翻页/重试次数，超出后交还调度器稍后继续

def fetch_page(source, snapshot, cursor):
    query = 'limit=%d' % source.page_size
    if snapshot:
        query += '&snapshot=%s&cursor=%s' % (urllib.parse.quote(snapshot), urllib.parse.quote(cursor))
    req = urllib.request.Request(source.base_url + '/records?' + query)
    if source.token:
        req.add_header('Authorization', 'Bearer ' + source.token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 410: raise CursorExpired()
        if e.code >= 500: raise SourceUnavailable(f'来源返回 HTTP {e.code}')
        raise ValueError(f'来源拒绝请求（HTTP {e.code}），请检查地址与令牌')
    except (urllib.error.URLError, http.client.HTTPException, OSError, json.JSONDecodeError) as e:
        raise SourceUnavailable(str(e)[:200])
    if not isinstance(payload, dict) or not isinstance(payload.get('records'), list) \
            or not isinstance(payload.get('snapshot'), str) or 'next_cursor' not in payload:
        raise ValueError('来源响应格式不符：需要 snapshot/records/next_cursor 字段')
    if payload['next_cursor'] is not None and not isinstance(payload['next_cursor'], str):
        raise ValueError('来源响应格式不符：next_cursor 须为字符串或 null')
    return payload

def fail(db, run, source, message):
    # 失败只标记运行，不触碰来源当前版本指针——本地沿用旧版
    run.status = 'failed'; run.error = message[:990]
    run.finished_at = run.updated_at = time.time()
    record(db, 'worker', 'sync.failed', {'run': run.id, 'source': source.id, 'error': run.error})

def finalize(db, run, source):
    rows = run.staged_records or []
    try:
        validate_records(rows)
    except ValueError as e:
        fail(db, run, source, f'整份校验未通过：{e}')
        return
    now = time.time()
    version_no = (db.scalar(select(func.max(SourceVersion.version_no)).where(SourceVersion.source_id == source.id)) or 0) + 1
    name = f'{source.name} · 同步批次 v{version_no}'
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        name = f'{name} · {int(now)}'
    d = Dataset(name=name, source=f'{source.name}（远端同步）', records=rows, checksum=checksum(rows), created_at=now)
    db.add(d); db.flush()
    db.add(SourceVersion(source_id=source.id, version_no=version_no, dataset_id=d.id,
                         snapshot=run.snapshot, rows=len(rows), checksum=d.checksum, created_at=now))
    source.current_dataset_id = d.id   # 与新版本、新批次同事务提交：一次性切换，失败整体回滚
    run.status = 'completed'; run.dataset_id = d.id; run.error = ''; run.finished_at = run.updated_at = now
    record(db, 'worker', 'sync.completed', {'run': run.id, 'source': source.id, 'version': version_no, 'rows': len(rows)})

def execute_sync(run_id, max_attempts=ATTEMPTS_PER_CALL):
    # 单 worker 顺序执行；每次翻页确认后立即落库，停机后从已确认游标继续
    attempts = 0
    while attempts < max_attempts:
        with Session() as db:
            run = db.get(SyncRun, run_id)
            if not run or run.status not in ('queued', 'running'): return
            source = db.get(RemoteSource, run.source_id)
            if not source:
                run.status = 'failed'; run.error = '来源已被删除'; run.finished_at = run.updated_at = time.time()
                db.commit(); return
            if run.snapshot and not run.cursor and run.fetched_rows and run.fetched_rows == run.total:
                # 上次在最后一页落库后、定版前中断：整份已在暂存中，直接校验切换
                finalize(db, run, source)
                db.commit(); return
            try:
                page = fetch_page(source, run.snapshot or None, run.cursor or None)
            except CursorExpired:
                # 游标失效：作废本次暂存，从空白游标重新取整份新快照
                run.staged_records = []; run.snapshot = ''; run.cursor = ''
                run.fetched_pages = run.fetched_rows = run.total = 0
                run.restarts += 1
                if run.restarts > MAX_RESTARTS:
                    fail(db, run, source, '来源游标反复失效，已放弃本次同步，请稍后重试')
                else:
                    run.error = '来源游标已失效：已作废本次暂存，重新取整份'
                    run.updated_at = time.time()
                    record(db, 'worker', 'sync.restart', {'run': run.id, 'source': source.id, 'restarts': run.restarts})
                db.commit(); attempts += 1; continue
            except SourceUnavailable as e:
                run.retries += 1
                run.error = f'连接中断，等待重试（第 {run.retries} 次）：{e}'[:990]
                run.updated_at = time.time()
                db.commit()
                time.sleep(min(0.4 * run.retries, 2.0)); attempts += 1; continue
            except ValueError as e:
                fail(db, run, source, str(e)); db.commit(); return
            if run.status == 'queued': run.status = 'running'
            if run.snapshot and page['snapshot'] != run.snapshot:
                fail(db, run, source, '来源在翻页期间返回了不同快照，已拒绝拼接两次快照')
                db.commit(); return
            run.snapshot = page['snapshot']
            run.staged_records = (run.staged_records or []) + page['records']
            run.cursor = page['next_cursor'] or ''
            run.fetched_pages += 1
            run.fetched_rows = len(run.staged_records)
            run.total = int(page.get('total') or 0)
            run.error = ''
            run.updated_at = time.time()
            if run.fetched_rows > MAX_ROWS:
                fail(db, run, source, f'来源记录数超过单批上限 {MAX_ROWS} 条')
                db.commit(); return
            db.commit()
            if not page['next_cursor']:
                finalize(db, run, source)
                db.commit(); return
            attempts += 1
