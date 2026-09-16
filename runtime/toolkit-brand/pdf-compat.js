// PDF.js 6 uses Map upsert in both the page and its dedicated worker.
// Only fill missing methods; preserve native implementations on newer engines.
// Semantics: https://tc39.es/proposal-upsert/
(()=>{
 'use strict';
 const {has,get,set}=Map.prototype;
 if(typeof Map.prototype.getOrInsert!=='function')Object.defineProperty(Map.prototype,'getOrInsert',{
  configurable:true,writable:true,value:function getOrInsert(key,value){
   if(has.call(this,key))return get.call(this,key);
   set.call(this,key,value);return value;
  }
 });
 if(typeof Map.prototype.getOrInsertComputed!=='function')Object.defineProperty(Map.prototype,'getOrInsertComputed',{
  configurable:true,writable:true,value:function getOrInsertComputed(key,callback){
   const exists=has.call(this,key); // Validate the receiver even for an invalid callback.
   if(typeof callback!=='function')throw new TypeError('callback must be callable');
   if(exists)return get.call(this,key);
   const value=callback(key===0?0:key);
   set.call(this,key,value);return value;
  }
 });
})();
