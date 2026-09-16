import fs from 'node:fs';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {defineTool} from '@deepseek-ai/dsh-tools';
import {canOpenNativePath,openNativePath,revealNativePath} from '../native-command.mjs';
import {scrubbedParentEnv} from '@deepseek-ai/dsh-subprocess';

const documents=new Set('.pptx .ppt .pdf .docx .doc .xlsx .xls .csv .txt .md .png .jpg .jpeg .gif .webp .svg .mp3 .mp4 .wav'.split(' '));
export const runDesktopCommand=(command,args,signal)=>new Promise((resolve,reject)=>{
 const argv=[...args],script=argv.indexOf('-Command');if(/powershell(?:\.exe)?$/i.test(command)&&script>=0)argv[script+1]="$ErrorActionPreference='Stop'; "+argv[script+1];
 execFile(command,argv,{encoding:'utf8',windowsHide:true,timeout:15000,maxBuffer:65536,signal,env:scrubbedParentEnv()},(error,stdout,stderr)=>error?reject(error):resolve({stdout,stderr}));
});
function offline(){try{return JSON.parse(fs.readFileSync(path.join(process.env.NV_DESKTOP_DATA||'', 'network.json'),'utf8')).offline===true;}catch{return process.env.SEQARA_OFFLINE==='1';}}
export async function desktopAction(args,signal,internals={}){
 signal?.throwIfAborted();const options={run:runDesktopCommand,...internals},platform=options.platform||process.platform;
 if(args.action==='status')return {native_open_available:canOpenNativePath(options),platform,ppt_application:'wps',offline:offline(),actions:['open_file','open_folder','reveal','open_url'],confirmation:'打开命令成功仅代表已交给系统；不等于已看到应用窗口'};
 if(args.action==='open_url'){
  const url=new URL(args.url);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw Error('只能打开不含登录凭据的 HTTP(S) 地址');
  if(offline()&&!['localhost','127.0.0.1','[::1]'].includes(url.hostname))throw Error('离线模式只能打开本机预览');
  const command=platform==='win32'?'powershell.exe':platform==='darwin'?'open':'xdg-open';
  const argv=platform==='win32'?['-NoProfile','-NonInteractive','-Command',"Start-Process -FilePath '"+url.href.replaceAll("'","''")+"'"]:[url.href];
  await options.run(command,argv,signal);return {status:'requested',action:args.action,url:url.href};
 }
 if(!['open_file','open_folder','reveal'].includes(args.action))throw Error('未知桌面操作');
 if(typeof args.path!=='string'||!path.isAbsolute(args.path)||args.path.includes('\0'))throw Error('请提供本地文件或文件夹的绝对路径');
 const target=fs.realpathSync(args.path),stat=fs.statSync(target);
 if(args.action==='open_file'&&(!stat.isFile()||!documents.has(path.extname(target).toLowerCase())))throw Error('打开文件支持 Office、PDF、文本、图片和影音；不能作为程序启动器');
 if(args.action==='open_folder'&&!stat.isDirectory())throw Error('目标不是文件夹；选中文件请用 reveal');
 if(args.action==='open_file'&&platform==='win32'&&['.pptx','.ppt'].includes(path.extname(target).toLowerCase())&&args.application!=='system'){
  // User preference: open presentations with registered WPS, without changing Windows associations.
  const literal="'"+target.replaceAll("'","''")+"'";
  const script="$p=$null; foreach($h in @('HKEY_CURRENT_USER','HKEY_LOCAL_MACHINE')){$v=(Get-ItemProperty -LiteralPath ('Registry::'+$h+'\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\wpp.exe') -ErrorAction SilentlyContinue).'(default)'; if($v -and (Test-Path -LiteralPath $v)){$p=$v;break}}; if(!$p){throw 'WPS Presentation is not registered. Install WPS or repair its application registration.'}; Start-Process -FilePath $p -ArgumentList ('\"' + "+literal+" + '\"'); Write-Output 'wps'";
  const r=await options.run('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],signal);
  return {status:'requested',action:args.action,path:target,application:r.stdout.trim()||'system'};
 }
 if(args.action==='reveal')await revealNativePath(target,signal,options);else await openNativePath(target,signal,options);
 return {status:'requested',action:args.action,path:target};
}
export function registerDesktopTools(ctx){
 ctx.tools.register(defineTool({name:'toolkit_desktop',description:'在用户电脑上实际打开已生成文件、打开文件夹、在资源管理器选中文件或用浏览器打开网页。PPT/PPTX 默认用 WPS 演示打开。用户要求打开时执行本工具，不只返回路径。文件/PPT 的工作台内预览通过 present 交付 PDF，编辑预览用 presentation_output.preview。',timeoutMs:20000,
  parameters:{action:{type:'string',required:true,enum:['status','open_file','open_folder','reveal','open_url'],description:'执行动作'},path:{type:'string',description:'文件/文件夹绝对路径'},url:{type:'string',description:'open_url 的 HTTP(S) 地址'}},
  output:{schema:{type:'json'},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]},execute:async(a,e)=>{const result=await desktopAction(a,e.signal);if(a.action==='status')result.session_tools=ctx.tools.schemas(e.agent).map(t=>t.name);return result;}}));
}
