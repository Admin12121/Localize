import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {randomBytes} from 'node:crypto';
const {default:worker}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('dist/server/index.js','utf8')).toString('base64'));
const sql=new DatabaseSync(':memory:');sql.exec(readFileSync('gateway/drizzle/0000_calm_jackal.sql','utf8'));
const env={CONFIG_ENCRYPTION_KEY:randomBytes(32).toString('base64'),DB:{prepare(q){const stmt=sql.prepare(q);return{bind(...v){return{first:async()=>stmt.get(...v)||null,run:async()=>stmt.run(...v)}}}}}};
createServer(async(req,res)=>{try{const chunks=[];for await(const c of req)chunks.push(c);const request=new Request('http://127.0.0.1:4173'+req.url,{method:req.method,headers:{...req.headers,'oai-authenticated-user-id':'local-preview'},...(['GET','HEAD'].includes(req.method)?{}:{body:Buffer.concat(chunks)})});const result=await worker.fetch(request,env);res.writeHead(result.status,Object.fromEntries(result.headers));res.end(Buffer.from(await result.arrayBuffer()))}catch{res.writeHead(500);res.end('Preview unavailable')}}).listen(4173,'127.0.0.1',()=>console.log('Local preview: http://127.0.0.1:4173'));
