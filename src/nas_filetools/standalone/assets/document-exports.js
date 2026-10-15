'use strict';
function exportFailureMessage(task){
 const error=task.error||{},message=error.message||'';
 if(message.startsWith('FONT_MISSING_GLYPHS:')){
  const detail=message.slice('FONT_MISSING_GLYPHS:'.length).trim();
  if(detail.includes('字体缺少'))return detail;
  const characters=[...new Set([...detail].filter(c=>!c.trim()?false:true))].map(c=>'“'+c+'”(U+'+c.codePointAt(0).toString(16).toUpperCase().padStart(4,'0')+')').join('、');
  return '当时模板字体“'+(task.template_data?.font?.name||task.template_data?.parameters?.font_family||'未记录')+'”缺少 '+characters+'。本次更新已提供可追溯补充字体，请保留文字版本重新导出。调整分页或允许续页不能解决字体缺字。';
 }
 return message.replace(/SOURCE_PAGE_OVERFLOW:\s*/g, '')||error.code||'导出失败，请查看技术详情。';
}
function openDocumentExport(aid){
 if(aid){if(![...$('#formatSource').options].some(o=>o.value===aid)){message('所选文字版本不可用，请重新选择。');return;}$('#formatSource').value=aid;}
 $('#exportError').textContent='';$('#exportDialog').showModal();refreshCleaningSummary();
}
function updateFormatSources(p){
 const drafts=[...p.artifacts].reverse().filter(a=>a.format==='markdown'&&!a.recycled);
 const selected=$('#formatSource').value,fingerprint=JSON.stringify(drafts.map(a=>[a.artifact_id,a.display_name]));
 if($('#formatSource').dataset.finger===fingerprint)return;
 $('#formatSource').dataset.finger=fingerprint;$('#formatSource').replaceChildren();
 $('#formatExisting').disabled=!drafts.length;$('#openDocumentExport').disabled=!drafts.length;
 for(const a of drafts){const o=el('option',(a.display_name||a.name)+' · 第'+a.version+'版'+(a.text_revision?' · 人工修订':''));o.value=a.artifact_id;$('#formatSource').append(o);}
 if(!drafts.length){const o=el('option','暂无文字稿，请先提取文字');o.value='';$('#formatSource').append(o);}
 if(drafts.some(a=>a.artifact_id===selected))$('#formatSource').value=selected;
}
function drawArtifacts(p){
 const fingerprint=JSON.stringify([p.artifacts,p.tasks]);if($('#artifacts').dataset.finger===fingerprint)return;
 $('#artifacts').dataset.finger=fingerprint;const open=new Set([...document.querySelectorAll('#artifacts details[open]')].map(d=>d.id));$('#artifacts').replaceChildren();
 const groups=[['original','原件'],['text','文字版本'],['exports','导出文件'],['recycled','回收站']];
 const areas={};for(const [id,title] of groups){const section=el(id==='recycled'?'details':'section',undefined,'artifact-group');section.id='files-'+id;if(id==='recycled'){section.open=open.has(section.id);section.append(el('summary',title));}else section.append(el('h3',title));const body=el('div');section.append(body);areas[id]=body;$('#artifacts').append(section);}
 for(const a of [...p.artifacts].reverse()){
  if(a.role==='diagnostic'||!['markdown','pdf','docx','image','reference'].includes(a.format))continue;
  const original=a.artifact_id===p.source_artifact_id,isExport=!original&&['pdf','docx'].includes(a.format),group=a.recycled?'recycled':original?'original':isExport?'exports':'text';
  const row=el('div',undefined,'artifact-row');row.dataset.artifactId=a.artifact_id;
  const meta=el('div');meta.append(el('strong',a.display_name||a.name),el('span',a.format.toUpperCase(),'format-tag'));
  const origin=a.export_source,source=origin&&p.artifacts.find(x=>x.artifact_id===origin.artifact_id);
  meta.append(el('p',isExport?(source?'来自 '+(source.display_name||source.name)+' · 第'+origin.version+'版 · ':'')+((p.template_names||{})[a.template_label]||a.template_label||'历史导出'):artifactMeta(a),'muted'));
  const actions=el('div',undefined,'task-actions');
  if(a.recycled)actions.append(button('恢复',()=>api(`/api/projects/${pid}/artifacts/${a.artifact_id}`,json('PATCH',{recycled:false})).then(detail)));
  else{
   if(isExport)actions.append(button(a.format==='docx'?'Word实际预览':'PDF预览',()=>previewExport(a)));
   else{const link=el('a',original?'查看原件':'对照 / 修改','button');link.href=reviewURL(a);actions.append(link);}
   if(a.format==='markdown')actions.append(button('导出',()=>openDocumentExport(a.artifact_id)));
   if(origin?.placeholders?.length)meta.append(el('p','空白占位：'+origin.placeholders.map(i=>i.source_page+'（'+i.reason+'）').join('；'),'muted'));
   if(origin?.mode==='markdown-direct')meta.append(el('p','来源物理页：'+compactSourceRanges(origin.source_pages||[])+'；明确未包含：'+(compactSourceRanges(origin.excluded_source_pages||[])||'无'),'muted'));if(a.path){const link=el('a','下载','button');link.href='/api/projects/'+pid+'/download/'+a.artifact_id;actions.append(link);}
   const menu=el('details',undefined,'artifact-menu');menu.append(el('summary','更多'));const choices=el('div',undefined,'menu-actions');menu.append(choices);actions.append(menu);
   choices.append(button('改名',async()=>{const name=prompt('文件显示名称',a.display_name||a.name);if(name!==null)await api(`/api/projects/${pid}/artifacts/${a.artifact_id}`,json('PATCH',{name})).then(detail);}));
   if(!original)choices.append(button('删除（可恢复）',()=>api(`/api/projects/${pid}/artifacts/${a.artifact_id}`,json('PATCH',{recycled:true})).then(detail)));
  }
  row.append(meta,actions);areas[group].append(row);
 }
 const jobs=[...(p.tasks||[])].reverse().filter(t=>t.operation==='format-artifact'&&!t.archived);
 const history=el('details',undefined,'export-history');history.id='export-history';history.open=open.has(history.id);history.append(el('summary','导出记录（'+jobs.length+'）'));const jobBody=el('div');history.append(jobBody);if(jobs.length)areas.exports.prepend(history);
 for(const t of [...jobs.filter(active),...jobs.filter(t=>!active(t)).slice(0,10)]){const row=el('div',undefined,'export-job');row.append(el('span',(t.document_export?.mode==='pandoc'?'Pandoc导出':'历史导出')+' · '+chineseTime(t.created_at)),badge(t.status));if(t.export_progress)row.append(el('p','阶段：'+({queued:'排队',prepare:'准备',parse:'整理正文与表格',fonts:'检查字体', 'pandoc-docx':'生成Word', 'validate-word':'校验Word', 'libreoffice-pdf':'转换PDF', 'validate-pdf':'校验PDF',finished:'完成'}[t.export_progress.phase]||t.export_progress.phase)+' · '+t.export_progress.completed+'/'+t.export_progress.total,'muted'));if(t.document_export?.cleaning_summary?.length)row.append(el('p','已确认清理 '+t.document_export.cleaning_summary.length+' 项（仅导出副本）','muted'));if(t.error)row.append(el('p','失败阶段：'+(t.error.stage||'未登记')+'；'+exportFailureMessage(t),'muted'));if(active(t))row.append(button('取消',()=>api(`/api/projects/${pid}/tasks/${t.task_id}/cancel`,json('POST',{})).then(detail)));(active(t)?areas.exports:jobBody).append(row);}
 if(jobs.length>10)jobBody.append(el('p','仅显示最近10条记录，完整记录保留在项目技术详情中。','muted'));
 for(const [id] of groups)if(!areas[id].children.length){if(id==='recycled')areas[id].parentElement.hidden=true;else areas[id].append(el('p',id==='exports'?'尚未导出 Word/PDF。':'暂无文字版本。','muted'));}
}
let previewRequest=0;
async function previewExport(a){
 const request=++previewRequest;
 const dialog=$('#exportPreview'),body=$('#exportPreviewBody');body.replaceChildren();$('#exportPreviewTitle').textContent=(a.format==='docx'?'Word实际预览 · ':'PDF文件预览 · ')+(a.display_name||a.name);dialog.showModal();
 const download=el('a','下载 '+(a.format==='docx'?'Word':'PDF'),'button primary');download.href='/api/projects/'+pid+'/download/'+a.artifact_id;body.append(download);
 const progress=el('p','正在读取预览状态…','muted');body.append(progress);
 // Publication can finish just before its preview is queued. Observe the open dialog only.
 const deadline=Date.now()+180000;let emptyReads=0;
 try{while(request===previewRequest&&dialog.open){
  const latest=await api('/api/projects/'+pid);a=latest.artifacts.find(item=>item.artifact_id===a.artifact_id)||a;
  const status=a.preview_render?.status||'NONE';
  if(!active(a.preview_render||{})&&!(status==='NONE'&&++emptyReads<3)||Date.now()>=deadline)break;
  progress.textContent='预览正在生成，完成后自动显示；可先下载文件。';await new Promise(resolve=>setTimeout(resolve,500));
 }}catch(e){if(request!==previewRequest||!dialog.open)return;progress.textContent='读取最新预览状态失败：'+e.message;return;}
 if(request!==previewRequest||!dialog.open)return;progress.remove();
 if(a.preview_render?.status==='SUCCEEDED'&&(a.pages||[]).some(p=>p.image)){
  const scroll=el('div',undefined,'export-preview-pages');for(const p of a.pages){if(!p.image)continue;const image=el('img');image.src='/p/'+pid+'/'+p.image;image.alt='导出文档第'+(p.output_page||p.locator?.page||'')+'页';image.loading='lazy';scroll.append(image);}body.append(scroll);
 }else{body.append(el('p',active(a.preview_render||{})?'预览正在生成，请稍后重新打开。':'尚无预览，可下载文件或生成预览。','muted'));if(!active(a.preview_render||{}))body.append(button('生成 / 重试预览',()=>api(`/api/projects/${pid}/previews/${a.artifact_id}`,json('POST',{retry:true})).then(()=>{dialog.close();return detail();})));}
}
let cleaningToken=0;
async function refreshCleaningSummary(){
 const token=++cleaningToken;$('#cleaningSummary').textContent='正在核对确认标记…';
 try{const d=await api(`/api/projects/${pid}/content-marks/${$('#formatSource').value}`);if(token!==cleaningToken)return;const range=$('#exportPages').value.trim();let selectedPages=null;if(range!=='全部'){selectedPages=new Set();for(const part of range.split(',')){const match=part.trim().match(/^(\d+)(?:-(\d+))?$/);if(!match)throw Error('来源范围格式无效');const a=Number(match[1]),b=Number(match[2]||match[1]);if(b<a||b-a>1000)throw Error('来源范围无效');for(let n=a;n<=b;n++)selectedPages.add(n);}}const selected=d.candidates.filter(m=>(!selectedPages||selectedPages.has(m.source_page))&&m.decision==='confirmed'&&m.actor_type==='human-self-declared'&&((m.kind==='header'&&$('#removeHeaders').checked)||(['footer','page_number'].includes(m.kind)&&$('#removeFooters').checked)));const body=$('#cleaningSummary');body.replaceChildren(el('p','已确认可清理 '+selected.length+' 项；实际范围内清理明细将随导出记录保存。'));for(const m of selected)body.append(el('p','来源物理页 '+m.source_page+'：'+m.text));}catch(e){if(token===cleaningToken)$('#cleaningSummary').textContent=e.message;}
}
window.addEventListener('DOMContentLoaded',()=>{
 $('#openDocumentExport').onclick=()=>openDocumentExport();$('#closeDocumentExport').onclick=()=>$('#exportDialog').close();$('#closeExportPreview').onclick=()=>$('#exportPreview').close();
 for(const id of ['formatSource','exportPages','removeHeaders','removeFooters'])$('#'+id).addEventListener('input',()=>{$('#exportError').textContent='';refreshCleaningSummary();});
 $('#formatExisting').onclick=async()=>{
  const formats=[$('#exportWord').checked?'docx':null,$('#exportPDF').checked?'pdf':null].filter(Boolean);if(!formats.length){$('#exportError').textContent='至少选择一种格式。';return;}
  $('#formatExisting').disabled=true;$('#exportError').textContent='';
  try{await api(`/api/projects/${pid}/document-exports`,json('POST',{source_artifact_id:$('#formatSource').value,formats,pages:$('#exportPages').value,remove_headers:$('#removeHeaders').checked,remove_footers:$('#removeFooters').checked,new_header:$('#newHeader').checked,new_page_numbers:$('#newPageNumbers').checked}));$('#exportDialog').close();message('导出任务已排队，离开页面后仍继续。完成后在导出文件区预览和下载。');await detail();}catch(e){$('#exportError').textContent=e.message;}finally{$('#formatExisting').disabled=false;}
 };
});
function compactSourceRanges(values){const a=[...new Set(values)].sort((x,y)=>x-y),r=[];for(let i=0;i<a.length;){let start=a[i],end=start;while(i+1<a.length&&a[i+1]===end+1)end=a[++i];r.push(start===end?String(start):start+'–'+end);i++;}return r.join(',');}
