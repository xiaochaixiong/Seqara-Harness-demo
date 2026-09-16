"""End-to-end Qt interaction checks against an isolated DSH profile."""
import json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/interaction-repairs'
serial=int(time.time())
def request(code=None,**args):
 global serial
 serial+=1
 command={'id':serial,**args}
 if code is not None:command['code']=code
 p=OUT/'command.json'
 p.write_text(json.dumps(command,ensure_ascii=False),encoding='utf8')
 deadline=time.monotonic()+40
 while time.monotonic()<deadline:
  try:
   result=json.loads((OUT/'result.json').read_text('utf8'))
   if result.get('id')==serial:
    assert 'error' not in result,result
    return result
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.1)
 raise AssertionError('Qt command timed out')
def js(code):return request(code)['value']
def wait_for(code,timeout=25):
 deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  value=js(code)
  if value:return value
  time.sleep(.2)
 raise AssertionError('Condition timed out: '+code+'\n'+str(js('document.body.innerText')))
def click(selector,text=None):
 selector=json.dumps(selector);text=json.dumps(text)
 row=json.loads(js(f'''(()=>{{const b=[...document.querySelectorAll({selector})].find(b=>{text}===null||b.textContent.trim()==={text});const row=b?.closest('[class*="_projectRow"],[class*="_sessionRow"]');if(!row)return null;row.scrollIntoView({{block:'nearest'}});const r=row.getBoundingClientRect();return JSON.stringify([Math.round(r.x+r.width/2),Math.round(r.y+r.height/2)])}})()''') or 'null')
 if row:request(action='move',point=row);time.sleep(.4)
 point=json.loads(js(f'''(()=>{{const b=[...document.querySelectorAll({selector})].find(b=>{text}===null||b.textContent.trim()==={text});if(!b)throw Error('button missing');b.scrollIntoView({{block:'nearest'}});const r=b.getBoundingClientRect();return JSON.stringify([Math.round(r.x+r.width/2),Math.round(r.y+r.height/2)])}})()'''))
 request(action='move',point=point);time.sleep(.3)
 assert js(f'''(()=>{{const b=[...document.querySelectorAll({selector})].find(b=>{text}===null||b.textContent.trim()==={text});return b.contains(document.elementFromPoint({point[0]},{point[1]}))}})()'''), 'Button obscured: '+selector
 request(action='click',point=point)
 time.sleep(.35)
def run():
 wait_for("!!document.querySelector('[data-native-tools]')",80)
 js("[...document.querySelectorAll('button')].find(b=>b.textContent==='稍后配置')?.click()")
 wait_for("!document.querySelector('[role=dialog]')")
 status=request('true')
 assert status['contextMenu']==status['shellContextMenu']=='NoContextMenu'
 assert status['clipboardEnabled']
 js('''window.qaProps=(selector,name)=>{const e=document.querySelector(selector);let root=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];function find(f){if(!f)return null;if(f.type?.name===name)return f.memoizedProps;return find(f.child)||find(f.sibling)}return find(root)};
 window.qaWorkspace=qaProps('[data-slot="sidebar.workspaces"]','WorkspaceBrowser');''')
 path=str(OUT/'workspace-fixture')
 js(f"qaWorkspace.createWorkspace({{path:{json.dumps(path)}}}).then(w=>window.qaCreated=w)")
 wait_for('!!window.qaCreated')
 click('[aria-label="在“workspace-fixture”中新建会话"]')
 wait_for("document.body.innerText.includes('新会话')&&!!document.querySelector('[contenteditable=true]')")
 time.sleep(1)
 print('Workspace session creation passed',flush=True)
 # Report the actual native clipboard, including Chinese and multiline text.
 js('''(()=>{window.qaCopied=false;window.qaCopyError=null;const b=document.createElement('button');b.id='qa-copy';b.textContent='复制验证';b.style='position:fixed;left:600px;top:200px;z-index:99999';b.onclick=()=>navigator.clipboard.writeText('复制回归：中文 ✓\\n第二行').then(()=>window.qaCopied=true,e=>window.qaCopyError=e.message);document.body.append(b);})()''')
 click('#qa-copy');wait_for('window.qaCopied||window.qaCopyError')
 assert request(action='clipboard')['value'].replace('\r\n','\n')=='复制回归：中文 ✓\n第二行',js('window.qaCopyError')
 js("document.querySelector('#qa-copy').remove()")
 # Keep a second workspace so the official picker opens a menu, rather than
 # asking Windows to show its native directory chooser during unattended QA.
 spare=OUT/'spare-workspace';spare.mkdir(exist_ok=True)
 js(f"qaWorkspace.createWorkspace({{path:{json.dumps(str(spare))}}}).then(w=>window.qaSpare=w)")
 wait_for('!!window.qaSpare')
 # Delete a registered workspace via its real menu and confirmation button.
 click('[aria-label="工作区“workspace-fixture”的操作"]')
 click('[role=menuitem]','删除工作区')
 wait_for("!!document.querySelector('[role=dialog]')")
 click('[role=dialog] button','删除工作区')
 wait_for("!document.querySelector('[aria-label=\"工作区“workspace-fixture”的操作\"]')")
 assert Path(path).is_dir()
 print('Workspace deletion passed (folder retained)',flush=True)
 wait_for("!!document.querySelector('[aria-label=\"在“未分组”中新建会话\"]')")
 js('''window.qaSessions=()=>{const e=document.querySelector('[data-slot="sidebar.workspaces"]');let root=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];function find(f){if(!f)return null;if(f.type?.name==='SessionTree')return f;return find(f.child)||find(f.sibling)}let h=find(root)?.memoizedState;while(h){if(h.memoizedState?.byId)return h.memoizedState;h=h.next}};window.qaBefore=qaSessions().current;''')
 click('[aria-label="在“未分组”中新建会话"]')
 time.sleep(1)
 assert not js("!!document.querySelector('[data-sq-session-error]')")
 assert js('qaSessions().current!==qaBefore&&!!qaSessions().current')
 wait_for("!!document.querySelector('[role=menu]')")
 js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
 print('Ungrouped creates and selects a new session, then opens the workspace picker',flush=True)
 click('[data-sq-taskboard]')
 wait_for("document.body.innerText.includes('+ 新建任务')")
 js('''(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('新建任务'));let f=b[Object.keys(b).find(k=>k.startsWith('__reactFiber'))];while(f){if(f.memoizedProps?.controller){window.qaBoard=f.memoizedProps.controller;break;}f=f.return;}})();qaBoard.createTaskConfirmed({title:'删除回归测试',description:'隔离测试',prompt:'无需运行'}).then(t=>{window.qaTask=t;qaBoard.openTask(t.id)});''')
 wait_for("!!document.querySelector('[role=dialog]')")
 assert request('true')['modal']
 click('[role=dialog] button','删除')
 wait_for("!!document.querySelector('[role=alertdialog]')")
 click('[role=alertdialog] button','取消')
 assert js('qaBoard.getSnapshot().tasks.length===1')
 click('[role=dialog] button','删除')
 click('[role=alertdialog] button','删除')
 wait_for('qaBoard.getSnapshot().tasks.length===0')
 assert js("document.documentElement.dataset.seqaraSurface==='plugin:taskboard'")
 print('Task deletion and cancellation passed',flush=True)
 click('[data-sq-taskboard]')
 fonts=json.loads(js('''JSON.stringify([...document.querySelectorAll('[class*="_sectionLabel"],.nv-group')].map(e=>{const s=getComputedStyle(e);return {text:e.textContent,font:[s.fontFamily,s.fontSize,s.fontWeight,s.lineHeight,s.letterSpacing]}}))'''))
 assert [x['text'] for x in fonts]==['工作区','工作工具','扩展工具']
 assert all(x['font']==fonts[0]['font'] for x in fonts)
 assert not js("!!document.querySelector('button[aria-label=\"导入会话\"]')")
 request(action='capture',name='verified-light')
 js("window.dispatchEvent(new CustomEvent('seqara-theme-set',{detail:'dark'}))")
 time.sleep(.8);request(action='capture',name='verified-dark')
 result=request('true');assert not result['errors'],result['errors']
 # Exercise the actual WebEngine download signal and native save handler offline.
 target=OUT/'offline-download.txt'
 if target.exists():target.unlink()
 assert request(action='prepare-download')['value']
 js("(()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['离线导出验证 ✓'],{type:'text/plain;charset=utf-8'}));a.download='offline-download.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),10000)})()")
 deadline=time.monotonic()+15
 while time.monotonic()<deadline and not target.exists():time.sleep(.2)
 assert target.read_text('utf8')=='离线导出验证 ✓'
 assert '已保存到' in request(action='download-status')['value']
 print('Offline blob download saved exact UTF-8 bytes',flush=True)
 (OUT/'acceptance.json').write_text(json.dumps({'passed':True,'checks':['native context menus disabled','clipboard round trip','workspace create/delete','ungrouped new selected session and picker','task delete/cancel','matching sidebar typography','light/dark captures','offline blob download bytes and completion status'],'fonts':fonts},ensure_ascii=False,indent=2),encoding='utf8')
 print('ALL_INTERACTION_CHECKS_PASSED',flush=True)
if __name__=='__main__':
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'command.json').write_text(json.dumps({'id':serial,'code':'true'}),encoding='utf8')
 log=(OUT/'qt-test.log').open('w',encoding='utf8')
 proc=subprocess.Popen([sys.executable,str(ROOT/'tests/interaction_probe.py')],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 try:run()
 finally:
  request(action='quit');proc.wait(timeout=30);log.close()
