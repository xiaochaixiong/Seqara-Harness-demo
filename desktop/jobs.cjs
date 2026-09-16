const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {EventEmitter} = require('node:events');

const ALLOWED = new Set(['invoices','clean','statistics','split','briefing','dashboard','activity-plan','delivery','print','classify_invoice_text']);
class Jobs extends EventEmitter {
  constructor(command, home) { super(); this.command=command; this.home=home; this.jobs=new Map(); }
  start(name,args) {
    if(!ALLOWED.has(name) || !args || typeof args!=='object' || JSON.stringify(args).length>1_000_000) throw Error('任务参数无效');
    if([...this.jobs.values()].some(j=>j.status==='running')) throw Error('已有业务任务运行，请等待完成或取消后再试。');
    const id=crypto.randomUUID();
    const job={id,name,status:'running',message:'正在读取文件…',percent:0,logs:[],startedAt:Date.now()};
    this.jobs.set(id,job);
    const child=spawn(this.command[0],this.command.slice(1),{windowsHide:true,
      env:{...process.env,NV_TOOLKIT_DATA_DIR:this.home,PYTHONIOENCODING:'utf-8'},stdio:['pipe','pipe','pipe']});
    job.child=child; let buffer='';
    child.stdout.setEncoding('utf8');
    const update=()=>this.emit('change',this.public(job));
    child.stdout.on('data',chunk=>{
      buffer+=chunk.toString('utf8'); const lines=buffer.split('\n'); buffer=lines.pop();
      for(const line of lines) { try {
        const event=JSON.parse(line);
        if(job.status!=='running') continue;
        if(event.type==='progress') {job.message=String(event.message);job.logs.push(job.message);job.logs=job.logs.slice(-100);if(event.percent!=null)job.percent=event.percent;}
        if(event.type==='result') {job.result=event.value;job.status='completed';job.percent=100;job.message='处理完成';this.persist(job);}
        if(event.type==='error') {job.status='failed';job.message=event.message;}
        update();
      } catch { /* native library stdout is not a protocol event */ } }
    });
    child.stderr.on('data',()=>{});
    child.on('error',e=>{job.status='failed';job.message='业务服务启动失败：'+e.message;update();});
    child.on('close',code=>{delete job.child;if(job.status==='running'){job.status='failed';job.message=`业务进程异常退出 (${code})`;}update();});
    child.stdin.on('error',()=>{});
    child.stdin.end(JSON.stringify({name,args})+'\n');
    update();return this.public(job);
  }
  public(j){const {child,...value}=j;return value;}
  list(){return [...this.jobs.values()].map(j=>this.public(j)).reverse();}
  cancel(id){const j=this.jobs.get(id);if(j?.status==='running'){j.status='cancelled';j.message='已取消，源文件保持不变';j.child?.kill();this.emit('change',this.public(j));}return true;}
  persist(job){fs.mkdirSync(this.home,{recursive:true});const p=path.join(this.home,'last-result.json');fs.writeFileSync(p,JSON.stringify(this.public(job)));}
  stop(){for(const j of this.jobs.values())this.cancel(j.id);}
}
module.exports={Jobs,ALLOWED};
