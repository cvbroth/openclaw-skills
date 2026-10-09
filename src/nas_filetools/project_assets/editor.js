/* Online mapped-text editing. No recognition, model calls or arbitrary paths. */
'use strict';
const editbar=document.createElement('div');editbar.className='editbar';
editbar.innerHTML='<button id="textMode">编辑文字</button><button id="saveRevision" hidden>保存修订版</button><button id="saveFormat" hidden>保存并生成 Word/PDF</button><button id="textHistory">版本与差异</button><button id="editParent" hidden>修改对应文字稿</button><span id="textState" role="status"></span><span id="formatState" role="status"></span>';
$('#rightPane').prepend(editbar);
let editing=false,editInfo=null,editText='',editOriginal='',editDirty=false,editBusy=false,editEpoch=0,requestId=null;
let dirtyDialogOpen=false,editorPending=Promise.resolve();
let displayed={aid:artifact('right').artifact_id,index:$('#rightPosition').value};
const state=t=>{$('#textState').textContent=t;};
const formatState=t=>{$('#formatState').textContent=t;};
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
 $('#saveRevision').hidden=!editing;$('#saveFormat').hidden=!editing;
 $('#textMode').textContent=editing?'返回阅读':'编辑文字';
 if(a.format!=='markdown'){editing=false;$('#saveRevision').hidden=true;$('#saveFormat').hidden=true;return;}
 if(!serverMode){$('#textMode').disabled=true;$('#textHistory').disabled=true;state('离线包仅供阅读；请在线保存修订，不能写入服务器。');return;}
 $('#textMode').disabled=true;editInfo=null;
 return api(revisionURL+'/text/'+a.artifact_id+'?locator='+encodeURIComponent(JSON.stringify(position('right').locator))).then(info=>{
  if(epoch!==editEpoch)return;editInfo=info;let page=info.pages.find(p=>stable(p.locator)===stable(position('right').locator));
  if(!page){state('当前位置缺少明确映射，不能逐页修补。');return;}
  editOriginal=page.text;editText=page.text;editDirty=false;requestId=null;
  $('#textMode').disabled=false;state(info.head_id!==a.artifact_id?'历史版本只读；可在版本与差异中恢复为新版本。':'已保存 · 仅修改当前来源位置');
  if(editing)mountEditor();
 }).catch(e=>{if(epoch===editEpoch){editing=false;$('#saveRevision').hidden=true;$('#saveFormat').hidden=true;state('不可编辑：'+e.message);}});
}
function mountEditor(){
 let box=$('#rightContent');box.replaceChildren();let area=document.createElement('textarea');area.id='textEditor';area.spellcheck=false;area.setAttribute('aria-label','当前页 Markdown 文字');area.value=editText;area.readOnly=editBusy||editInfo.head_id!==editInfo.artifact_id;
 area.oninput=()=>{editText=area.value;editDirty=editText!==editOriginal;requestId=null;state(editDirty?'有未保存修改':'已保存');};box.append(area);area.focus();
 $('#saveRevision').hidden=false;$('#saveFormat').hidden=false;
 $('#saveRevision').disabled=area.readOnly;$('#saveFormat').disabled=area.readOnly;
}
async function chooseDirty(){
 if(!editDirty)return true;
 if(dirtyDialogOpen)return false;dirtyDialogOpen=true;
 return new Promise(resolve=>{let d=document.createElement('dialog');d.className='revision-dialog';let p=document.createElement('p');p.textContent='当前文字有未保存修改。请选择保存、放弃或取消切换。';d.append(p);
  for(let [label,action] of [['保存','save'],['放弃','discard'],['取消','cancel']]){let b=document.createElement('button');b.textContent=label;b.onclick=async()=>{if(action==='save'){b.disabled=true;if(!await saveRevision(false)){b.disabled=false;return;}}if(action==='discard'){editDirty=false;editText=editOriginal;}dirtyDialogOpen=false;d.close();d.remove();resolve(action!=='cancel');};d.append(b);}d.oncancel=e=>{e.preventDefault();dirtyDialogOpen=false;d.close();d.remove();resolve(false);};document.body.append(d);d.showModal();});
}
async function installProject(aid,loc,preserveEditor=false){
 let p=await api(revisionURL);Object.assign(P,p);arts.splice(0,arts.length,...p.artifacts);P.artifacts=arts;
 for(let side of ['left','right']){let select=$('#'+side+'Artifact'),selected=select.value;for(let a of [...arts].reverse()){if(!a.recycled&&['markdown','docx','pdf'].includes(a.format)&&![...select.options].some(o=>o.value===a.artifact_id)){let o=document.createElement('option');o.value=a.artifact_id;o.textContent=(a.display_name||a.name)+' · 第'+a.version+'版';select.insertBefore(o,select.options[1]||null);}}select.value=selected;}
 if(preserveEditor)return;
 $('#rightArtifact').value=aid;positions('right');let a=artifact('right'),index=a.pages.findIndex(p=>stable(p.locator)===stable(loc));if(index>=0)$('#rightPosition').value=String(index);refresh('right');await editorPending;
}
function lockTextNavigation(value){for(let id of ['rightArtifact','rightPosition','rightPageInput','rightPagePrev','rightPageNext','compactRightPrev','compactRightNext','textMode','textHistory','saveRevision','saveFormat','commentFilter','errorFilter','markdownMode'])$('#'+id).disabled=value;}
async function saveRevision(format){
 if(editBusy||!editInfo)return false;editBusy=true;lockTextNavigation(true);state('正在保存修订…');if($('#textEditor'))$('#textEditor').readOnly=true;
 let loc=position('right').locator,template=editInfo.template||P.selected_template;
 try{
  requestId=requestId||uuid();let result=await post(revisionURL+'/text-revisions',{request_id:requestId,parent_artifact_id:editInfo.artifact_id,parent_sha256:editInfo.sha256,head_id:editInfo.head_id,head_sha256:editInfo.head_sha256,locator:loc,text:editText,reviewer_type:$('#reviewer').value});
  editDirty=false;editOriginal=editText;editing=false;await installProject(result.artifact_id,loc);state(result.no_change?'无变化，未创建重复版本':'已保存修订版');
  if(format){if(!template){formatState('修订已保存；未选择模板，请返回项目选择模板后排版。');return true;}
   try{let job=await post(revisionURL+'/format',{source_artifact_id:result.artifact_id,template});formatState('修订已保存 · 排版排队中');watchFormat(job.task_id);}catch(e){formatState('修订已保存；排版启动失败，可单独重试：'+e.message);}}
  return true;
 }catch(e){state('保存失败：'+e.message+'；草稿仍保留。');return false;}finally{editBusy=false;lockTextNavigation(false);$('#textMode').disabled=!editInfo;if($('#textEditor'))$('#textEditor').readOnly=editInfo.head_id!==editInfo.artifact_id;}
}
async function watchFormat(tid){
 let timer=setInterval(async()=>{try{let p=await api(revisionURL),t=p.tasks.find(t=>t.task_id===tid);if(!['QUEUED','RUNNING'].includes(t?.status)){clearInterval(timer);let loc=position('right').locator;await installProject(artifact('right').artifact_id,loc,true);formatState(t.status==='SUCCEEDED'?'修订已保存 · Word/PDF 排版成功（预览另行生成）':'修订已保存；排版'+t.status+'，请在项目任务中重试。');}}catch(e){clearInterval(timer);formatState('修订已保存；排版状态读取失败：'+e.message);}},1000);
}
$('#textMode').onclick=async()=>{if(!editInfo||!await chooseDirty())return;editing=!editing;$('#textMode').textContent=editing?'返回阅读':'编辑文字';if(editing)mountEditor();else{render('right');$('#saveRevision').hidden=true;$('#saveFormat').hidden=true;}};
$('#saveRevision').onclick=()=>saveRevision(false);$('#saveFormat').onclick=()=>saveRevision(true);
$('#editParent').onclick=async()=>{let p=parentMarkdown(artifact('right'));if(p&&await chooseDirty()){editing=false;await installProject(p.artifact_id,{kind:'document'});}};
$('#textHistory').onclick=async()=>{
 if(!editInfo)return;let info=editInfo,d=document.createElement('dialog');d.className='revision-dialog history-dialog';let h=document.createElement('h3');h.textContent='历史版本与差异';d.append(h);let select=document.createElement('select');select.id='revisionHistory';for(let item of info.history){let o=document.createElement('option');o.value=item.artifact_id;o.textContent='第'+item.version+'版'+(item.artifact_id===info.artifact_id?'（当前）':'');select.append(o);}d.append(select);let pre=document.createElement('pre');pre.id='revisionDiff';d.append(pre);
 async function diff(){try{let data=await api(revisionURL+'/text-diff/'+info.artifact_id+'?against='+select.value);pre.textContent=data.diff||'文字没有差异。';}catch(e){pre.textContent=e.message;}}select.onchange=diff;diff();
 let view=document.createElement('button');view.textContent='查看所选版本';view.onclick=async()=>{if(await chooseDirty()){d.close();d.remove();editing=false;await installProject(select.value,position('right').locator);}};d.append(view);
 let restore=document.createElement('button');restore.id='restoreRevision';restore.textContent='恢复为新版本';restore.onclick=async()=>{if(!await chooseDirty())return;try{let head=await api(revisionURL+'/text/'+info.head_id);let result=await post(revisionURL+'/text-revisions',{request_id:uuid(),parent_artifact_id:head.artifact_id,parent_sha256:head.sha256,head_id:head.head_id,head_sha256:head.head_sha256,restore_artifact_id:select.value,reviewer_type:$('#reviewer').value});let loc=position('right').locator;d.close();d.remove();editing=false;await installProject(result.artifact_id,loc);state(result.no_change?'所选内容与最新稿相同，未重复创建':'已将历史内容恢复为新版本');}catch(e){pre.textContent='恢复失败：'+e.message;}};d.append(restore);
 let close=document.createElement('button');close.textContent='关闭';close.onclick=()=>{d.close();d.remove();};d.append(close);document.body.append(d);d.showModal();
};
// Guard right-side object changes before replacing the editor; left navigation stays independent.
for(let id of ['rightArtifact','rightPosition','commentFilter','errorFilter','markdownMode']){
 let control=$('#'+id),handler=control.onchange;control.onchange=async event=>{let next=control.value,old=id==='rightArtifact'?displayed.aid:id==='rightPosition'?displayed.index:control.dataset.previous;
  if(editDirty){if(old!==undefined)control.value=old;if(!await chooseDirty()){compactLabels();return;}control.value=next;}
  editing=false;handler?.call(control,event);control.dataset.previous=control.value;
 };control.dataset.previous=control.value;
}
const originalRefresh=refresh;refresh=function(side){originalRefresh(side);if(!side||side==='right')editorPending=updateEditor();};
window.addEventListener('beforeunload',e=>{if(editDirty){e.preventDefault();e.returnValue='';}});
$('#back').addEventListener('click',async e=>{if(editBusy){e.preventDefault();state('正在保存，请稍候再离开。');return;}if(editDirty){let href=e.currentTarget.href;e.preventDefault();if(await chooseDirty())location.href=href;}});
updateEditor();

for(let side of ['left','right'])$('#'+side+'PageInput').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();jump(side,e.target.value);}};
