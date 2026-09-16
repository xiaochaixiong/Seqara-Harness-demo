import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {VisionBridge,runModlens} from '../runtime/toolkit-plugin/vision.mjs';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII=','base64');
const evidence={provider:'openai',result:{summary:'图片观察',ocr:{full_text:'测试'},layout:{regions:[]},semantics:{scene:'演示页'},visual:{notes:['文字可读']},uncertainty:[]},meta:{model:'vision-test',usage:{total_tokens:5}}};
function fixture(run){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'seqara-vision-')),cli=path.join(root,'cli.mjs'),configFile=path.join(root,'config.json'),source=path.join(root,'image.png');
 fs.writeFileSync(cli,'');fs.writeFileSync(source,png);fs.writeFileSync(configFile,JSON.stringify({provider:'openai',providers:{openai:{baseUrl:'https://api.deepseek.com',model:'vision-test',apiKey:'test-secret-never-output'}}}));
 return {root,source,configFile,bridge:new VisionBridge({root:path.join(root,'vision'),cli,configFile,run:run||(async()=>structuredClone(evidence))})};
}

test('vision sends an immutable image and focused question; cache invalidates for pixels, focus and configuration',async()=>{
 let calls=0;const f=fixture(async(_cli,args)=>{calls++;assert.equal(args.at(-1),'openai');assert.ok(args.includes('--prompt'));const input=args[args.indexOf('-i')+1];assert.notEqual(input,f.source);assert.deepEqual(fs.readFileSync(input),fs.readFileSync(f.source));return structuredClone(evidence);});
 const first=await f.bridge.read(f.source,'检查标题');assert.equal(calls,1);assert.equal(first.status,'observed');assert.ok(!JSON.stringify(first).includes('test-secret-never-output'));
 assert.equal((await f.bridge.read(f.source,'检查标题')).cached,true);assert.equal(calls,1);
 await f.bridge.read(f.source,'检查图表');assert.equal(calls,2);
 fs.appendFileSync(f.source,'changed');await f.bridge.read(f.source,'检查标题');assert.equal(calls,3);
 const c=JSON.parse(fs.readFileSync(f.configFile));c.providers.openai.model='changed-model';fs.writeFileSync(f.configFile,JSON.stringify(c));await f.bridge.read(f.source,'检查标题');assert.equal(calls,4);
});

test('invalid inputs, missing engine output and cancellation never create a successful vision record',async()=>{
 const f=fixture(async()=>({error:'provider unavailable'}));
 await assert.rejects(f.bridge.read('relative.png'),/绝对路径/);
 const txt=path.join(f.root,'fake.png');fs.writeFileSync(txt,'plain text');await assert.rejects(f.bridge.read(txt),/实际内容/);
 await assert.rejects(f.bridge.read(f.source),/缺少/);assert.equal(fs.readdirSync(path.join(f.root,'vision/reports')).length,0);
 const abort=new AbortController();abort.abort();await assert.rejects(f.bridge.read(f.source,'',abort.signal));
});

test('subprocess errors do not leak provider stderr and abort terminates work',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'seqara-vision-process-')),cli=path.join(root,'fail.mjs');
 fs.writeFileSync(cli,"console.error('Authorization: Bearer test-secret-never-output');process.exit(1)");
 await assert.rejects(runModlens(cli,[]),e=>e.message.includes('退出码 1')&&!e.message.includes('test-secret'));
 fs.writeFileSync(cli,'setInterval(()=>{},1000)');const controller=new AbortController();const pending=runModlens(cli,[],controller.signal,3000);setTimeout(()=>controller.abort(),100);
 await assert.rejects(pending,/已取消/);
});

test('vision subprocess honors the workbench offline preference',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'seqara-vision-offline-')),cli=path.join(root,'offline.mjs');
 fs.writeFileSync(path.join(root,'network.json'),JSON.stringify({offline:true}));
 fs.writeFileSync(cli,"try{await fetch('https://example.invalid');console.log('{}')}catch(e){console.log(JSON.stringify({code:e.code}))}");
 const before=process.env.NV_DESKTOP_DATA;process.env.NV_DESKTOP_DATA=root;
 try{assert.equal((await runModlens(cli,[])).code,'SEQARA_OFFLINE');}finally{if(before===undefined)delete process.env.NV_DESKTOP_DATA;else process.env.NV_DESKTOP_DATA=before;}
});
