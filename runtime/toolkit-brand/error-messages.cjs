function localizeFailure(message,code){
 const raw=String(message??''),text=raw.toLowerCase(),key=String(code??'').toUpperCase();
 const rules=[
 [/insufficient[ _-]*(balance|credit|quota)|balance.*(insufficient|exhausted)|credit.*(exhausted|insufficient)|payment required/,'余额不足','模型服务账户余额不足，请充值或切换模型服务。'],
 [/invalid[ _-]*(api[ _-]*)?key|incorrect[ _-]*api|authentication|unauthorized/,'认证失败','API 密钥无效或已失效，请检查当前模型服务的密钥配置。'],
 [/context.*(length|limit)|maximum context|too many tokens|prompt.*too long/,'内容过长','对话内容超出模型长度限制，请精简内容或新建会话。'],
 [/rate[ _-]*limit|too many requests|requests per minute/,'请求限流','请求过于频繁，请稍后重试。'],
 [/quota|usage limit|spending limit/,'额度不足','模型服务可用额度不足，请检查账户余额和用量限制。'],
 [/timed? ?out|timeout|deadline exceeded/,'连接超时','模型服务响应超时，请检查网络后重试。'],
 [/model.*(not found|does not exist|not available)|unknown model/,'模型不可用','当前模型不存在或不可用，请检查模型名称和访问权限。'],
 [/permission denied|forbidden|access denied/,'无访问权限','当前账户无权访问此服务，请检查服务权限和配置。'],
 [/overloaded|service unavailable|bad gateway|internal server error/,'服务异常','模型服务暂时不可用，请稍后重试或切换服务。'],
 [/fetch failed|failed to fetch|network error|connection (refused|reset)|econn|enotfound|dns|certificate/,'连接失败','无法连接模型服务，请检查网络和 API 地址后重试。'],
 [/invalid request|bad request|invalid parameter|unsupported parameter/,'请求无效','模型服务不接受当前请求，请检查模型和参数配置。']
 ];
 const match=rules.find(([re])=>re.test(text));if(match)return {label:match[1],message:match[2]};
 const fallback={AUTH:['认证失败','模型服务认证失败，请检查 API 密钥和账户权限。'],QUOTA:['额度不足','模型服务可用额度不足，请检查账户余额和用量限制。'],RATE_LIMIT:['请求限流','请求过于频繁，请稍后重试。'],TIMEOUT:['连接超时','模型服务响应超时，请检查网络后重试。']};
 if(fallback[key])return {label:fallback[key][0],message:fallback[key][1]};
 return {label:'运行错误',message:/[\u3400-\u9fff]/.test(raw)?raw:'模型请求失败，请展开原始报错查看详情，检查服务配置后重试。'};
}
if(typeof module!=='undefined')module.exports={localizeFailure};
