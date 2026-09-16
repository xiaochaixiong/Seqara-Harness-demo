/* Offline keeps the local settings host alive while rejecting external I/O. */
const fs=require('node:fs'),path=require('node:path');
const net=require('node:net'),dns=require('node:dns'),http=require('node:http'),https=require('node:https');
const local=host=>['127.0.0.1','::1','localhost'].includes(String(host||'localhost').replace(/^\[|\]$/g,'').toLowerCase());
function isOffline(){
 try{return JSON.parse(fs.readFileSync(path.join(process.env.NV_DESKTOP_DATA,'network.json'),'utf8')).offline===true;}
 catch{return process.env.SEQARA_OFFLINE==='1';}
}
function blocked(){const e=new Error('离线模式下无法联网；本地设置仍可使用。');e.code='SEQARA_OFFLINE';return e;}
function hostOf(args){
 const a=args[0];
 if(typeof a==='string'||a instanceof URL){try{return new URL(a).hostname;}catch{return args[1]?.hostname||args[1]?.host||'localhost';}}
 return a?.hostname||a?.host||'localhost';
}
let installed=false;
function install(){
 if(installed)return;installed=true;
 const sockets=new Set(),connect=net.Socket.prototype.connect;
 net.Socket.prototype.connect=function(...args){
  const a=Array.isArray(args[0])?args[0]:args;
  const option=a[0];const host=typeof option==='object'?option.host:typeof a[1]==='string'?a[1]:'localhost';
  const pipe=typeof option==='object'?option.path:typeof option==='string'&&!/^\d+$/.test(option);
  if(!pipe&&isOffline()&&!local(host)){queueMicrotask(()=>this.destroy(blocked()));return this;}
  if(!pipe&&!local(host)){sockets.add(this);this.once('close',()=>sockets.delete(this));}
  return connect.apply(this,args);
 };
 for(const mod of [http,https]){
  const request=mod.request;
  mod.request=function(...args){if(isOffline()&&!local(hostOf(args)))throw blocked();return request.apply(this,args);};
  mod.get=function(...args){const req=mod.request(...args);req.end();return req;};
 }
 const lookup=dns.lookup;
 dns.lookup=function(host,...args){if(isOffline()&&!local(host)){const callback=args.at(-1);if(typeof callback==='function'){queueMicrotask(()=>callback(blocked()));return;}throw blocked();}return lookup.call(this,host,...args);};
 const promiseLookup=dns.promises.lookup;
 dns.promises.lookup=async function(host,...args){if(isOffline()&&!local(host))throw blocked();return promiseLookup.call(this,host,...args);};
 if(globalThis.fetch){const fetch=globalThis.fetch;globalThis.fetch=function(input,...args){if(isOffline()&&!local(hostOf([typeof input==='object'&&input.url?input.url:input])))return Promise.reject(blocked());return fetch.call(this,input,...args);};}
 // Existing pooled connections must also close when the mode changes.
 setInterval(()=>{if(isOffline())for(const socket of sockets)socket.destroy(blocked());},100).unref();
 require('node:module').syncBuiltinESMExports();
}
module.exports={install,isOffline,local};
