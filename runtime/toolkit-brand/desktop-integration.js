/* DSH owns sections and preferences. Seqara owns desktop routing and section persistence. */
function installSeqaraDesktop(ctx, React, jsx, jsxs, tell, Modal) {
 const {useState,useEffect,useRef}=React;
 const disposers=[];let activeNative=-1,activeRoute='conversation',modal=false,lastSection='general',taskState={native:[],agent:[]};
 disposers.push(installSeqaraMarket());
 installWorkspaceManager(ctx,React,jsx,jsxs,Modal);
 let exitRequested=false;const dirty=new Set();const dirtyChanged=()=>{tell({type:'settings-dirty',dirty:dirty.size>0});settingsTrigger()?.toggleAttribute('data-sq-unsaved',dirty.size>0);window.dispatchEvent(new CustomEvent('sq-dirty',{detail:dirty.size}));};
 const desktop=async(action,args)=>{if(!window.seqaraDesktopReady)throw Error('此设置需要在有序 Seqara 桌面中使用。');const call=await window.seqaraDesktopReady;return call(action,args);};
 const icon=(path)=>jsx('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.5,'aria-hidden':true,children:jsx('path',{d:path})});
 let pluginTransition=false,haveTaskboard=false;
 const setRoute=(id,closePlugins=true)=>{if(closePlugins&&id!=='plugin:taskboard'&&document.documentElement.hasAttribute('data-dsh-taskboard-active')){pluginTransition=true;try{document.querySelector('[data-dsh-taskboard-entry]')?.click();}finally{pluginTransition=false;}}activeRoute=id;document.documentElement.dataset.seqaraSurface=id;window.dispatchEvent(new CustomEvent('seqara-route',{detail:id}));};
 const route=(id,title,closePlugins=true)=>{activeNative=-1;window.dispatchEvent(new CustomEvent('nv-select',{detail:-1}));setRoute(id,closePlugins);if(id==='conversation')ctx.layout.selectPanel(null);tell({type:'web-surface',id,title});};
 const listen=(target,event,fn,options)=>{target.addEventListener(event,fn,options);disposers.push(()=>target.removeEventListener(event,fn,options));};
 // Upstream renders an Ungrouped + but only handles rows with a workspace ID.
 // Create through the session controller without attaching to a recent workspace.
 let creatingUngrouped=false;
 let overlayState='';const overlayTimer=setInterval(()=>{
  const rects=[...document.querySelectorAll('[role="tooltip"],[role="menu"]')].filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden').map(e=>{const r=e.getBoundingClientRect();return [Math.floor(r.x)-8,Math.floor(r.y)-8,Math.ceil(r.width)+16,Math.ceil(r.height)+16];});
  const next=JSON.stringify(rects);if(next!==overlayState){overlayState=next;tell({type:'web-overlays',rects});}
 },100);disposers.push(()=>clearInterval(overlayTimer));
 listen(document,'click',e=>{
  const button=e.target.closest?.('[data-slot="sidebar.workspaces"] button');
  if(!button||!['在“未分组”中新建会话','New session in Ungrouped'].includes(button.getAttribute('aria-label')))return;
  e.preventDefault();e.stopImmediatePropagation();
  if(creatingUngrouped)return;
  if(window.seqaraOffline){tell({type:'session-notice',message:'请先恢复联网，再新建会话。'});return;}
  creatingUngrouped=true;button.disabled=true;
  tell({type:'session-notice',message:'正在新建未分组会话…'});
  document.querySelector('[data-sq-session-error]')?.remove();
  route('conversation','有序 Seqara · 工作台');
  const navigation=ctx.layout.beginNavigation();
  ctx.sessions.create().then(id=>{
   ctx.sessions.open(id);
   tell({type:'session-notice',message:'已新建未分组会话，请选择工作区后开始输入。'});
   requestAnimationFrame(()=>requestAnimationFrame(()=>{
    if(navigation.aborted)return;
    const input=document.querySelector('[data-composer-input]');
    // DSH requires choosing a workspace before the first message. Open its
    // picker for this new ungrouped draft instead of leaving a disabled editor.
    if(input?.getAttribute('contenteditable')==='false'){
     document.querySelector('button[aria-label="选择工作区"],button[aria-label="Choose workspace"]')?.click();
    }else input?.focus();
   }));
  }).catch(error=>{
   const message=document.createElement('p');message.dataset.sqSessionError='';message.setAttribute('role','alert');
   message.textContent='新建会话失败：'+error.message+'。请重试。';
   document.querySelector('[data-slot="sidebar.workspaces"]')?.append(message);
  }).finally(()=>{creatingUngrouped=false;button.disabled=false;});
 },true);
 listen(window,'seqara-conversation',()=>route('conversation','有序 Seqara · 工作台'));
 const sectionRows=()=>ctx.slots.entries('settings.section').map(e=>({id:e.options.id,order:e.options.order||0,label:typeof e.options.label==='function'?e.options.label():e.options.label||e.options.id})).filter(r=>r.id).sort((a,b)=>a.order-b.order);
 const drafts=new Map();
 const settingsDialog=()=>document.querySelector('[data-slot="sidebar.settings"] [role="dialog"]');
 const settingsTrigger=()=>document.querySelector('[data-slot="sidebar.settings"] button[aria-haspopup="dialog"]');
 const closeButton=()=>settingsDialog()?.querySelector('button[class*="_close"]');
 // Some plugins omit aria-modal on their task/delete dialogs. They still own
 // focus and must release the native page mask until the last dialog closes.
 const dialogSelector='[role="dialog"]:not([aria-modal="false"]),[role="alertdialog"]:not([aria-modal="false"])';
 const visibleDialogs=()=>[...document.querySelectorAll(dialogSelector)].filter(d=>d.getClientRects().length&&getComputedStyle(d).visibility!=='hidden');
 const childDialog=panel=>visibleDialogs().filter(d=>d!==panel&&!d.contains(panel)).at(-1);
 let nestedDialog=null,settingsReturnFocus=null;
 function syncDialogFocus(panel){
  const next=panel?childDialog(panel):null;
  if(next===nestedDialog)return;
  const previous=nestedDialog;nestedDialog=next;
  if(next){
   if(!previous)settingsReturnFocus=document.activeElement;
   if(!next.contains(document.activeElement))next.querySelector('button:not(:disabled),input:not(:disabled),[tabindex="0"]')?.focus({preventScroll:true});
  }else{
   if(panel&&settingsReturnFocus?.isConnected)settingsReturnFocus.focus({preventScroll:true});
   settingsReturnFocus=null;
  }
 }
 let offline=!!window.seqaraOffline;
 function syncOfflineSettings(){
  document.body.toggleAttribute('data-seqara-offline',offline);
  const panel=settingsDialog();
  if(panel){
   const targets=[...panel.querySelectorAll('button')].filter(b=>b.dataset.sqSectionLink==='market'||/^(测试连接|检查连接|测试模型|刷新模型|检查版本|检查更新|下载并验证更新|安装插件|下载插件|Test connection|Check for updates|Download update)$/i.test(b.textContent.trim()));
   for(const b of targets){if(offline&&!b.hasAttribute('data-sq-network-disabled')){b.dataset.sqPreviousDisabled=String(b.disabled);b.dataset.sqPreviousTitle=b.title;b.setAttribute('data-sq-network-disabled','');b.disabled=true;b.title='离线模式下不可用，请先恢复联网。';}}
   if(!offline)for(const b of panel.querySelectorAll('[data-sq-network-disabled]')){b.disabled=b.dataset.sqPreviousDisabled==='true';b.title=b.dataset.sqPreviousTitle||'';b.removeAttribute('data-sq-network-disabled');delete b.dataset.sqPreviousDisabled;delete b.dataset.sqPreviousTitle;}
  }
  if(offline){const later=[...document.querySelectorAll('[role="dialog"] button')].find(b=>['稍后配置','Set up later'].includes(b.textContent.trim()));later?.click();}
 }
 listen(window,'seqara-network-mode',e=>{offline=!!e.detail?.offline;window.seqaraOffline=offline;syncOfflineSettings();});
 listen(document,'click',e=>{if(offline&&e.target.closest?.('[data-sq-network-disabled]')){e.preventDefault();e.stopImmediatePropagation();}},true);
 const offlineObserver=new MutationObserver(syncOfflineSettings);offlineObserver.observe(document.body,{childList:true,subtree:true});disposers.push(()=>offlineObserver.disconnect());syncOfflineSettings();
 function Guard(){const [show,setShow]=useState(false),[,refresh]=useState(0);useEffect(()=>{const f=()=>{setShow(true);refresh(v=>v+1);};const clear=e=>{if(!e.detail)setShow(false);};window.addEventListener('sq-unsaved',f);window.addEventListener('sq-dirty',clear);return()=>{window.removeEventListener('sq-unsaved',f);window.removeEventListener('sq-dirty',clear);};},[]);return show&&jsxs('div',{className:'sq-unsaved',role:'alert',children:[jsx('span',{children:exitRequested?'设置还有未保存的更改。可继续编辑，或放弃更改并退出。':'还有未保存的更改，请保存后关闭，或放弃更改。'}),jsx('button',{onClick:()=>{exitRequested=false;setShow(false);},children:'继续编辑'}),jsx('button',{onClick:()=>{dirty.clear();drafts.clear();dirtyChanged();if(exitRequested){exitRequested=false;tell({type:'close-approved'});}else closeButton()?.click();},children:exitRequested?'放弃并退出':'放弃并关闭'})]});}
 ctx.slots.inject('settings.action',()=>ctx.slots.register({name:'settings.action',id:'seqara-unsaved',order:-100},Guard));
 const originalSettingsButtons=()=>[...(settingsDialog()?.querySelectorAll('nav [class*="_navList"] > button')||[])];
 const sectionButton=id=>{const rows=sectionRows(),buttons=originalSettingsButtons(),index=rows.findIndex(r=>r.id===id);return index>=0&&buttons.length===rows.length&&buttons[index]?.textContent.trim()===rows[index].label?buttons[index]:undefined;};
 function SettingsNavigation(){
  const [query,setQuery]=useState(''),[,refresh]=useState(0);
  useEffect(()=>{const f=()=>refresh(v=>v+1);const off=ctx.slots.subscribe('settings.section',f);window.addEventListener('sq-section',f);window.addEventListener('sq-dirty',f);return()=>{off();window.removeEventListener('sq-section',f);window.removeEventListener('sq-dirty',f);};},[]);
  const groups=SeqaraNavigation.sections(sectionRows(),query);
  return jsxs('div',{className:'sq-settings-navigation',children:[jsx('h1',{id:'sq-settings-heading',children:'设置'}),
   jsxs('div',{className:'sq-settings-search',children:[jsx('input',{type:'search',value:query,'aria-label':'搜索设置',placeholder:'搜索设置',onChange:e=>setQuery(e.target.value)}),query&&jsx('button',{type:'button','aria-label':'清除设置搜索',onClick:()=>setQuery(''),children:'×'})]}),
   jsx('div',{className:'sq-settings-groups',role:'navigation','aria-label':'设置分区',children:groups.map(group=>jsxs('section',{'aria-label':group.label,children:[jsx('h2',{children:group.label}),...group.rows.map(row=>jsxs('button',{type:'button','data-sq-section-link':row.id,'aria-current':lastSection===row.id?'page':undefined,onClick:()=>sectionButton(row.id)?.click(),children:[jsx('span',{children:row.label}),dirty.has(row.id.replace('seqara-',''))&&jsx('span',{className:'sq-dirty-dot','aria-label':'未保存',title:'未保存',children:'•'})]},row.id))]},group.id))}),
   !groups.length&&jsx('p',{role:'status',className:'sq-search-empty',children:'未找到相关设置，可尝试“模型”“院校”或“更新”。'})]});
 }
 ctx.slots.inject('settings.header',()=>ctx.slots.register({name:'settings.header',priority:-100},SettingsNavigation));
 let pendingSection=null;
 const selectPending=()=>{if(!pendingSection||!settingsDialog())return;const button=sectionButton(pendingSection)||sectionButton('general');if(button){pendingSection=null;button.click();}};
 listen(window,'seqara-settings',e=>{if(e.detail?.open===false){closeButton()?.click();return;}pendingSection=e.detail?.section||lastSection;tell({type:'modal-open'});if(!settingsDialog())settingsTrigger()?.click();requestAnimationFrame(selectPending);});
 listen(window,'seqara-close-request',()=>{if(!dirty.size){tell({type:'close-approved'});return;}exitRequested=true;window.dispatchEvent(new CustomEvent('seqara-settings',{detail:{section:'seqara-'+[...dirty][0]}}));requestAnimationFrame(()=>window.dispatchEvent(new Event('sq-unsaved')));});
 listen(document,'click',e=>{if(e.target.closest?.('button')===settingsTrigger()&&!settingsDialog()){pendingSection=pendingSection||lastSection;tell({type:'modal-open'});}},true);
 listen(document,'click',e=>{const panel=settingsDialog();if(!panel||!dirty.size)return;const target=e.target;const closing=target.closest?.('button[class*="_close"]')===closeButton()||target.matches?.('[class*="_mask"]');if(closing){e.preventDefault();e.stopImmediatePropagation();window.dispatchEvent(new Event('sq-unsaved'));}},true);
 listen(document,'keydown',e=>{
  const settings=settingsDialog();if(!settings)return;
  const child=childDialog(settings),panel=child||settings;
  if(e.key==='Escape'&&child){
   const close=child.querySelector('button[class*="_close"],button[aria-label="关闭"],button[aria-label="Close"]');
   if(close){e.preventDefault();e.stopImmediatePropagation();close.click();}return;
  }
  if(e.key==='Escape'&&dirty.size){e.preventDefault();e.stopImmediatePropagation();window.dispatchEvent(new Event('sq-unsaved'));}
  if(e.key==='Tab'){
   const items=[...panel.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')].filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length);
   const first=items[0],last=items.at(-1);
   if(e.shiftKey&&(document.activeElement===first||!panel.contains(document.activeElement))){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&(document.activeElement===last||!panel.contains(document.activeElement))){e.preventDefault();first?.focus();}
  }
 },true);
 const defaults={deepseek_model:'deepseek-v4-flash',max_tokens:2000,connect_timeout:30,read_timeout:480,net_retry_times:3,server_retry_times:3};
 function Editor({section,title}) {
  const [data,setData]=useState(null),[revision,setRevision]=useState(''),[status,setStatus]=useState('正在读取…'),[busy,setBusy]=useState(false),[changed,setChanged]=useState(false);
  const update=(next)=>{setData(next);setChanged(true);dirty.add(section);dirtyChanged();drafts.set(section,{data:next,revision});setStatus('有未保存的更改');};
  const load=()=>{setBusy('正在读取设置…');desktop('settings.read',{section}).then(r=>{setData(section==='connection'?{...defaults,...r.value}:section==='tickets'||section==='projects'?Object.entries(r.value).map(([company,schools])=>({company,schools:schools.map(v=>Array.isArray(v)?v[0]:typeof v==='object'?v.school:v).join('\n')})):r.value);setRevision(r.revision);setChanged(false);dirty.delete(section);drafts.delete(section);dirtyChanged();setStatus('');}).catch(e=>setStatus(e.message)).finally(()=>setBusy(false));};
  useEffect(()=>{const draft=drafts.get(section);if(draft){setData(draft.data);setRevision(draft.revision);setChanged(true);setStatus('有未保存的更改');}else load();},[]);
  const save=async()=>{setBusy('正在保存…');try{let value=data;if(Array.isArray(data)){value={};for(const row of data){const company=row.company.trim();if(!company||Object.hasOwn(value,company))throw Error('请填写公司名称，并合并重复的公司。');value[company]=row.schools.split('\n').map(s=>s.trim()).filter(Boolean);}}const r=await desktop('settings.save',{section,value,revision});setRevision(r.revision);if(section==='connection')setData({...defaults,...r.value});setChanged(false);dirty.delete(section);drafts.delete(section);dirtyChanged();setStatus('设置已保存，将用于下一次处理。');}catch(e){setStatus(e.message);}finally{setBusy(false);}};
  const field=(key,label,type='text',min,max)=>jsxs('label',{className:'sq-field',children:[jsx('span',{children:label}),jsx('input',{type,disabled:busy,value:data[key]??'',min,max,onChange:e=>update({...data,[key]:type==='number'?Number(e.target.value):e.target.value})})]},key);
  return jsxs('section',{className:'sq-editor',children:[jsx('h2',{children:title}),section==='connection'&&jsx('p',{children:'配置活动方案使用的模型与 API 密钥。智能会话请在“模型”中设置。'}),data&&(section==='connection'?jsxs(React.Fragment,{children:[
   jsxs('label',{className:'sq-field',children:[jsx('span',{children:data.key_configured?'API 密钥（已配置，留空保持不变）':'API 密钥'}),jsx('input',{type:'password',disabled:busy,autoComplete:'new-password',value:data.deepseek_api_key||'',placeholder:data.env_key_configured?'可使用环境变量中的密钥':'填写新密钥',onChange:e=>update({...data,replace_key:true,deepseek_api_key:e.target.value})})]}),
   jsx('button',{type:'button',disabled:busy,onClick:()=>update({...data,replace_key:true,deepseek_api_key:''}),title:'保存后生效；环境变量中的密钥不受影响',children:'移除已保存的密钥'}),
   jsxs('label',{className:'sq-field',children:[jsx('span',{children:'活动方案模型'}),jsx('select',{disabled:busy,value:data.deepseek_model,onChange:e=>update({...data,deepseek_model:e.target.value}),children:['deepseek-v4-flash','deepseek-v4-pro'].map(v=>jsx('option',{value:v,children:v},v))})]}),
   jsx('button',{type:'button',disabled:busy,onClick:async()=>{setBusy('正在测试连接…');setStatus('正在测试连接…');try{setStatus((await desktop('connection.test',data)).message);}catch(e){setStatus(e.message);}finally{setBusy(false);}},title:'检查可用模型，不生成内容，也不保存设置',children:'测试连接'}),
   jsxs('details',{children:[jsx('summary',{children:'高级连接参数'}),field('max_tokens','最大输出长度（Token）','number',1,32768),field('connect_timeout','连接超时（秒）','number',1,120),field('read_timeout','读取超时（秒）','number',1,3600),field('net_retry_times','网络重试次数','number',1,10),field('server_retry_times','服务重试次数','number',1,10)]})
  ]}):Array.isArray(data)?jsxs(React.Fragment,{children:[jsx('p',{children:'每组填写一家公司的院校，一行一个院校名称。'}),...data.map((row,i)=>jsxs('fieldset',{className:'sq-mapping',children:[jsx('legend',{children:`公司 ${i+1}`}),jsxs('label',{className:'sq-field',children:[jsx('span',{children:'公司名称'}),jsx('input',{disabled:busy,value:row.company,onChange:e=>update(data.map((r,n)=>n===i?{...r,company:e.target.value}:r))})]}),jsxs('label',{className:'sq-field',children:[jsx('span',{children:'院校名称'}),jsx('textarea',{rows:4,disabled:busy,value:row.schools,onChange:e=>update(data.map((r,n)=>n===i?{...r,schools:e.target.value}:r))})]}),jsx('button',{type:'button',disabled:busy,onClick:()=>update(data.filter((_,n)=>n!==i)),children:'移除此组'})]},i)),jsx('button',{type:'button',disabled:busy,onClick:()=>update([...data,{company:'',schools:''}]),children:'添加公司'})]}):jsxs(React.Fragment,{children:[field('company_name','默认公司名称'),field('group_prefix','默认分组名称前缀')]})),
   jsx('p',{role:'status','aria-live':'polite',className:'sq-status',children:status}),jsxs('div',{className:'sq-form-actions',title:'仅保存当前设置页；放弃更改会恢复上次保存的内容',children:[jsx('button',{type:'button',disabled:busy||!changed,onClick:load,children:'放弃更改'}),jsx('button',{type:'button',className:'sq-primary',disabled:busy||!data||!changed,onClick:save,children:busy||'保存更改'})]})]});
 }
 for(const [section,title,order] of [['connection','方案生成服务',15],['tickets','机票院校配置',50],['projects','产教院校配置',51],['defaults','发票默认设置',52]])ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'seqara-'+section,label:title,order},()=>jsx(Editor,{section,title})));
 function About(){const [info,setInfo]=useState(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);const read=()=>desktop('desktop.status').then(setInfo).catch(e=>setMessage(e.message));useEffect(()=>{read();const timer=setInterval(read,3000);return()=>clearInterval(timer);},[]);const act=async(type,enabled)=>{setBusy(true);try{setMessage((await desktop('desktop.action',{type,enabled})).message);read();}catch(e){setMessage(e.message);}finally{setBusy(false);}};return jsxs('section',{className:'sq-editor',children:[jsx('h2',{children:'关于与更新'}),jsx('p',{children:`有序 Seqara ${info?.version||'0.3.11'} · DSH ${info?.core||'读取中'}`}),jsx('p',{children:'设置、业务数据和会话保存在当前 Windows 用户目录中。'}),jsx('button',{onClick:()=>desktop('desktop.open-data').catch(e=>setMessage(e.message)),children:'打开数据文件夹'}),info?.migration?.preserved?.length>0&&jsx('p',{children:'已保留原生业务规则；不同的 Agent 旧规则已备份在 config-backups，未覆盖原文件。'}),jsx('hr',{}),jsxs('label',{className:'sq-check',children:[jsx('input',{type:'checkbox',checked:!!info?.autoUpdate,disabled:busy,onChange:e=>act('auto',e.target.checked)}),'自动准备兼容内核更新（即时保存）']}),...['check','install','restart'].map((type,i)=>jsx('button',{disabled:busy,onClick:()=>act(type),children:['检查版本','下载并验证更新','重新启动工作台'][i]},type)),jsx('p',{role:'status',children:message}),jsxs('details',{children:[jsx('summary',{children:'诊断日志'}),jsx('pre',{children:(info?.logs||[]).join('\n')||'暂无日志'})]})]});}
 ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'seqara-about',label:'关于与更新',order:90},About));
 ctx.slots.inject('settings.general.item',()=>ctx.slots.register({name:'settings.general.item',id:'seqara-language-scope',order:95},()=>jsx('p',{className:'sq-language-scope',children:'语言设置作用于 DSH 会话与原有设置；业务页面、业务设置及部分第三方插件使用各自支持的语言。'})));
 function Extras(){const [,redraw]=useState(0);useEffect(()=>{const f=()=>redraw(v=>v+1);const off=ctx.slots.subscribe('settings.section',f);for(const event of ['seqara-tasks','seqara-route','seqara-modal','sq-section'])window.addEventListener(event,f);return()=>{off();for(const event of ['seqara-tasks','seqara-route','seqara-modal','sq-section'])window.removeEventListener(event,f);};},[]);
  const market=sectionRows().some(r=>r.id==='market'),count=taskState.native.filter(n=>n>0).length+taskState.agent.filter(t=>['running','queued'].includes(t.state)).length;
  const item=(id,label,path,click,attributes={})=>jsxs('button',{type:'button',title:label,'aria-label':label,'data-sq-route':id,'aria-current':activeRoute===id?'page':undefined,onClick:click,...attributes,children:[icon(path),jsx('span',{children:label})]},id);
  return jsxs('nav',{className:'sq-extras','aria-label':'扩展工具',children:[jsx('div',{className:'nv-group',children:'扩展工具'}),
   item('nv-skills','Skill技能库','M5 4h14v16H5z M8 8h8 M8 12h8',()=>tell({type:'hub'}),{'data-native-tool':7}),
   item('seqara-tasks',count?`处理任务（${count}）`:'处理任务','M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5',()=>{route('seqara-tasks','处理任务');ctx.layout.selectPanel('seqara-tasks');}),
   haveTaskboard&&item('plugin:taskboard','任务看板','M3 4h18v16H3z M3 9h18 M10 9v11',()=>document.querySelector('[data-dsh-taskboard-entry]')?.click(),{'data-sq-taskboard':true}),
   market&&item('settings:market','插件市场','M3 9h18v12H3z M3 9l3-6h12l3 6 M9 21v-8h6v8',()=>window.dispatchEvent(new CustomEvent('seqara-settings',{detail:{section:'market'}})),{'data-seqara-market':true,'aria-haspopup':'dialog','aria-expanded':!!settingsDialog()&&lastSection==='market'})]});
 }
 function Tasks(){const [,update]=useState(0);useEffect(()=>{const f=()=>update(v=>v+1);window.addEventListener('seqara-tasks',f);return()=>window.removeEventListener('seqara-tasks',f);},[]);return jsxs('section',{className:'sq-task-page',children:[jsx('h1',{children:'处理任务'}),jsx('p',{children:'业务页和智能会话的执行状态。切换页面不会中断任务。'}),...taskState.native.map((n,i)=>n>0?jsx('p',{role:'status',children:`${['数据看板','数据整理','统计报表','活动简报','发票整理','活动方案','自动打印'][i]} · 正在运行`},i):null),...taskState.agent.slice().reverse().map(t=>jsxs('article',{className:'sq-task-row',children:[jsx('strong',{children:t.label||t.name}),jsx('p',{children:`${({running:'运行中',queued:'排队中',completed:'已完成',failed:'失败',cancelled:'已取消'})[t.state]||t.state} · ${t.message||''}`}),t.output&&jsx('p',{children:t.output})]},t.id)),!taskState.native.some(n=>n>0)&&!taskState.agent.length&&jsx('p',{children:'暂无处理任务。启动工具或会话任务后，可在这里查看执行情况。'})]});}
 ctx.slots.inject('sidebar.footer.action',()=>ctx.slots.register({name:'sidebar.footer.action',id:'seqara-extras',order:10},Extras));
 ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'seqara-tasks'},Tasks));
 listen(window,'nv-select',e=>{activeNative=e.detail;if(e.detail>=0)setRoute(e.detail===7?'nv-skills':'native:'+e.detail);});
 listen(window,'seqara-tasks',e=>{taskState=e.detail;document.querySelectorAll('[data-native-tool]').forEach(el=>{const busy=taskState.native[Number(el.dataset.nativeTool)]>0;el.toggleAttribute('data-running',busy);el.setAttribute('aria-busy',String(busy));});});
 listen(document,'click',e=>{const el=e.target.closest?.('button,a');if(pluginTransition||!el||modal||el.closest('[role="dialog"],[role="alertdialog"],[role="menu"],[data-native-tools],.sq-extras,[data-slot="sidebar.settings"]'))return;const sidebar=el.closest('[data-pane="sidebar"],[class*="_sidebarCol"]');if(sidebar&&!el.closest('[class*="_toggle"]')){const plugin=el.hasAttribute('data-dsh-taskboard-entry');const closing=plugin&&document.documentElement.hasAttribute('data-dsh-taskboard-active');const other=!!el.closest('[data-slot="sidebar.footer.action"]');route(plugin&&!closing?'plugin:taskboard':other?'plugin:external':'conversation',plugin&&!closing?'任务看板':other?(el.textContent.trim()||el.getAttribute('aria-label')||'扩展'):'有序 Seqara · 工作台',!plugin);}},true);
 const reportTheme=()=>tell({type:'theme',theme:ctx.theme.getTheme().active.colorScheme});
 listen(window,'seqara-theme-report',reportTheme);listen(window,'seqara-theme-toggle',()=>ctx.theme.setTheme(ctx.theme.getTheme().active.colorScheme==='dark'?'light':'dark'));
 listen(window,'seqara-theme-set',e=>{if(['light','dark'].includes(e.detail)){ctx.theme.setTheme(e.detail);reportTheme();}});
 disposers.push(ctx.on('theme/change',reportTheme));reportTheme();
 const sessionsChanged=()=>tell({type:'session-busy',busy:Object.values(ctx.sessions.list.getSnapshot().byId).some(s=>s.running)});
 disposers.push(ctx.sessions.list.subscribe(sessionsChanged));sessionsChanged();
 let lastWidth=0,resizeFrame=0;const measure=()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{const sidebar=document.querySelector('[data-pane="sidebar"],[class*="_sidebarCol"]');if(sidebar){const width=Math.round(sidebar.getBoundingClientRect().right);if(width!==lastWidth){lastWidth=width;tell({type:'width',width});}}});};
 const resize=new ResizeObserver(measure);let observed=null;
 const observer=new MutationObserver(()=>{const panel=settingsDialog();syncDialogFocus(panel);const isModal=visibleDialogs().length>0;if(isModal!==modal){modal=isModal;tell({type:modal?'modal-open':'modal-close'});window.dispatchEvent(new Event('seqara-modal'));if(!modal)dirtyChanged();}if(panel){panel.classList.add('sq-settings');panel.setAttribute('aria-labelledby','sq-settings-heading');const original=panel.querySelector('nav [class*="_navList"]');original?.setAttribute('aria-hidden','true');selectPending();const active=originalSettingsButtons().find(b=>b.hasAttribute('aria-current'));const current=sectionRows()[originalSettingsButtons().indexOf(active)]?.id;if(current&&current!==lastSection){lastSection=current;window.dispatchEvent(new Event('sq-section'));}}const board=!!document.querySelector('[data-dsh-taskboard-entry]');if(board!==haveTaskboard){haveTaskboard=board;if(!board&&activeRoute==='plugin:taskboard')route('conversation','有序 Seqara · 工作台');else window.dispatchEvent(new Event('seqara-route'));}const sidebar=document.querySelector('[class*="_sidebarCol"]');if(sidebar&&sidebar!==observed){if(observed)resize.unobserve(observed);observed=sidebar;resize.observe(sidebar);measure();}});observer.observe(document.body,{childList:true,subtree:true});
 measure();if(document.querySelector('[class*="_sidebarCol"]')){observed=document.querySelector('[class*="_sidebarCol"]');resize.observe(observed);}
 const boardState=new MutationObserver(()=>{const open=document.documentElement.hasAttribute('data-dsh-taskboard-active');if(open&&activeRoute!=='plugin:taskboard')route('plugin:taskboard','任务看板',false);else if(!open&&activeRoute==='plugin:taskboard')route('conversation','有序 Seqara · 工作台',false);});boardState.observe(document.documentElement,{attributes:true,attributeFilter:['data-dsh-taskboard-active']});disposers.push(()=>boardState.disconnect());
 requestAnimationFrame(()=>tell({type:'ready'}));
 ctx.on('dispose',()=>{disposers.forEach(f=>typeof f==='function'&&f());resize.disconnect();observer.disconnect();cancelAnimationFrame(resizeFrame);});
}
