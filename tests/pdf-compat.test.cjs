const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..'),compat=fs.readFileSync(path.join(root,'runtime/toolkit-brand/pdf-compat.js'),'utf8');
const {patch}=require('../scripts/patch-pdf-compat.cjs');
test('Map compatibility preserves cached undefined and computed/reentrant semantics',()=>{
 const ctx=vm.createContext({});vm.runInContext('delete Map.prototype.getOrInsert;delete Map.prototype.getOrInsertComputed;',ctx);vm.runInContext(compat,ctx);
 const value=vm.runInContext(`(()=>{const m=new Map([['cached',undefined]]);let calls=0;
 m.getOrInsertComputed('cached',()=>{calls++;return 3});
 const value=m.getOrInsertComputed(-0,key=>{if(Object.is(key,-0))throw Error('negative zero');m.set(0,1);return 2});
 let rejected=false;try{m.getOrInsertComputed('cached',null)}catch{rejected=true}
 return JSON.stringify({calls,value,stored:m.get(0),rejected,enumerable:Object.keys(Map.prototype).includes('getOrInsertComputed'),nan:m.getOrInsert(NaN,4),again:m.getOrInsert(NaN,5)})})()`,ctx);
 assert.deepEqual(JSON.parse(value),{calls:0,value:2,stored:2,rejected:true,enumerable:false,nan:4,again:4});
 const first=vm.runInContext('Map.prototype.getOrInsertComputed',ctx);vm.runInContext(compat,ctx);assert.equal(vm.runInContext('Map.prototype.getOrInsertComputed',ctx),first);
});
test('PDF bundle patch is repeatable and reaches the dedicated worker',()=>{
 const file=path.join(root,'runtime/node_modules/@deepseek-ai/dsh-client-ui-sidebar-documentpreview/lib/client.js');
 const once=patch(fs.readFileSync(file,'utf8'),compat);assert.equal(patch(once,compat),once);
 assert.ok(once.startsWith('/* SEQARA_PDF_COMPAT_START */'));
 assert.ok(once.includes('new Blob([/* SEQARA_PDF_WORKER_COMPAT */'+JSON.stringify(compat)+', _dsh_pdf_worker_default,'));
 assert.throws(()=>patch('unknown upstream bundle',compat),/PDF bundle changed/);
});
