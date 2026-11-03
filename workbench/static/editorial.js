let step = 0, current = '', audio;
let sound = localStorage.getItem('editorial-sound') === 'on';
const questions = ['这一次，你想写怎样的故事？','哪些作品值得放到你的桌上？','你准备保留什么，又改变什么？','现在，你想怎样推进这个故事？'];
const hints = ['先写下那个让你想动笔的念头。细节可以慢慢补齐。','选出三到五本值得细读的作品，看看它们如何兑现读者的期待。','把原文的依据与自己的判断放在一起，寻找属于你的不同。','留下一个明确的决定，以及今天就能开始的下一步。'];
export function tone(done=false){if(!sound)return;try{audio ||= new AudioContext();audio.resume();[0,...(done?[.12]:[])].forEach((delay,i)=>{const o=audio.createOscillator(),g=audio.createGain(),t=audio.currentTime+delay;o.type='sine';o.frequency.value=i?660:440;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.035,t+.008);g.gain.exponentialRampToValueAtTime(.001,t+.10);o.connect(g);g.connect(audio.destination);o.start(t);o.stop(t+.11);});}catch{}}
export function setupSound(){const b=document.querySelector('#sound');const update=()=>{b.textContent=sound?'声音 · 开':'声音 · 关';b.setAttribute('aria-pressed',String(sound));};update();b.onclick=()=>{sound=!sound;localStorage.setItem('editorial-sound',sound?'on':'off');update();tone();};}
export function editorial(project,save){
 const editor=document.querySelector('#editor');
 if(current!==project.id){step=0;current=project.id;}
 const headings=[...editor.querySelectorAll(':scope > h2')], panels=[];
 for(const [i,h] of headings.entries()){
   const panel=document.createElement('section');panel.className='chapter';panel.id='chapter-'+i;
   h.before(panel);panel.append(h);while(panel.nextSibling&& !headings.includes(panel.nextSibling))panel.append(panel.nextSibling);
   h.textContent=questions[i];const hint=document.createElement('p');hint.className='chapter-hint';hint.textContent=hints[i];h.after(hint);panels.push(panel);
 }
 const introGrid=panels[0].querySelector('.grid');
 if(introGrid){const idea=introGrid.firstElementChild;introGrid.before(idea);const optional=document.createElement('details');const summary=document.createElement('summary');summary.textContent='补充创作背景 · 分类、阅读体验与素材优势';optional.append(summary);introGrid.before(optional);optional.append(introGrid);}
 const nav=document.createElement('nav');nav.className='chapter-nav';nav.setAttribute('aria-label','研究步骤');
 ['构思','对标','比较','决定'].forEach((label,i)=>{const b=document.createElement('button');b.textContent=`0${i+1} / ${label}`;b.onclick=()=>go(i);nav.append(b);});
 editor.prepend(nav);
 const footer=document.createElement('div');footer.className='chapter-footer';
 const progress=document.createElement('span'),back=document.createElement('button'),next=document.createElement('button');back.textContent='← 上一页';next.className='primary';footer.append(progress,back,next);editor.append(footer);
 const show=()=>{panels.forEach((p,i)=>p.hidden=i!==step);[...nav.children].forEach((b,i)=>{b.classList.toggle('active',i===step);b.setAttribute('aria-current',i===step?'step':'false');});progress.textContent=`研究手记 / 第 ${step+1} 页，共 4 页`;back.hidden=step===0;next.textContent=step===3?'保存这份选题卡 ✓':'保存，继续下一页 →';};
 async function go(i){back.disabled=next.disabled=true;try{await save();step=i;show();tone();nav.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}catch(e){document.querySelector('#message').textContent=e.message;}finally{back.disabled=next.disabled=false;}}
 back.onclick=()=>go(Math.max(0,step-1));next.onclick=async()=>{if(step<3)await go(step+1);else{try{await save();tone(true);}catch(e){document.querySelector('#message').textContent=e.message;}}};show();
}
