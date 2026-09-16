// Seqara's Windows adapter shared by upstream delivery cards, settings,
// workspace launchers and toolkit_desktop. Keep upstream packages untouched.
import * as upstream from './node_modules/@deepseek-ai/dsh-native-command/lib/index.js';
import {execFile} from 'node:child_process';
import {stat} from 'node:fs/promises';
import {isAbsolute} from 'node:path';
import {scrubbedParentEnv} from '@deepseek-ai/dsh-subprocess';

export const {canOpenNativePath,nativeFileManager}=upstream;
export const adapterVersion=1;

export function runNativeCommand(command,args,signal){
 const argv=[...args],index=argv.findIndex(a=>a.toLowerCase()==='-command');
 if(/powershell(?:\.exe)?$/i.test(command)&&index>=0){
  argv[index+1]="$ErrorActionPreference='Stop'; "+argv[index+1];
 }
 return new Promise((resolve,reject)=>{
  execFile(command,argv,{encoding:'utf8',signal,windowsHide:true,timeout:15000,maxBuffer:1024*1024,env:scrubbedParentEnv()},(error,stdout,stderr)=>{
   if(error)reject(Object.assign(new Error(stderr.trim()||error.message,{cause:error}),{code:error.code,stdout,stderr}));
   else resolve({stdout,stderr});
  });
 });
}

async function existingPath(target,signal){
 signal?.throwIfAborted();
 if(typeof target!=='string'||!isAbsolute(target)||target.includes('\0'))throw Error('需要有效的绝对文件路径');
 await stat(target);
}
const optionsOf=internals=>({run:runNativeCommand,...internals});
export async function openNativePath(target,signal=new AbortController().signal,internals={}){
 await existingPath(target,signal);
 return upstream.openNativePath(target,signal,optionsOf(internals));
}
export async function openNativeTextFile(target,signal=new AbortController().signal,internals={}){
 await existingPath(target,signal);
 return upstream.openNativeTextFile(target,signal,optionsOf(internals));
}

export function revealScript(target){
 const literal="'"+target.replaceAll("'","''")+"'";
 // A literal Unicode path goes directly to the shell PIDL API, never through
 // Explorer's /select command-line parser or a percent-encoded file URL.
 // https://learn.microsoft.com/windows/win32/api/shlobj_core/nf-shlobj_core-shopenfolderandselectitems
 return `$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SeqaraReveal {
 [DllImport("ole32.dll")] static extern int CoInitializeEx(IntPtr reserved, uint mode);
 [DllImport("ole32.dll")] static extern void CoUninitialize();
 [DllImport("shell32.dll", CharSet=CharSet.Unicode)] static extern int SHParseDisplayName(string name, IntPtr bind, out IntPtr pidl, uint mask, out uint attributes);
 [DllImport("shell32.dll")] static extern int SHOpenFolderAndSelectItems(IntPtr pidl, uint count, IntPtr children, uint flags);
 public static void Show(string path) {
  int initialized=CoInitializeEx(IntPtr.Zero,2);
  if(initialized<0)Marshal.ThrowExceptionForHR(initialized);
  IntPtr pidl=IntPtr.Zero;
  try {
   uint attributes;
   Marshal.ThrowExceptionForHR(SHParseDisplayName(path,IntPtr.Zero,out pidl,0,out attributes));
   Marshal.ThrowExceptionForHR(SHOpenFolderAndSelectItems(pidl,0,IntPtr.Zero,0));
  } finally {if(pidl!=IntPtr.Zero)Marshal.FreeCoTaskMem(pidl);CoUninitialize();}
 }
}
'@
[SeqaraReveal]::Show(${literal})
`;
}
export async function revealNativePath(target,signal=new AbortController().signal,internals={}){
 await existingPath(target,signal);
 const options=optionsOf(internals);
 if((options.platform??process.platform)!=='win32')return upstream.revealNativePath(target,signal,options);
 const encoded=Buffer.from(revealScript(target),'utf16le').toString('base64');
 await options.run('powershell.exe',['-NoProfile','-NonInteractive','-STA','-EncodedCommand',encoded],signal);
}
