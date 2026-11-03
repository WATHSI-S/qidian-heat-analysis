export function navigation({save,getProject,openProject}){
 const main=document.querySelector('main'),market=document.querySelector('#market-view'),frame=document.querySelector('#market-frame');
 async function show(view){if(getProject())await save();const isMarket=view==='market';main.hidden=isMarket;market.hidden=!isMarket;document.querySelectorAll('[data-workspace]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.workspace===view)));if(isMarket){const pid=getProject()?.id||'';const url='/market/?project='+encodeURIComponent(pid);if(frame.getAttribute('src')!==url)frame.src=url;}}
 document.querySelectorAll('[data-workspace]').forEach(b=>b.onclick=()=>show(b.dataset.workspace).catch(e=>document.querySelector('#message').textContent=e.message));
 window.addEventListener('message',async e=>{if(e.origin!==location.origin||e.source!==frame.contentWindow||e.data?.type!=='open-research')return;try{await openProject(e.data.id);await show('research');}catch(error){document.querySelector('#message').textContent=error.message;}});
}
