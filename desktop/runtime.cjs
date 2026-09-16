const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {EventEmitter}=require('node:events');
const {validateRuntimePage}=require('./health.cjs');

class Runtime extends EventEmitter {
  constructor(root,data,node,python){super();Object.assign(this,{root,data,node,python,state:'stopped',logs:[],child:null,url:null});}
  info(){return {state:this.state,url:this.url,version:this.version,logs:this.logs.slice(-40)};}
  update(state){this.state=state;this.emit('change',this.info());}
  start(runtimePath){
    if(this.child)return;
    this.url=null;this.probing=false;
    this.runtime=runtimePath||path.join(this.root,'runtime');
    this.version=JSON.parse(fs.readFileSync(path.join(this.runtime,'node_modules/@deepseek-ai/dsh/package.json'),'utf8')).version;
    const home=path.join(this.data,'harness');const workspace=path.join(this.data,'workspace');
    fs.mkdirSync(home,{recursive:true});fs.mkdirSync(workspace,{recursive:true});
    const plugin=pathToFileURL(path.join(this.runtime,'toolkit-plugin/index.mjs')).href;
    const patch=path.join(home,'toolkit.patch.yml');
    fs.writeFileSync(patch,JSON.stringify([{insert:[{id:'seqara-file-present',name:'@deepseek-ai/dsh-tool-present'},{id:'nv-business-tools',name:plugin},{id:'seqara-presentation-skills',name:'@deepseek-ai/dsh-skill-filesystem',config:{providerName:'seqara-presentation',includeDefaultRoots:false,customSkillDirs:[path.join(this.runtime,'toolkit-plugin/skills')],watch:false}}]}]));
    const webPatch=path.join(home,'toolkit-web.patch.yml');
    fs.writeFileSync(webPatch,JSON.stringify([{id:'ui-brand-official',disabled:true},{insert:[{id:'nv-desktop-brand',name:pathToFileURL(path.join(this.runtime,'toolkit-brand/index.mjs')).href}]}]));
    const cli=path.join(this.runtime,'node_modules/@deepseek-ai/dsh/lib/bin.js');
    this.update('starting');let buffer='';
    const child=spawn(this.node,['--import',pathToFileURL(path.join(this.root,'runtime/lifecycle.mjs')).href,cli,'--profile','web','--patch',patch,'--patch',webPatch,'--host','127.0.0.1','--port','0','--no-open'],{
      cwd:workspace,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,
      DSH_HOME:home,DSH_AGENTS_HOME:path.join(home,'agents'),NV_HARNESS_MANAGED:'1',NV_DESKTOP_ROOT:this.root,
      PATH:[path.dirname(this.node),path.join(path.dirname(this.node),'node_modules/.bin'),process.env.PATH||''].join(path.delimiter),
      NV_TOOLKIT_COMMAND:JSON.stringify(this.python),NV_TOOLKIT_DATA_DIR:path.join(this.data,'business'),NV_TOOLKIT_CONFIG_DIR:path.join(this.data,'native'),NV_TOOLKIT_TASK_DIR:path.join(this.data,'tasks'),PYTHONIOENCODING:'utf-8'}});
    this.child=child;
    const read=chunk=>{buffer+=chunk.toString('utf8');const lines=buffer.split(/\r?\n/);buffer=lines.pop();for(const line of lines){
      const clean=line.replace(/\x1b\[[0-9;]*m/g,'');
      const match=clean.match(/http:\/\/127\.0\.0\.1:\d+(?:\/[^\s]*)?/);
      if(match&&!this.url&&!this.probing){this.probing=true;const candidate=match[0];(async()=>{for(let attempt=0;attempt<10&&this.child===child&&this.state==='starting';attempt++){try{await validateRuntimePage(candidate);if(this.child===child&&this.state==='starting'){this.url=candidate;this.update('running');clearTimeout(this.deadline);}return;}catch(e){if(attempt===9)throw e;await new Promise(resolve=>setTimeout(resolve,500));}}})().catch(e=>{this.logs.push('启动验证：'+e.message);}).finally(()=>{this.probing=false;});}
      this.logs.push(clean.replace(/([?&]token=)[^\s&]+/g,'$1[hidden]'));this.logs=this.logs.slice(-80);
    }this.emit('change',this.info());};
    child.stdout.on('data',read);child.stderr.on('data',read);
    child.once('error',e=>{this.logs.push(e.message);this.child=null;this.update('failed');});
    child.once('close',()=>{clearTimeout(this.deadline);this.child=null;this.url=null;this.update(this.state==='stopping'?'stopped':'failed');});
    this.deadline=setTimeout(()=>{if(this.state==='starting'){this.logs.push('启动超过 120 秒，请检查运行日志');child.kill();this.update('failed');}},120000);
  }
  async stop(){const child=this.child;if(!child)return;this.update('stopping');await new Promise(resolve=>{
    const timer=setTimeout(()=>child.kill(),4000);child.once('close',()=>{clearTimeout(timer);resolve();});
    child.stdin.on('error',()=>{});child.stdin.end('shutdown\n');
  });}
}
module.exports={Runtime};
