"""Authenticated local QWebChannel boundary; credentials never enter console logs."""
import json
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QFile, QIODevice, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript
from seqara_settings import SettingsStore
from seqara_prompts import PromptStore

class DesktopBridge(QObject):
    response = Signal(str)
    def __init__(self, window, data):
        super().__init__(window)
        self.window, self.data = window, Path(data)
        self.store = SettingsStore(self.data/'native')

    @Slot(str)
    def request(self, raw):
        w = self.window
        if not w.last_url or w.webpage.url().host() != '127.0.0.1' or w.webpage.url().port() != QUrl(w.last_url).port():
            return
        request_id = None
        try:
            if len(raw) > 2_000_000:
                raise ValueError('设置内容过大')
            req = json.loads(raw)
            request_id = req['id']
            action, args = req['action'], req.get('args', {})
            if w.offline and (action=='connection.test' or action=='desktop.action' and args.get('type') in ('check','install')):
                raise ValueError('离线模式下无法执行联网操作，请先恢复联网。')
            if action == 'connection.test':
                import toolkit
                saved = toolkit.nv_ds.load_api_config_dict()
                key = args.get('deepseek_api_key') if args.get('replace_key') else saved.get('deepseek_api_key', '')
                model = args.get('deepseek_model', 'deepseek-v4-flash')
                def check():
                    ok, message = toolkit.nv_ds.test_api_connection(key, model)
                    self.response.emit(json.dumps({'id':request_id,'ok':True,'value':{'connected':ok,'message':message}}))
                threading.Thread(target=check, daemon=True).start()
                return
            if action == 'prompts.list':
                value = PromptStore(self.data).read()
            elif action in ('prompts.upsert','prompts.delete'):
                value = PromptStore(self.data).change(action.split('.')[1],args)
            elif action == 'settings.read':
                value = self.store.read(args['section'])
            elif action == 'settings.save':
                value = self.store.save(args['section'], args['value'], args['revision'])
                page = w.stack.widget(4)
                if hasattr(page, 'apply_classify_defaults_from_disk'):
                    page.apply_classify_defaults_from_disk()
            elif action == 'desktop.status':
                value = {'version':'0.8.0-demo.1','offline':w.offline,'core':w.runtime_state.get('version','读取中'),
                         'runtime':w.runtime_state.get('state'),'autoUpdate':w.service_settings.get('autoUpdate',False),
                         'logs':w.service_logs[-15:],'data':str(self.data), 'migration':w.config_migration,
                         'tasks':list(w.agent_tasks.values())[-30:]}
            elif action == 'desktop.action':
                if args.get('type') not in ('check','install','restart','auto'):
                    raise ValueError('不支持的操作')
                if args['type'] == 'restart' and (w._background_work_active() or w.agent_busy or w.session_busy):
                    raise ValueError('仍有任务运行，请先停止任务或等待完成，再重启工作台。')
                w.send(args)
                value = {'message':'操作已提交，状态将在此页面更新。'}
            elif action == 'desktop.open-data':
                import toolkit
                if not toolkit.QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data))):
                    raise ValueError('无法打开数据文件夹，请检查文件资源管理器是否可用。')
                value = {}
            else:
                raise ValueError('不支持的设置操作')
            self.response.emit(json.dumps({'id':request_id,'ok':True,'value':value},ensure_ascii=False))
        except Exception as exc:
            self.response.emit(json.dumps({'id':request_id,'ok':False,'error':str(exc)},ensure_ascii=False))

def install(window, data):
    bridge = DesktopBridge(window, data)
    channel = QWebChannel(window.webpage)
    channel.registerObject('seqara', bridge)
    window.webpage.setWebChannel(channel)
    resource = QFile(':/qtwebchannel/qwebchannel.js')
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError('无法加载桌面设置桥接')
    source = bytes(resource.readAll()).decode('utf8')
    source += '\nwindow.seqaraOffline='+json.dumps(window.offline)+';'
    source += '''\nwindow.seqaraDesktopReady = new Promise(resolve => {
      new QWebChannel(qt.webChannelTransport, channel => {
        const pending = new Map(); let serial=0;
        channel.objects.seqara.response.connect(raw => { const r=JSON.parse(raw); const p=pending.get(r.id); if(!p)return; clearTimeout(p.timer);pending.delete(r.id);r.ok?p.resolve(r.value):p.reject(Error(r.error)); });
        window.seqaraDesktop = (action,args={}) => new Promise((resolve,reject)=>{const id=++serial;const timer=setTimeout(()=>{pending.delete(id);reject(Error('桌面响应超时，请重试。'));},30000);pending.set(id,{resolve,reject,timer});channel.objects.seqara.request(JSON.stringify({id,action,args}));});
        resolve(window.seqaraDesktop);
      });
    });'''
    script = QWebEngineScript()
    script.setName('seqara-desktop-channel')
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(source)
    window.webpage.scripts().insert(script)
    window.desktop_bridge, window.desktop_channel = bridge, channel
