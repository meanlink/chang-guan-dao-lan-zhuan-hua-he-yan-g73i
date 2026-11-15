import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j, dataset=None):
    d = {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
    d['dataset_name'] = dataset.name if dataset else None
    return d
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def version_dict(v):
    return {k:getattr(v,k) for k in ['id','version_no','dataset_id','snapshot','rows','checksum','created_at']}
def run_dict(r):
    return {k:getattr(r,k) for k in ['id','source_id','status','snapshot','fetched_pages','fetched_rows','total','retries','restarts','error','dataset_id','created_at','updated_at','finished_at']}
def source_dict(s, version=None, run=None):
    return {'id':s.id, 'name':s.name, 'base_url':s.base_url, 'page_size':s.page_size,
            'current_dataset_id':s.current_dataset_id, 'created_at':s.created_at,
            'current_version':version_dict(version) if version else None,
            'active_run':run_dict(run) if run else None}
