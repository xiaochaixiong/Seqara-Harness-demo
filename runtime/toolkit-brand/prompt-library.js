function createPromptLibrary(React,jsx,jsxs){
 const {useState,useEffect}=React;
 return function PromptLibrary({insert,session,query}){
  const [rows,setRows]=useState([]),[edit,setEdit]=useState(null),[remove,setRemove]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[loaded,setLoaded]=useState(false);
  const call=async(action,args)=>{const desktop=await window.seqaraDesktopReady;if(!desktop)throw Error('请在桌面应用中使用提示词库。');return desktop(action,args);};
  useEffect(()=>{let live=true;call('prompts.list').then(r=>{if(live){setRows(r);setLoaded(true);}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
  const save=async(action,item)=>{setBusy(true);setError('');try{setRows(await call(action,item));setEdit(null);setRemove(null);}catch(e){setError(e.message)}finally{setBusy(false)}};
  const shown=rows.filter(r=>(r.name+' '+r.prompt).toLowerCase().includes(query.toLowerCase()));
  return jsxs('div',{className:'sq-prompt-library',children:[
   jsx('button',{type:'button',onClick:()=>{setError('');setEdit({name:'',prompt:''})},children:'新增提示词'}),
   error&&jsx('p',{role:'alert',children:error}),
   loaded&&!rows.length&&jsx('p',{children:'还没有保存的提示词。点击“新增提示词”开始添加。'}),
   shown.map(r=>jsxs('article',{className:'nv-skill-row',children:[jsxs('div',{children:[jsx('strong',{children:r.name}),jsx('p',{className:'sq-prompt-text',children:r.prompt})]}),jsxs('div',{className:'sq-prompt-actions',children:[jsx('button',{disabled:!session,onClick:()=>insert(r.prompt),children:'添加到对话'}),jsx('button',{onClick:()=>setEdit({...r}),children:'编辑'}),jsx('button',{onClick:()=>setRemove(r),children:'删除'})]})]},r.id)),
   (edit||remove)&&jsx('div',{className:'sq-library-backdrop',children:jsxs('section',{role:'dialog','aria-modal':true,'aria-label':edit?'编辑提示词':'删除提示词',className:'sq-library-dialog',children:[
    jsx('h2',{children:edit?(edit.id?'编辑提示词':'新增提示词'):'删除提示词'}),
    edit?jsxs(React.Fragment,{children:[jsx('label',{children:['名称',jsx('input',{autoFocus:true,value:edit.name,maxLength:120,onChange:e=>setEdit({...edit,name:e.target.value})})]}),jsx('label',{children:['提示词内容',jsx('textarea',{value:edit.prompt,rows:10,maxLength:100000,onChange:e=>setEdit({...edit,prompt:e.target.value})})]})]}):jsx('p',{children:'确定删除“'+remove.name+'”？'}),
    error&&jsx('p',{role:'alert',children:error}),
    jsxs('div',{className:'sq-prompt-actions',children:[jsx('button',{disabled:busy,onClick:()=>{setEdit(null);setRemove(null);setError('')},children:'取消'}),jsx('button',{disabled:busy||!!edit&&(!edit.name.trim()||!edit.prompt.trim()),onClick:()=>save(edit?'prompts.upsert':'prompts.delete',edit||remove),children:busy?'正在保存…':edit?'保存':'确认删除'})]})
   ]})})
  ]});
 };
}
