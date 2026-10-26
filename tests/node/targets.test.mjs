import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const html=readFileSync('src/web_bridge/ui/control.html','utf8');
function parser(){const match=html.match(/function parseWebsiteTarget\(name,value\)\s*\{[\s\S]*?\n\}/);assert(match,'Local target form must validate normal website URLs');return runInNewContext(match[0]+';parseWebsiteTarget',{URL});}
test('website input accepts full links and preserves the exact approved origin',()=>{
  const parse=parser();const result=parse('challenge','https://example.test:8443/login?next=/');
  assert.equal(result.name,'challenge');assert.equal(result.origin,'https://example.test:8443');
  assert.equal(parse('my-site','http://example.test:80/path').origin,'http://example.test');
});
test('website input rejects unsafe names, protocols and embedded credentials',()=>{
  const parse=parser();for(const [name,url] of [['bad name','https://example.test'],['','https://example.test'],['lab','file:///etc/passwd'],['lab','https://user:secret@example.test'],['lab','not a url']])assert.throws(()=>parse(name,url));
});
