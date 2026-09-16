const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const start='/* SEQARA_PDF_COMPAT_START */',end='/* SEQARA_PDF_COMPAT_END */';
function patch(source,compat){
 source=source.replace(/\/\* SEQARA_PDF_COMPAT_START \*\/[\s\S]*?\/\* SEQARA_PDF_COMPAT_END \*\/\n?/g,'');
 const anchor='url = URL.createObjectURL(new Blob([_dsh_pdf_worker_default,';
 const patched='url = URL.createObjectURL(new Blob([/* SEQARA_PDF_WORKER_COMPAT */';
 // Replace our prior worker prefix without parsing or rewriting the embedded PDF.js bundle.
 source=source.replace(/url = URL\.createObjectURL\(new Blob\(\[\/\* SEQARA_PDF_WORKER_COMPAT \*\/"(?:\\.|[^"\\])*"\s*, _dsh_pdf_worker_default,/g,anchor);
 if(source.split(anchor).length!==2||!source.includes('this.#methodPromises.getOrInsertComputed'))throw Error('PDF bundle changed; review compatibility patch before packaging');
 const block=start+'\n'+compat+'\n'+end+'\n';
 return block+source.replace(anchor,patched+JSON.stringify(compat)+', _dsh_pdf_worker_default,');
}
function apply(){
 const file=path.join(root,'runtime/node_modules/@deepseek-ai/dsh-client-ui-sidebar-documentpreview/lib/client.js');
 const compat=fs.readFileSync(path.join(root,'runtime/toolkit-brand/pdf-compat.js'),'utf8');
 const before=fs.readFileSync(file,'utf8'),after=patch(before,compat);
 if(before!==after)fs.writeFileSync(file,after);
}
module.exports={patch,apply};
if(require.main===module)apply();
