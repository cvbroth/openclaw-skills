'use strict';
// Page-level source evidence only. Array order is the registered text assembly order.
function explicitSources(a,p){
 const valid=n=>Number.isInteger(n)&&n>0;
 if(p.source_page!==undefined){if(!valid(p.source_page))return [];if(p.source_pages!==undefined&&(!Array.isArray(p.source_pages)||!p.source_pages.includes(p.source_page)))return [];}
 if(p.source_pages!==undefined)return Array.isArray(p.source_pages)&&p.source_pages.length&&p.source_pages.every(valid)?[...new Set(p.source_pages)]:[];
 if(valid(p.source_page))return [p.source_page];
 return p.locator?.kind==='physical_page'&&valid(p.locator.page)?[p.locator.page]:[];
}
function sourceMatches(a,n){return a.pages.map((p,i)=>({p,i})).filter(({p})=>explicitSources(a,p).includes(n));}
function sourceMessage(text){$('#rightNotice').textContent=text;}
function readingPlaceholder(box,text){let d=document.createElement('div');d.className='placeholder';d.textContent=text;box.append(d);}
function renderSourceReading(){
 const a=artifact('right'),n=sourceReading.page,token=++tokens.right,box=$('#rightContent');box.replaceChildren();
 $('#diagnostics').querySelectorAll('[data-side="right"]').forEach(d=>d.remove());
 const matches=a.format==='markdown'?sourceMatches(a,n):[];
 positions('right');let selected=matches.find(({p})=>stable(p.locator)===sourceReading.selected);
 if(!selected)sourceReading.selected=null;
 $('#rightPosition').value=String((selected||matches[0])?.i??-1);
 let printed=source.pages.find(p=>p.physical_page===n||p.locator?.kind==='physical_page'&&p.locator.page===n)?.printed_page;
 let message='原件物理第'+n+'页 · 匹配'+matches.length+'个片段 · '+(printed!=null?'印刷页码 '+printed:'印刷页码未登记');
 const unknown=a.pages.filter(p=>!explicitSources(a,p).length).length;if(unknown)message+=' · 另有'+unknown+'个片段来源未知';
 if($('#errorFilter').value||$('#commentFilter').value)message+=' · 此阅读视图忽略错误/评论筛选';
 sourceMessage(message);
 if(a.path){let download=link(box,a.path,'下载文字版本');download.download=a.name;download.removeAttribute('target');if(serverMode)download.href='/api/projects/'+P.project_id+'/download/'+a.artifact_id;}
 if(!matches.length){readingPlaceholder(box,a.pages.some(p=>explicitSources(a,p).length)?'该原件物理页没有登记的对应文字。请使用文字位置独立查看其他片段。':'此文字版本缺少可靠来源页映射，不能按原件页对应阅读。请使用文字位置独立查看和编辑。');return;}
 let order=document.createElement('p');order.className='muted';order.textContent='按文字版本登记顺序连续阅读；先选中具体片段，再编辑或评论。';box.append(order);
 for(const {p,i} of matches){
  let card=document.createElement('article');card.className='source-fragment';card.dataset.locator=stable(p.locator);card.dataset.index=i;card.classList.toggle('selected',sourceReading.selected===stable(p.locator));
  let heading=document.createElement('div');heading.className='fragment-heading';let title=document.createElement('strong');title.textContent='文字位置 '+(i+1)+' · 来源物理页 '+explicitSources(a,p).join('、');heading.append(title);
  let button=document.createElement('button');button.textContent=card.classList.contains('selected')?'已选中':'选中片段';button.setAttribute('aria-pressed',String(card.classList.contains('selected')));button.onclick=()=>selectSourceFragment(i);heading.append(button);card.append(heading);
  if(explicitSources(a,p).length>1){let note=document.createElement('p');note.className='fragment-note';note.textContent='跨页片段：完整显示原登记内容，尚无更细映射，未按本页拆分。';card.append(note);}
  if(p.error){let status=document.createElement('p');status.className='fragment-note';status.textContent='此片段处理失败 / 存在错误：'+label(typeof p.error==='boolean'?({local:'本地处理错误',remote:'远端处理错误'}[p.error_category]||'已登记处理错误'):p.error.code||p.error.message||p.error);card.append(status);}
  let content=document.createElement('div');content.className='fragment-body';card.append(content);box.append(card);
  if(!p.data){readingPlaceholder(content,'此登记片段没有可读取的文字资源。');continue;}
  content.textContent='正在加载此片段…';
  loading=loading.then(()=>new Promise(resolve=>{
   if(token!==tokens.right){resolve();return;}
   let script=document.createElement('script');script.src='../'+p.data;
   const finish=()=>{delete window.PROJECT_PAGE;script.remove();resolve();};
   script.onload=()=>{if(token===tokens.right){content.replaceChildren();appendReadingText(content,window.PROJECT_PAGE||{});zoom('right');if(window.PROJECT_PAGE?.raw_path){let d=document.createElement('details'),summary=document.createElement('summary');summary.textContent='文字位置 '+(i+1)+' · 原始资料';d.append(summary);d.dataset.side='right';link(d,window.PROJECT_PAGE.raw_path,'打开诊断');$('#diagnostics').append(d);}}finish();};
   script.onerror=()=>{if(token===tokens.right){content.replaceChildren();readingPlaceholder(content,'此片段文字加载失败，请重试来源页定位。');}finish();};document.head.append(script);
  }));
 }
}
async function selectSourceFragment(index){
 if(editBusy||!await chooseDirty())return;
 let p=artifact('right').pages[index];if(!p||!explicitSources(artifact('right'),p).includes(sourceReading.page))return;
 save();editing=false;sourceReading.selected=stable(p.locator);$('#rightPosition').value=String(index);refresh('right');await editorPending;
}
async function findMappedSource(value){
 if(editBusy)return;const n=Number(value),count=source.physical_index?.count||source.pages.length;
 if(!/^\d+$/.test(String(value))||!Number.isInteger(n)||n<1||n>count){pageNavigationNotice('来源页必须是原件物理页，范围1–'+count+'；未更换当前内容。');return;}
 if(artifact('right').format!=='markdown'){pageNavigationNotice('请选择文字版本后按来源页阅读。');return;}
 if(!await chooseDirty()){$('#sourcePageLookup').value=sourceReading.page||'';return;}
 save();editing=false;sourceReading={active:true,page:n,selected:null};$('#sourcePageLookup').value=n;pageNavigationNotice('');refresh('right');
 if(innerWidth<=600)document.body.classList.add('result');
}
$('#findSourcePage').onclick=()=>findMappedSource($('#sourcePageLookup').value);
$('#sourcePageLookup').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findMappedSource(e.target.value);}};
$('#locateSelectedSource').onclick=()=>{const p=position('left'),n=p.physical_page||(p.locator?.kind==='physical_page'?p.locator.page:null);if(artifact('left').artifact_id===source.artifact_id&&n)findMappedSource(String(n));else pageNavigationNotice('左侧当前不是可核实的原件物理页，请独立输入来源页。');};
