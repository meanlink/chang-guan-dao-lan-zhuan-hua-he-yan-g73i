import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, SyncRun
from src.services.business import analyze
from src.services.reports import deliver
from src.services.sync import execute_sync
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def sync_tick():
    # SQL 兜底与停机恢复：承接 Redis 不可用时的排队运行，以及中断后从已确认游标继续的运行
    with Session() as db:
        due=list(db.scalars(select(SyncRun.id).where(SyncRun.status.in_(('queued','running')),SyncRun.updated_at<=time.time()-1).limit(3)))
    for run_id in due:
        try:execute_sync(run_id)
        except Exception:logging.exception('Sync run %s failed unexpectedly; will retry',run_id)
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    # 数据库可能尚未就绪（迁移未完成）：恢复扫描重试直至成功，随后进入主循环
    while True:
        try:
            with Session() as db:
                for j in db.scalars(select(Job).where(Job.status=='running')):
                    j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
                for run in db.scalars(select(SyncRun).where(SyncRun.status.in_(('queued','running')))):
                    record(db,'worker','sync.resume',{'run':run.id,'page':run.fetched_pages})
                db.commit()
            break
        except Exception:
            logging.exception('Worker recovery scan failed; retrying');time.sleep(3)
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop(['analysis:queue','sync:queue'],timeout=1)
            if item:
                queue,key=item[0].decode(),int(item[1])
                if queue=='sync:queue':execute_sync(key)
                else:execute(key)
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
        try:
            tick();sync_tick()
        except Exception:
            logging.exception('Tick failed');time.sleep(2)
if __name__=='__main__':main()
