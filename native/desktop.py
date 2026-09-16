"""Native macOS-style toolkit chrome and full legacy pages around official DSH."""
import os,sys,json
from pathlib import Path
ROOT=Path(os.environ.get('NV_DESKTOP_ROOT',Path(__file__).resolve().parents[1]))
DATA=Path(os.environ.get('NV_DESKTOP_DATA',Path(os.environ.get('APPDATA',Path.home()))/'SeqaraHarnessDemo'))
DATA.mkdir(parents=True,exist_ok=True)
if sys.stderr is None:sys.stderr=open(DATA/'native-startup.log','a',encoding='utf8')
if sys.stdout is None:sys.stdout=sys.stderr
def record_exception(kind,value,tb):
    import traceback
    with (DATA/'native-startup.log').open('a',encoding='utf8') as f:traceback.print_exception(kind,value,tb,file=f)
sys.excepthook=record_exception
from seqara_settings import prepare_shared_config
CONFIG_MIGRATION=prepare_shared_config(DATA)
os.environ['NV_NATIVE_DATA']=str(DATA/'native')
import seqara_network
from seqara_navigation import navigation_target,download_allowed
os.environ['SEQARA_OFFLINE']='1' if seqara_network.load(DATA) else '0'
seqara_network.install_requests_guard()
import toolkit as old
import ui_design
import seqara_shell
import seqara_chrome
old.ui_font=ui_design.font
old.palette=ui_design.palette
for default_name in ('project_company_schools.json','ticket_company_schools.json','invoice_classify_defaults.json'):
    import shutil
    source=old._RESOURCE_DIR/default_name;target=old._DATA_DIR/default_name
    if source.is_file() and not target.exists():shutil.copy2(source,target)
from PySide6.QtCore import QUrl,QProcess,QProcessEnvironment,Signal,QTimer,Qt,QPropertyAnimation,QEasingCurve,QRect
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QTabWidget,QCheckBox,QTextEdit,QScrollArea,QGraphicsOpacityEffect
from PySide6.QtGui import QRegion,QPalette,QColor,QIcon
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings,QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self,parent,origin=None):
        super().__init__(parent);self.origin=origin
    def interceptRequest(self,info):
        if seqara_network.is_offline() and info.requestUrl().scheme() in ('http','https','ws','wss','ftp'):
            trusted=QUrl(self.origin() or '') if self.origin else QUrl()
            url=info.requestUrl()
            if trusted.host()=='127.0.0.1' and url.host()==trusted.host() and url.port()==trusted.port():return
            info.block(True)

class Page(QWebEnginePage):
    action=Signal(str)
    def javaScriptConsoleMessage(self,level,message,line,source):
        if message.startswith('__NV_NATIVE__') and self.url().host()=='127.0.0.1':
            self.action.emit(message[len('__NV_NATIVE__'):])
        elif level==QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.console_errors=getattr(self,'console_errors',[])+[message[:500]]
    def acceptNavigationRequest(self,url,kind,main):
        trusted=QUrl(self.trusted_origin()) if hasattr(self,'trusted_origin') else self.url()
        target=navigation_target(url.toString(),trusted.toString(),seqara_network.is_offline())
        if target=='blocked':return False
        if main and target=='external':
            if not old.QDesktopServices.openUrl(url):
                self.action.emit(json.dumps({'type':'desktop-error','message':'无法打开外部链接，请检查系统默认浏览器设置。'}))
            return False
        return super().acceptNavigationRequest(url,kind,main)

class ShellPage(QWebEnginePage):
    action=Signal(str)
    def javaScriptConsoleMessage(self,level,message,line,source):
        if message.startswith('__SQ_SHELL__'):
            self.action.emit(message[len('__SQ_SHELL__'):])
    def acceptNavigationRequest(self,url,kind,main):
        return url.scheme() in ('data','about','qrc')

class Surface(QWidget):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'owner'):self.owner.layout_surface()

class Window(old.MainWindow):
    def __init__(self):
        seqara_chrome.install()
        self.settings_requested=False
        self.offline=seqara_network.is_offline();self.network_transition=False;self.pending_theme=None
        self.settings_dirty=False;self.config_migration=CONFIG_MIGRATION;self.agent_tasks={};self.agent_busy=False;self.session_busy=False;self.modal_return=None;self.surface_id='conversation';self.web_ready=False
        self.sidebar_snapshot=seqara_shell.load_cache(DATA);self.shell_visible=True;self.offline_reason='';self.restart_requested=False
        self.native_ready=False;self.sidebar_width=max(52,min(400,int((self.sidebar_snapshot or {}).get('width',280))));self.runtime_state={};self.service_settings={};self.service_logs=[];self.last_url='';self.stopping=False
        super().__init__()
        self.setWindowTitle('有序 Seqara Harness · 0.8.0-demo.1');self.resize(1440,900)
        seqara_chrome.fit_initial_window(self)
        self.page_transition=None
        for index in range(7):ui_design.normalize_page(self.stack.widget(index),index)
        nav=self.findChild(old.QFrame,'nav');nav.hide()
        wrap=self.stack.parentWidget();layout=wrap.layout();layout.removeWidget(self.stack)
        self.surface=Surface();self.surface.owner=self;layout.addWidget(self.surface,1)
        self.web=QWebEngineView(self.surface)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.profile=QWebEngineProfile('native-desktop',self.web)
        self.profile.setPersistentStoragePath(str(DATA/'native-browser/storage'));self.profile.setCachePath(str(DATA/'native-browser/cache'))
        self.network_interceptor=OfflineInterceptor(self.profile,lambda:self.last_url);self.profile.setUrlRequestInterceptor(self.network_interceptor)
        self.webpage=Page(self.profile,self.web);self.web.setPage(self.webpage)
        self.webpage.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,True)
        self.webpage.trusted_origin=lambda:self.last_url
        import seqara_bridge
        seqara_bridge.install(self,DATA)
        self.webpage.action.connect(self.web_action);self.web.loadFinished.connect(self.loaded)
        self.webpage.newWindowRequested.connect(self.open_new_window)
        self.profile.downloadRequested.connect(self.download)
        self.stack.setParent(self.surface);self.stack.hide()
        self.topbar_title.setText('有序 Seqara · 工作台')
        self.status_label=QLabel('正在启动智能工作台…');self.status_label.setObjectName('nv_runtime_status');self.status_label.setFixedHeight(24);layout.addWidget(self.status_label)
        self.shell=QWebEngineView(self.surface)
        self.shell.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.shell_profile=QWebEngineProfile(self.shell)
        self.shell_interceptor=OfflineInterceptor(self.shell_profile);self.shell_profile.setUrlRequestInterceptor(self.shell_interceptor)
        self.shell_page=ShellPage(self.shell_profile,self.shell);self.shell.setPage(self.shell_page)
        self.shell_page.action.connect(self.shell_action)
        self.shell.loadFinished.connect(self.shell_loaded)
        self.snapshot_timer=QTimer(self);self.snapshot_timer.setSingleShot(True);self.snapshot_timer.timeout.connect(self.capture_sidebar)
        self.startup_timer=QTimer(self);self.startup_timer.setSingleShot(True);self.startup_timer.setInterval(60000)
        self.startup_timer.timeout.connect(lambda:self.enter_offline_after_failure('连接超时'))
        self.build_network_controls()
        self.native_ready=True;self.layout_surface();self.apply_theme()
        self.settings_shortcut=old.QShortcut(old.QKeySequence('Ctrl+,'),self);self.settings_shortcut.activated.connect(self._show_settings_dialog)
        self.process=QProcess(self);env=QProcessEnvironment.systemEnvironment();env.insert('NV_DESKTOP_DATA',str(DATA));self.process.setProcessEnvironment(env)
        self.process.setProgram(str(ROOT/'node-runtime/node.exe') if (ROOT/'node-runtime/node.exe').is_file() else (shutil.which('node') or 'node'));self.process.setArguments([str(ROOT/'desktop/native-service.cjs')]);self.process.setWorkingDirectory(str(ROOT));self.buffer=b''
        self.process.readyReadStandardOutput.connect(self.read_service);self.process.readyReadStandardError.connect(self.read_error);self.process.finished.connect(self.service_finished)
        self.process.errorOccurred.connect(lambda _:self.enter_offline_after_failure('工作台服务未能启动'))
        if self.offline:self.enter_local_mode()
        else:self.select_page(0);self.show_shell()
        # The settings renderer is local in both modes. External I/O is guarded.
        self.startup_timer.start();self.process.start()
        if '--native-smoke' in sys.argv:QTimer.singleShot(18000,self.smoke)
        if '--visual-qa' in sys.argv:QTimer.singleShot(20000,self.visual_qa)

    def build_network_controls(self):
        self.network_toggle=QPushButton();self.network_toggle.setObjectName('network_toggle');self.network_toggle.setFixedSize(32,32)
        self.network_toggle.setCheckable(True);self.network_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.network_toggle.setCursor(Qt.CursorShape.PointingHandCursor);self.network_toggle.clicked.connect(lambda:self.toggle_network())
        bar=self._topbar_frame.layout();bar.insertWidget(bar.indexOf(self.mode_toggle),self.network_toggle)
        self.mode_toggle.setFixedSize(32,32);self.mode_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QWidget.setTabOrder(self.network_toggle,self.mode_toggle)
        self.network_shortcut=old.QShortcut(old.QKeySequence('Ctrl+Shift+O'),self);self.network_shortcut.activated.connect(self.toggle_network)
        # All chrome controls have the same hit box and icon center.
        previous=self.mode_toggle;bar.removeWidget(previous);previous.hide();previous.deleteLater()
        self.mode_toggle=QPushButton();self.mode_toggle.setObjectName('mode_toggle');self.mode_toggle.setFixedSize(32,32)
        self.mode_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.mode_toggle.clicked.connect(self.toggle_theme)
        bar.addWidget(self.mode_toggle);QWidget.setTabOrder(self.network_toggle,self.mode_toggle)
        traffic=self.findChild(QWidget,'traffic_lights_wrap');bar.removeWidget(traffic);bar.addWidget(traffic)
        lights=traffic.layout()
        for button in (self._traffic_close,self._traffic_min,self._traffic_zoom):lights.removeWidget(button)
        for button in (self._traffic_min,self._traffic_zoom,self._traffic_close):lights.addWidget(button)
        lights.setSpacing(0);bar.setContentsMargins(12,6,12,6);bar.setSpacing(12)
        self._topbar_frame.setFixedHeight(44);self._topbar_shadow.setEnabled(False)
        self.update_network_controls()

    def capture_sidebar(self,callback=None):
        if not self.web_ready or self.modal_return is not None:
            if callback:callback()
            return
        def captured(raw):
            try:
                value=json.loads(raw) if raw else None
                if value and value.get('version')==1 and len(value.get('html',''))<500000:
                    self.sidebar_snapshot=value
                    if not self.shell_visible:self.sidebar_width=max(52,min(400,value['width']));self.layout_surface()
                    (DATA/'sidebar-cache.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
            except (OSError,ValueError,TypeError):pass
            if callback:callback()
        self.webpage.runJavaScript(seqara_shell.CAPTURE,captured)

    def show_shell(self):
        self.shell_visible=True;self.web.show()
        self.shell.setHtml(seqara_shell.render(self.sidebar_snapshot,self.dark,self.sidebar_width,self.stack.currentIndex(),self.offline),QUrl('qrc:/seqara/sidebar/'))
        self.shell.show();self.shell.raise_();self.layout_surface()

    def shell_loaded(self,ok):
        if not ok or not self.shell_visible:return
        # setHtml is asynchronous. Changes during loading are applied only after
        # the shell's handlers exist, so cached selection/theme cannot win a race.
        self.shell_page.runJavaScript('window.sqShell?.theme('+str(self.dark).lower()+');window.sqShell?.select('+str(self.stack.currentIndex())+')')

    def shell_action(self,raw):
        if not self.shell_visible:return
        try:v=json.loads(raw)
        except ValueError:return
        if v.get('type')=='tool' and type(v.get('index')) is int and v['index'] in (0,1,2,3,4,6):self.select_page(v['index'])
        elif v.get('type')=='settings':self._show_settings_dialog()
        elif v.get('type')=='width' and type(v.get('width')) is int:
            self.sidebar_width=max(52,min(400,v['width']));self.layout_surface()
            if self.sidebar_snapshot:
                self.sidebar_snapshot['width']=self.sidebar_width
                try:(DATA/'sidebar-cache.json').write_text(json.dumps(self.sidebar_snapshot,ensure_ascii=False),encoding='utf8')
                except OSError:pass

    def enter_offline_after_failure(self,reason):
        if self.stopping:return
        self.web_ready=False;self.web.stop();self.settings_requested=False
        self.service_logs.append(reason);self.startup_timer.stop();self.offline_reason='智能工作台暂不可用，已进入离线模式。'
        # The environment guard must engage even when the preference cannot be written.
        try:seqara_network.save(DATA,True)
        except OSError:os.environ['SEQARA_OFFLINE']='1'
        self.offline=True;self.network_transition=self.process.state()!=QProcess.ProcessState.NotRunning
        self.enter_local_mode();self.send({'type':'stop'});self.update_network_controls()
        QTimer.singleShot(8000,self.finish_offline_shutdown)

    def finish_offline_shutdown(self):
        if self.offline and not self.stopping and self.process.state()!=QProcess.ProcessState.NotRunning:self.process.kill()

    def update_network_controls(self):
        if not hasattr(self,'network_toggle'):return
        from PySide6.QtGui import QPixmap,QPainter
        from PySide6.QtCore import QSize,QRectF
        from PySide6.QtSvg import QSvgRenderer
        color='#e7e9ed' if self.dark else '#44474e'
        paths='<path d="M2 8.5a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M8.5 15.5a5.5 5.5 0 0 1 7 0"/><circle cx="12" cy="19" r=".8" fill="currentColor" stroke="none"/>'
        if self.offline:paths+='<path d="M3 3l18 18" stroke-width="2"/>'
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" color="{color}" stroke="{color}" stroke-width="1.6" stroke-linecap="round">{paths}</svg>'
        dpr=self.devicePixelRatioF();pix=QPixmap(round(18*dpr),round(18*dpr));pix.setDevicePixelRatio(dpr);pix.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pix);QSvgRenderer(svg.encode()).render(painter,QRectF(0,0,18,18));painter.end()
        self.network_toggle.setIcon(QIcon(pix));self.network_toggle.setIconSize(QSize(18,18));self.network_toggle.setChecked(self.offline)
        text=('正在暂停网络服务…' if self.network_transition else '离线模式 · 点击恢复联网' if self.offline else '联网模式 · 点击切换离线')
        self.network_toggle.setToolTip(text+'（Ctrl+Shift+O）');self.network_toggle.setAccessibleName(text);self.network_toggle.setEnabled(not self.network_transition)

    def toggle_network(self,captured=False):
        if self.network_transition:return
        if self.modal_return is not None or self.settings_dirty or self._background_work_active() or self.agent_busy or self.session_busy:
            self.update_network_controls();self.status_label.setText('请先保存设置，并等待任务完成或停止任务，再切换联网模式。');return
        if not self.offline and self.web_ready and not captured:
            self.capture_sidebar(lambda:self.toggle_network(True));return
        target=not self.offline
        try:seqara_network.save(DATA,target)
        except OSError as exc:
            self.update_network_controls();self.status_label.setText('无法保存联网模式：'+str(exc));return
        self.offline=target;self.offline_reason='';self.clear_theme_transition();self.stop_transition();self.startup_timer.stop()
        if target:
            self.enter_local_mode()
        else:
            self.shell_visible=False;self.shell.hide();self.stack.widget(5).setEnabled(True);self.layout_surface()
            if self.web_ready:self.status_label.setText('工作台就绪')
            else:
                self.status_label.setText('正在连接智能工作台…');self.show_shell();self.startup_timer.start()
                if self.process.state()==QProcess.ProcessState.NotRunning:self.process.start()
        self.publish_network_mode()
        self.update_network_controls()

    def enter_local_mode(self):
        self.modal_return=None;self.startup_timer.stop()
        self.agent_busy=False;self.session_busy=False
        # The seven local pages retain their widgets, inputs and result state.
        self.show_shell()
        index=self.stack.currentIndex() if self.surface_id.startswith('native:') else 0
        if index not in range(7):index=0
        self.stack.widget(5).setEnabled(False)
        self.select_page(index,allow_unavailable=True)
        self.status_label.setText(self.offline_reason or '离线模式：本地工具可用，联网功能已暂停。')
        self.publish_network_mode()

    def publish_network_mode(self):
        if hasattr(self,'webpage'):
            self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('seqara-network-mode',{detail:{offline:"+str(self.offline).lower()+"}}))")

    def send(self,value):
        if value.get('type')=='restart':self.restart_requested=True;self.startup_timer.start()
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.write((json.dumps(value)+'\n').encode())
    def read_error(self):
        value=bytes(self.process.readAllStandardError()).decode('utf-8','replace');self.service_logs.append(value)
    def read_service(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try:v=json.loads(line)
            except ValueError:continue
            kind=v.pop('type','')
            if kind=='runtime':
                self.runtime_state=v
                if not self.offline:self.status_label.setText({'running':'工作台就绪','starting':'正在启动智能工作台…','failed':'工作台启动失败；原生业务仍可使用','stopped':'工作台已停止'}.get(v.get('state'),'工作台正在关闭'))
                if v.get('state')=='failed' or (v.get('state')=='stopped' and not self.restart_requested and not self.stopping):
                    self.enter_offline_after_failure('工作台服务不可用');continue
                if v.get('state')=='running':self.restart_requested=False
                if v.get('url') and v['url']!=self.last_url:self.last_url=v['url'];self.web.setUrl(QUrl(v['url']))
            elif kind=='settings':self.service_settings=v
            elif kind=='task':
                self.agent_tasks[v['id']]=v;self.agent_busy=any(t.get('state') in ('running','queued') for t in self.agent_tasks.values());self.publish_tasks()
            elif kind in ('update','error'):
                message=v.get('message') or ('官方版本检查完成 · '+v.get('latest',''))
                self.service_logs.append(message);self.service_logs=self.service_logs[-80:]
                if hasattr(self,'update_label'):self.update_label.setText(self.service_logs[-1])

    def layout_surface(self):
        if not hasattr(self,'web'):return
        w,h=self.surface.width(),self.surface.height();self.web.setGeometry(0,0,w,h)
        if hasattr(self,'shell'):self.shell.setGeometry(0,0,w,h)
        self.stack.setGeometry(self.sidebar_width,0,max(0,w-self.sidebar_width),h);self.stack.raise_()
        # Clip the browser itself: transparent native children must never expose
        # the conversation underneath, including while resizing the sidebar.
        if self.stack.isVisible():
            mask=QRegion(0,0,self.sidebar_width,h)
            for rect in getattr(self,'web_overlays',[]):mask=mask.united(QRegion(QRect(*rect)))
            self.web.setMask(mask)
            if getattr(self,'web_overlays',[]):self.web.raise_()
        else:self.web.clearMask()
        if hasattr(self,'shell'):self.shell.setMask(QRegion(0,0,self.sidebar_width,h))
        for shortcut in getattr(self,'_page_shortcuts',[]):
            key=shortcut.key().toString()
            shortcut.setEnabled(self.modal_return is None and (self.stack.isVisible() or key not in ('Ctrl+Return','Ctrl+Enter')))

    def select_page(self,index,allow_unavailable=False):
        if not self.native_ready:return super().select_page(index)
        if self.modal_return is not None and not self.offline and not allow_unavailable:return
        if self.offline and index in (5,old.NAV_PAGE_HARNESS) and not allow_unavailable:
            self.status_label.setText('此功能需要联网。请使用窗口顶部的联网开关恢复连接。');return
        if index==old.NAV_PAGE_HARNESS:
            self.show_workbench()
            self.webpage.runJavaScript("window.dispatchEvent(new Event('seqara-conversation'))")
            return
        if index not in range(7):return
        self.surface_id='native:'+str(index)
        for i,button in enumerate(getattr(self,'local_buttons',[])):button.setChecked(i==index)
        changed=not self.stack.isVisible() or self.stack.currentIndex()!=index
        self.stop_transition()
        self.stack.setUpdatesEnabled(False)
        super().select_page(index);self.stack.show();self.layout_surface()
        self.topbar_title.setText('有序 Seqara · '+self._nav_titles[index])
        if self.offline:self.status_label.setText('离线模式：简报使用表格中的内容，暂不获取在线文章与图片。' if index==3 else self.offline_reason or '离线模式：本地工具可用，联网功能已暂停。')
        self.stack.currentWidget().layout().activate()
        self.stack.setUpdatesEnabled(True)
        self.topbar_title.setToolTip(self.stack.currentWidget().accessibleDescription())
        if changed and old.animations_enabled():
            viewport=self.stack.currentWidget().findChild(QScrollArea,'page_scroll').viewport()
            effect=viewport.graphicsEffect()
            if effect is None:effect=QGraphicsOpacityEffect(viewport);viewport.setGraphicsEffect(effect)
            effect.setEnabled(True)
            animation=QPropertyAnimation(effect,b'opacity',self)
            animation.setDuration(140);animation.setStartValue(.72);animation.setEndValue(1.)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.finished.connect(lambda:effect.setEnabled(False))
            self.page_transition=animation;animation.start()
        self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('nv-select',{detail:"+str(index)+"}))")
        if self.shell_visible:self.shell_page.runJavaScript("window.sqShell?.select("+str(index)+")")

    def stop_transition(self):
        animation=getattr(self,'page_transition',None)
        if animation is not None:
            animation.stop();animation.targetObject().setEnabled(False);animation.deleteLater();self.page_transition=None

    def show_workbench(self):
        if self.offline:return self.select_page(0)
        self.surface_id='conversation'
        self.stop_transition();self.topbar_title.setToolTip('')
        self.stack.hide();self.layout_surface();self.topbar_title.setText('有序 Seqara · 工作台')
        self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('nv-select',{detail:-1}))")

    def web_action(self,raw):
        try:v=json.loads(raw)
        except ValueError:return
        if self.offline and v.get('type') in ('conversation','web-surface','hub','skills-folder'):return
        if v.get('type')=='tool' and isinstance(v.get('index'),int):self.select_page(v['index'])
        elif v.get('type')=='settings':self._show_settings_dialog()
        elif v.get('type')=='ready':
            collapsed=self.sidebar_width<100
            self.webpage.runJavaScript("(()=>{const s=document.querySelector('[class*=\"_sidebarCol\"]');if(s&&(s.getBoundingClientRect().width<100)!=="+str(collapsed).lower()+"){s.querySelector('[class*=\"_logoRow\"] button[class*=\"_toggle\"]')?.click();}})()")
            self.web_ready=True;self.startup_timer.stop();self.shell_visible=self.offline;self.shell.setVisible(self.offline);self.web.show();self.stack.widget(5).setEnabled(not self.offline);self.layout_surface();self.publish_tasks();self.snapshot_timer.start(800)
            if not self.offline:self.status_label.setText('工作台就绪')
            self.publish_network_mode()
            self.sync_theme()
            if self.stack.isVisible():self.select_page(self.stack.currentIndex())
            if self.settings_requested:QTimer.singleShot(200,self._show_settings_dialog)
        elif v.get('type')=='web-overlays':
            self.web_overlays=v.get('rects',[])[:20];self.layout_surface()
        elif v.get('type')=='session-notice':self.status_label.setText(v.get('message',''))
        elif v.get('type')=='settings-dirty':self.settings_dirty=bool(v.get('dirty'))
        elif v.get('type')=='close-approved':self.settings_dirty=False;self.close()
        elif v.get('type')=='session-busy':self.session_busy=bool(v.get('busy'))
        elif v.get('type')=='modal-open':
            if self.modal_return is None or self.stack.isVisible():self.modal_return=(self.stack.currentIndex(),self.stack.isVisible())
            self.stop_transition();self.stack.hide();self.shell.hide();self.layout_surface()
        elif v.get('type')=='modal-close':
            previous=self.modal_return;self.modal_return=None;self.layout_surface()
            if previous and previous[1]:self.select_page(previous[0])
            if self.offline:self.shell.show();self.shell.raise_()
        elif v.get('type')=='web-surface':
            self.show_workbench();self.surface_id=v.get('id','plugin');self.topbar_title.setText(v.get('title') if v.get('title','').startswith('有序 Seqara') else '有序 Seqara · '+v.get('title','工作台'))
        elif v.get('type')=='conversation':self.show_workbench()
        elif v.get('type')=='hub':
            self.show_workbench();self.topbar_title.setText('有序 Seqara · Skill技能库')
            self.webpage.runJavaScript("window.dispatchEvent(new Event('nv-open-hub'))")
        elif v.get('type')=='skills-folder':
            folder=DATA/'harness/skills';folder.mkdir(parents=True,exist_ok=True)
            old.open_local_folder(self,folder)
        elif v.get('type')=='desktop-error':self.status_label.setText(v.get('message','系统未能完成此操作，请重试。'))
        elif v.get('type')=='width':
            if not self.shell_visible:self.sidebar_width=max(52,min(400,int(v.get('width',260))));self.layout_surface()
            self.snapshot_timer.start(800)
        elif v.get('type')=='theme' and v.get('theme') in ('light','dark'):
            if self.pending_theme and self.pending_theme!=v['theme']:return
            self.pending_theme=None
            dark=v['theme']=='dark'
            if self.dark!=dark:self.change_theme(dark)
        elif v.get('type')=='theme-painted' and v.get('serial')==getattr(self,'theme_serial',None):
            callback=getattr(self,'theme_reveal',None)
            if callback is not None:callback()

    def _sync_theme_controls(self):
        super()._sync_theme_controls()
        self.mode_chip.hide()
        self.mode_toggle.setAccessibleName(self.mode_toggle.toolTip())
        self.mode_toggle.setIcon(old.mono_svg_icon('moon' if self.dark else 'sun',18,ui_design.TOKENS['dark' if self.dark else 'light']['text']));self.mode_toggle.setIconSize(old.QSize(18,18))

    def toggle_theme(self):
        if self.web_ready:self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('seqara-theme-toggle'))")
        else:self.change_theme(not self.dark)

    def clear_theme_transition(self,preserve_change=False):
        if not preserve_change:self.theme_change_active=False
        self.theme_reveal=None
        animation=getattr(self,'theme_transition',None)
        if animation is not None:
            animation.stop();animation.deleteLater();self.theme_transition=None
        overlay=getattr(self,'theme_overlay',None)
        if overlay is not None:
            overlay.hide();overlay.deleteLater();self.theme_overlay=None

    def change_theme(self,dark):
        if self.dark==dark:return
        self.theme_change_active=True
        animate=self.native_ready and self.isVisible() and old.animations_enabled()
        # Capture the currently composited frame, including an interrupted fade.
        snapshot=self.grab() if animate else None
        self.clear_theme_transition(preserve_change=True)
        self.stop_transition()
        overlay=None
        if snapshot is not None:
            overlay=QLabel(self);overlay.setObjectName('theme_transition_overlay')
            overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            overlay.setStyleSheet('background: transparent; border: none; padding: 0;')
            overlay.setPixmap(snapshot);overlay.setGeometry(self.rect())
            effect=QGraphicsOpacityEffect(overlay);effect.setOpacity(1.);overlay.setGraphicsEffect(effect)
            self.theme_overlay=overlay;overlay.show();overlay.raise_()
        self.setUpdatesEnabled(False)
        try:
            self.dark=dark;self.apply_theme()
        finally:self.setUpdatesEnabled(True)
        old._save_ui_preferences(theme='dark' if dark else 'light')
        if overlay is None:
            self.theme_change_active=False
            return
        def reveal(*_):
            if getattr(self,'theme_overlay',None) is not overlay or getattr(self,'theme_transition',None) is not None:return
            animation=QPropertyAnimation(effect,b'opacity',self)
            animation.setDuration(280);animation.setStartValue(1.);animation.setEndValue(0.)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.finished.connect(self.clear_theme_transition)
            self.theme_transition=animation;animation.start()
        # Let the embedded workbench paint its new palette before revealing it.
        self.theme_reveal=reveal
        self.theme_serial=getattr(self,'theme_serial',0)+1
        self.webpage.runJavaScript('requestAnimationFrame(() => requestAnimationFrame(() => console.log('+json.dumps('__NV_NATIVE__'+json.dumps({'type':'theme-painted','serial':self.theme_serial}))+')))')
        QTimer.singleShot(180,reveal)

    def resizeEvent(self,event):
        self.clear_theme_transition()
        super().resizeEvent(event)

    def loaded(self,ok):
        if ok:self.sync_theme()
        else:self.enter_offline_after_failure('工作台页面加载失败')
    def sync_theme(self):
        # DSH owns the preference; never turn system into a persisted light/dark value.
        if not hasattr(self,'webpage'):return
        if self.pending_theme:self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('seqara-theme-set',{detail:"+json.dumps(self.pending_theme)+"}))")
        else:self.webpage.runJavaScript("window.dispatchEvent(new Event('seqara-theme-report'))")

    def apply_theme(self):
        # Build the inherited and native styles together, then polish once.
        self._pending_theme_css=super().styleSheet()
        self._building_theme=True
        try:self._apply_theme_styles()
        finally:
            self._building_theme=False
            super().setStyleSheet(self._pending_theme_css)

    def setStyleSheet(self,css):
        if getattr(self,'_building_theme',False):self._pending_theme_css=css
        else:super().setStyleSheet(css)

    def styleSheet(self):
        if getattr(self,'_building_theme',False):return self._pending_theme_css
        return super().styleSheet()

    def _apply_theme_styles(self):
        super().apply_theme()
        p=ui_design.TOKENS['dark' if self.dark else 'light']
        bg=p['canvas'];panel=p['panel'];line=p['line'];hover=p['hover'];primary=p['primary'];primary_text=p['onPrimary']
        self.setStyleSheet(self.styleSheet()+f'''
            QFrame#topbar {{ background: {panel}; }}
            QScrollArea#page_scroll, QWidget#page_root, QWidget#page_viewport {{ background: {bg}; }}
            QFrame#card, QFrame#card_group, QFrame#card_soft {{ background: {bg}; border: 1px solid {line}; border-radius: 10px; }}
            QPushButton#network_toggle, QPushButton#mode_toggle {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 0; min-width:30px; max-width:30px; min-height:30px; max-height:30px; }}
            QPushButton#network_toggle:hover, QPushButton#mode_toggle:hover {{ background: {hover}; }}
            QPushButton#network_toggle:focus, QPushButton#mode_toggle:focus, QPushButton:focus, QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['focus']}; }}
            QPushButton#secondary {{ background: {panel}; border: 1px solid {line}; font-weight: 500; }}
            QPushButton#secondary:hover {{ background: {hover}; }}
            QPushButton#secondary:pressed {{ background: {hover}; }}
            QPushButton#primary {{ background: {primary}; color: {primary_text}; }}
            QPushButton#primary:hover, QPushButton#primary:pressed {{ background: {primary}; }}
            QPushButton#primary:disabled {{ background: {line}; color: {'#9ba0aa' if self.dark else '#737780'}; }}
        ''')
        if hasattr(self,'stack'):
            pal=self.stack.palette();pal.setColor(QPalette.ColorRole.Window,QColor(bg))
            self.stack.setPalette(pal);self.stack.setAutoFillBackground(True)
            dashboard=self.stack.widget(0)
            dashboard.setStyleSheet(ui_design.harmonize(dashboard.styleSheet()))
        self.setStyleSheet(ui_design.harmonize(self.styleSheet())+ui_design.stylesheet(self.dark))
        if hasattr(self,'stack'):
            for index in range(7):ui_design.theme_scrolls(self.stack.widget(index),self.dark)
        for button in self.findChildren(QPushButton):
            if hasattr(button,'_fold_angle'):
                ui_design.fold_indicator(button,button._fold_angle)
            if getattr(button,'_stitch_icon_color_role',None)=='primary':
                color=ui_design.TOKENS['dark' if self.dark else 'light']['onPrimary']
                button.setIcon(old.mono_svg_icon(button._stitch_icon_name,16,color))
            ui_design.action_icon(button,self.dark)
        self.sync_theme();self.update_network_controls()
        if hasattr(self,'shell_page'):self.shell_page.runJavaScript('window.sqShell?.theme('+str(self.dark).lower()+')')

    def _show_settings_dialog(self):
        if self.web_ready:
            self.settings_requested=False
            self.publish_network_mode()
            self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('seqara-settings',{detail:{open:true}}))")
        else:
            self.settings_requested=True;self.status_label.setText('正在准备设置…')
            if self.process.state()==QProcess.ProcessState.NotRunning:self.startup_timer.start();self.process.start()

    def recover_runtime(self):
        if self.offline:return self.toggle_network()
        if self._background_work_active() or self.agent_busy or self.session_busy:
            old.stitch_msg_information(self,'任务正在运行','请先停止任务或等待完成，再恢复工作台。');return
        self.last_url='';self.web_ready=False;self.restart_requested=True;self.startup_timer.start();self.show_shell()
        if self.process.state()==QProcess.ProcessState.NotRunning:self.process.start()
        else:self.send({'type':'restart'})

    def publish_tasks(self):
        if not hasattr(self,'webpage'):return
        busy=list(getattr(self,'_nav_busy_count',[0]*7))[:7]
        self.webpage.runJavaScript("window.dispatchEvent(new CustomEvent('seqara-tasks',{detail:"+json.dumps({'native':busy,'agent':list(self.agent_tasks.values())[-30:]})+"}))")

    def nav_task_begin(self,index):
        super().nav_task_begin(index);self.publish_tasks()

    def nav_task_end(self,index):
        super().nav_task_end(index);self.publish_tasks()

    def open_new_window(self,request):
        url=request.requestedUrl()
        if navigation_target(url.toString(),self.last_url,self.offline)=='blocked' or url.scheme() not in ('http','https'):
            self.status_label.setText('此链接无法打开：离线模式或链接类型不受支持。');return
        if not old.QDesktopServices.openUrl(url):
            self.status_label.setText('无法打开外部链接，请检查系统默认浏览器设置。')

    def download(self,item):
        if not download_allowed(item.url().toString(),self.last_url,self.offline):
            self.status_label.setText('离线模式下无法下载远程文件。');item.cancel();return
        target,_=old.QFileDialog.getSaveFileName(self,'保存下载文件',item.downloadFileName())
        if target:
            def changed(state):
                if state.name=='DownloadCompleted':self.status_label.setText('已保存到：'+target)
                elif state.name=='DownloadInterrupted':self.status_label.setText('下载失败：'+item.interruptReasonString())
                elif state.name=='DownloadCancelled':self.status_label.setText('下载已取消。')
            item.stateChanged.connect(changed)
            item.setDownloadDirectory(str(Path(target).parent));item.setDownloadFileName(Path(target).name);item.accept()
        else:item.cancel()

    def closeEvent(self,event):
        if self.settings_dirty and self.web_ready and not self.stopping:
            self.webpage.runJavaScript("window.dispatchEvent(new Event('seqara-close-request'))");event.ignore();return
        if self.native_ready and not self.stopping and not self._background_work_active() and not self.agent_busy and not self.session_busy:
            self.stopping=True
            if self.process.state()==QProcess.ProcessState.NotRunning:return super().closeEvent(event)
            self.send({'type':'stop'});event.ignore();QTimer.singleShot(7000,self.force_close);return
        if self.agent_busy or self.session_busy:
            old.stitch_msg_information(self,'任务正在运行','请先停止会话任务或等待完成，再退出工作台。');event.ignore();return
        super().closeEvent(event)

    def force_close(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.kill()
        self.close()
    def service_finished(self,*args):
        if self.stopping:QTimer.singleShot(0,self.close)
        elif self.offline:
            self.network_transition=False;self.update_network_controls();self.status_label.setText(self.offline_reason or '离线模式：本地工具可用，联网功能已暂停。')
        else:self.enter_offline_after_failure('工作台服务已退出')
    def smoke(self):
        out=DATA/'native-smoke.json';out.parent.mkdir(parents=True,exist_ok=True)
        counts=[]
        for i in range(7):self.select_page(i);counts.append({'page':self._nav_titles[i],'widgets':len(self.stack.widget(i).findChildren(QWidget))})
        self.select_page(0)
        self.grab().save(str(DATA/'native-smoke.png'))
        out.write_text(json.dumps({'version':'0.8.0-demo.1','runtime':self.runtime_state.get('state'),'offline':self.offline,'sidebarWidth':self.sidebar_width,'recoveryBar':hasattr(self,'recovery'),'pages':counts,'rightDock':False},ensure_ascii=False,indent=2),encoding='utf8');self.close()

    def visual_qa(self):
        out=DATA/'visual';out.mkdir(parents=True,exist_ok=True)
        self.webpage.runJavaScript("JSON.stringify({text:document.body.innerText,tools:document.querySelectorAll('[data-native-tool]').length})",lambda value:(out/'page.json').write_text(value or '{}',encoding='utf8'))
        self.grab().save(str(out/'workspace-light.png'))
        self.select_page(4)
        QTimer.singleShot(800,lambda:self.grab().save(str(out/'invoice-light.png')))
        QTimer.singleShot(1200,self.toggle_theme)
        QTimer.singleShot(2000,lambda:self.grab().save(str(out/'invoice-dark.png')))
        QTimer.singleShot(2400,lambda:self.resize(900,620))
        QTimer.singleShot(3200,lambda:self.grab().save(str(out/'minimum-dark.png')))
        QTimer.singleShot(3600,self.close)

if __name__=='__main__':
    app=old.QApplication(sys.argv);app.setFont(old.ui_font('body'));window=Window();window.show();sys.exit(app.exec())
