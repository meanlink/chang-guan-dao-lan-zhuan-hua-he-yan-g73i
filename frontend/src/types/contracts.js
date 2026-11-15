/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,origin:'manual'|'remote',version_no:number|null}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,dataset_name:string|null,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,version_no:number,dataset_id:number,snapshot:string,rows:number,checksum:string,created_at:number}} SourceVersion */
/** @typedef {{id:number,source_id:number,status:'queued'|'running'|'completed'|'failed',snapshot:string,fetched_pages:number,fetched_rows:number,total:number,retries:number,restarts:number,error:string,dataset_id:number|null,created_at:number,updated_at:number,finished_at:number|null}} SyncRun */
/** @typedef {{id:number,name:string,base_url:string,page_size:number,current_dataset_id:number|null,current_version:SourceVersion|null,active_run:SyncRun|null}} RemoteSource */
export {};
