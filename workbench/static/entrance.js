// Product entrance: CSS 3D composition over a pointer-responsive WebGL field.
export function setupEntrance() {
  const gate=document.createElement('section');gate.id='entrance';gate.setAttribute('aria-label','选题研究工作站入口');
  gate.innerHTML=`<canvas id="entrance-field" aria-hidden="true"></canvas><div class="entrance-grain" aria-hidden="true"></div>
    <div class="entrance-top"><span>STORY NOTES</span><span>观察 · 思考 · 开始创作</span></div>
    <div class="entrance-layout"><div class="entrance-copy"><p class="entrance-kicker">给尚未写下的故事，一个开始。</p><h1>选题研究<br><em>工作站</em><span class="entrance-period">。</span></h1><p class="entrance-description">从榜单发现线索，在作品之间寻找自己的方向。<br>让一个念头，成为值得动笔的故事。</p><div class="entrance-actions"><button id="enter-research">进入选题研究 <span>↗</span></button><button id="enter-market">先逛逛榜单 <span>→</span></button></div><p class="entrance-error" role="status"></p></div>
    <div class="entrance-scene" aria-hidden="true"><div class="entrance-orbit"></div><div class="entrance-object"><div class="entrance-backplate"></div><div class="entrance-art"><img src="/static/assets/paper-sculpture.png" alt="" width="1122" height="1402"><div class="entrance-art-label">THE UNWRITTEN<br><strong>故事尚未定形</strong></div><div class="entrance-sheen"></div></div><div class="entrance-tag">灵感 / IN PROGRESS</div><span class="entrance-folio">001—∞</span></div></div></div>
    <div class="entrance-bottom"><span>一本属于你的创作手记</span><span>移动指针，轻触故事的轮廓 ↗</span></div>`;
  document.body.append(gate);
  const outside=[...document.querySelectorAll('body > header,body > main,#market-view')];
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');let frame=0,visible=true,targetX=0,targetY=0,x=0,y=0,last=0,elapsed=0;
  const canvas=gate.querySelector('canvas'),gl=canvas.getContext('webgl',{alpha:false,antialias:false,powerPreference:'low-power'});
  let uniforms;
  if(gl){
    const vertex='attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
    const fragment=`precision mediump float;uniform vec2 resolution;uniform vec2 pointer;uniform float time;
    void main(){vec2 uv=gl_FragCoord.xy/resolution;vec2 p=(uv-.5)*vec2(resolution.x/resolution.y,1.);vec2 m=pointer*vec2(resolution.x/resolution.y,1.);
    float wave=sin(p.x*4.+p.y*3.+time*.24)+sin(p.y*5.-p.x*2.-time*.18);
    float ribbon=exp(-pow((p.y-p.x*.22+wave*.055-.06)*8.,2.));
    float glow=exp(-length(p-m)*2.7);vec3 paper=vec3(.957,.941,.906);
    vec3 color=mix(paper,vec3(.90,.76,.48),ribbon*.24);
    color=mix(color,vec3(.86,.40,.29),glow*ribbon*.24);
    color=mix(color,vec3(.40,.47,.69),smoothstep(.3,.95,uv.x)*(1.-uv.y)*.11);
    float lines=pow(.5+.5*sin((p.y-p.x*.22+wave*.055)*120.),18.);
    color-=vec3(lines*ribbon*.035);gl_FragColor=vec4(color,1.);}`;
    const compile=(type,source)=>{const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);return null;}return shader;};
    const vs=compile(gl.VERTEX_SHADER,vertex),fs=compile(gl.FRAGMENT_SHADER,fragment);
    if(vs&&fs){const program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);gl.deleteShader(vs);gl.deleteShader(fs);
      if(gl.getProgramParameter(program,gl.LINK_STATUS)){gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);const pos=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(pos);gl.vertexAttribPointer(pos,2,gl.FLOAT,false,0,0);uniforms={resolution:gl.getUniformLocation(program,'resolution'),pointer:gl.getUniformLocation(program,'pointer'),time:gl.getUniformLocation(program,'time')};}
    }
  }
  function resize(){const dpr=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(innerWidth*dpr);canvas.height=Math.round(innerHeight*dpr);if(gl)gl.viewport(0,0,canvas.width,canvas.height);}
  function draw(now){frame=0;if(!visible||document.hidden)return;if(now-last>=30||reduced.matches){const delta=Math.min(now-last,50);last=now;if(!reduced.matches)elapsed+=delta/1000;x+=(targetX-x)*.12;y+=(targetY-y)*.12;gate.style.setProperty('--tilt-x',`${reduced.matches?0:-y*12}deg`);gate.style.setProperty('--tilt-y',`${reduced.matches?0:x*16}deg`);gate.style.setProperty('--glow-x',`${50+x*80}%`);gate.style.setProperty('--glow-y',`${50+y*80}%`);if(uniforms){gl.uniform2f(uniforms.resolution,canvas.width,canvas.height);gl.uniform2f(uniforms.pointer,x,-y);gl.uniform1f(uniforms.time,elapsed);gl.drawArrays(gl.TRIANGLES,0,6);}}if(!reduced.matches)frame=requestAnimationFrame(draw);}
  function start(){if(visible&&!document.hidden&&!frame)frame=requestAnimationFrame(draw);}
  gate.addEventListener('pointermove',e=>{if(e.pointerType!=='mouse'||reduced.matches)return;targetX=e.clientX/innerWidth-.5;targetY=e.clientY/innerHeight-.5;});
  gate.addEventListener('pointerleave',()=>{targetX=targetY=0;});
  window.addEventListener('resize',()=>{resize();start();});
  document.addEventListener('visibilitychange',()=>{cancelAnimationFrame(frame);frame=0;start();});
  reduced.addEventListener('change',()=>{cancelAnimationFrame(frame);frame=0;targetX=targetY=x=y=0;start();});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();uniforms=null;});
  function show(){visible=true;gate.hidden=false;outside.forEach(e=>e.inert=true);document.body.classList.add('entrance-open');resize();start();gate.querySelector('#enter-research').focus({preventScroll:true});}
  function enter(view){visible=false;cancelAnimationFrame(frame);frame=0;gate.hidden=true;outside.forEach(e=>e.inert=false);document.body.classList.remove('entrance-open');const button=document.querySelector(`[data-workspace="${view}"]`);button.click();button.focus();}
  gate.querySelector('#enter-research').onclick=()=>enter('research');gate.querySelector('#enter-market').onclick=()=>enter('market');
  const back=document.createElement('button');back.id='return-entrance';back.textContent='封面';back.onclick=show;document.querySelector('body > header').append(back);show();
}
