import {randomUUID} from 'node:crypto';
import {ToolCallId} from '@deepseek-ai/dsh-llm';

export async function presentFiles(ctx,exec,files){
 if(!ctx.tools.get('present',exec.agent))throw Error('当前会话没有 DSH present 工具，无法登记交付卡片；生成文件仍在原路径');
 const delivered=await ctx.tools.execute({name:'present',callId:ToolCallId('seqara-present-'+randomUUID()),rootCallId:exec.rootCallId||exec.callId,arguments:{files},agent:exec.agent,parent:exec.token,signal:exec.signal});
 if(delivered.isError)throw Error('DSH 交付登记失败：'+JSON.stringify(delivered.content||delivered.error||'未知错误').slice(0,600));
 for(const context of delivered.additionalContexts||[])exec.deferContext?.(context);
 return {status:'presented',files};
}
