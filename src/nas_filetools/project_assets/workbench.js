'use strict';
// Auxiliary controls never rerender documents or discard editor state.
let panelScroll=null;
const paneScroll=()=>['left','right'].map(s=>({top:$('#'+s+'Pane').scrollTop,left:$('#'+s+'Pane').scrollLeft}));
function openAuxPanel(group='comments'){
 if($('#auxPanel').hidden)panelScroll={before:paneScroll(),clamped:null};
 layoutChange(()=>{document.body.classList.add('aux-open');$('#auxPanel').hidden=false;$('#toggleAux').setAttribute('aria-expanded','true');for(let section of document.querySelectorAll('[data-section]'))section.hidden=section.dataset.section!==group;for(let tab of document.querySelectorAll('[data-panel]'))tab.setAttribute('aria-selected',String(tab.dataset.panel===group));});
 requestAnimationFrame(()=>{if(panelScroll&&!panelScroll.clamped)panelScroll.clamped=paneScroll();});
 if(group==='comments')$('#commentPanel').open=true;
 if(group==='technical'){document.querySelector('.technical').open=true;updateTechnical();}
 if(group==='versions')loadHistory();
}
function closeAuxPanel(){let current=paneScroll(),restore=current.map((p,i)=>panelScroll?.clamped&&p.top===panelScroll.clamped[i].top&&p.left===panelScroll.clamped[i].left?panelScroll.before[i]:p);layoutChange(()=>{document.body.classList.remove('aux-open');$('#auxPanel').hidden=true;$('#toggleAux').setAttribute('aria-expanded','false');},restore);panelScroll=null;}
$('#toggleAux').onclick=()=>$('#auxPanel').hidden?openAuxPanel():closeAuxPanel();
$('#closeAux').onclick=()=>{closeAuxPanel();$('#toggleAux').focus();};
for(let tab of document.querySelectorAll('[data-panel]'))tab.onclick=()=>openAuxPanel(tab.dataset.panel);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&!$('#auxPanel').hidden)closeAuxPanel();});
$('#commentPanel').open=true;document.querySelector('.technical').open=false;$('#qualityDetails').open=false;
$('#closeQuality').onclick=()=>{$('#qualityDetails').open=false;};
function explicitSources(a,p,seen=new Set()){
 if(p.source_page)return [p.source_page];
 if(Array.isArray(p.source_pages))return p.source_pages;
 if(p.locator?.kind==='physical_page')return [p.locator.page];
 // Output mappings only: never infer output page from parent/source page count.
 return [];
}
function findMappedSource(n){
 let a=artifact('right'),candidates=[];
 if(!Number.isInteger(n)||n<1||n>(source.physical_index?.count||source.pages.length)){ $('#mapMessage').textContent='原件物理页越界。';return;}
 for(let [i,p] of a.pages.entries())if(explicitSources(a,p).includes(n))candidates.push({i,p});
 const picker=$('#sourceCandidates');picker.replaceChildren();picker.hidden=true;
 if(!a.pages.some(p=>explicitSources(a,p).length)){ $('#mapMessage').textContent='当前产物没有已登记的来源页映射，请独立定位。';return;}
 if(!candidates.length){$('#mapMessage').textContent='原件第'+n+'页没有对应结果；当前内容未更换。';return;}
 let visible=candidates.filter(x=>[...$('#rightPosition').options].some(o=>o.value===String(x.i)));
 if(!visible.length){$('#mapMessage').textContent='对应结果被当前产物筛选排除，请先清除筛选。';return;}
 function navigate(i){$('#rightPosition').value=String(i);$('#rightPosition').dispatchEvent(new Event('change'));}
 if(visible.length===1){let p=visible[0].p;$('#mapMessage').textContent='已找到登记映射'+(explicitSources(a,p).length>1?'（此输出位置对应多个原件页）':'')+'。';navigate(visible[0].i);}
 else{picker.hidden=false;let first=document.createElement('option');first.textContent='请选择对应内容（'+visible.length+'个）';first.value='';picker.append(first);for(let {i,p}of visible){let o=document.createElement('option');o.value=i;o.textContent='片段/输出位置'+(i+1)+' · '+p.label;picker.append(o);}picker.onchange=()=>{if(picker.value!=='')navigate(Number(picker.value));};$('#mapMessage').textContent='一页对应多个位置，请选择；没有自动猜选。';}
}
$('#findSourcePage').onclick=()=>findMappedSource(Number($('#sourcePageLookup').value));
$('#sourcePageLookup').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findMappedSource(Number(e.target.value));}};
$('#locateSelectedSource').onclick=()=>{let p=source.pages[Number($('#sourcePosition').value)];let n=p?.physical_page||p?.locator?.page;if(n){$('#sourcePageLookup').value=n;findMappedSource(n);}else $('#mapMessage').textContent='没有可定位的原件物理页。';};
