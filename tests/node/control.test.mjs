import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext, Script} from 'node:vm';
const html=readFileSync('src/web_bridge/ui/control.html','utf8').replaceAll('\r\n','\n');
function element(tag,text){return {tag,text,children:[],append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}}}

test('website settings preserve the active command profile',async()=>{
 const source=html.match(/async function saveTargets\(next\)\{[^\n]+\}/)?.[0];assert(source);
 const profile={environment:'docker',shell:'sh',default_timeout:600,max_timeout:3600};let saved;
 const save=runInNewContext(source+';saveTargets',{ctfSaving:false,api:async(path,data)=>{if(!data)return {root:'C:/project',workspace:'demo',permissions:{read:true},profile};saved=data},$:()=>({checked:true}),refresh:async()=>{},say:()=>{}});
 await save({lab:'https://example.test'});
 assert.equal(saved.profile,profile);
});

test('shell command history shows exact command text and shell',async()=>{
 const source=html.match(/async function loadJob\(block\)\{[\s\S]*?\n\}\nfunction moreJobs/)?.[0];assert(source);
 const load=runInNewContext(source.replace(/\nfunction moreJobs$/,'')+';loadJob',{api:async()=>({job_id:'j',state:'completed',request:{command:'npm test',shell:'cmd',argv:['encoded-launcher'],environment:'host'},output:'passed',exit_code:0}),node:element,requestInfo:()=>'',action:()=>{}});
 const block={item:{job_id:'j',state:'completed'},open:true,isConnected:true,body:element('div')};await load(block);
 assert(block.body.children.some(e=>e.text==='cmd\nnpm test'));
});

test('MCP form sends only the selected transport with explicit tools',()=>{
 const source=html.match(/function mcpEntry\(\)\{[\s\S]*?\n\}/)?.[0];assert(source,'MCP form parser exists');
 const fields={'mcp-name':'editor','mcp-transport':'streamable_http','mcp-tools':'read_document, edit_document','mcp-timeout':'30','mcp-url':'http://127.0.0.1:8000/mcp','mcp-headers':'{"Authorization":"Bearer local"}','mcp-command':'stale command','mcp-args':'[]','mcp-env':'{}'};
 const parse=runInNewContext(source+';mcpEntry',{$:id=>({value:fields[id]}),JSON,Error,Number});
 const result=parse();assert.equal(result.transport,'streamable_http');assert.equal(result.command,undefined);assert.deepEqual(Array.from(result.enabled_tools),['read_document','edit_document']);assert.equal(result.headers.Authorization,'Bearer local');
 fields['mcp-tools']='';assert.equal(parse().enabled_tools.length,0);
 fields['mcp-headers']='broken';assert.throws(parse);
});

test('full controls bootstrap and render setup without invoking an external action',()=>{
 class Node {
  constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};this.value='';this.disabled=false}
  append(...values){this.children.push(...values)}
  replaceChildren(...values){this.children=values}
  addEventListener(){}
  setAttribute(name,value){this[name]=value}
  removeAttribute(name){delete this[name]}
  get firstChild(){return this.children[0]||null}
  querySelectorAll(selector){return this.children.filter(x=>selector==='.'+x.className)}
  insertBefore(row,cursor){const old=this.children.indexOf(row);if(old>=0)this.children.splice(old,1);const at=this.children.indexOf(cursor);this.children.splice(at<0?this.children.length:at,0,row)}
 }
 const elements=new Map();for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){assert(!elements.has(match[3]),'duplicate DOM id '+match[3]);const item=new Node(match[1]);item.value=match[2].match(/\bvalue="([^"]*)"/)?.[1]||'';elements.set(match[3],item)}
 elements.get('mcp-transport').value='stdio';
 const buttons=Array.from(html.matchAll(/<button\b[^>]*data-docker-action="([^"]+)"[^>]*>/g),match=>{const item=new Node('button');item.dataset.dockerAction=match[1];return item});
 const document={getElementById:id=>{assert(elements.has(id),'missing DOM id '+id);return elements.get(id)},createElement:tag=>new Node(tag),documentElement:new Node('html'),hidden:false,addEventListener:()=>{},querySelector:()=>null,querySelectorAll:selector=>selector.startsWith('[data-docker-action')?buttons:[]};
 const fixture={paused:false,platform:'Windows',root:'C:/fixture',workspace:'fixture',permissions:{image:'node:24-alpine'},targets:{},jobs:[],edits:[],profile:{environment:'docker',shell:'sh',default_timeout:600,max_timeout:3600},docker:{configured:true,owned:false,ready:true},integrations:{skills:[{name:'selected'}],servers:[],mcp_available:true},runner:{configured:false,config:{enabled:false},running:[],api_key_present:false,sdk_available:true},tasks:[{task_id:'saved',intent:'Continue work',status:'pending'}]};
 let calls=0;const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
 runInNewContext(script+';render(fixture,true)',{document,fixture,localStorage:{getItem:()=>null},setTimeout:()=>1,clearTimeout:()=>{},fetch:()=>{calls++;throw Error('unexpected API call')},window:{addEventListener:()=>{},scrollTo:()=>{}},location:{pathname:'/docker'},history:{pushState:()=>{},replaceState:()=>{}},URL,Map,Set,JSON,Number,Object});
 assert.equal(calls,0);assert.equal(elements.get('profile-environment').value,'docker');
 assert.equal(elements.get('mcp-url').disabled,true);assert.equal(elements.get('mcp-command').required,true);
 assert(buttons.filter(x=>['stop','remove'].includes(x.dataset.dockerAction)).every(x=>x.disabled));
 const taskButtons=elements.get('task-list').children[0].children.at(-1).children; assert.equal(taskButtons.find(x=>x.textContent==='Resume with local agent').disabled,true); assert.equal(taskButtons.find(x=>x.textContent==='Use in ChatGPT').disabled,false);
 elements.get('mcp-transport').value='streamable_http';elements.get('mcp-transport').onchange();assert.equal(elements.get('mcp-url').disabled,false);assert.equal(elements.get('mcp-command').disabled,true);
});


test('dashboard script parses and pages remain bookmarkable',()=>{
 const script=html.split('<script>')[1]?.split('</script>')[0];
 assert(script,'dashboard script missing');
 assert.doesNotThrow(()=>new Script(script));
 for(const route of ['/overview','/workspace','/docker','/connections','/activity','/agent']){
   assert(html.includes('href="'+route+'"'),'missing dashboard route '+route);
 }
});

function dockerFlow(prior){
 const source=html.match(/async function startDockerProject\(\)\{[\s\S]*?\n\}\nsubmitLocal/)?.[0];
 assert(source,'Docker setup handler exists');
 const calls=[],fields=new Map();
 const $=id=>{if(!fields.has(id))fields.set(id,{value:id==='root'?'C:/project':'',setAttribute(){}});return fields.get(id)};
 const current={root:'C:/project',workspace:'project',permissions:{execution:true},profile:{environment:'docker',shell:'sh'},targets:{}};
 const ready={configured:true,image_ready:true,container_id:'new-container',running:true,ready:true};
 let checks=0;
 const api=async(path,data)=>{
  calls.push({path,data});
  if(path==='/api/state')return current;
  if(path==='/api/docker/status')return checks++===0?prior:checks===2?{image_ready:true}:checks===3?{image_ready:true}:ready;
  return {};
 };
 const start=runInNewContext(source.replace(/\nsubmitLocal$/,'')+';startDockerProject',{
  $,api,dockerBusy:false,dockerInput:()=>({context:'desktop-linux',image:'node:24-alpine',workdir:'/workspace',network:'bridge'}),
  dockerProgress:()=>{},dockerStatus:()=>{},refresh:async()=>{},Error,
 });
 return {start,calls};
}

test('owner start recreates a positively missing container without removing any container',async()=>{
 const {start,calls}=dockerFlow({container_id:'deleted-container',container_missing:true,image:'node:24-alpine',error:'missing'});
 await start();
 const actions=calls.filter(c=>c.path==='/api/docker/action').map(c=>c.data.action);
 assert.deepEqual(actions,['detach','create']);
 assert(calls.findIndex(c=>c.data?.action==='detach')<calls.findIndex(c=>c.path==='/api/docker/configure'));
});

test('an inspection failure does not detach or replace a possibly existing container',async()=>{
 const {start,calls}=dockerFlow({container_id:'unknown-container',container_missing:false,error:'Docker engine is unavailable'});
 await assert.rejects(start,/engine is unavailable/);
 assert.equal(calls.filter(c=>c.data).length,0);
});

test('a containerless Docker mapping can be configured for the newly selected project',async()=>{
 const {start,calls}=dockerFlow({workspace_matches:false,container_id:null,error:'another project'});
 await start();
 assert(calls.some(c=>c.path==='/api/docker/configure'));
 assert.deepEqual(calls.filter(c=>c.path==='/api/docker/action').map(c=>c.data.action),['create']);
});

test('a previous project container requires an explicit forget action',async()=>{
 const {start,calls}=dockerFlow({workspace_matches:false,container_id:'previous-project',error:'another project'});
 await assert.rejects(start,/previous project/);
 assert.equal(calls.filter(c=>c.data).length,0);
});
