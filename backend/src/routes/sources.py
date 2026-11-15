from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from src.config.database import get_db
from src.models import RemoteSource, SourceVersion, SyncRun
from src.schemas.source import SourceInput
from src.middlewares.auth import current_user, can_write
from src.services import sources
from src.services.audit import record
from src.utils.serialization import source_dict, version_dict, run_dict
router=APIRouter(prefix='/sources')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    result=[]
    for s in db.scalars(select(RemoteSource).order_by(RemoteSource.id)):
        result.append(source_dict(s, sources.current_version(db,s), sources.active_run(db,s.id)))
    return result
@router.post('',status_code=201)
def register(data:SourceInput,db=Depends(get_db),u=Depends(can_write)):
    s=sources.register(db,data); record(db,u.email,'source.register',{'id':s.id,'base_url':s.base_url})
    db.commit(); return source_dict(s)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    s=db.get(RemoteSource,id)
    if not s: raise HTTPException(404,'远端来源不存在')
    runs=db.scalars(select(SyncRun).where(SyncRun.source_id==id).order_by(SyncRun.id.desc()).limit(10))
    versions=db.scalars(select(SourceVersion).where(SourceVersion.source_id==id).order_by(SourceVersion.version_no.desc()).limit(10))
    return {**source_dict(s, sources.current_version(db,s), sources.active_run(db,s.id)),
            'runs':[run_dict(r) for r in runs], 'versions':[version_dict(v) for v in versions]}
@router.post('/{id}/sync',status_code=201)
def sync(id:int,response:Response,db=Depends(get_db),u=Depends(can_write)):
    s=db.get(RemoteSource,id)
    if not s: raise HTTPException(404,'远端来源不存在')
    run,created=sources.start_sync(db,s)
    if created: record(db,u.email,'sync.start',{'run':run.id,'source':s.id})
    db.commit()
    if created: sources.enqueue_sync(run.id)
    if not created: response.status_code=200  # 并发或重试：返回进行中的同一运行
    return run_dict(run)
