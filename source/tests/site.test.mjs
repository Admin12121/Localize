import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {randomBytes} from 'node:crypto';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
const source=readFileSync('dist/server/index.js','utf8');
const {default:worker,endpoint,seal,unseal}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const origin='https://site.example';
function storage(){
  const sql=new DatabaseSync(':memory:');
  for(const filename of ['drizzle/0000_calm_jackal.sql'])sql.exec(readFileSync(filename,'utf8'));
  const DB={prepare(query){const s=sql.prepare(query);return {bind(...values){return {first:async()=>s.get(...values)||null,run:async()=>s.run(...values)}}}}};
  return {DB,sql,CONFIG_ENCRYPTION_KEY:randomBytes(32).toString('base64')};
}
const headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','oai-authenticated-user-id':'owner-test'};
function request(path,method='GET',data,extra={}){return new Request(origin+path,{method,headers:{...headers,...extra},...(data===undefined?{}:{body:JSON.stringify(data)})})}
async function call(env,name,args={},extra={}){const res=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}},extra),env);return {status:res.status,...await res.json()}}
const settingsHeaders={'Origin':origin,'X-CTF-Settings':'1'};
async function save(env,url,token){return worker.fetch(request('/api/settings','POST',{endpoint:url,token},settingsHeaders),env)}
test('current Sites MCP discovery and tool listing work without bridge settings',async()=>{
  const current={'MCP-Protocol-Version':'2026-07-28'};
  const res=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',id:3,method:'server/discover'},current),{});
  assert.equal(res.status,200);
  const discovery=(await res.json()).result;
  assert(discovery.supportedVersions.includes('2026-07-28'));
  assert.deepEqual(discovery.capabilities,{tools:{}});
  const list=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',id:4,method:'tools/list'},current),{});
  assert.equal(list.status,200);
  assert.equal((await list.json()).result.tools.length,16);
  assert.equal((await call({},'list_targets',{},current)).result.isError,true);
});
test('MCP discovery exposes all original tools and evidence history without data',async()=>{
  const res=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',id:1,method:'tools/list'}),{});
  const names=(await res.json()).result.tools.map(t=>t.name);
  assert.equal(names.length,16);for(const name of ['list_targets','http_request','http_batch','inspect_html','session_cookies','reset_session','browser_action','request_history','bridge_status','workspace_list','workspace_read','workspace_search','workspace_edit','command_request','command_status','command_cancel'])assert(names.includes(name));
  const init=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',id:2,method:'initialize',params:{protocolVersion:'2025-06-18'}}),{});assert.equal((await init.json()).result.protocolVersion,'2025-06-18');
  const notification=await worker.fetch(request('/mcp','POST',{jsonrpc:'2.0',method:'notifications/initialized'}),{});assert.equal(notification.status,202);
});
test('identity, origin, protocol and settings CSRF checks reject unauthorized data access',async()=>{
  const env=storage();
  assert.equal((await call(env,'list_targets',{}, {'oai-authenticated-user-id':''})).status,401);
  assert.equal((await call(env,'list_targets',{}, {'Origin':'https://evil.example'})).status,403);
  assert.equal((await call(env,'list_targets',{}, {'MCP-Protocol-Version':'invalid'})).status,400);
  assert.equal((await worker.fetch(request('/api/settings','POST',{}),env)).status,403);
  assert.equal((await worker.fetch(request('/api/settings','GET',undefined,{'oai-authenticated-user-id':''}),env)).status,401);
  assert.equal((await call(env,'http_request',{target:'lab',arbitrary:'unsafe'})).result.isError,true);
  assert.equal((await call(env,'list_targets')).result.isError,true);
});
test('bridge endpoint validation blocks SSRF, credentials, queries and unapproved hosts',()=>{
  assert.equal(endpoint('https://fresh-tunnel.trycloudflare.com/mcp'),'https://fresh-tunnel.trycloudflare.com/mcp');
  for(const url of ['http://fresh-tunnel.trycloudflare.com/mcp','https://127.0.0.1/mcp','https://evil.example/mcp','https://u:p@fresh-tunnel.trycloudflare.com/mcp','https://fresh-tunnel.trycloudflare.com/mcp?token=x','https://fresh-tunnel.trycloudflare.com:8443/mcp','https://fresh-tunnel.trycloudflare.com.other/mcp'])assert.throws(()=>endpoint(url));
  assert.equal(endpoint('https://bridge.example/mcp',{BRIDGE_ALLOWED_HOSTS:'bridge.example'}),'https://bridge.example/mcp');
});
test('settings encrypt credentials, bind encryption to user and support endpoint rotation',async()=>{
  const env=storage(), token=randomBytes(48).toString('base64url');
  assert.equal((await save(env,'https://first-tunnel.trycloudflare.com/mcp',token)).status,200);
  const row=env.sql.prepare('SELECT * FROM connections').get();assert(!row.credential.includes(token));assert.equal(await unseal(row.credential,'owner-test',env),token);
  await assert.rejects(unseal(row.credential,'other-owner',env));
  const response=await worker.fetch(request('/api/settings'),env);assert(!(await response.text()).includes(token));
  assert.equal((await save(env,'https://new-tunnel.trycloudflare.com/mcp','')).status,200);
  assert.equal(env.sql.prepare('SELECT credential FROM connections').get().credential,row.credential);
  assert.equal((await worker.fetch(request('/api/settings','GET',undefined,{'oai-authenticated-user-id':'other-owner'}),env)).status,200);
  assert.equal((await call(env,'list_targets',{}, {'oai-authenticated-user-id':'other-owner'})).result.isError,true);
});
test('Site tools delegate to real authenticated Python bridge and real HTTP GET/POST',async()=>{
  const env=storage(), token=randomBytes(48).toString('base64url'), realFetch=globalThis.fetch;
  const child=spawn('python',['bridge/tests/integration_fixture.py'],{env:{...process.env,FIXTURE_SERVICE_TOKEN:token},stdio:['ignore','pipe','pipe'],windowsHide:true});
  let errors='';child.stderr.on('data',b=>{errors+=b});
  const lines=createInterface({input:child.stdout});
  const first=await Promise.race([once(lines,'line'),once(child,'exit').then(()=>{throw Error('Fixture exited: '+errors)})]);
  const fixture=JSON.parse(first[0]);
  globalThis.fetch=(url,options)=>realFetch(url==='https://fixture.trycloudflare.com/mcp'?`http://127.0.0.1:${fixture.bridge_port}/mcp`:url,options);
  try{
    await save(env,'https://fixture.trycloudflare.com/mcp',token);
    const status=(await call(env,'bridge_status')).result;assert.equal(status.isError,false);assert.equal(JSON.parse(status.content[0].text).version,'3.1.1');assert.equal(JSON.parse(status.content[0].text).creator,'admin12121');assert.equal(JSON.parse(status.content[0].text).license,'MIT');
    assert.equal((await call(env,'workspace_list')).result.isError,true);
    let result=(await call(env,'list_targets')).result;assert.equal(result.isError,false,JSON.stringify(result));assert.equal(JSON.parse(result.content[0].text).targets[0].origin,`http://127.0.0.1:${fixture.challenge_port}`);
    result=(await call(env,'http_request',{target:'lab'})).result;assert.equal(JSON.parse(result.content[0].text).status,200);
    result=(await call(env,'http_request',{target:'lab',method:'POST',body:'real-post-body'})).result;assert.equal(JSON.parse(result.content[0].text).body_text,'real-post-body');
    await call(env,'http_request',{target:'lab',path:'/set'});
    result=(await call(env,'http_request',{target:'lab',path:'/echo'})).result;assert.equal(JSON.parse(JSON.parse(result.content[0].text).body_text).cookie_present,true);
    result=(await call(env,'session_cookies',{target:'lab'})).result;assert(!JSON.stringify(result).includes('secret-session-value'));
    result=(await call(env,'http_request',{target:'lab',path:'/redirect'})).result;assert.equal(JSON.parse(result.content[0].text).status,302);
    assert.equal((await call(env,'http_request',{target:'unknown'})).result.isError,true);
    assert.equal((await call(env,'http_request',{target:'lab',path:'//off-scope.invalid'})).result.isError,true);
    const unauth=await realFetch(`http://127.0.0.1:${fixture.bridge_port}/mcp`,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json, text/event-stream'},body:'{}'});assert.equal(unauth.status,401);
    await save(env,'https://fixture.trycloudflare.com/mcp',randomBytes(48).toString('base64url'));assert.equal((await call(env,'list_targets')).result.isError,true);
  }finally{globalThis.fetch=realFetch;lines.close();child.kill();await once(child,'exit')}
});

test('single-file companion download is private and returns the packaged bundle',async()=>{
  const result=await worker.fetch(request('/download/Web-Bridge.pyz'),{});
  assert.equal(result.status,200);
  assert.equal(result.headers.get('Content-Disposition'),'attachment; filename="Web-Bridge.pyz"');
  assert.deepEqual(Buffer.from(await result.arrayBuffer()),readFileSync('outputs/Web-Bridge.pyz'));
  assert.equal((await worker.fetch(request('/download/Web-Bridge.pyz','GET',undefined,{'oai-authenticated-user-id':''}),{})).status,401);
});
