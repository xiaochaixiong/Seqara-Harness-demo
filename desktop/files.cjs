// Node 24 fs.cpSync can crash on this Windows Unicode workspace.
// Walk directories in JavaScript; preserve pnpm directory links without cycles.
const fs=require('node:fs'),path=require('node:path');
function copyDirectory(source,destination){
 const base=path.resolve(source),out=path.resolve(destination);
 const within=(root,p)=>{const r=path.relative(root,p);return r===''||(!r.startsWith('..')&&!path.isAbsolute(r));};
 if(within(base,out))throw Error('复制目标不能位于源目录中');
 function walk(src,dst){
  const stat=fs.lstatSync(src);
  if(stat.isSymbolicLink()){
   const original=path.resolve(path.dirname(src),fs.readlinkSync(src));
   const target=within(base,original)?path.join(out,path.relative(base,original)):original;
   fs.mkdirSync(path.dirname(dst),{recursive:true});
   if(fs.existsSync(dst)){
    if(!fs.lstatSync(dst).isSymbolicLink())throw Error('复制链接时目标已被普通文件占用：'+dst);
    fs.unlinkSync(dst);
   }
   if(fs.statSync(src).isDirectory())fs.symlinkSync(target,dst,process.platform==='win32'?'junction':'dir');
   else fs.copyFileSync(src,dst);
  }else if(stat.isDirectory()){
   fs.mkdirSync(dst,{recursive:true});
   for(const entry of fs.readdirSync(src))walk(path.join(src,entry),path.join(dst,entry));
  }else fs.copyFileSync(src,dst);
 }
 walk(base,out);
}
module.exports={copyDirectory};
