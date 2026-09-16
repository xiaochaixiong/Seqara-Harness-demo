window.__ModuleLoader__.load({id:'@nv/dsh-business-ui',factory:require=>{
 const {jsx,jsxs}=require('react/jsx-runtime');const React=require('react');const {useState,useEffect,useSyncExternalStore}=React;
 const tell=value=>console.log('__NV_NATIVE__'+JSON.stringify(value));
 const titles=['数据看板','数据整理','统计报表','活动简报','发票整理','活动方案','自动打印'];
 const icons=['M3 3v18h18 M7 16v-5 M12 16V7 M17 16V4','M4 5h16 M6 12h12 M9 19h6','M5 20V10h4v10 M10 20V4h4v16 M15 20v-7h4v7','M5 3h11l3 3v15H5z M8 12h8 M8 16h6','M6 3h12v18H6z M9 8h6 M9 12h6 M9 16h3','M4 5h16v15H4z M8 9h8 M8 13h5','M7 8V3h10v5 M7 17H4V9h16v8h-3 M7 14h10v7H7z'];
 function Tools(){const [active,setActive]=useState(-1);useEffect(()=>{const f=e=>setActive(e.detail);window.addEventListener('nv-select',f);return()=>window.removeEventListener('nv-select',f);},[]);
 return jsxs('nav',{'data-native-tools':true,'aria-label':'工作工具',children:[jsx('div',{className:'nv-group',children:'工作工具'}),...titles.map((title,i)=>{const index=i;return jsxs('button',{type:'button',title,'aria-label':title,'data-native-tool':index,'aria-current':active===index?'page':undefined,onClick:()=>{setActive(index);tell({type:'tool',index});},children:[jsx('svg',{viewBox:'0 0 24 24',width:19,height:19,fill:'none',stroke:'currentColor',strokeWidth:1.5,strokeLinecap:'round',strokeLinejoin:'round',children:jsx('path',{d:icons[i]})}),jsx('span',{children:title})]},title);})]});}
 return {inject:['workspaces','documentPreviews','slots','theme','layout','sessions','remote','remote.skills','conversation'],apply(ctx){
 installPresentationPreview(ctx,React,jsx,jsxs);
 installPresentationStyles(ctx,React,jsx,jsxs);
 // Skip the upstream testing notice without persisting an acknowledgement or blocking model setup.
 function SkipWelcomeNotice({complete}){useEffect(()=>{complete();},[complete]);return null;}
 ctx.slots.inject('settings.onboarding',()=>ctx.slots.register({name:'settings.onboarding',id:'welcome-notice',order:-100,priority:-100},SkipWelcomeNotice));
 const select=e=>document.documentElement.classList.toggle('nv-business-active',e.detail>=0&&e.detail<7);
 window.addEventListener('nv-select',select);
 const style=document.createElement('style');style.textContent=`
 :root{--nv-sidebar:#f7f7f8;--nv-canvas:#fff;--nv-text:#24262b;--nv-muted:#666870;--nv-hover:#eeeeef;--nv-selected:#e9eaed;--nv-line:#e4e5e8}
 body[data-ds-dark-theme]{--nv-sidebar:#22252b;--nv-canvas:#191b20;--nv-text:#e7e9ed;--nv-muted:#b8bec8;--nv-hover:#2d3139;--nv-selected:#343942;--nv-line:#363a42}
 body,input,textarea,button,select{font-family:var(--dsw-font-family)}

 [data-seqara-signature]{display:inline-flex;align-items:center;width:174px;height:37px;vertical-align:middle}
 [data-seqara-signature] img{display:block;width:174px;height:37px;max-width:none}
 [data-seqara-signature] [data-seqara-mode=night]{display:none}
 body[data-ds-dark-theme] [data-seqara-signature] [data-seqara-mode=day]{display:none}
 body[data-ds-dark-theme] [data-seqara-signature] [data-seqara-mode=night]{display:block}
 [class*='_brandMark']:has([data-seqara-compact]){display:none}
 [class*='_brandIdentity']:has([data-seqara-signature]){gap:0;overflow:visible}
 [class*='_brandName']:has([data-seqara-signature]){overflow:visible}
 [data-nv-brand]{font-size:15px;font-weight:650;letter-spacing:0}
 [data-nv-hero]{font-size:22px;font-weight:600;letter-spacing:0;color:var(--nv-text)}
 div:has(>span>[data-slot='conversation.hero.brand.mark']):has([data-nv-hero])>span:not(:has([data-nv-hero])){display:none}
 span:has(>[data-slot='conversation.hero.brand.mark'] [data-nv-hero]){width:auto;height:auto}
 [class*='_root']:has(>[class*='_logoRow']){background:var(--nv-sidebar)!important;color:var(--nv-text);border-right:1px solid var(--nv-line);padding:12px!important}
 [class*='_frame']:has(>[class*='_sidebarCol']){transition:grid-template-columns 240ms cubic-bezier(.22,1,.36,1)}
 [class*='_centerCol']{background:var(--nv-canvas)}
 [class*='_regionArea']{flex:0 1 auto!important;min-height:80px;max-height:30vh;overflow:auto}
 [class*='_footArea']{flex:1!important;min-height:0;display:flex!important;flex-direction:column!important;justify-content:flex-start!important}
 [class*='_footerActions']{flex:1;overflow:auto;display:block!important;padding-top:16px}
 [class*='_settingsArea']{margin-top:auto;border-top:1px solid var(--nv-line);padding-top:8px}
 [data-native-tools]{display:flex;flex-direction:column;gap:4px;width:100%;color:var(--nv-text)}
 .nv-group{font-size:11px;font-weight:600;letter-spacing:.3px;color:var(--nv-muted);padding:0 12px 8px}
 [data-native-tool]{display:flex;gap:12px;align-items:center;width:100%;min-height:40px;padding:8px 12px;border:1px solid transparent;border-radius:8px;background:transparent;color:inherit;text-align:left;font-size:14px;cursor:pointer}
 [data-native-tool]{box-sizing:border-box}[data-native-tool] svg{flex-shrink:0}[data-native-tool] span{white-space:nowrap;overflow:hidden}
 [data-native-tool]:hover{background:var(--nv-hover)}[data-native-tool][aria-current=page]{background:var(--nv-selected);font-weight:600}
 [class*='_collapsed']:has(>[class*='_logoRow']){padding:12px 8px!important}
 [class*='_collapsed'] .nv-group,[class*='_collapsed'] [data-native-tool] span{display:none}
 [class*='_collapsed'] [data-native-tool]{width:100%;min-height:40px;padding:6px 4px;justify-content:center}
 [class*='_collapsed'] [class*='_regionArea']{min-height:0;max-height:100px;flex:0 0 auto!important;overflow-x:hidden}
 [class*='_footerActions']{overflow-x:hidden}
 [class*='_collapsed'] [class*='_footerActions']{scrollbar-width:thin}
 [class*='_collapsed'] [class*='_footerActions']{width:100%;padding-top:8px}
 [data-composer-card]{border-radius:14px!important;box-shadow:none!important;border:1px solid var(--nv-line)!important}
 .nv-hub{height:100%;overflow:auto;scrollbar-gutter:stable;box-sizing:border-box;padding:28px 32px;background:var(--nv-canvas);color:var(--nv-text);font-size:14px}
 .nv-hub input::placeholder{color:var(--nv-muted);opacity:1}
 .nv-hub,[class*='_footerActions']{scrollbar-width:thin;scrollbar-color:var(--nv-muted) transparent}
 .nv-hub input{caret-color:var(--nv-text)}
 .nv-hub h1{font-size:22px;line-height:30px;font-weight:600;margin:0 0 6px}.nv-hub p{color:var(--nv-muted);line-height:22px;max-width:72ch}
 .nv-hub-actions,.nv-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}
 .nv-hub button,.nv-hub input{font:inherit;color:inherit;background:var(--nv-sidebar);border:1px solid var(--nv-line);border-radius:8px;padding:10px 14px}
 .nv-hub button{cursor:pointer}.nv-hub button:hover{background:var(--nv-hover)}.nv-hub button:disabled{opacity:.5;cursor:default}
 .nv-tabs button[aria-selected=true]{background:var(--nv-selected);font-weight:600}
 .nv-hub input{box-sizing:border-box;width:100%;margin-bottom:16px;background:var(--nv-canvas)}
 .nv-skill-row{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:20px 0;border-bottom:1px solid var(--nv-line)}
 .nv-skill-row p{margin:6px 0 0;font-size:13px}.nv-skill-row button{flex-shrink:0}
 .nv-hub-status{padding:24px 0;color:var(--nv-muted)}
 @media(max-width:1000px){.nv-skill-row{align-items:flex-start;flex-direction:column;gap:12px}}
 button:focus-visible,input:focus-visible,[contenteditable]:focus-visible{outline:2px solid #2563eb;outline-offset:2px}
 ::selection{background:#2563eb33}
 @media(max-height:700px){[data-native-tool]{min-height:34px;padding:6px 10px}[class*='_footerActions']{padding-top:8px}}
 @media(prefers-reduced-motion:reduce){[data-native-tools] *,[class*='_frame']:has(>[class*='_sidebarCol']){animation:none!important;transition:none!important}}
 `+seqaraDesktopCss;document.head.append(style);
 installSeqaraDesktop(ctx,React,jsx,jsxs,tell,require('@deepseek-ai/dsh-client-ui-primitives').Modal);
 ctx.slots.inject('sidebar.footer.action',()=>ctx.slots.register({name:'sidebar.footer.action',id:'nv-native-tools',order:0},Tools));
 ctx.slots.inject('sidebar.brand.name',()=>ctx.slots.register({name:'sidebar.brand.name'},()=>jsxs('span',{'data-seqara-signature':true,'aria-label':'有序 Seqara',children:[jsx('img',{'data-seqara-mode':"day",alt:'',width:174,height:37,src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(seqaraAssets.day)}),jsx('img',{'data-seqara-mode':"night",alt:'',width:174,height:37,src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(seqaraAssets.night)})]})));
 ctx.slots.inject('sidebar.brand.mark',()=>ctx.slots.register({name:'sidebar.brand.mark'},()=>jsx('svg',{'data-seqara-compact':true,viewBox:'0 0 720 720',width:24,height:24,'aria-hidden':true,children:jsx('path',{fill:'currentColor',transform:'translate(69 45)',d:"M55 185 Q55 172 67 165 L387 0 Q407 -11 407 11 L407 128 Q407 142 395 148 L71 314 Q55 322 55 304 Z M9 388 Q9 375 21 369 L559 94 Q577 85 577 106 L577 213 Q577 226 565 233 L250 395 Q237 402 237 415 L237 432 Q237 450 253 443 L520 306 Q540 296 540 318 L540 427 Q540 441 528 447 L197 620 Q174 632 174 609 L174 507 Q174 493 187 486 L366 393 Q377 387 377 374 L377 355 Q377 336 360 344 L218 417 Q205 424 205 438 L205 482 Q205 495 193 501 L28 587 Q9 597 9 576 Z"})})));
 ctx.slots.inject('conversation.hero.brand.mark',()=>ctx.slots.register({name:'conversation.hero.brand.mark'},()=>jsx('span',{'data-nv-hero':true,children:'开始今天的工作'})));
 const PromptLibrary=createPromptLibrary(React,jsx,jsxs);
 function Hub(){
  const session=useSyncExternalStore(ctx.sessions.list.subscribe,ctx.sessions.list.getSnapshot).current;
  const [tab,setTab]=useState('skills'),[query,setQuery]=useState(''),[items,setItems]=useState([]),[state,setState]=useState('loading'),[error,setError]=useState(''),[revision,refresh]=useState(0);
  useEffect(()=>{const abort=new AbortController();setItems([]);setError('');
   if(!session){setState('no-session');return()=>abort.abort();}setState('loading');
   ctx.remote.skills.list({sessionId:session},abort.signal).then(result=>{if(abort.signal.aborted)return;if(!result.ok)throw Error(result.error.message);setItems(result.value.skills);setState('ready');}).catch(e=>{if(!abort.signal.aborted){setError('技能目录读取失败：'+e.message);setState('error');}});
   return()=>abort.abort();
  },[session,revision]);
  const insert=text=>{try{const scope=session&&ctx.sessions.scope(session);if(!scope)throw Error('请先选择工作区并打开会话。');
   const input=ctx.conversation.input.for(scope),snapshot=input.state.getSnapshot();
   if(snapshot.phase!=='plain')throw Error('当前输入正在处理命令，请完成后再插入。');
   input.setDraft(snapshot.draft?`${snapshot.draft}\n${text}`:text);
   ctx.layout.selectPanel(null);window.dispatchEvent(new Event('seqara-conversation'));
  }catch(e){setError(e.message);}};
  const shown=(tab==='skills'?items:[]).filter(v=>(v.name+' '+v.description).toLowerCase().includes(query.toLowerCase()));
  return jsxs('section',{className:'nv-hub','aria-label':'Skill技能库',children:[
   jsxs('div',{className:'nv-tabs',role:'tablist','aria-label':'类型',children:[['skills','已安装技能'],['workflows','提示词库']].map(([id,label])=>jsx('button',{type:'button',role:'tab','aria-selected':tab===id,id:'sq-tab-'+id,'aria-controls':'sq-panel-'+id,tabIndex:tab===id?0:-1,onKeyDown:e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?'skills':e.key==='End'?'workflows':tab==='skills'?'workflows':'skills';setTab(next);setQuery('');requestAnimationFrame(()=>document.getElementById('sq-tab-'+next)?.focus());}},onClick:()=>{setTab(id);setQuery('');},children:label},id))}),
   jsx('input',{type:'search',value:query,'aria-label':'搜索技能或提示词',placeholder:'搜索名称或用途',onChange:e=>setQuery(e.target.value)}),
   error&&jsx('p',{role:'alert',children:error}),
   tab==='skills'&&!session&&jsx('p',{className:'nv-hub-status',children:'请先返回会话，选择一个工作区。技能目录会根据该会话的工作区与智能体加载。'}),
   tab==='skills'&&session&&state==='loading'&&jsx('p',{role:'status',className:'nv-hub-status',children:'正在读取当前会话的技能…'}),
   tab==='skills'&&state==='ready'&&!items.length&&jsx('p',{className:'nv-hub-status',children:'当前会话还没有可调用技能。安装 Skill 后重新打开此页，也可使用工作区的 .dsh/skills 目录。'}),
   jsx('div',{role:'tabpanel',id:'sq-panel-'+tab,'aria-labelledby':'sq-tab-'+tab,children:shown.map(item=>jsxs('article',{className:'nv-skill-row',children:[jsxs('div',{children:[jsx('strong',{children:item.name}),jsx('p',{children:item.description})]}),jsx('button',{type:'button',disabled:!session,onClick:()=>insert(tab==='skills'?'/'+item.name+' ':item.prompt),children:'添加到草稿'})]},item.name))}),
   tab==='skills'&&query&&!shown.length&&jsx('p',{role:'status',children:'未找到匹配结果，请尝试其他关键词。'}),
   tab==='workflows'&&jsx(PromptLibrary,{insert,session,query})
  ]});
 }
 ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'nv-skills'},Hub));
 const openHub=()=>{ctx.layout.selectPanel('nv-skills');window.dispatchEvent(new CustomEvent('nv-select',{detail:7}));};
 window.addEventListener('nv-open-hub',openHub);
 const open=()=>window.dispatchEvent(new CustomEvent('seqara-settings',{detail:{open:true}}));window.addEventListener('nv-official-settings',open);
 ctx.on('dispose',()=>{style.remove();window.removeEventListener('nv-official-settings',open);window.removeEventListener('nv-open-hub',openHub);window.removeEventListener('nv-select',select);});
 }};
}});
