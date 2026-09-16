const network=require('./network-guard.cjs');network.install();
const {copyDirectory}=require('./files.cjs');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {Runtime}=require('./runtime.cjs');const {Updates}=require('./updates.cjs');
const {validatedCoreVersions}=require('./compatibility.json');
const root=path.resolve(__dirname,'..'),data=path.resolve(process.env.NV_DESKTOP_DATA||'');
if(!process.env.NV_DESKTOP_DATA)throw Error('Missing desktop data directory');fs.mkdirSync(data,{recursive:true});
const config=path.join(data,'desktop.json');let settings={autoUpdate:false,coreVersion:'0.1.5-rc.1'};
try{settings={...settings,...JSON.parse(fs.readFileSync(config,'utf8'))};}catch{}
function save(){fs.writeFileSync(config+'.tmp',JSON.stringify(settings,null,2));fs.renameSync(config+'.tmp',config);}
const send=(type,value)=>process.stdout.write(JSON.stringify({type,...value})+'\n');
const executable=path.join(root,'backend-bin/worker/worker.exe');
const worker=fs.existsSync(executable)?[executable]:[path.join(root,'.venv/Scripts/python.exe'),path.join(root,'backend/worker.py')];
const runtime=new Runtime(root,data,process.execPath,worker);const updates=new Updates(root,data,process.execPath,worker,settings,save);
const inside=(folder,p)=>{if(typeof p!=='string')return false;const r=path.relative(folder,p);return !!r&&!r.startsWith('..')&&!path.isAbsolute(r);};
let transaction=null,closing=false,restarting=false;
function restore(tx){
 if(!inside(path.join(data,'upgrade-backups'),tx.backup))throw Error('回退备份路径不正确');
 const home=path.join(data,'harness'),backup=path.join(tx.backup,'harness');
 if(fs.existsSync(home))fs.renameSync(home,path.join(tx.backup,'failed-harness-'+Date.now()));
 if(fs.existsSync(backup))copyDirectory(backup,home,{recursive:true});
 settings.runtimePath=tx.previous.runtimePath;settings.coreVersion=tx.previous.coreVersion;
 delete settings.activation;delete settings.pendingRuntime;delete settings.pendingVersion;save();
}
if(settings.activation){try{restore(settings.activation);}catch(e){send('error',{message:'上次升级恢复失败：'+e.message});delete settings.activation;delete settings.pendingRuntime;delete settings.pendingVersion;settings.runtimePath=undefined;settings.coreVersion='0.1.5-rc.1';save();}}
function fail(error){send('error',{message:error.message});if(transaction){const tx=transaction;transaction=null;try{restore(tx);send('update',{message:'新内核未通过验证，已恢复原内核与会话。'});start(false);}catch(e){send('runtime',{state:'failed',message:e.message});}}else send('runtime',{state:'failed'});}
function start(allowPending=true){
 try{
  let selected=settings.runtimePath;
  if(selected&&!inside(path.join(data,'runtimes'),selected))throw Error('活动内核路径无效');
  if(allowPending&&settings.pendingRuntime){
   if(!inside(path.join(data,'runtimes'),settings.pendingRuntime)||!validatedCoreVersions.includes(settings.pendingVersion))throw Error('候选内核尚未通过当前外壳兼容验证');
   const backup=path.join(data,'upgrade-backups',String(Date.now()));fs.mkdirSync(backup,{recursive:true});
   if(fs.existsSync(path.join(data,'harness')))copyDirectory(path.join(data,'harness'),path.join(backup,'harness'),{recursive:true});
   transaction={backup,previous:{runtimePath:settings.runtimePath,coreVersion:settings.coreVersion},candidate:settings.pendingRuntime,version:settings.pendingVersion};
   settings.activation=transaction;save();selected=transaction.candidate;
  }
  if(selected)for(const dir of ['toolkit-brand','toolkit-plugin'])copyDirectory(path.join(root,'runtime',dir),path.join(selected,dir),{recursive:true});
  runtime.start(selected);
 }catch(e){if(!transaction&&settings.pendingRuntime){delete settings.pendingRuntime;delete settings.pendingVersion;save();send('error',{message:e.message});start(false);}else fail(e);}
}
runtime.on('change',v=>{
 send('runtime',v);
 if(v.state==='running'&&transaction){settings.runtimePath=transaction.candidate;settings.coreVersion=transaction.version;delete settings.activation;delete settings.pendingRuntime;delete settings.pendingVersion;save();transaction=null;send('settings',settings);}
 if(v.state==='failed'&&transaction&&!runtime.child)fail(Error('候选内核启动失败'));
});
updates.on('change',v=>send('update',v));
async function stop(){if(closing)return;closing=true;watcher.close();await updates.cancel();await runtime.stop();process.exit(0);}
const taskFolder=path.join(data,'tasks');fs.mkdirSync(taskFolder,{recursive:true});
const seen=new Map();function publishTask(name){if(!name||!name.endsWith('.json')||path.basename(name)!==name)return;try{const raw=fs.readFileSync(path.join(taskFolder,name),'utf8');if(seen.get(name)===raw)return;seen.set(name,raw);send('task',JSON.parse(raw));}catch{}}
const watcher=fs.watch(taskFolder,(_,name)=>publishTask(name));
for(const name of fs.readdirSync(taskFolder).filter(n=>n.endsWith('.json')).slice(-100)){
 try{const file=path.join(taskFolder,name),task=JSON.parse(fs.readFileSync(file,'utf8'));if(['running','queued'].includes(task.state)){let alive=false;if(task.pid)try{process.kill(task.pid,0);alive=true;}catch{}if(!alive)fs.writeFileSync(file,JSON.stringify({...task,state:'failed',message:'上次运行中断，请核对输出后重试',updatedAt:Date.now()}));}}catch{}
 publishTask(name);
}
const rl=readline.createInterface({input:process.stdin});rl.on('line',async line=>{try{
 const m=JSON.parse(line);if(m.type==='stop')return stop();
 if(m.type==='restart'){if(restarting)throw Error('正在重启，请稍候');restarting=true;try{await runtime.stop();start(false);}finally{restarting=false;}}
 if(network.isOffline()&&['check','install'].includes(m.type))throw Error('离线模式下无法检查或下载更新。');
 if(m.type==='check')await updates.check();if(m.type==='install')await updates.install();
 if(m.type==='auto'){settings.autoUpdate=!!m.enabled;save();}send('settings',settings);
}catch(e){send('error',{message:e.message});}});rl.on('close',stop);
send('settings',settings);start();
const check=async()=>{if(network.isOffline())return;try{const v=await updates.check();if(!closing&&settings.autoUpdate&&!updates.busy&&v.latest!==v.current&&!v.pending)await updates.install();}catch(e){send('error',{message:e.message});}};
setTimeout(check,15000).unref();setInterval(check,21600000).unref();
