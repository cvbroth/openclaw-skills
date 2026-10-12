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
 if($('#exportMode').value==='template'&&!$('#formatTemplate').value){message('暂无可用模板，请先在模板管理中发布模板。');return;}
 $('#exportError').textContent='';$('#exportDialog').showModal();
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
   if(origin?.mode==='markdown-direct')meta.append(el('p','来源物理页：'+compactSourceRanges(origin.source_pages||[])+'；明确未包含：'+(compactSourceRanges(origin.excluded_source_pages||[])||'无'),'muted'));if(a.path){const link=el('a','下载','button');link.href='/api/projects/'+pid+'/download/'+a.artifact_id;actions.append(link);}
   const menu=el('details',undefined,'artifact-menu');menu.append(el('summary','更多'));const choices=el('div',undefined,'menu-actions');menu.append(choices);actions.append(menu);
   choices.append(button('改名',async()=>{const name=prompt('文件显示名称',a.display_name||a.name);if(name!==null)await api(`/api/projects/${pid}/artifacts/${a.artifact_id}`,json('PATCH',{name})).then(detail);}));
   if(!original)choices.append(button('删除（可恢复）',()=>api(`/api/projects/${pid}/artifacts/${a.artifact_id}`,json('PATCH',{recycled:true})).then(detail)));
  }
  row.append(meta,actions);areas[group].append(row);
 }
 const jobs=[...(p.tasks||[])].reverse().filter(t=>t.operation==='format-artifact'&&!t.archived);
 const history=el('details',undefined,'export-history');history.id='export-history';history.open=open.has(history.id);history.append(el('summary','导出记录（'+jobs.length+'）'));const jobBody=el('div');history.append(jobBody);if(jobs.length)areas.exports.prepend(history);
 for(const t of [...jobs.filter(active),...jobs.filter(t=>!active(t)).slice(0,10)]){const row=el('div',undefined,'export-job');row.append(el('span',(t.document_export?.mode==='markdown-direct'?(t.document_export?.purpose==='check'?'原文直出检查':t.document_export?.purpose==='preview'?'PDF纸张预览':'原文直出'):'模板导出')+' · '+chineseTime(t.created_at)),badge(t.status));if(t.direct_progress)row.append(el('p','来源物理页 '+(t.direct_progress.source_page||'—')+' · 已检查 '+t.direct_progress.completed+'/'+t.direct_progress.total,'muted'));if(t.direct_report?.issues?.length)row.append(el('p','阻塞 '+t.direct_report.issues.length+' 项；在导出窗口完整检查可查看页码和原因。','muted'));if(t.error)row.append(el('p',exportFailureMessage(t),'muted'));if(t.direct_report&&!active(t))row.append(button('查看检查结果',()=>showDirectInspection(t)));if(active(t))row.append(button('取消',()=>api(`/api/projects/${pid}/tasks/${t.task_id}/cancel`,json('POST',{})).then(detail)));(active(t)?areas.exports:jobBody).append(row);}
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
function exportModeChanged(){const direct=$('#exportMode').value==='markdown-direct';for(const e of document.querySelectorAll('[data-template-only]'))e.hidden=direct;$('#directSettings').hidden=!direct;$('#directDescription').hidden=!direct;$('#directPaper').hidden=!direct;}
window.addEventListener('DOMContentLoaded',()=>{
 $('#exportMode').onchange=exportModeChanged;exportModeChanged();installPaperPreview();
 api('/api/reading-style').then(s=>{const font=s.body_pt;$('#directDescription').textContent='A4，'+s.margin_mm+'毫米边距；正文'+font+'磅、'+s.line_multiple+'倍行距。每个来源页只占一张输出页，放不下时明确失败。';$('#directMinimum').max=font;$('#directLine').max=s.line_multiple;}).catch(e=>{$('#exportError').textContent='读取阅读样式失败：'+e.message;});
 $('#openDocumentExport').onclick=()=>openDocumentExport();$('#closeDocumentExport').onclick=()=>$('#exportDialog').close();$('#closeExportPreview').onclick=()=>$('#exportPreview').close();
 $('#formatExisting').onclick=async()=>{
  const formats=[$('#exportWord').checked?'docx':null,$('#exportPDF').checked?'pdf':null].filter(Boolean);
  if(!formats.length){$('#exportError').textContent='至少选择一种格式。';return;}
  $('#formatExisting').disabled=true;$('#exportError').textContent='';
  try{await api('/api/projects/'+pid+'/document-exports',json('POST',{source_artifact_id:$('#formatSource').value,mode:$('#exportMode').value,formats,pages:$('#exportPages').value,...($('#exportMode').value==='markdown-direct'?{compact:{enabled:$('#directCompact').checked,minimum_font_pt:Number($('#directMinimum').value),minimum_line_multiple:Number($('#directLine').value),minimum_paragraph_em:Number($('#directGap').value)}}:{template:JSON.parse($('#formatTemplate').value),pagination:{mode:$('#paginationMode').value,font_fit:$('#paginationFontFit').checked,minimum_font_pt:Number($('#paginationMinimum').value),allow_continuation:$('#paginationContinue').checked}})}));$('#exportDialog').close();message('正在生成导出文件，可在“导出文件”中查看进度。');await detail();}catch(e){$('#exportError').textContent=e.message;}finally{$('#formatExisting').disabled=false;}
 };

});

function directSettings(purpose){
 return {source_artifact_id:$('#formatSource').value,mode:'markdown-direct',purpose,
  formats:purpose==='preview'?['pdf']:[$('#exportWord').checked?'docx':null,$('#exportPDF').checked?'pdf':null].filter(Boolean),
  pages:purpose==='preview'?$('#paperSourcePage').value:$('#exportPages').value,
  compact:{enabled:$('#directCompact').checked,minimum_font_pt:Number($('#directMinimum').value),minimum_line_multiple:Number($('#directLine').value),minimum_paragraph_em:Number($('#directGap').value)}};
}
function drawPaperResult(data){
 const body=$('#paperResult'),r=data.report||{};body.replaceChildren();
 if(!r.groups)return;body.append(el('p','本次来源范围：'+compactSourceRanges(r.requested_source_pages||r.groups.map(g=>g.source_page))+'；明确未包含：'+(compactSourceRanges(r.excluded_source_pages||[])||'无'),'paper-metrics'));
 body.append(el('p',r.ready?(r.purpose==='preview'?'PDF纸张检查通过；Word实际分页需另行生成校验。':'检查通过：每个来源页均可单页输出。'):'检查发现阻塞：不会自动跳页或发布为成功导出。','paper-state'));
 if(r.issues?.length){const list=el('ul',undefined,'paper-problems');for(const i of r.issues)list.append(el('li','来源物理页 '+(i.source_page??'未知')+'：'+i.reason.replace(/SOURCE_PAGE_OVERFLOW:\s*/g,'')));body.append(list);}
 const technical=el('details');technical.append(el('summary','正文状态与生成详情'));for(const state of r.content_states||[])technical.append(el('p','来源 '+state.source_page+'：'+state.reason,'muted'));technical.append(el('pre',JSON.stringify(r.renderer||{},null,2)));body.append(technical);const params=r.preview_parameters;
 if(params){body.append(el('p',r.reading_style.paper_mm.join('×')+'毫米纸张 · '+r.reading_style.margin_mm+'毫米边距 · 正文 '+params.body_pt+'磅 · 行距 '+params.line_multiple+'倍 · 段距 '+params.paragraph_em+'em · 需要 '+params.pdf.actual_output_pages+' 张纸 · '+(params.pdf.overflow?'溢出，禁止导出':'未溢出')+' · 本地字体 '+(params.pdf.fonts.every(f=>f.status==='loaded')?'已加载':'未加载'),'paper-metrics'));}
 for(const url of data.images||[]){const img=el('img',undefined,'paper-sheet');img.src=url;img.alt='PDF实际纸张预览（候选；是否允许导出以检查结果为准）';body.append(img);}
 if(data.candidate_pdf){const a=el('a','查看本次PDF纸张候选（阻塞时不是成功导出）','button');a.href=data.candidate_pdf;a.target='_blank';a.rel='noopener';body.append(a);}
 if((data.images||[]).length===10&&params?.pdf.actual_output_pages>10)body.append(el('p','仅展示前10张诊断候选页；该来源页已溢出，不能作为正式导出。','muted'));
 if(r.groups.length>1){const table=el('div',undefined,'paper-problems');for(const g of r.groups)table.append(el('p','来源 '+g.source_page+'：'+(g.status==='READY'?'可单页输出':g.reason||'阻塞')));body.append(table);}
}
function installPaperPreview(){
 let task=null,busy=false,wanted=0,timer=null,shown=false,cancelled=false,lastPurpose='preview';
 async function run(purpose){
  const revision=++wanted;shown=true;lastPurpose=purpose;
  if(busy){if(task)await api(`/api/projects/${pid}/tasks/${task}/cancel`,json('POST',{}));return;}
  busy=true;cancelled=false;$('#formatExisting').disabled=true;$('#paperResult').replaceChildren();$('#cancelDirectCheck').hidden=false;$('#paperStatus').textContent='正在建立'+(purpose==='preview'?'纸张预览':'完整检查')+'任务…';
  try{
   const created=await api(`/api/projects/${pid}/document-exports`,json('POST',directSettings(purpose)));task=created.task_id;
   while(true){
    const d=await api(`/api/projects/${pid}/direct-results/${task}`),p=d.progress;
    $('#paperStatus').textContent=p?'来源物理页 '+(p.source_page||'—')+' · 已检查 '+p.completed+'/'+p.total+' · 阻塞 '+p.blocked+'项':'正在加载本地字体与纸张…';
    if(!['QUEUED','RUNNING','CANCELLING'].includes(d.status)){
     if(revision===wanted){drawPaperResult(d);$('#paperStatus').textContent=d.status==='CANCELLED'?'本次检查已取消。':d.status==='FAILED'?'检查执行失败：'+(d.error?.message||'请查看诊断'):d.report.ready?(d.report.purpose==='preview'?'PDF纸张检查完成，未溢出；Word采用独立实际校验。':'所选格式检查完成，可以导出。'):'检查完成，存在阻塞，请调整范围、格式或紧凑边界。';}
     break;
    }
    if(revision!==wanted||cancelled)await api(`/api/projects/${pid}/tasks/${task}/cancel`,json('POST',{}));
    await new Promise(resolve=>setTimeout(resolve,500));
   }
  }catch(e){$('#paperStatus').textContent=e.message;}finally{busy=false;task=null;$('#formatExisting').disabled=false;$('#cancelDirectCheck').hidden=true;if(revision!==wanted&&!cancelled)run(lastPurpose);}
 }
 document.addEventListener('loaded-direct-inspection',event=>{shown=true;lastPurpose=event.detail.purpose==='preview'?'preview':'check';});$('#updatePaper').onclick=()=>run('preview');$('#checkDirectRange').onclick=()=>run('check');
 $('#cancelDirectCheck').onclick=async()=>{cancelled=true;if(task)await api(`/api/projects/${pid}/tasks/${task}/cancel`,json('POST',{}));};
 for(const id of ['paperSourcePage','formatSource','directCompact','directMinimum','directLine','directGap','exportPages','exportWord','exportPDF'])$('#'+id).addEventListener('change',()=>{if(!shown||(lastPurpose==='preview'&&['exportPages','exportWord','exportPDF'].includes(id)))return;clearTimeout(timer);timer=setTimeout(()=>run(lastPurpose),500);});
}

function compactSourceRanges(values){const a=[...new Set(values)].sort((x,y)=>x-y),r=[];for(let i=0;i<a.length;){let start=a[i],end=start;while(i+1<a.length&&a[i+1]===end+1)end=a[++i];r.push(start===end?String(start):start+'–'+end);i++;}return r.join(',');}

async function showDirectInspection(t){
 $('#exportMode').value='markdown-direct';exportModeChanged();openDocumentExport(t.source_artifact_id);
 const e=t.document_export;$('#exportPages').value=compactSourceRanges(e.source_pages||e.included_source_pages||[]).replaceAll('–','-')||'全部';
 $('#directCompact').checked=e.compact.enabled;$('#directMinimum').value=e.compact.minimum_font_pt;$('#directLine').value=e.compact.minimum_line_multiple;$('#directGap').value=e.compact.minimum_paragraph_em;
 $('#exportWord').checked=e.formats.includes('docx');$('#exportPDF').checked=e.formats.includes('pdf');
 const data=await api(`/api/projects/${pid}/direct-results/${t.task_id}`);drawPaperResult(data);
 $('#paperSourcePage').value=data.report.groups?.[0]?.source_page||1;
 $('#paperStatus').textContent='已保存的检查快照；修改参数将建立新检查。'+(data.report.ready?'检查通过。':'存在阻塞，不能作为整份成功导出。');
 document.dispatchEvent(new CustomEvent('loaded-direct-inspection',{detail:{purpose:e.purpose}}));$('#paperStatus').scrollIntoView({block:'nearest'});
}
