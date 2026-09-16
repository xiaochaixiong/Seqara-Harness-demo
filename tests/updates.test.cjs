const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const {Updates}=require('../desktop/updates.cjs');
test('startup probe follows local authentication cookie redirect',async()=>{
 const http=require('node:http');const {probePage}=require('../desktop/updates.cjs');let authenticated=false;
 const server=http.createServer((req,res)=>{if(req.url==='/bootstrap'){res.writeHead(303,{'Set-Cookie':'session=probe; HttpOnly; SameSite=Strict','Location':'/'});res.end();return;}
 authenticated=req.headers.cookie==='session=probe';res.writeHead(authenticated?200:401);res.end('local test');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));try{await probePage(`http://127.0.0.1:${server.address().port}/bootstrap`);assert.equal(authenticated,true);}finally{await new Promise(r=>server.close(r));}
});
test('official update check returns published identity without changing active runtime',async()=>{
 const root=path.resolve(__dirname,'..');const settings={coreVersion:'0.1.5-rc.1',runtimePath:'sentinel'};let saved=false;
 const u=new Updates(root,path.join(root,'outputs/update-tests'),process.execPath,[],settings,()=>saved=true);
 const value=await u.check();assert.match(value.latest,/^\d+\.\d+\.\d+/);assert.equal(settings.runtimePath,'sentinel');assert.equal(saved,false);
});
test('failed registry check cannot activate or save an update',async()=>{
 const root=path.resolve(__dirname,'..');const settings={coreVersion:'0.1.5-rc.1',runtimePath:'sentinel'};let saved=false;
 const u=new Updates(root,path.join(root,'outputs/update-tests'),process.execPath,[],settings,()=>saved=true);
 const old=global.fetch;global.fetch=async()=>{throw Error('offline');};
 try{await assert.rejects(u.install(),/offline/);assert.equal(settings.runtimePath,'sentinel');assert.equal(saved,false);assert.equal(u.busy,false);}finally{global.fetch=old;}
});

test('suspending updates stops owned processes and rejects further network work',async()=>{
 const u=new Updates('', '', process.execPath, [], {}, ()=>{});let killed=false,stopped=false;
 u.installer={kill(){killed=true;}};u.smoke={async stop(){stopped=true;}};
 await u.cancel();assert.equal(killed,true);assert.equal(stopped,true);
 await assert.rejects(u.check(),/已暂停/);await assert.rejects(u.install(),/已暂停/);
});
