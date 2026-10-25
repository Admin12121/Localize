import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const html=readFileSync('bridge/control.html','utf8').replaceAll('\r\n','\n');
function element(tag,text){return {tag,text,children:[],append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}}}

test('expanded command refreshes final output when it completes during detail fetch',async()=>{
  const match=html.match(/async function loadJob\(block\)\{[\s\S]*?\n\}\nfunction moreJobs/);
  assert(match);
  let resolveFirst,reads=0;
  const api=()=>{reads++;if(reads===1)return new Promise(resolve=>{resolveFirst=resolve});return Promise.resolve({job_id:'job',state:'completed',request:{argv:['python','demo.py'],environment:'host',timeout:30},output:'finished',exit_code:0})};
  const load=runInNewContext(match[0].replace(/\nfunction moreJobs$/,'')+';loadJob',{api,node:element,requestInfo:()=>'',action:()=>{}});
  const block={item:{job_id:'job',state:'running',output_length:0},open:true,isConnected:true,body:element('div')};
  const first=load(block);
  block.item={job_id:'job',state:'completed',output_length:8};
  await load(block); // Poll arrived while the previous detail read was pending.
  resolveFirst({job_id:'job',state:'running',request:{argv:['python','demo.py'],environment:'host',timeout:30},output:'working'});
  await first;await new Promise(resolve=>setImmediate(resolve));
  assert.equal(reads,2);
  assert(block.body.children.some(e=>e.text==='finished'));
  assert(block.body.children.some(e=>e.text==='Exit code 0'));
});
