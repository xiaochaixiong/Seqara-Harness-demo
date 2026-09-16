"""The same sidebar survives startup, offline mode and a stopped service.

THESIS: an orderly desktop workspace, with local tools available in every state.
OWN-WORLD: silver and graphite, medium brand lettering, neutral primary actions.
STORY: choose a tool, supply material, process and open the actual result.
FIRST VIEWPORT: 44px chrome, preserved sidebar, full native business page.
FORM: user-approved B typography and desktop framework; no direction roll.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md.
"""
import json,sys
from pathlib import Path

RESOURCE=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
CAPTURE=r'''(()=>{
 const source=document.querySelector('[class*="_sidebarCol"]');
 if(!source||!source.querySelector('[data-native-tool]'))return null;
 const clone=source.cloneNode(true);
 const originals=[...source.querySelectorAll('*')],copies=[...clone.querySelectorAll('*')];
 originals.forEach((el,i)=>{if(el.scrollTop)copies[i].dataset.sqScroll=el.scrollTop;});
 clone.querySelectorAll('script,iframe,object,embed,link,style').forEach(n=>n.remove());
 [clone,...clone.querySelectorAll('*')].forEach(n=>{
  [...n.attributes].forEach(a=>{if(/^on/i.test(a.name)||['srcset','action','formaction'].includes(a.name))n.removeAttribute(a.name);});
  if(n.hasAttribute('src')&&!n.getAttribute('src').startsWith('data:image/'))n.removeAttribute('src');
  if(n.hasAttribute('href'))n.removeAttribute('href');
 });
 const buttons=[...clone.querySelectorAll('button')];
 buttons.forEach(b=>{
  const label=(b.getAttribute('aria-label')||b.title||b.textContent).trim();
  if(b.matches('[data-native-tool]')&&Number(b.dataset.nativeTool)<7)b.dataset.sqLocal=b.dataset.nativeTool;
  else if(b.matches('.sq-settings-trigger')||label==='设置'||label==='Settings')b.dataset.sqAction='settings';
  else if(/收起侧|展开侧|打开侧|Collapse sidebar|Expand sidebar|Open sidebar/i.test(label)||b.matches('[class*="_collapseBtn"],[class*="_collapseButton"]'))b.dataset.sqAction='collapse';
 });
 let css='';for(const sheet of document.styleSheets){try{css+=[...sheet.cssRules].map(r=>r.cssText).join('\n');}catch{}}
 return JSON.stringify({version:1,html:clone.outerHTML,css,width:Math.round(source.getBoundingClientRect().width),scroll:source.scrollTop});
})()'''

def load_cache(data):
 try:
  value=json.loads((data/'sidebar-cache.json').read_text(encoding='utf8'))
  if not isinstance(value,dict) or value.get('version')!=1:return None
  if not isinstance(value.get('html'),str) or len(value['html'])>=500000:return None
  if not isinstance(value.get('css',''),str) or len(value.get('css',''))>=2000000:return None
  value['width']=max(52,min(400,int(value.get('width',280))))
  return value
 except (OSError,ValueError,TypeError,OverflowError):pass
 return None

def render(snapshot,dark,width,index,offline):
 assets=json.loads((RESOURCE/'seqara_shell.json').read_text(encoding='utf8'))
 payload={'snapshot':snapshot,'assets':assets,'dark':dark,'width':width,'index':index,'offline':offline}
 # JSON never becomes markup. Cached content is inert, with no remote resources,
 # no QWebChannel, and only three explicitly accepted desktop actions.
 encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')
 return r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
 <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; connect-src 'none'">
 <style>html,body{margin:0;width:100%;height:100%;overflow:hidden}#sidebar{position:absolute;inset:0 auto 0 0;height:100%;overflow:hidden}#sidebar>[class*='_sidebarCol']{height:100%;width:100%!important;flex-basis:auto!important}#sidebar [class*='_root']:has(>[class*='_logoRow']){height:100%;box-sizing:border-box}
 button:disabled,[aria-disabled=true]{opacity:.4!important;cursor:default!important;filter:grayscale(1)}
 button:disabled:has([data-seqara-signature]){opacity:1!important;filter:none!important}
 #sidebar button[aria-current=page]{background:var(--nv-selected);font-weight:600}
 #sidebar button:focus-visible{outline:2px solid var(--nv-focus);outline-offset:-2px}
 .sq-shell{display:flex;flex-direction:column;height:100%;box-sizing:border-box;padding:12px;background:var(--nv-sidebar);color:var(--nv-text);border-right:1px solid var(--nv-line);font:14px 'Segoe UI','Microsoft YaHei',sans-serif}
 .sq-shell-logo{display:flex;align-items:center;justify-content:space-between;min-height:44px;gap:6px}.sq-shell-logo svg{max-width:174px;height:37px}.sq-shell button{display:flex;align-items:center;gap:12px;box-sizing:border-box;width:100%;min-height:36px;padding:8px 12px;border:0;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left}.sq-shell button:hover:enabled{background:var(--nv-hover)}.sq-shell button svg{flex-shrink:0}.sq-shell-logo button{width:28px;padding:4px;flex-shrink:0}.sq-shell-logo button span{display:none}.sq-shell-scroll{flex:1;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;padding:14px 0}.sq-shell .nv-group{font-size:12px;color:var(--nv-muted);padding:12px 12px 8px}.sq-shell hr{width:100%;border:0;border-top:1px solid var(--nv-line);margin:10px 0}.sq-shell.collapsed span,.sq-shell.collapsed .nv-group,.sq-shell.collapsed .sq-shell-logo>svg{display:none}.sq-shell.collapsed{padding:12px 8px}.sq-shell.collapsed button{justify-content:center;padding:8px 4px}
 </style></head><body><div id="sidebar"></div><script>
 const data='''+encoded+r''';
 const tell=value=>console.log('__SQ_SHELL__'+JSON.stringify(value));
 const host=document.getElementById('sidebar'),style=document.createElement('style');
 style.textContent=(data.snapshot?.css||'')+'\n'+data.assets.css;document.head.append(style);
 const icon=path=>'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+path+'"/></svg>';
 const button=(title,path,attr='')=>'<button '+attr+(attr.includes('collapse')?'':' title="'+title+'"')+' aria-label="'+title+'">'+icon(path)+'<span>'+title+'</span></button>';
 // A compact React snapshot omits labels from its markup; reconstruct the local
 // shell so expanding it can restore the complete brand and control labels.
 if(data.snapshot&&Number(data.snapshot.width||data.width)>=100)host.innerHTML=data.snapshot.html;
 else host.innerHTML='<aside class="sq-shell"><div class="sq-shell-logo">'+data.assets.day+button('收起侧栏','M9 5l-7 7 7 7 M16 4v16','data-sq-action="collapse"')+'</div>'+button('新建会话','M12 4v16 M4 12h16')+button('工作区','M3 7h7l2 3h9v10H3z')+'<div class="sq-shell-scroll"><div class="nv-group">工作工具</div>'+data.assets.titles.map((t,i)=>button(t,data.assets.icons[i],'data-sq-local="'+i+'"')).join('')+'<hr><div class="nv-group">扩展工具</div>'+[['技能与模板','M5 4h14v16H5z M8 8h8 M8 12h8'],['处理任务','M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5'],['插件市场','M3 9h18v12H3z M3 9l3-6h12l3 6 M9 21v-8h6v8']].map(v=>button(...v)).join('')+'</div><hr>'+button('设置','M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2','data-sq-action="settings"')+'</aside>';
 // Discard the retired presentation entry from version 0.4.0 sidebar caches.
 host.querySelectorAll('[data-sq-local="8"],[data-native-tool="8"]').forEach(n=>n.remove());
 host.querySelectorAll('button[aria-label="导入会话"],button[aria-label="Import sessions"]').forEach(n=>n.remove());
 host.querySelectorAll('.nv-group').forEach(n=>{if(n.textContent==='工具与扩展')n.textContent='扩展工具';});
 host.style.width=data.width+'px';
 host.querySelectorAll('script,iframe,object,embed').forEach(n=>n.remove());
 host.querySelectorAll('button,a,input,select,textarea,[role=button]').forEach(b=>{
  const label=b.getAttribute('aria-label')||b.title||b.textContent.trim();
  if(/收起侧|展开侧|打开侧|Collapse sidebar|Expand sidebar|Open sidebar/i.test(label))b.dataset.sqAction='collapse';
  const local=b.dataset.sqLocal,action=b.dataset.sqAction;
  const available=(local!==undefined&&local!=='5')||action==='settings'||action==='collapse';
  b.disabled=!available;b.setAttribute('aria-disabled',String(!available));
  if(!available){b.tabIndex=-1;b.title=(b.title||b.textContent.trim())+' · '+(data.offline?'需要联网':'正在连接');}
 });
 function select(index){data.index=index;host.querySelectorAll('[data-sq-local]').forEach(b=>{if(Number(b.dataset.sqLocal)===index)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});}
 function theme(dark){data.dark=dark;document.body.toggleAttribute('data-ds-dark-theme',dark);document.documentElement.style.colorScheme=dark?'dark':'light';const logo=host.querySelector('.sq-shell-logo>svg');if(logo)logo.outerHTML=dark?data.assets.night:data.assets.day;}
 function collapse(width){if(width>=100)host.querySelectorAll('[class*="_collapsed"]').forEach(n=>n.className=n.className.split(' ').filter(c=>!c.includes('_collapsed')).join(' '));host.querySelectorAll('[data-sq-action="collapse"]').forEach(b=>b.setAttribute('aria-label',width<100?'展开侧边栏':'收起侧边栏'));data.width=width;host.style.width=width+'px';host.querySelector('.sq-shell')?.classList.toggle('collapsed',width<100);const original=host.querySelector('[class*="_root"]:has(>[class*="_logoRow"])');if(original){original.style.width='100%';if(width<100){original.classList.add('sq-cached-collapsed');}else original.classList.remove('sq-cached-collapsed');}tell({type:'width',width});}
 const collapsedStyle=document.createElement('style');collapsedStyle.textContent='.sq-cached-collapsed .nv-group,.sq-cached-collapsed button span,.sq-cached-collapsed [class*="_brandIdentity"],.sq-cached-collapsed [class*="_regionArea"]{display:none!important}.sq-cached-collapsed button{justify-content:center;padding-inline:4px!important}';document.head.append(collapsedStyle);
 // Captured collapsed classes are kept until the user explicitly expands.
 host.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;e.preventDefault();if(b.dataset.sqLocal!==undefined){select(Number(b.dataset.sqLocal));tell({type:'tool',index:Number(b.dataset.sqLocal)});}else if(b.dataset.sqAction==='settings')tell({type:'settings'});else if(b.dataset.sqAction==='collapse'){if(data.width<100)host.querySelectorAll('[class*="_collapsed"]').forEach(n=>n.className=n.className.split(' ').filter(c=>!c.includes('_collapsed')).join(' '));collapse(data.width<100?280:60);}});
 window.sqShell={select,theme};theme(data.dark);select(data.index);collapse(data.width);
 host.querySelectorAll('[data-sq-scroll]').forEach(n=>n.scrollTop=Number(n.dataset.sqScroll));
 </script></body></html>'''
