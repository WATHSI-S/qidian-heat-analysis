const box=document.querySelector('#drawerBody');
const selected=new URLSearchParams(location.search).get('project');
let books,projects;
async function request(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'操作失败');return data;}
// The original dashboard owns its drawer; attach the local action after it renders.
new MutationObserver(async()=>{
 if(!box.querySelector('h3')||box.querySelector('#add-reference')||!box.textContent.includes('作品简介'))return;
 const title=document.querySelector('#drawerTitle').textContent;
 const author=[...box.querySelectorAll('dt')].find(e=>e.textContent==='作者')?.nextElementSibling?.textContent;
 if(!author)return;
 const area=document.createElement('section');area.id='add-reference';area.className='local-research';box.prepend(area);
 try{
   projects=await request('/projects');
   const select=document.createElement('select');select.setAttribute('aria-label','加入哪个选题');
   select.add(new Option('新建选题并加入',''));
   projects.forEach(p=>select.add(new Option(p.name,p.id)));
   if(projects.some(p=>p.id===selected))select.value=selected;
   const button=document.createElement('button');button.textContent='加入选题对标';
   const status=document.createElement('p');status.setAttribute('role','status');area.append(select,button,status);
   button.onclick=async()=>{button.disabled=true;try{let pid=select.value;if(!pid){const p=await request('/projects','POST',{name:'从《'+title+'》开始的选题'});pid=p.id;select.add(new Option(p.name,pid));select.value=pid;}await request('/projects/'+pid+'/from-ranking','POST',{title,author});status.textContent='已加入。';const link=document.createElement('button');link.textContent='去研究这本作品 →';link.onclick=()=>{if(parent!==window)parent.postMessage({type:'open-research',id:pid},location.origin);else location.href='/?project='+encodeURIComponent(pid);};status.append(link);}catch(e){status.textContent=e.message;}finally{button.disabled=false;}};
 }catch(e){area.textContent=e.message;}
}).observe(box,{childList:true,subtree:true});
