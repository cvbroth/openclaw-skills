'use strict';
// Auxiliary controls never rerender documents or discard editor state.
let panelScroll=null;
const paneScroll=()=>['left','right'].map(s=>({top:$('#'+s+'Pane').scrollTop,left:$('#'+s+'Pane').scrollLeft}));
function openAuxPanel(group='comments'){
 if($('#auxPanel').hidden)panelScroll={before:paneScroll(),clamped:null};
 layoutChange(()=>{document.body.classList.add('aux-open');$('#auxPanel').hidden=false;$('#toggleAux').setAttribute('aria-expanded','true');for(let section of document.querySelectorAll('[data-section]'))section.hidden=section.dataset.section!==group;for(let tab of document.querySelectorAll('[data-panel]'))tab.setAttribute('aria-selected',String(tab.dataset.panel===group));});
 if(panelScroll&&!panelScroll.clamped)panelScroll.clamped=paneScroll();
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
