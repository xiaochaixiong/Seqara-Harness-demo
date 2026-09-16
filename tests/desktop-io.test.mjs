import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {openNativePath,revealNativePath,runNativeCommand} from '../runtime/native-command.mjs';
import {desktopAction} from '../runtime/toolkit-plugin/desktop.mjs';
import {apply as deliveryRoutes} from '../runtime/node_modules/@deepseek-ai/dsh-client-ui-deliverables/lib/index.js';
import {SessionController} from '../runtime/node_modules/@deepseek-ai/dsh-api-session-controller/lib/index.js';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'seqara-desktop-io-'));
const file=path.join(root,"中文 空格,100% & $() '测试.pdf");fs.writeFileSync(file,'%PDF-fixture');

test('Explorer uses a literal Unicode PIDL path, including commas and shell punctuation',async()=>{
 let call;await revealNativePath(file,undefined,{platform:'win32',run:async(command,args)=>{call={command,args};}});
 assert.equal(call.command,'powershell.exe');assert.ok(call.args.includes('-STA'));
 const script=Buffer.from(call.args.at(-1),'base64').toString('utf16le');
 assert.ok(script.includes("[SeqaraReveal]::Show('"+file.replaceAll("'","''")+"')"));
 assert.match(script,/SHOpenFolderAndSelectItems/);assert.match(script,/ThrowExceptionForHR/);
 assert.ok(!script.includes('/select,'));assert.ok(!script.includes('file:///'));
});
test('Explorer errors, including exit code 1, are not reported as success',async()=>{
 await assert.rejects(revealNativePath(file,undefined,{platform:'win32',run:async()=>{throw Object.assign(Error('shell failed'),{code:1});}}),/shell failed/);
});
test('missing files and cancelled operations do not launch a helper',async()=>{
 let calls=0;const run=async()=>{calls++};
 await assert.rejects(openNativePath(path.join(root,'missing.pdf'),undefined,{run}),/ENOENT/);
 await assert.rejects(revealNativePath(file,AbortSignal.abort(),{run}));assert.equal(calls,0);
});
test('toolkit reveal works even when the optional cancellation signal is omitted',async()=>{
 let calls=0;const r=await desktopAction({action:'reveal',path:file},undefined,{platform:'win32',run:async()=>{calls++;return {stdout:'',stderr:''}}});
 assert.equal(r.status,'requested');assert.equal(calls,1);
});
test('PowerShell non-terminating errors reject, rather than displaying false success',{skip:process.platform!=='win32'},async()=>{
 await assert.rejects(runNativeCommand('powershell.exe',['-NoProfile','-Command',"Write-Error 'fixture-open-failed'; Write-Output 'incorrect-success'"]),/fixture-open-failed/);
});
test('DSH startup imports the same adapter for built-in card and settings actions',()=>{
 const project=fileURLToPath(new URL('../',import.meta.url));
 const value=execFileSync(process.execPath,['--import','./runtime/native-command-loader.mjs','--input-type=module','-e',"import {adapterVersion} from '@deepseek-ai/dsh-native-command';console.log(adapterVersion)"],{cwd:project,encoding:'utf8',windowsHide:true});
 assert.equal(value.trim(),'1');
});
test('real delivery route propagates native failures through the session controller',async()=>{
 const routes=new Map();let failing=false,calls=0;
 const controller={workspaceDesktop:()=>({available:true}),
  revealPath:async(target,signal)=>{assert.equal(target,file);await revealNativePath(target,signal,{platform:'win32',run:async()=>{calls++;if(failing)throw Error('Explorer failure');}})},
  openWorkspacePath:SessionController.prototype.openWorkspacePath};
 deliveryRoutes({connection:{fetch:{register:r=>routes.set(r.path,r.fetch)}},effect:()=>{},
  systemPrompt:{section:()=>{},getSectionOrder:()=>0},sessionController:controller,
  sessionQuery:{readEvent:async()=>({session:{cwd:root},target:{type:'deliverables/presented',data:{turn:1,callId:'fixture',files:[{path:file}]}}})},
  workspaceFiles:{stat:async()=>({absolutePath:file})},fs:{processPathFromHostPath:p=>p,resolve:async p=>p,processPath:p=>p}});
 const request=()=>new Request('http://localhost/api/present.open?sessionId=fixture&seq=1&index=0&action=reveal',{method:'POST'});
 assert.equal((await routes.get('/api/present.open')(request())).status,204);
 failing=true;assert.equal((await routes.get('/api/present.open')(request())).status,500);
 assert.equal(calls,2);
});
