function installWorkspaceManager(ctx,React,jsx,jsxs,Modal){
 const {useState,useEffect,useSyncExternalStore}=React;
 function Manager(){
  const workspaces=useSyncExternalStore(fn=>ctx.workspaces.list.subscribe(fn),()=>ctx.workspaces.list.getSnapshot());
  const sessions=useSyncExternalStore(ctx.sessions.list.subscribe,ctx.sessions.list.getSnapshot);
  const [target,setTarget]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{const open=e=>{const value=e.detail;if(!value||!['session','workspace'].includes(value.kind))return;setError('');setTarget(value);window.dispatchEvent(new Event('seqara-conversation'));};window.addEventListener('seqara-delete',open);return()=>window.removeEventListener('seqara-delete',open);},[]);
  const running=target&&(target.kind==='session'?sessions.byId[target.id]?.running:workspaces.items.find(w=>w.workspaceId===target.id)?.sessionIds.some(id=>sessions.byId[id]?.running));
  const remove=async()=>{if(busy||running)return;setBusy(true);setError('');try{
   if(target.kind==='workspace')await ctx.workspaces.delete(target.id);
   else{await ctx.workspaces.archiveSession(target.id);if(sessions.current===target.id)ctx.sessions.clear();}
   setTarget(null);
  }catch(e){setError(e.message)}finally{setBusy(false)}};
  return target&&jsx(Modal,{open:true,onClose:()=>{if(!busy)setTarget(null)},title:'删除“'+target.name+'”？',children:jsxs('div',{'data-sq-delete-dialog':true,children:[jsx('p',{children:target.kind==='workspace'?'移除工作区登记，磁盘文件和会话保留。':'从任务列表移除，保留本地历史记录供恢复，生成的文件不受影响。'}),running&&jsx('p',{role:'status',children:'请等待任务运行结束后再删除。'}),error&&jsx('p',{role:'alert',children:error}),jsxs('div',{className:'sq-prompt-actions',children:[jsx('button',{disabled:busy,onClick:()=>setTarget(null),children:'取消'}),jsx('button',{disabled:busy||running,onClick:remove,children:busy?'正在删除…':'确认删除'})]})]})});
 }
 ctx.slots.inject('sidebar.footer.action',()=>ctx.slots.register({name:'sidebar.footer.action',id:'sq-delete-confirmation',order:100},Manager));
}
