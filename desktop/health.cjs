async function readLocalPage(url){
 let target=new URL(url);if(target.hostname!=='127.0.0.1'||target.protocol!=='http:')throw Error('内核必须使用本地 HTTP 地址');
 const origin=target.origin;let cookie='';
 for(let i=0;i<5;i++){
  const response=await fetch(target,{redirect:'manual',headers:cookie?{Cookie:cookie}:{},signal:AbortSignal.timeout(10000)});
  const received=response.headers.getSetCookie();if(received.length)cookie=received.map(v=>v.split(';')[0]).join('; ');
  if([301,302,303,307,308].includes(response.status)&&response.headers.has('location')){target=new URL(response.headers.get('location'),target);if(target.origin!==origin)throw Error('内核页面跳转到非本地来源');continue;}
  if(!response.ok)throw Error('内核页面不可用：HTTP '+response.status);
  return {html:await response.text(),url:target.href,cookie};
 }
 throw Error('内核页面跳转次数异常');
}
async function validateRuntimePage(url){
 const page=await readLocalPage(url);
 for(const marker of ['__DSH_BOOT__','@nv/dsh-business-ui','@deepseek-ai/dsh-client-ui-settings-general'])if(!page.html.includes(marker))throw Error('内核启动清单缺少 '+marker);
 return page;
}
module.exports={readLocalPage,validateRuntimePage};
