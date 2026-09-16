import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {defineTool} from '@deepseek-ai/dsh-tools';

export function redactError(value){return String(value||'未知错误').replace(/\bsk-[\w-]+/g,'[redacted]').replace(/(bearer\s+)[\w.-]+/gi,'$1[redacted]').replace(/((?:api[_-]?key|token|password|secret)["']?\s*[=:]\s*["']?)[^\s"'&<>]+/gi,'$1[redacted]').replace(/\/s\/[a-f0-9]{32,}/gi,'/s/[redacted]').slice(0,3500);}
export function failureKind(message){
 const s=String(message);
 if(/abort|cancel|已取消/i.test(s))return 'cancelled';
 if(/版本已变化|revision|stale/i.test(s))return 'version_conflict';
 if(/403|forbidden|拒绝|blocked|denied/i.test(s))return 'access_denied';
 if(/timed?\s*out|timeout|超时|fetch failed|网络/i.test(s))return 'connection';
 if(/ENOENT|not found|不存在|找不到/i.test(s))return 'missing_resource';
 if(/NO_PROVIDER|未启用|未配置|不可用/i.test(s))return 'missing_capability';
 if(/需要|须为|无效|缺少|不一致|锁定|unsupported|invalid/i.test(s))return 'validation';
 return 'runtime';
}
export function recordFailure(event,root=process.env.NV_TOOLKIT_DATA_DIR){
 if(!root)return null;
 try{
  const dir=path.join(root,'diagnostics');fs.mkdirSync(dir,{recursive:true});
  const message=redactError(event.message),kind=failureKind(message),fingerprint=createHash('sha256').update(String(event.tool)+'\n'+message).digest('hex').slice(0,16);
  const row={at:new Date().toISOString(),fingerprint,kind,tool:String(event.tool||'workbench').slice(0,120),action:String(event.action||'').slice(0,50),call_id:event.call_id||null,session_id:event.session_id||null,message};
  const file=path.join(dir,row.at.slice(0,10)+'.jsonl');
  // Bound daily storage; never record tool arguments, file bytes, or provider credentials.
  if(!fs.existsSync(file)||fs.statSync(file).size<8_000_000)fs.appendFileSync(file,JSON.stringify(row)+'\n');
  return row;
 }catch{return null;}
}
export function recentFailures(root=process.env.NV_TOOLKIT_DATA_DIR,limit=30){
 const dir=path.join(root||'','diagnostics');if(!root||!fs.existsSync(dir))return {events:[],directory:root?dir:null};
 const rows=fs.readdirSync(dir).filter(n=>/^\d{4}-\d{2}-\d{2}\.jsonl$/.test(n)).sort().slice(-7).flatMap(n=>fs.readFileSync(path.join(dir,n),'utf8').split('\n').filter(Boolean).flatMap(s=>{try{return [JSON.parse(s)];}catch{return [];}}));
 return {events:rows.slice(-Math.max(1,Math.min(100,Number(limit)||30))).reverse(),directory:dir};
}
export function registerDiagnostics(ctx){
 ctx.on?.('tools/result',(exec,result)=>{
  const message=result.isError?(result.content||[]).filter(c=>c.type==='text').map(c=>c.text).join('\n'):result.value?.delivery_error;
  if(message)recordFailure({tool:exec.name,action:exec.arguments?.action,call_id:exec.callId,session_id:exec.agent?.session?.id,message});
 });
 ctx.tools.register(defineTool({name:'toolkit_diagnostics',description:'读取最近工作台工具调用错误台账，含时间、工具、错误分类、去重标识。不记录提示词、材料和密钥；取消与权限拒绝分别记录，不绕过限制。',parameters:{limit:{type:'integer',description:'最多 100 条，默认 30'}},output:{schema:{type:'json'},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]},execute:a=>recentFailures(undefined,a.limit)}));
}
