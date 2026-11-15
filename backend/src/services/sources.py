import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import RemoteSource, SourceVersion, SyncRun
def register(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '来源名称去除空格后至少需要两个字符')
    if db.scalar(select(RemoteSource).where(RemoteSource.name==name)):
        raise HTTPException(409, '该来源名称已登记，请更换名称')
    s=RemoteSource(name=name, base_url=data.base_url, token=data.token.strip(), page_size=data.page_size, created_at=time.time())
    db.add(s); db.flush()
    return s
def active_run(db, source_id):
    return db.scalar(select(SyncRun).where(SyncRun.source_id==source_id, SyncRun.status.in_(('queued','running'))))
def start_sync(db, source):
    # 幂等：已有进行中的运行（含并发请求撞上唯一索引）时复用，不重复建批次
    run=active_run(db, source.id)
    if run: return run, False
    now=time.time()
    run=SyncRun(source_id=source.id, status='queued', created_at=now, updated_at=now)
    try:
        with db.begin_nested():
            db.add(run); db.flush()
        return run, True
    except IntegrityError:
        return active_run(db, source.id), False
def enqueue_sync(run_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('sync:queue',run_id); r.close()
    except Exception:
        pass # SQL 中的 queued 状态是持久兜底，worker 周期扫描会接手
def version_map(db, dataset_ids):
    if not dataset_ids: return {}
    return {v.dataset_id:v for v in db.scalars(select(SourceVersion).where(SourceVersion.dataset_id.in_(dataset_ids)))}
def current_version(db, source):
    if not source.current_dataset_id: return None
    return db.scalar(select(SourceVersion).where(SourceVersion.dataset_id==source.current_dataset_id))
