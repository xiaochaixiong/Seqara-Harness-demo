const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {localizeFailure:f}=require('../runtime/toolkit-brand/error-messages.cjs');
test('specific provider messages outrank broad quota codes',()=>{
 assert.equal(f('Insufficient Balance','QUOTA').label,'余额不足');
 assert.equal(f('Too many requests','QUOTA').label,'请求限流');
 assert.equal(f('maximum context length exceeded','').label,'内容过长');
 for(const [message,label] of [['invalid_api_key','认证失败'],['timeout','连接超时'],['model not found','模型不可用'],['Forbidden','无访问权限'],['Service unavailable','服务异常'],['fetch failed','连接失败'],['Invalid parameter','请求无效']])assert.equal(f(message).label,label);
 assert.equal(f('','QUOTA').label,'额度不足');
 assert.equal(f('服务暂不可用').message,'服务暂不可用');
 assert.match(f('Unrecognized provider error').message,/模型请求失败/);
});
test('patched formatter retains original error and is repeatable',()=>{
 const {patch}=require('../scripts/patch-error-messages.cjs');
 const source=fs.readFileSync('runtime/node_modules/@deepseek-ai/dsh-client-ui-chat/lib/client.js','utf8');
 const helper=fs.readFileSync('runtime/toolkit-brand/error-messages.cjs','utf8');
 assert.equal(patch(source,helper),source);
 const fn=source.match(/function failureMessage\(message, code, t\) \{([\s\S]*?)\n\s*\}/)[0];
 const jsx=(type,props)=>({type,...props});
 const result=vm.runInNewContext(fn+';failureMessage("Insufficient Balance","QUOTA",()=>{})',{localizeFailure:f,react_jsx_runtime:{jsx,jsxs:jsx}});
 assert.match(result.children[0],/余额不足/);
 assert.equal(result.children[1].type,'details');
 assert.equal(result.children[1].children[1].children,'QUOTA\nInsufficient Balance');
});
