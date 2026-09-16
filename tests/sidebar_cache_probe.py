"""Isolated Qt WebEngine renderer test (not visual evidence)."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'native'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import seqara_shell
app=QApplication([]);view=QWebEngineView();view.resize(280,800)
snapshot={'version':1,'width':56,'html':'<div class="_sidebarCol_test"><button aria-label="打开侧边栏"></button></div>','css':''}

def ready(ok):
    if not ok:app.exit(2);return
    script="""(()=>{
       const root=document.querySelector('.sq-shell');
       const collapsedFirst=!!root?.classList.contains('collapsed');
       document.querySelector('[data-sq-action="collapse"]').click();
       const logo=document.querySelector('.sq-shell-logo>svg');
       const span=[...document.querySelectorAll('button span')].find(n=>n.textContent==='新建会话');
       return JSON.stringify({collapsedFirst,brandVisible:!!logo&&logo.getBoundingClientRect().width>30,
          label:span?.textContent,labelWidth:span?.getBoundingClientRect().width,
          width:document.querySelector('#sidebar').getBoundingClientRect().width});
    })()"""
    def done(value):
        print(value,flush=True);view.close();app.quit()
    view.page().runJavaScript(script,done)

view.loadFinished.connect(ready)
view.setHtml(seqara_shell.render(snapshot,False,56,0,True))
QTimer.singleShot(20000,lambda:app.exit(3))
sys.exit(app.exec())
