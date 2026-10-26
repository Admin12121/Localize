/* The original SVG geometry is stored unchanged in scene-original.svg.
 * scene-dashboard.svg removes its sample findings; this controller binds
 * only values actually reported by the local companion.
 */
const SVG_NS='http://www.w3.org/2000/svg';
let sceneNode=null,sceneLoading=null,sceneKey='';
function sceneLabel(group,x,y,value,anchor='start',cls='scene-runtime-text'){
 const element=document.createElementNS(SVG_NS,'text');
 element.setAttribute('x',String(x));element.setAttribute('y',String(y));
 element.setAttribute('text-anchor',anchor);element.setAttribute('class',cls);
 element.textContent=String(value);group.appendChild(element);return element;
}
async function loadScene(){
 if(sceneNode)return sceneNode;
 if(sceneLoading)return sceneLoading;
 sceneLoading=(async()=>{
  const response=await fetch('/assets/scene.svg',{credentials:'same-origin'});
  if(!response.ok)throw Error('SVG asset is not available ('+response.status+')');
  const body=await response.text();
  // The pasted Vue-rendered SVG omits the explicit SVG xmlns. Add only the
  // namespace required for standalone XML parsing; its paths remain intact.
  const xml=body.includes('xmlns="http://www.w3.org/2000/svg"')
   ? body : body.replace(/^<svg\b/, '<svg xmlns="http://www.w3.org/2000/svg"');
  const doc=new DOMParser().parseFromString(xml,'image/svg+xml');
  if(doc.querySelector('parsererror'))throw Error('The supplied SVG did not parse.');
  const svg=document.importNode(doc.documentElement,true);
  if(svg.localName!=='svg'||svg.getAttribute('viewBox')!=='0 0 1310 1105')
   throw Error('Unexpected SVG asset.');
  // Canvas dots belong to the original Vue renderer; recreate only that
  // background texture without changing any supplied path coordinates.
  svg.querySelectorAll('foreignObject,script,animate,animateTransform').forEach(x=>x.remove());
  const defs=svg.querySelector('defs');
  const pattern=document.createElementNS(SVG_NS,'pattern');
  pattern.setAttribute('id','localize-scene-dots');pattern.setAttribute('width','17');
  pattern.setAttribute('height','17');pattern.setAttribute('patternUnits','userSpaceOnUse');
  const dot=document.createElementNS(SVG_NS,'circle');
  dot.setAttribute('cx','1');dot.setAttribute('cy','1');dot.setAttribute('r','.75');
  dot.setAttribute('fill','#487780');dot.setAttribute('opacity','.27');
  pattern.append(dot);defs.append(pattern);
  const field=document.createElementNS(SVG_NS,'rect');
  for(const [key,value] of Object.entries({x:'0',y:'0',width:'1310',height:'1105',fill:'url(#localize-scene-dots)','pointer-events':'none'}))
   field.setAttribute(key,value);
  const ground=svg.querySelector('.scene-stage__ground');
  ground?.insertAdjacentElement('afterend',field);
  svg.removeAttribute('width');svg.removeAttribute('height');
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  svg.removeAttribute('role');svg.setAttribute('aria-hidden','true');
  document.getElementById('bridge-scene').replaceChildren(svg);
  sceneNode=svg;sceneKey='';
  return svg;
 })().catch(error=>{
  sceneLoading=null;
  document.getElementById('bridge-scene').textContent='SVG unavailable: '+error.message;
  throw error;
 });
 return sceneLoading;
}
function sceneCounts(s){
 const jobs=Array.isArray(s.jobs)?s.jobs:[];
 const edits=Array.isArray(s.edits)?s.edits:[];
 const tasks=Array.isArray(s.tasks)?s.tasks:[];
 const servers=Array.isArray(s.integrations?.servers)?s.integrations.servers:[];
 const skills=Array.isArray(s.integrations?.skills)?s.integrations.skills:[];
 const targets=s.targets&&typeof s.targets==='object'?Object.keys(s.targets):[];
 const pendingJobs=jobs.filter(x=>x.state==='pending').length;
 const running=jobs.filter(x=>x.state==='running'||x.state==='approved').length;
 const completed=jobs.filter(x=>x.state==='completed').length;
 const failed=jobs.filter(x=>['failed','cancelled','timed_out','recovery_required'].includes(x.state)).length;
 const settled=jobs.filter(x=>!['pending','approved','running'].includes(x.state)).length;
 return {
  sources:[
   ['WORKSPACE',s.workspace?1:0],['WEB TARGETS',targets.length],
   ['MCP ADAPTERS',servers.filter(x=>x.enabled).length],
   ['TRUSTED SKILLS',skills.length],['COMMAND JOBS',jobs.length],
   ['SAVED TASKS',tasks.length],['PENDING EDITS',edits.length]
  ],
  outcomes:[
   ['NEEDS APPROVAL',pendingJobs+edits.length],
   ['RUNNING',running],['COMPLETED',completed],
   ['FAILED / CANCELLED',failed],['SAVED TASKS',tasks.length]
  ],
  jobs:jobs.length,settled,pending:pendingJobs+edits.length,
  status:s.paused?'PAUSED':s.workspace?'READY':'NO PROJECT',
  workspace:s.workspace||'No project selected',
  docker:s.docker?.ready?'Docker ready':'Docker not ready',
  integration:servers.filter(x=>x.enabled).length,
  paused:!!s.paused
 };
}
function paintScene(s){
 if(!sceneNode)return;
 const c=sceneCounts(s),signature=JSON.stringify(c);
 if(sceneKey===signature)return;sceneKey=signature;
 const svg=sceneNode;
 svg.querySelectorAll('.scene-runtime-overlay').forEach(x=>x.remove());
 const group=document.createElementNS(SVG_NS,'g');
 group.setAttribute('class','scene-runtime-overlay');
 group.setAttribute('pointer-events','none');
 svg.append(group);
 sceneLabel(group,42,76,'INPUT SOURCES','start','scene-head');
 c.sources.forEach(([name,count],i)=>{
  const y=132+i*113.37;
  sceneLabel(group,225,y-19,Number(count).toLocaleString(),'end','scene-side-number');
  sceneLabel(group,225,y+11,name,'end','scene-side-label');
 });
 sceneLabel(group,1080,118,'OUTCOMES','start','scene-head');
 c.outcomes.forEach(([name,count],i)=>{
  const y=[246,356,614,724,834][i];
  sceneLabel(group,1078,y-18,name,'start','scene-side-label');
  sceneLabel(group,1078,y+27,Number(count).toLocaleString(),'start','scene-outcome-number');
 });
 sceneLabel(group,1078,527,'HISTORY','start','scene-head');
 sceneLabel(group,655,252,'LOCALIZE · '+c.workspace,'middle','scene-top-note');
 sceneLabel(group,655,293,c.status,'middle',c.paused?'scene-status-paused':'scene-status');
 sceneLabel(group,655,877,'Live companion snapshot · rings are a visual flow schematic','middle','scene-foot-note');
 const ringNumbers=svg.querySelectorAll('.scene-ring__number');
 [c.jobs,c.settled,c.pending].forEach((n,i)=>{if(ringNumbers[i])ringNumbers[i].textContent=Number(n).toLocaleString()});
 const ringCaptions=svg.querySelectorAll('.scene-ring__label');
 ['Recorded','Settled','Needs review'].forEach((n,i)=>{if(ringCaptions[i])ringCaptions[i].textContent=n});
 const ringDetails=svg.querySelectorAll('.scene-ring__sublabel');
 ['Command jobs','Terminal states','Pending approvals'].forEach((n,i)=>{if(ringDetails[i])ringDetails[i].textContent=n});
 const scoreReason=svg.querySelectorAll('.scene-score__reason');
 if(scoreReason[0])scoreReason[0].textContent='Active project · verified local state';
 if(scoreReason[1])scoreReason[1].textContent=c.docker;
 const scoreVal=svg.querySelector('[data-role="value"]');
 if(scoreVal)scoreVal.textContent='';
 const scoreScale=svg.querySelector('[data-role="scale"]');
 if(scoreScale)scoreScale.textContent='';
 const scoreBand=svg.querySelector('[data-role="band"]');
 if(scoreBand)scoreBand.textContent='';
 const bands=svg.querySelectorAll('.scene-score__caption textPath');
 ['Execution','Task history','File access','Docker status','Integrations'].forEach((name,i)=>{
  if(bands[i])bands[i].textContent=name;
 });
 document.getElementById('scene-caption').textContent=
  'Actual data · '+c.jobs+' command receipts · '+c.pending+' awaiting approval · '+c.integration+' enabled MCP adapters';
}
function updateScene(s){
 if(sceneNode){paintScene(s);return}
 if(sceneLoading)return;
 loadScene().then(()=>{if(state)paintScene(state)}).catch(()=>{});
}
