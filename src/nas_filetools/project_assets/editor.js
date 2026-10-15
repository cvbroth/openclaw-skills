/* Online mapped-text editing. No recognition, model calls or arbitrary paths. */
'use strict';
let editing=false,editInfo=null,editText='',editOriginal='',editDirty=false,editBusy=false,editEpoch=0,requestId=null;
let dirtyDialogOpen=false,editorPending=Promise.resolve();
let displayed={aid:artifact('right').artifact_id,index:$('#rightPosition').value};
const state=t=>{$('#textState').textContent=t;$('#textState').hidden=!editing&&!t.startsWith('不可编辑')&&!t.startsWith('保存失败');};
function editControls(){document.body.classList.toggle('editing',editing);$('#saveRevision').hidden=!editing;$('#cancelEdit').hidden=!editing;$('#textMode').hidden=editing||(sourceReading.active&&!sourceReading.selected)||artifact('right').format!=='markdown'||!!editInfo&&editInfo.head_id!==editInfo.artifact_id;$('#textState').hidden=!editing;}
const revisionURL='/api/projects/'+P.project_id;
async function api(url,options){let r=await fetch(url,options),data=await r.json();if(!r.ok)throw Error(data.reason||data.error||r.status);return data;}
function post(url,data){return api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}
function uuid(){return crypto.randomUUID?crypto.randomUUID():'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));}
function parentMarkdown(a){return (a.parents||[]).map(id=>arts.find(x=>x.artifact_id===id)).find(x=>x?.format==='markdown'&&!x.recycled);}
function updateEditor(){
 let a=artifact('right'),epoch=++editEpoch;displayed={aid:a.artifact_id,index:$('#rightPosition').value};
 $('#textMode').hidden=a.format!=='markdown';$('#textHistory').hidden=a.format!=='markdown';
 $('#editParent').hidden=!['docx','pdf'].includes(a.format);$('#editParent').disabled=!parentMarkdown(a);
 if(['docx','pdf'].includes(a.format)&&!parentMarkdown(a))state('没有明确关联的文字稿，不能猜测编辑来源。');
 $('#saveRevision').hidden=!editing;$('#exportText').hidden=a.format!=='markdown';
 $('#textMode').textContent='编辑';editControls();
 $('#historyState').hidden=true;$('#restoreForEdit').hidden=true;if(a.format!=='markdown'){editing=false;editControls();return;}
 if(!serverMode){$('#exportText').disabled=true;$('#textMode').disabled=true;$('#textHistory').disabled=true;$('#textMode').title=$('#exportText').title='离线包仅供阅读，请在在线项目编辑或导出';state('离线包仅供阅读；请在线保存修订，不能写入服务器。');return;}
 $('#textMode').disabled=true;editInfo=null;
 return api(revisionURL+'/text/'+a.artifact_id+'?locator='+encodeURIComponent(JSON.stringify(position('right').locator))).then(info=>{
  if(epoch!==editEpoch)return;editInfo=info;let page=info.pages.find(p=>stable(p.locator)===stable(position('right').locator));
  if(!page){$('#historyState').hidden=info.head_id===a.artifact_id;$('#restoreForEdit').hidden=true;editControls();state('请选择已登记的具体文字片段后编辑。');return;}
  editOriginal=page.text;editText=page.text;editDirty=false;requestId=null;
  let historical=info.head_id!==a.artifact_id;$('#historyState').hidden=!historical;$('#restoreForEdit').hidden=!historical||(sourceReading.active&&!sourceReading.selected);$('#textMode').disabled=false;editControls();state(info.head_id!==a.artifact_id?'历史版本只读；可在版本与差异中恢复为新版本。':'已保存 · 仅修改当前来源位置');
  if(editing)mountEditor();if(!$('#auxPanel').hidden&&document.querySelector('[data-panel=versions]').getAttribute('aria-selected')==='true')loadHistory();
 }).catch(e=>{if(epoch===editEpoch){editing=false;$('#saveRevision').hidden=true;state('不可编辑：'+e.message);}});
}
function mountEditor(){
 tokens.right++;editControls();let box=$('#rightContent');box.replaceChildren();let area=document.createElement('textarea');area.id='textEditor';area.spellcheck=false;area.setAttribute('aria-label','当前页 Markdown 文字');area.value=editText;area.readOnly=editBusy||editInfo.head_id!==editInfo.artifact_id;
 area.oninput=()=>{editText=area.value;editDirty=editText!==editOriginal;requestId=null;state((editDirty?'有未保存修改':'已保存')+' · 文字位置 '+(Number($('#rightPosition').value)+1));};box.append(area);if(innerWidth<=600)document.body.classList.add('result');area.focus({preventScroll:true});area.setSelectionRange(0,0);area.scrollTop=0;
 $('#saveRevision').hidden=false;
 $('#saveRevision').disabled=area.readOnly;
}
async function chooseDirty(){
 if(!editDirty)return true;
 if(dirtyDialogOpen)return false;dirtyDialogOpen=true;
 return new Promise(resolve=>{let d=document.createElement('dialog');d.className='revision-dialog';let p=document.createElement('p');p.textContent='当前文字有未保存修改。请选择保存、放弃或取消切换。';d.append(p);
  for(let [label,action] of [['保存','save'],['放弃','discard'],['取消','cancel']]){let b=document.createElement('button');b.textContent=label;b.onclick=async()=>{if(action==='save'){for(let button of d.querySelectorAll('button'))button.disabled=true;if(!await saveRevision()){for(let button of d.querySelectorAll('button'))button.disabled=false;return;}}if(action==='discard'){editDirty=false;editText=editOriginal;}dirtyDialogOpen=false;d.close();d.remove();resolve(action!=='cancel');};d.append(b);}d.oncancel=e=>{e.preventDefault();if(editBusy)return;dirtyDialogOpen=false;d.close();d.remove();resolve(false);};document.body.append(d);d.showModal();});
}
async function installProject(aid,loc,preserveEditor=false){
 let p=await api(revisionURL);Object.assign(P,p);arts.splice(0,arts.length,...p.artifacts);P.artifacts=arts;
 for(let side of ['left','right']){let select=$('#'+side+'Artifact'),selected=select.value;for(let a of [...arts].reverse()){if(!a.recycled&&a.format==='markdown'&&![...select.options].some(o=>o.value===a.artifact_id)){let o=document.createElement('option');o.value=a.artifact_id;o.textContent=(a.display_name||a.name)+' · 第'+a.version+'版';select.insertBefore(o,select.options[1]||null);}}select.value=selected;}
 if(preserveEditor)return;
 $('#rightArtifact').value=aid;positions('right');let a=artifact('right'),index=a.pages.findIndex(p=>stable(p.locator)===stable(loc));if(index>=0)$('#rightPosition').value=String(index);refresh('right');await editorPending;
}
function lockTextNavigation(value){for(let id of ['rightArtifact','rightPosition','rightPageInput','rightPagePrev','rightPageNext','textMode','textHistory','saveRevision','exportText','commentFilter','errorFilter','markdownMode','sourcePageLookup','findSourcePage','locateSelectedSource'])$('#'+id).disabled=value;$('#cancelEdit').disabled=value;$('#restoreForEdit').disabled=value;}
async function saveRevision(){
 if(editBusy||!editInfo)return false;editBusy=true;lockTextNavigation(true);state('正在保存修订…');if($('#textEditor'))$('#textEditor').readOnly=true;
 let loc=position('right').locator;
 try{
  requestId=requestId||uuid();let result=await post(revisionURL+'/text-revisions',{request_id:requestId,parent_artifact_id:editInfo.artifact_id,parent_sha256:editInfo.sha256,head_id:editInfo.head_id,head_sha256:editInfo.head_sha256,locator:loc,text:editText,reviewer_type:$('#reviewer').value});
  editDirty=false;editOriginal=editText;editing=false;await installProject(result.artifact_id,loc);state(result.no_change?'无变化，未创建重复版本':'已保存修订版');
  return true;
 }catch(e){state('保存失败：'+e.message+'；草稿仍保留。');return false;}finally{editBusy=false;lockTextNavigation(false);$('#textMode').disabled=!editInfo;if($('#textEditor'))$('#textEditor').readOnly=editInfo.head_id!==editInfo.artifact_id;}
}
$('#textMode').onclick=async()=>{if(!editInfo||editInfo.head_id!==editInfo.artifact_id||!await chooseDirty())return;editing=true;mountEditor();state(position('right').locator.kind==='document'?'整份文字编辑 · 无来源页映射':'仅编辑文字位置 '+(Number($('#rightPosition').value)+1));};
$('#cancelEdit').onclick=async()=>{if(editBusy||!await chooseDirty())return;editing=false;editControls();render('right');};
$('#saveRevision').onclick=()=>saveRevision();
$('#editParent').onclick=async()=>{let p=parentMarkdown(artifact('right'));if(p&&await chooseDirty()){editing=false;await installProject(p.artifact_id,{kind:'document'});}};
async function restoreText(aid,forEdit=false){
 if(editBusy||!editInfo||!await chooseDirty())return;
 editBusy=true;lockTextNavigation(true);let loc=position('right').locator;
 try{let head=await api(revisionURL+'/text/'+editInfo.head_id);let result=await post(revisionURL+'/text-revisions',{request_id:uuid(),parent_artifact_id:head.artifact_id,parent_sha256:head.sha256,head_id:head.head_id,head_sha256:head.head_sha256,restore_artifact_id:aid,reviewer_type:$('#reviewer').value});editing=false;await installProject(result.artifact_id,loc);if(forEdit){editing=true;mountEditor();}state(result.no_change?'所选内容与最新稿相同':'已将历史内容恢复为新版本');}
 catch(e){$('#historyContent').textContent='恢复失败：'+e.message;state('保存失败：'+e.message);}
 finally{editBusy=false;lockTextNavigation(false);if($('#textEditor'))$('#textEditor').readOnly=false;}
}
function loadHistory(){
 let container=$('#historyContent');container.replaceChildren();if(!editInfo){container.textContent='请选择在线文字版本。';return;}
 let info=editInfo,select=document.createElement('select');select.id='revisionHistory';select.setAttribute('aria-label','历史文字版本');for(let item of info.history){let o=document.createElement('option');o.value=item.artifact_id;o.textContent='第'+item.version+'版'+(item.artifact_id===info.artifact_id?'（正在查看）':'')+(item.artifact_id===info.head_id?'（最新）':'');select.append(o);}select.value=info.artifact_id;container.append(select);
 let pre=document.createElement('pre');pre.id='revisionDiff';container.append(pre);let diffEpoch=0;
 async function diff(){let epoch=++diffEpoch;try{let data=await api(revisionURL+'/text-diff/'+info.artifact_id+'?against='+select.value);if(epoch===diffEpoch)pre.textContent=data.diff||'文字没有差异。';}catch(e){if(epoch===diffEpoch)pre.textContent=e.message;}}select.onchange=diff;diff();
 let view=document.createElement('button');view.textContent='查看所选版本';view.id='viewRevision';view.onclick=async()=>{let aid=select.value,loc=position('right').locator;if(!editBusy&&await chooseDirty()){editing=false;await installProject(aid,loc);}};container.append(view);
 let restore=document.createElement('button');restore.id='restoreRevision';restore.textContent='恢复为新版本';restore.onclick=()=>restoreText(select.value);container.append(restore);
}
$('#textHistory').onclick=()=>openAuxPanel('versions');
$('#restoreForEdit').onclick=()=>restoreText(artifact('right').artifact_id,true);
// Guard right-side object changes before replacing the editor; left navigation stays independent.
for(let id of ['rightArtifact','rightPosition','commentFilter','errorFilter','markdownMode']){
 let control=$('#'+id),handler=control.onchange;control.onchange=async event=>{let next=control.value,old=id==='rightArtifact'?displayed.aid:id==='rightPosition'?displayed.index:control.dataset.previous;
  if(editDirty||(typeof tableDraft!=='undefined'&&tableDraft?.dirty)){if(old!==undefined)control.value=old;if(!await chooseDirty()){compactLabels();return;}control.value=next;}
  editing=false;if(id==='rightPosition'){sourceReading.active=false;sourceReading.selected=null;positions('right');control.value=next;}if(id==='rightArtifact')sourceReading.selected=null;if(id==='rightArtifact'&&artifact('right').format!=='markdown'){sourceReading.active=false;sourceReading.selected=null;}handler?.call(control,event);control.dataset.previous=control.value;
 };control.dataset.previous=control.value;
}
const originalRefresh=refresh;refresh=function(side){originalRefresh(side);if(!side||side==='right')editorPending=updateEditor();};
window.addEventListener('beforeunload',e=>{if(editDirty||(typeof tableDraft!=='undefined'&&tableDraft?.dirty)){e.preventDefault();e.returnValue='';}});
$('#back').addEventListener('click',async e=>{if(editBusy){e.preventDefault();state('正在保存，请稍候再离开。');return;}if(editDirty||(typeof tableDraft!=='undefined'&&tableDraft?.dirty)){let href=e.currentTarget.href;e.preventDefault();if(await chooseDirty())location.href=href;}});
updateEditor();

for(let side of ['left','right'])$('#'+side+'PageInput').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();jump(side,e.target.value);}};

$('#exportText').onclick=async()=>{
 if(editBusy||!await chooseDirty())return;
 location.href='/projects/'+P.project_id+'?export_source='+encodeURIComponent(artifact('right').artifact_id);
};
