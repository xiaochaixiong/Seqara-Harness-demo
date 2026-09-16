const {copyDirectory}=require('./files.cjs');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {EventEmitter}=require('node:events');
const {Runtime}=require('./runtime.cjs');
const {validateRuntimePage}=require('./health.cjs');
const {validatedCoreVersions}=require('./compatibility.json');
const REGISTRY='https://registry.npmjs.org/';
const VERSION=/^\d+\.\d+\.\d+(?:-(?:rc|alpha|beta)\.\d+)?$/;
async function official(url){if(!url.startsWith(REGISTRY))throw Error('更新源必须是官方 npm 注册表');
 const r=await fetch(url,{signal:AbortSignal.timeout(30000)});if(!r.ok)throw Error('官方版本检查失败：'+r.status);return r.json();}
async function probePage(url){let target=new URL(url);const origin=target.origin;let cookie='';
 for(let i=0;i<4;i++){const response=await fetch(target,{redirect:'manual',headers:cookie?{Cookie:cookie}:{},signal:AbortSignal.timeout(30000)});
  const received=response.headers.getSetCookie();if(received.length)cookie=received.map(v=>v.split(';')[0]).join('; ');
  if([301,302,303,307,308].includes(response.status)&&response.headers.has('location')){target=new URL(response.headers.get('location'),target);if(target.origin!==origin)throw Error('新内核页面跳转到非本地来源');continue;}
  if(!response.ok)throw Error('新内核页面不可用：HTTP '+response.status);return;
 }throw Error('新内核页面跳转次数异常');}
class Updates extends EventEmitter{
 constructor(root,data,node,python,settings,save){super();Object.assign(this,{root,data,node,python,settings,save,busy:false});}
 async cancel(){this.closed=true;this.installer?.kill();if(this.smoke)await this.smoke.stop();}
 assertOpen(){if(this.closed)throw Error('已暂停在线更新');}
 async check(){this.assertOpen();const meta=await official(REGISTRY+'@deepseek-ai%2Fdsh');
 const v=meta['dist-tags'].latest;if(!VERSION.test(v))throw Error('官方版本格式异常');
 this.latest=v;const value={latest:v,next:meta['dist-tags'].next,current:this.settings.coreVersion||'0.1.5-rc.1',pending:this.settings.pendingVersion||null,
   source:'@deepseek-ai/dsh · npm 官方发布',checkedAt:new Date().toISOString()};this.emit('change',value);return value;}
 async install(){this.assertOpen();if(this.busy)throw Error('正在准备更新');this.busy=true;let smoke;
 try{const info=await this.check();if(info.latest===info.current||info.latest===info.pending)return {...info,message:'当前已是所选渠道版本'};
 const version=info.latest;if(!validatedCoreVersions.includes(version))throw Error('此内核版本尚未通过 Seqara 兼容验证，请先升级 Seqara。当前内核保持不变。');const meta=await official(REGISTRY+'@deepseek-ai%2Fdsh/'+version);
 if(meta.name!=='@deepseek-ai/dsh'||meta.version!==version||!meta.dist?.integrity)throw Error('官方包身份或完整性元数据不匹配');
 const stage=path.join(this.data,'runtimes',version+'-'+Date.now());fs.mkdirSync(stage,{recursive:true});
 const overrides={};for(const name of Object.keys(meta.dependencies||{}))if(name.startsWith('@deepseek-ai/dsh'))overrides[name]=version;
 fs.writeFileSync(path.join(stage,'package.json'),JSON.stringify({private:true,type:'module',dependencies:{'@deepseek-ai/dsh':version},overrides}));
 for(const dir of ['toolkit-plugin','toolkit-brand'])copyDirectory(path.join(this.root,'runtime',dir),path.join(stage,dir),{recursive:true});
 this.emit('change',{message:'正在下载官方内核 '+version});
 const npm=path.join(path.dirname(this.node),'node_modules/npm/bin/npm-cli.js');
 if(!fs.existsSync(npm))throw Error('更新需要随应用提供的 npm。');
 this.assertOpen();
 await new Promise((resolve,reject)=>{const p=spawn(this.node,[npm,'install','--no-audit','--no-fund','--registry='+REGISTRY],{cwd:stage,windowsHide:true,stdio:'ignore'});
 this.installer=p;
 const timer=setTimeout(()=>{p.kill();reject(Error('下载超时，现有内核未改变'));},600000);
 p.once('error',e=>{clearTimeout(timer);reject(e);});p.once('close',c=>{clearTimeout(timer);c===0?resolve():reject(Error('内核安装失败，现有内核未改变'));});});
 this.emit('change',{message:'正在验证新内核启动与业务插件'});
 const smokeHome=path.join(this.data,'update-checks',version+'-'+Date.now());
 this.assertOpen();smoke=new Runtime(this.root,smokeHome,this.node,this.python);this.smoke=smoke;
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('新内核启动验证超时')),125000);
 let probing=false;smoke.on('change',async value=>{if(value.state==='running'&&!probing){probing=true;try{await validateRuntimePage(value.url);clearTimeout(timer);resolve();}catch(e){clearTimeout(timer);reject(e);}}
 if(value.state==='failed'){clearTimeout(timer);reject(Error('新内核启动验证失败'));}});smoke.start(stage);});
 await smoke.stop();smoke=null;
 this.settings.pendingRuntime=stage;this.settings.pendingVersion=version;this.save();
 const value={pending:version,message:'新内核已通过启动验证，下次启动应用时切换；定制界面与业务文件保持独立。'};this.emit('change',value);return value;
 }finally{if(smoke)await smoke.stop();this.smoke=null;this.installer=null;this.busy=false;}}
}
module.exports={Updates,VERSION,REGISTRY,probePage};
