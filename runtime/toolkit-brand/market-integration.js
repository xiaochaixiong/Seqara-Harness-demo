/* Seqara offers its shared Appearance controls; the market's theme gallery is
 * intentionally unavailable. Keep this in the host so plugin updates do not
 * overwrite the policy, and leave React-owned nodes attached to their tree. */
function installSeqaraMarket() {
 const roots='[data-dsh-market-root][data-dsh-market-tab]';
 const hidden='data-sq-market-theme-entry';
 const themeLabel=/^(主题|Themes)$/i;
 const forgetThemeTab=()=>{
  try{if(sessionStorage.getItem('dshm-tab')==='themes')sessionStorage.removeItem('dshm-tab');}catch{/* Storage may be unavailable during teardown. */}
 };
 const tabsOf=root=>[...root.querySelectorAll('button')].filter(button=>
  [...button.parentElement.classList].some(name=>name.endsWith('_tabs')));
 const discoverOf=tabs=>tabs.find(button=>/^(发现|Discover)$/.test(button.textContent.trim()));
 function sync(){
  forgetThemeTab();
  for(const root of document.querySelectorAll(roots)){
   const tabs=tabsOf(root);
   for(const button of tabs){
    if(themeLabel.test(button.textContent.trim())){
     button.setAttribute(hidden,'');
     button.hidden=true;
    }
   }
   // Also handles a restored tab when the market was already mounted, without
   // changing the user's preferred appearance or any installed packages.
   if(root.dataset.dshMarketTab==='themes')discoverOf(tabs)?.click();
  }
 }
 const preventTheme=e=>{
  const button=e.target.closest?.('button['+hidden+']');
  if(!button)return;
  e.preventDefault();e.stopImmediatePropagation();
  const root=button.closest(roots);if(root)discoverOf(tabsOf(root))?.click();
 };
 forgetThemeTab();
 const observer=new MutationObserver(sync);
 observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-dsh-market-tab']});
 document.addEventListener('click',preventTheme,true);
 sync();
 return()=>{observer.disconnect();document.removeEventListener('click',preventTheme,true);};
}
