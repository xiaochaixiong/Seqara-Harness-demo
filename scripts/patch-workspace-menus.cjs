const fs=require('node:fs'),path=require('node:path');
function patch(source){
 if(source.includes('/* SEQARA_DELETE_MENUS */'))return source;
 const edits=[
 ['const sessionMenuItems = [',`const sessionMenuItems = [/* SEQARA_DELETE_MENUS */
 {id:"sq-delete",label:"删除任务",danger:true,disabled:!!node.running,icon:(0, react_jsx_runtime.jsx)(_deepseek_ai_dsh_client_ui_primitives.IconTrashOutline16,{})},`],
 ['if (id === "archive") onArchive(node.id);',`if (id === "archive") onArchive(node.id);
 if(id === "sq-delete") window.dispatchEvent(new CustomEvent('seqara-delete',{detail:{kind:'session',id:node.id,name:title}}));`],
 ['else actions.delete();',`else window.dispatchEvent(new CustomEvent('seqara-delete',{detail:{kind:'workspace',id:row.workspaceId,name:label}}));`],
 ['!row.blank && (0, react_jsx_runtime.jsx)("span", {\n\t\t\t\t\t\t\tclassName: Rows_module_css_default.rowActions,','(0, react_jsx_runtime.jsx)("span", {\n\t\t\t\t\t\t\tclassName: Rows_module_css_default.rowActions,']
 ];
 source=source.replace(/\r\n/g,'\n');
 for(const [from,to] of edits){if(source.split(from).length!==2)throw Error('Workspace menu bundle changed: '+from);source=source.replace(from,to);}
 return source;
}
function apply(){const file=path.resolve(__dirname,'../runtime/node_modules/@deepseek-ai/dsh-client-ui-workspace/lib/client.js');const before=fs.readFileSync(file,'utf8'),after=patch(before);if(before!==after)fs.writeFileSync(file,after);}
module.exports={patch,apply};if(require.main===module)apply();
