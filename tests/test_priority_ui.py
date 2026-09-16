import json,subprocess,sys,time
from pathlib import Path
from test_sidebar_interactions import request,js,wait_for,click,OUT,ROOT,serial

def fill(selector,value):
 js(f'''(()=>{{const e=document.querySelector({json.dumps(selector)});Object.getOwnPropertyDescriptor(e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(e,{json.dumps(value)});e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()''')

def run():
 wait_for("!!document.querySelector('[data-native-tools]')",90)
 js("[...document.querySelectorAll('button')].find(b=>b.textContent==='稍后配置')?.click()")
 wait_for("!document.querySelector('[role=dialog]')")
 js('''window.qaProps=(selector,name)=>{const e=document.querySelector(selector);let root=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];function find(f){if(!f)return null;if(f.type?.name===name)return f.memoizedProps;return find(f.child)||find(f.sibling)}return find(root)};window.qaWorkspace=qaProps('[data-slot="sidebar.workspaces"]','WorkspaceBrowser');''')
 folder=OUT/'library-workspace';folder.mkdir(exist_ok=True)
 js(f"qaWorkspace.createWorkspace({{path:{json.dumps(str(folder))}}}).then(w=>window.qaCreated=w)")
 wait_for('!!window.qaCreated');click('[aria-label="在“library-workspace”中新建会话"]')
 wait_for("!!document.querySelector('[contenteditable=true]')")
 click('[data-native-tool="7"]');wait_for("!!document.querySelector('[aria-label=\"Skill技能库\"]')")
 assert not js("document.querySelector('.nv-hub').innerText.includes('刷新目录')")
 click('[role=tab]','提示词库');click('.sq-prompt-library button','新增提示词')
 fill('[role=dialog] input','测试提示词');fill('[role=dialog] textarea','请核对材料后生成报告。\n保留原始文件。')
 click('[role=dialog] button','保存');wait_for("!document.querySelector('[role=dialog]')")
 data=Path(request(action='native-status')['value']['data'])
 assert json.loads((data/'prompt-library.json').read_text('utf8'))[0]['name']=='测试提示词'
 click('.sq-prompt-library button','添加到对话')
 wait_for("document.querySelector('[contenteditable=true]')?.innerText.includes('请核对材料')")
 click('[data-native-tool="7"]');click('[role=tab]','提示词库');wait_for("document.querySelector('.sq-prompt-library')?.innerText.includes('测试提示词')")
 click('.sq-prompt-library button','编辑');fill('[role=dialog] input','已编辑提示词');click('[role=dialog] button','保存')
 wait_for("!document.querySelector('[role=dialog]')");click('.sq-prompt-library button','删除');click('[role=dialog] button','确认删除')
 wait_for("!document.querySelector('[role=dialog]')");assert json.loads((data/'prompt-library.json').read_text('utf8'))==[]
 print('Prompt CRUD, disk persistence and insert passed',flush=True)
 click('[aria-label^="会话“"][aria-label$="的操作"]');click('[role=menuitem]','删除任务');click('[data-sq-delete-dialog] button','取消')
 wait_for("!document.querySelector('[role=dialog]')")
 click('[aria-label="工作区“library-workspace”的操作"]');click('[role=menuitem]','删除工作区');click('[data-sq-delete-dialog] button','确认删除')
 wait_for("!document.querySelector('[aria-label=\"工作区“library-workspace”的操作\"]')")
 assert folder.is_dir()
 click('[aria-label="在“未分组”中新建会话"]')
 time.sleep(1)
 assert '已新建' in request(action='native-status')['value']['status']
 request(action='dismiss-native-dialog')
 js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
 while js("!!document.querySelector('[aria-label^=\"会话“\"][aria-label$=\"的操作\"]')"):
  click('[aria-label^="会话“"][aria-label$="的操作"]');click('[role=menuitem]','删除任务');click('[data-sq-delete-dialog] button','确认删除');wait_for("!document.querySelector('[role=dialog]')")
 print('Task and workspace removal, ungrouped creation passed',flush=True)
 request(action='native',index=0)
 js("(()=>{let e=document.createElement('div');e.id='qa-tooltip';e.role='tooltip';e.style='position:fixed;left:250px;top:200px;width:280px;height:80px;background:#222;color:white;z-index:2147483000';e.textContent='Tooltip above native dashboard';document.body.append(e)})()")
 time.sleep(.5);assert request(action='native-status')['value']['overlays']
 assert request('true')['nativeVisible']
 request(action='capture',name='priority-tooltip');js("document.querySelector('#qa-tooltip').remove()")
 (OUT/'priority-acceptance.json').write_text(json.dumps({'passed':True,'checks':['prompt CRUD and persisted bytes','insert draft','task and workspace removal/cancel','ungrouped create feedback','native tooltip overlay'],'runtime':request(action='native-status')['value']['runtime']},ensure_ascii=False,indent=2),'utf8')
 print('PRIORITY_UI_PASSED',flush=True)

if __name__=='__main__':
 OUT.mkdir(exist_ok=True);(OUT/'command.json').write_text(json.dumps({'id':serial,'code':'true'}),'utf8')
 log=(OUT/'priority.log').open('w',encoding='utf8')
 proc=subprocess.Popen([sys.executable,str(ROOT/'tests/interaction_probe.py'),'--priority-profile'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 try:run()
 except Exception:
  request(action='capture',name='priority-failed')
  (OUT/'priority-failure.txt').write_text(js('document.body.innerText'),'utf8')
  raise
 finally:
  request(action='quit');proc.wait(timeout=30);log.close()
