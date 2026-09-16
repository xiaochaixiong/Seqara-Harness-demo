const fs=require('node:fs'),path=require('node:path');
function patch(source,helper){
 source=source.replace(/\/\* SEQARA_ERRORS_START \*\/[\s\S]*?\/\* SEQARA_ERRORS_END \*\/\n?/g,'');
 const anchor='function failureMessage(message, code, t) {';
 if(source.split(anchor).length!==2)throw Error('Chat failure formatter changed');
 source=source.replace(anchor,'/* SEQARA_ERRORS_START */\n'+helper.replace(/if\(typeof module[^\n]+/,'')+'\n/* SEQARA_ERRORS_END */\n'+anchor);
 source=source.replace('return code === "AUTH" ? t("message.failure.auth") : message;',`return (0, react_jsx_runtime.jsxs)("span", {children:[localizeFailure(message,code).message,(0, react_jsx_runtime.jsxs)("details", {className:"sq-error-details",children:[(0, react_jsx_runtime.jsx)("summary",{children:"查看原始报错"}),(0, react_jsx_runtime.jsx)("pre",{children:String(code??'')+'\\n'+String(message??'')})]})]});`);
 source=source.replace('children: node.code\n','children: localizeFailure(node.message,node.code).label\n');
 return source;
}
function apply(){const file=path.resolve(__dirname,'../runtime/node_modules/@deepseek-ai/dsh-client-ui-chat/lib/client.js');const helper=fs.readFileSync(path.resolve(__dirname,'../runtime/toolkit-brand/error-messages.cjs'),'utf8');const before=fs.readFileSync(file,'utf8'),after=patch(before,helper);if(before!==after)fs.writeFileSync(file,after);}
module.exports={patch,apply};if(require.main===module)apply();
