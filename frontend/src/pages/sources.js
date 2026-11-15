import {sources} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {SyncStatus} from '../constants/enums.js';
const runLine=r=>'<div class="run-progress"><div class="section-title"><h2>同步进度</h2><span>'+esc(SyncStatus[r.status]||r.status)+'</span></div><div class="kv"><span>已确认页数</span><strong>'+r.fetched_pages+'</strong><span>已暂存记录</span><strong>'+r.fetched_rows+(r.total?' / '+r.total:'')+' 条</strong><span>来源快照</span><strong>'+esc(r.snapshot||'待建立')+'</strong><span>断线重试</span><strong>'+r.retries+' 次</strong><span>游标重取</span><strong>'+r.restarts+' 次</strong></div>'+(r.error?'<p class="warning">'+esc(r.error)+'</p>':'')+'</div>';
const versionLine=v=>v?'<div class="kv"><span>当前版本</span><strong>v'+v.version_no+' · 批次 #'+v.dataset_id+'</strong><span>记录数</span><strong>'+v.rows+' 条</strong><span>切换时间</span><strong>'+date(v.created_at)+'</strong><span>内容指纹</span><strong>SHA256 '+esc(v.checksum.slice(0,18))+'…</strong></div>':'<p class="hint">尚未完成首次同步，来源暂无本地版本。</p>';
export async function sourcesPage(){
 const list=await sources.list();workspace.sources=list;
 let detail=null;
 if(list.length){const id=workspace.selectedSource&&list.some(s=>s.id===workspace.selectedSource)?workspace.selectedSource:list[0].id;workspace.selectedSource=id;detail=await sources.get(id);}
 const canWrite=session.user.role!=='viewer';
 const item=s=>{const v=s.current_version,r=s.active_run;return '<button class="batch-item" data-source="'+s.id+'"><strong>'+esc(s.name)+'</strong><span>'+esc(s.base_url)+' · 每页 '+s.page_size+' 条</span><span>'+(v?'当前 v'+v.version_no+' · '+v.rows+' 条 · '+date(v.created_at):'尚未同步')+'</span>'+(r?'<small>'+esc(SyncStatus[r.status]||r.status)+' · 已确认 '+r.fetched_pages+' 页 / '+r.fetched_rows+' 条</small>':'')+'</button>';};
 const runs=detail?detail.runs.map(r=>'<tr><td>#'+r.id+'</td><td>'+esc(SyncStatus[r.status]||r.status)+'</td><td>'+r.fetched_pages+' 页 / '+r.fetched_rows+' 条</td><td>'+r.restarts+'</td><td>'+(r.dataset_id?'批次 #'+r.dataset_id:'—')+'</td><td>'+date(r.created_at)+'</td><td class="error-cell">'+esc(r.error||'')+'</td></tr>').join(''):'';
 const versions=detail?detail.versions.map(v=>'<div class="delivery"><div><strong>v'+v.version_no+' · 批次 #'+v.dataset_id+'</strong><p>'+v.rows+' 条 · '+date(v.created_at)+' · 快照 '+esc(v.snapshot)+'</p><small>SHA256 '+esc(v.checksum.slice(0,24))+'…</small></div></div>').join(''):'';
 return heading('03 / REMOTE SOURCES','远端客流源与分页同步','登记远端客流源后按快照分页同步为分析批次。一次同步固定一个来源快照；整份校验通过后一次性切换本地版本，失败沿用旧版。')
 +'<div class="source-grid"><section class="panel"><div class="section-title"><h2>已登记来源</h2><span>'+list.length+' 个</span></div><div class="batch-list">'
 +(list.map(item).join('')||'<p class="hint">尚未登记来源。</p>')
 +'</div><div class="section-title"><h2>登记新来源</h2></div><form id="source-form"><label>来源名称<input name="name" required minlength="2" placeholder="例如：闸机客流服务"></label><label>服务地址<input name="base_url" required placeholder="http://demo-source:8100"></label><label>访问令牌（可选）<input name="token" placeholder="留空则不发送"></label><label>分页大小<input name="page_size" type="number" min="1" max="500" value="100"></label><button type="submit" class="primary" '+(canWrite?'':'disabled')+'>登记来源</button><p class="hint">来源需实现分页快照协议：GET /records?limit=N[&snapshot=S&cursor=C]，游标失效返回 410。</p></form></section>'
 +(detail?'<section class="panel"><div class="section-title"><h2>'+esc(detail.name)+'</h2><button class="button small" id="sync-now" data-source="'+detail.id+'" '+(canWrite&&!detail.active_run?'':'disabled')+'>立即同步 ↗</button></div>'
 +versionLine(detail.current_version)
 +(detail.active_run?runLine(detail.active_run):(detail.runs.length&&detail.runs[0].status==='failed'?'<p class="warning">最近同步失败：'+esc(detail.runs[0].error)+'。本地仍沿用当前版本。</p>':''))
 +'<div class="section-title"><h2>同步记录</h2><span>最近 '+detail.runs.length+' 次</span></div>'+(runs?'<div class="table-wrap"><table><thead><tr><th>运行</th><th>状态</th><th>进度</th><th>重取</th><th>产出</th><th>发起时间</th><th>失败原因</th></tr></thead><tbody>'+runs+'</tbody></table></div>':'<p class="hint">尚无同步记录。</p>')
 +'<div class="section-title"><h2>本地版本</h2><span>最近 '+detail.versions.length+' 版</span></div>'+(versions||'<p class="hint">尚无版本。</p>')
 +'</section>':'<section class="panel"><p class="empty">登记一个远端客流源后，在此查看同步进度与版本。</p></section>')
 +'</div>';
}
export function bindSources(refresh){
 clearTimeout(workspace.sourceTimer);
 if(workspace.sources?.some(s=>s.active_run)) workspace.sourceTimer=setTimeout(()=>{if(location.hash.startsWith('#/sources'))refresh();},1500);
 document.querySelectorAll('[data-source].batch-item').forEach(b=>b.onclick=()=>{workspace.selectedSource=Number(b.dataset.source);refresh();});
 document.querySelector('#sync-now')?.addEventListener('click',async e=>{try{await sources.sync(e.target.dataset.source);notify('同步已发起，页面将自动刷新进度');await refresh();}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#source-form'),async f=>{await sources.create({name:f.get('name'),base_url:f.get('base_url'),token:f.get('token')||'',page_size:Number(f.get('page_size'))||100});notify('来源已登记，可发起首次同步');await refresh();});
}
