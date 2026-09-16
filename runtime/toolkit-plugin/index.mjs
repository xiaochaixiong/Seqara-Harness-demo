import {defineTool} from '@deepseek-ai/dsh-tools';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {registerVisionTools} from './vision.mjs';
import {registerDesktopTools} from './desktop.mjs';
import {presentFiles} from './delivery.mjs';
import {registerDiagnostics} from './diagnostics.mjs';
export const inject=['tools','userQuestions'];
export async function invoke(name,args,signal){
 const command=JSON.parse(process.env.NV_TOOLKIT_COMMAND||'[]');if(!command.length)throw Error('请通过数据整理工具集启动');
 signal?.throwIfAborted();
 return new Promise((resolve,reject)=>{
  const child=spawn(command[0],command.slice(1),{windowsHide:true,stdio:['pipe','pipe','pipe'],env:process.env});
  const labels={invoices:'发票整理',clean:'数据整理',statistics:'统计报表',split:'拆分活动表',briefing:'活动简报',dashboard:'数据看板','activity-plan':'活动方案',delivery:'交付报告',print:'文档转换与打印',classify_invoice_text:'发票规则预检查'};
  const task={id:randomUUID(),name,label:labels[name]||name,state:'running',pid:child.pid,startedAt:Date.now(),message:'正在启动'};
  const publish=patch=>{Object.assign(task,patch,{updatedAt:Date.now()});if(!process.env.NV_TOOLKIT_TASK_DIR)return;try{fs.mkdirSync(process.env.NV_TOOLKIT_TASK_DIR,{recursive:true});const file=path.join(process.env.NV_TOOLKIT_TASK_DIR,task.id+'.json');fs.writeFileSync(file+'.tmp',JSON.stringify(task));fs.renameSync(file+'.tmp',file);}catch{}};
  publish({});
  let buffer='',result,error,cancelled=false;const abort=()=>{cancelled=true;child.kill();error='业务任务已取消';};
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  child.stdout.setEncoding('utf8');child.stdout.on('data',chunk=>{buffer+=chunk;const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines){try{const e=JSON.parse(line);if(e.type==='result')result=e.value;if(e.type==='error')error=e.message;if(e.type==='progress')publish({message:e.message,percent:e.percent});}catch{}}});
  child.stderr.on('data',()=>{});child.stdin.on('error',()=>{});
  child.once('error',e=>{error=e.message;publish({state:'failed',message:error});reject(e);});child.once('close',code=>{signal?.removeEventListener('abort',abort);if(error||!result||code!==0){publish({state:cancelled?'cancelled':'failed',message:error||'业务处理失败'});reject(Error(error||'业务处理失败'));}else {publish({state:'completed',message:'处理完成',percent:100,output:result.output_dir});resolve(result);}});
  child.stdin.end(JSON.stringify({name,args})+'\n');
 });
}
const string=description=>({type:'string',required:true,description});
const optional=(type,description)=>({type,description});
export function apply(ctx){
 registerDiagnostics(ctx);
 registerDesktopTools(ctx);
 registerVisionTools(ctx);
 const rows=[
 ['invoices','沿用数据整理工具集的完整发票分类、票种拆分、分组和封面流程；生成新 Excel，不覆盖源文件。',{source:string('Excel 绝对路径'),company:string('公司名称'),project:string('项目名称')}],
 ['clean','关联活动申请和报销 Excel，生成清洗后的 Excel 与 CSV。',{source:string('活动申请表绝对路径'),reimbursement:string('活动报销表绝对路径')}],
 ['statistics','根据清洗结果生成原工具集口径的项目统计 Excel。',{source:string('清洗结果 Excel 绝对路径')}],
 ['split','将活动 Excel 按院校拆分，生成独立工作簿。',{source:string('活动总表绝对路径')}],
 ['briefing','读取活动 Excel 中新闻链接并生成 Word 简报，网络访问可能失败。',{source:string('活动 Excel 绝对路径')}],
 ['activity-plan','将已完成的活动方案 Markdown 排版为工具集标准 Word。',{project:string('项目名称'),school:string('服务院校'),activity_type:string('活动类型'),period:string('活动周期'),body:string('完整 Markdown 正文')}],
 ['delivery','将已完成的交付报告 Markdown 排版为工具集标准 Word。',{school:string('服务院校'),year:string('报告年份'),period:string('报告周期'),body:string('完整 Markdown 正文')}],
 ['classify_invoice_text','用原关键词规则预检查一条发票描述，不能代替整表分类。',{text:string('发票描述')}]
 ];
 rows.push(['dashboard','读取活动台账，按月份筛选数据看板；不修改源文件。',{source:string('活动 Excel 绝对路径'),reimbursement:optional('string','可选报销表绝对路径'),supplementary:optional('string','可选补充活动表绝对路径'),start:optional('string','开始月份 YYYY-MM'),end:optional('string','结束月份 YYYY-MM')}],['print','将 Word 转为 PDF，或在用户明确确认文件和默认打印机后提交打印。实际打印必须 confirmed=true。',{source:string('文件绝对路径'),mode:optional('string','convert（默认）或 print'),engine:optional('string','word（默认）或 wps'),confirmed:optional('boolean','用户已明确确认本次实际打印；转 PDF 不需要')}]);
 const extras={invoices:{base:optional('number','分组目标金额'),jitter:optional('number','金额浮动'),seed:optional('number','随机种子'),ticket_threshold:optional('number','机票拆分阈值'),ticket_group_size:optional('number','机票分组条数'),cover_series:optional('number','封面系列'),start_index:optional('number','分组起始序号'),amount_fallback:optional('boolean','启用金额兜底')},clean:{threshold:optional('number','院校模糊匹配阈值 50–100')},briefing:{split_by_activity:optional('boolean','按活动拆分简报'),full_content:optional('boolean','保留完整新闻正文')},delivery:{source:optional('string','可选活动 Excel 绝对路径')}};
 for(const [name,description,parameters] of rows)ctx.tools.register(defineTool({name:'toolkit_'+name.replaceAll('-','_'),description,parameters:{...parameters,...extras[name]},
  output:{schema:{type:'json'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},execute:async(args,exec)=>{
   const result=await invoke(name,args,exec.signal);
   if(result.artifacts?.length){result.deliveries=[];try{for(let i=0;i<result.artifacts.length;i+=8)result.deliveries.push(await presentFiles(ctx,exec,result.artifacts.slice(i,i+8).map(file=>({path:file,description:path.basename(file)}))));}catch(error){result.delivery_error=error.message+'。文件已生成；只需重新调用 present，不要重复运行业务处理。';}}
   return result;
  }}));
}
