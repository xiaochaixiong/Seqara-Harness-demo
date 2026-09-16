/* Shared navigation identities; third-party settings keep their own IDs. */
const SeqaraNavigation = (() => {
 const groups=[{id:'workspace',label:'工作台',ids:['general','models','agent-presets']},
  {id:'business',label:'业务',ids:['seqara-connection','seqara-defaults','seqara-tickets','seqara-projects']},
  {id:'extensions',label:'扩展',ids:['plugins','market']},
  {id:'application',label:'应用',ids:['seqara-about']}];
 const keywords={general:'主题 外观 深色 浅色 系统 字体 字号 语言 权限',models:'模型 API Key 密钥 会话',
  'seqara-connection':'API Key 密钥 活动方案 连接 超时 活动方案连接', 'seqara-defaults':'发票 公司 默认 前缀 分类默认',
  'seqara-tickets':'机票 公司 学校 院校 机票院校','seqara-projects':'产教 公司 学校 院校',plugins:'插件 安装 启用 禁用',market:'插件 市场 下载', 'seqara-about':'版本 更新 日志 恢复 重启'};
 function sections(rows,query=''){
  const term=query.trim().toLocaleLowerCase();const seen=new Set();
  const unique=rows.filter(r=>r.id&&!seen.has(r.id)&&seen.add(r.id));
  return groups.map(group=>({id:group.id,label:group.label,rows:unique.filter(row=>{
   const owner=groups.find(g=>g.ids.includes(row.id))?.id||'extensions';
   return owner===group.id&&(!term||(row.label+' '+(keywords[row.id]||'')).toLocaleLowerCase().includes(term));
  }).sort((a,b)=>{const ai=group.ids.indexOf(a.id),bi=group.ids.indexOf(b.id);return (ai<0?100:ai)-(bi<0?100:bi)||(a.order||0)-(b.order||0);})})).filter(g=>g.rows.length);
 }
 return {sections,groups};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=SeqaraNavigation;
