const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'seqara-offline-host-'));
process.env.NV_DESKTOP_DATA=folder;
const network=require('../desktop/network-guard.cjs');network.install();
const mode=value=>fs.writeFileSync(path.join(folder,'network.json'),JSON.stringify({offline:value}));
test('offline permits the settings host but blocks external fetch, HTTP and DNS',async()=>{
 mode(true);const server=http.createServer((req,res)=>res.end('local settings'));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const response=await fetch('http://127.0.0.1:'+server.address().port);assert.equal(await response.text(),'local settings');
  await assert.rejects(fetch('https://example.invalid'),{code:'SEQARA_OFFLINE'});
  assert.throws(()=>http.get('http://example.invalid'),{code:'SEQARA_OFFLINE'});
  await assert.rejects(require('node:dns').promises.lookup('example.invalid'),{code:'SEQARA_OFFLINE'});
 }finally{await new Promise(resolve=>server.close(resolve));mode(false);}
});
test('offline preference changes are read by an already running host',()=>{mode(false);assert.equal(network.isOffline(),false);mode(true);assert.equal(network.isOffline(),true);mode(false);});
test.after(()=>{assert.equal(path.dirname(folder),os.tmpdir());assert.match(path.basename(folder),/^seqara-offline-host-/);fs.rmSync(folder,{recursive:true,force:true});});
