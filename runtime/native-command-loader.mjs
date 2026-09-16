import {registerHooks} from 'node:module';
const adapter=new URL('./native-command.mjs',import.meta.url).href;
// All consumers, including DSH's built-in file cards, must use the same bridge.
// The adapter imports the original by relative filename, avoiding recursion.
registerHooks({resolve(specifier,context,nextResolve){
 if(specifier==='@deepseek-ai/dsh-native-command')return {url:adapter,shortCircuit:true};
 return nextResolve(specifier,context);
}});
