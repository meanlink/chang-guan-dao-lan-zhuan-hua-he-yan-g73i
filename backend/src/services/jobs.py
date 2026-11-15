import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, RemoteSource
from src.services.business import metadata
def create(db, data, user):
    if data.source_id:
        # 远端来源：在入队这一刻读取当前版本指针并固定到任务，之后的版本切换不影响本任务
        source=db.get(RemoteSource,data.source_id)
        if not source: raise HTTPException(404,'远端来源不存在')
        if not source.current_dataset_id: raise HTTPException(409,'该来源尚未完成首次同步，暂无可用版本')
        dataset_id=source.current_dataset_id
    elif data.dataset_id:
        dataset_id=data.dataset_id
    else:
        raise HTTPException(422,'需要指定数据批次或远端来源')
    if not db.get(Dataset,dataset_id): raise HTTPException(404,'数据批次不存在')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=dataset_id, params=params, created_by=user.id, created_at=time.time(), status='queued')
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
