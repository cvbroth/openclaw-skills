'use strict';
let markInfo=null,contentEpoch=0,tableDraft=null,tableBusy=false;
const toolElement=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
function contentContext(){const a=artifact('right'),loc=position('right').locator;if(!serverMode||a.format!=='markdown'||!loc||sourceReading.active&&!sourceReading.selected)throw Error('请在线选中具体文字片段；历史版本可只读核对。');return {a,loc};}
async function loadContentTools(group){
 const epoch=++contentEpoch;
 try{const {a,loc}=contentContext();if(group==='marks'){
  const data=await api(revisionURL+'/content-marks/'+a.artifact_id);if(epoch!==contentEpoch)return;markInfo=data;drawMarks();
  const info=await api(revisionURL+'/text/'+a.artifact_id+'?locator='+encodeURIComponent(JSON.stringify(loc)));if(epoch!==contentEpoch)return;$('#markRangeText').value=info.pages[0].text;
 }else{
  if(tableDraft?.dirty)return;
  const data=await api(revisionURL+'/tables/'+a.artifact_id+'?locator='+encodeURIComponent(JSON.stringify(loc)));if(epoch!==contentEpoch)return;
  const info=await api(revisionURL+'/text/'+a.artifact_id);if(epoch!==contentEpoch)return;drawTables(data,info,loc);
 }}catch(e){$('#'+(group==='marks'?'marksStatus':'tableStatus')).textContent=e.message;}
}
function drawMarks(){
 const body=$('#marksList');body.replaceChildren();$('#marksStatus').textContent='当前文字版本候选 '+markInfo.candidates.length+' 项；决定绑定此版本。';
 for(const m of markInfo.candidates){const card=toolElement('article');card.className='mark-candidate';const check=toolElement('input');check.type='checkbox';check.value=m.id;check.disabled=m.decision==='needs_review';card.append(check,toolElement('strong','来源 '+m.source_page+' · '+({header:'页眉',footer:'页脚',page_number:'页码',body:'正文'}[m.kind]||m.kind)+' · '+({pending:'待确认',confirmed:'已确认',rejected:'保留',needs_review:'修订后待复核'}[m.decision])+(m.actor_type==='developer-agent'?'（开发验收，不参与清理）':'')));
  card.append(toolElement('p',m.text),toolElement('p',m.basis+'；置信度 '+m.confidence+'；'+(m.coordinates?'有已登记坐标':'无原图坐标')));
  const kind=toolElement('select');for(const [value,label] of [['header','页眉'],['footer','页脚'],['page_number','原页码'],['body','保留正文']]){const o=toolElement('option',label);o.value=value;kind.append(o);}kind.value=m.kind;card.append(kind);
  const locate=toolElement('button','跳转对照');locate.onclick=async()=>{if(!await chooseDirty())return;await installProject(artifact('right').artifact_id,m.locator);const index=source.pages.findIndex(p=>(p.physical_page||p.locator?.page)===m.source_page);if(index>=0){$('#leftArtifact').value=source.artifact_id;positions('left');$('#leftPosition').value=index;refresh('left');}await loadContentTools('marks');};card.append(locate);
  const confirm=toolElement('button',m.decision==='needs_review'?'重新选择范围':'保存此项决定');confirm.onclick=async()=>{if(m.decision==='needs_review'){await locate.onclick();$('#markRangeText').closest('details').open=true;$('#markRangeText').focus();$('#markRangeText').setSelectionRange(m.start,m.end);return;}await decideMarks([m.id],kind.value==='body'?'rejected':'confirmed',kind.value);};card.append(confirm);body.append(card);
 }
}
async function decideMarks(ids,decision,kind){try{const {a}=contentContext();markInfo=await api(revisionURL+'/content-marks/'+a.artifact_id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:markInfo.revision,ids,decision,reviewer_type:$('#reviewer').value,...(kind?{kind}:{})})});drawMarks();}catch(e){$('#marksStatus').textContent=e.message;}}
$('#identifyMarks').onclick=async()=>{try{const {a}=contentContext();const epoch=++contentEpoch;const result=await post(revisionURL+'/content-marks/'+a.artifact_id,{});if(epoch!==contentEpoch||artifact('right').artifact_id!==a.artifact_id)return;markInfo=result;drawMarks();}catch(e){$('#marksStatus').textContent=e.message;}};
$('#refreshMarks').onclick=()=>loadContentTools('marks');
for(const [id,decision] of [['confirmMarks','confirmed'],['rejectMarks','rejected']])$('#'+id).onclick=()=>decideMarks([...$('#marksList').querySelectorAll('input:checked')].map(c=>c.value),decision);
$('#addManualMark').onclick=async()=>{try{const {a,loc}=contentContext(),area=$('#markRangeText');markInfo=await post(revisionURL+'/content-marks/'+a.artifact_id,{action:'manual',revision:markInfo.revision,locator:loc,start:area.selectionStart,end:area.selectionEnd,kind:$('#manualMarkKind').value});drawMarks();}catch(e){$('#marksStatus').textContent=e.message;}};
function drawTables(data,info,loc){
 const body=$('#tableTools');body.replaceChildren();tableDraft=null;$('#tableStatus').textContent=data.length?'找到 '+data.length+' 个表格。':'此片段没有规范表格；若旧结果丢失列或合并信息，请对照原件在文字编辑中修正，不能推断。';
 for(const t of data){const card=toolElement('section');card.dataset.tableId=t.id;card.append(toolElement('h3','表格 '+(data.indexOf(t)+1)));
  if(t.error){card.append(toolElement('p','待复核：'+t.error));body.append(card);continue;}
  if(t.review_required)card.append(toolElement('p','待复核：'+t.review_required));
  const grid=toolElement('table');for(let r=0;r<t.model.rows;r++){const row=toolElement('tr');for(const c of t.model.cells.filter(c=>c.row===r).sort((a,b)=>a.column-b.column)){const cell=toolElement(c.header?'th':'td');cell.rowSpan=c.rowspan;cell.colSpan=c.colspan;const area=toolElement('textarea');area.value=c.text;area.readOnly=info.head_id!==info.artifact_id;area.setAttribute('aria-label',`行${r+1}列${c.column+1}`);area.dataset.row=r;area.dataset.column=c.column;const head=toolElement('input');head.type='checkbox';head.checked=c.header;head.disabled=info.head_id!==info.artifact_id;head.title='表头单元格';head.dataset.header='true';cell.append(area,head);row.append(cell);}grid.append(row);}card.append(grid);
  const controls=toolElement('div');controls.className='table-operations';const fields={};for(const [key,label,value] of [['row','起始行',1],['column','起始列',1],['rowspan','跨行',1],['colspan','跨列',1]]){const l=toolElement('label',label);const input=toolElement('input');input.type='number';input.min=1;input.value=value;input.setAttribute('aria-label',label);fields[key]=input;l.append(input);controls.append(l);}
  const snapshot=()=>[...grid.querySelectorAll('textarea')].map(a=>({row:Number(a.dataset.row),column:Number(a.dataset.column),text:a.value,header:a.parentElement.querySelector('input').checked}));
  const draft=()=>{tableDraft={info,loc,table:t,edits:snapshot(),dirty:true,card,fields};$('#tableStatus').textContent='表格有未保存修改，保存创建新文字版本。';};grid.addEventListener('input',draft);
  for(const [label,action] of [['保存单元格','save'],['合并矩形并保存','merge'],['拆分单元格并保存','unmerge'],['确认结构并保存规范格式','save']]){const b=toolElement('button',label);b.disabled=info.head_id!==info.artifact_id;b.onclick=async()=>{if(editDirty&&!await chooseDirty())return;draft();const rect=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Number(v.value)-(k==='row'||k==='column'?1:0)]));await saveTable(action==='save'?{}:{[action]:rect});};controls.append(b);}card.append(controls);body.append(card);
 }
}
async function saveTable(operation={}){
 if(tableBusy||!tableDraft)return false;const d=tableDraft;tableBusy=true;$('#tableStatus').textContent='正在保存表格修订…';
 try{const result=await post(revisionURL+'/table-revisions',{request_id:uuid(),parent_artifact_id:d.info.artifact_id,parent_sha256:d.info.sha256,head_id:d.info.head_id,head_sha256:d.info.head_sha256,locator:d.loc,table_id:d.table.id,reviewer_type:$('#reviewer').value,edits:d.edits,...operation});tableDraft=null;editing=false;await installProject(result.artifact_id,d.loc);await loadContentTools('tables');$('#tableStatus').textContent='表格修订已保存为新版本，来源定位与评论对象保持原定位。';return true;}catch(e){$('#tableStatus').textContent='保存失败：'+e.message+'；表格草稿保留。';return false;}finally{tableBusy=false;}
}
$('#refreshTables').onclick=async()=>{if(await chooseDirty())loadContentTools('tables');};
const originalChooseDirty=chooseDirty;
chooseDirty=async function(){if(tableBusy)return false;if(tableDraft?.dirty){if(dirtyDialogOpen)return false;dirtyDialogOpen=true;const answer=await new Promise(resolve=>{const d=toolElement('dialog');d.append(toolElement('p','表格有未保存修改：保存、放弃或取消切换。'));for(const [label,value] of [['保存','save'],['放弃','discard'],['取消','cancel']]){const b=toolElement('button',label);b.onclick=()=>{dirtyDialogOpen=false;d.close();d.remove();resolve(value);};d.append(b);}d.oncancel=e=>{e.preventDefault();dirtyDialogOpen=false;d.remove();resolve('cancel');};document.body.append(d);d.showModal();});if(answer==='cancel')return false;if(answer==='save'&&!await saveTable())return false;if(answer==='discard')tableDraft=null;}return originalChooseDirty();};
window.addEventListener('beforeunload',e=>{if(tableDraft?.dirty){e.preventDefault();e.returnValue='';}});
const contentUpdateEditor=updateEditor;
updateEditor=function(){const result=contentUpdateEditor();Promise.resolve(result).then(()=>{const group=document.querySelector('[data-panel][aria-selected=true]')?.dataset.panel;if(!$('#auxPanel').hidden&&['marks','tables'].includes(group))loadContentTools(group);});return result;};
