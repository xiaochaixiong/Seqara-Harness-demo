const fs=require('node:fs'),path=require('node:path');
require('./patch-pdf-compat.cjs').apply();
require('./patch-workspace-menus.cjs').apply();
require('./patch-error-messages.cjs').apply();
const root=path.resolve(__dirname,'../runtime/toolkit-brand');
const integration=fs.readFileSync(path.join(root,'desktop-integration.js'),'utf8');
const workspaceManager=fs.readFileSync(path.join(root,'workspace-manager.js'),'utf8');
const promptLibrary=fs.readFileSync(path.join(root,'prompt-library.js'),'utf8');
const marketIntegration=fs.readFileSync(path.join(root,'market-integration.js'),'utf8');
const navigation=fs.readFileSync(path.join(root,'navigation.cjs'),'utf8');
const css=fs.readFileSync(path.join(root,'desktop.css'),'utf8');
const sidebarCss=fs.readFileSync(path.join(root,'sidebar.css'),'utf8');
const windowCss=fs.readFileSync(path.join(root,'window.css'),'utf8');
const core=fs.readFileSync(path.join(root,'brand-core.js'),'utf8');
const project=path.resolve(root,'../..');
const tokens=JSON.parse(fs.readFileSync(path.join(project,'native/ui_tokens.json'),'utf8'));
function theme(p){return `--nv-sidebar:${p.panel};--nv-canvas:${p.canvas};--nv-text:${p.text};--nv-muted:${p.muted};--nv-hover:${p.hover};--nv-selected:${p.selected};--nv-line:${p.line};--nv-focus:${p.focus};--nv-primary:${p.primary};--nv-on-primary:${p.onPrimary}`;}
const sharedCss=`:root{${theme(tokens.light)}}body[data-ds-dark-theme]{${theme(tokens.dark)}}body,input,textarea,button,select{font-family:'Segoe UI','Microsoft YaHei','PingFang SC',sans-serif}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline-color:var(--nv-focus)!important}`+'\n'+sidebarCss+'\n'+windowCss;
const assets={day:fs.readFileSync(path.join(project,'assets/brand/seqara-signature-day.svg'),'utf8'),night:fs.readFileSync(path.join(project,'assets/brand/seqara-signature-night.svg'),'utf8')};
fs.writeFileSync(path.join(root,'client.js'),'(()=>{\n'+navigation+'\n'+promptLibrary+'\n'+workspaceManager+'\n'+marketIntegration+'\n'+integration+'\nconst seqaraAssets='+JSON.stringify(assets)+';\nconst seqaraDesktopCss='+JSON.stringify(css+'\n'+sharedCss)+';\n'+core+'\n})();\n');
// Cold start and offline sidebar consume the exact brand assets and semantic tokens.
const titles=JSON.parse(core.match(/const titles=(\[[^;]+\])/)[1].replaceAll("'",'"'));
const icons=JSON.parse(core.match(/const icons=(\[[^;]+\])/)[1].replaceAll("'",'"'));
fs.writeFileSync(path.join(project,'native/seqara_shell.json'),JSON.stringify({...assets,titles,icons,css:sharedCss}));
