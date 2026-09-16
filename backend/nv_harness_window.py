"""Embedded desktop view hosting the Harness application inside the main window."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QFileDialog, QWidget, QVBoxLayout, QLabel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView


class HarnessView(QWidget):
    def __init__(self, home: Path, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._active_url = ""
        self._disposed = False
        self._popups = []
        profile_root = home / "web-profile"
        profile_root.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("toolkit-harness", self)
        self.profile.setPersistentStoragePath(str(profile_root / "storage"))
        self.profile.setCachePath(str(profile_root / "cache"))
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(self.profile, self.view))
        layout.addWidget(self.view, 1)
        self.status = QLabel("正在加载工作台…")
        layout.addWidget(self.status)
        self.view.loadStarted.connect(lambda: self._status("正在加载工作台…"))
        self.view.loadFinished.connect(self._loaded)
        self.view.page().newWindowRequested.connect(self._new_window)
        self.profile.downloadRequested.connect(self._download)
        refresh = QAction("刷新", self)
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        refresh.triggered.connect(self.view.reload)
        self.addAction(refresh)

    def set_theme(self, dark: bool):
        self._desktop_theme = "dark" if dark else "light"
        self._apply_desktop_theme()

    def _apply_desktop_theme(self):
        if not self._active_url or self._disposed:
            return
        import json
        mode = json.dumps(getattr(self, "_desktop_theme", "light"))
        self.view.page().runJavaScript("window.__NV_THEME=" + mode + ";window.dispatchEvent(new Event('nv-theme'));")

    def open_workspace(self, url: str):
        # Reopening a hidden window must preserve an unfinished message and its session.
        if self._active_url != url:
            self._active_url = url
            self.view.setUrl(QUrl(url))
        self.show()

    def _status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _loaded(self, ok: bool):
        if not self._active_url:
            return
        if ok:
            self._apply_desktop_theme()
        self._status("" if ok else "加载失败。请确认工作台仍在运行，按 F5 重试。")

    def runtime_stopped(self):
        self._active_url = ""
        self.view.stop()
        self.view.setHtml("<html lang='zh-CN'><meta charset='utf-8'><body style='font:16px sans-serif;padding:40px'>"
                          "<h2>工作台已停止</h2><p>点击下方“启动工作台”继续。</p></body></html>")
        self._status("工作台已停止")
        for popup in self._popups:
            popup.close()

    def _new_window(self, request):
        popup = QMainWindow(self, Qt.WindowType.Window)
        popup.setWindowTitle("Agent 工作台")
        popup.resize(1000, 760)
        view = QWebEngineView(popup)
        page = QWebEnginePage(self.profile, view)
        view.setPage(page)
        popup.setCentralWidget(view)
        page.windowCloseRequested.connect(popup.close)
        page.newWindowRequested.connect(self._new_window)
        self._popups.append(popup)
        request.openIn(page)
        popup.show()

    def _download(self, download):
        suggested = Path(download.downloadDirectory()) / download.downloadFileName()
        filename, _ = QFileDialog.getSaveFileName(self, "保存工作台文件", str(suggested))
        if not filename:
            download.cancel()
            return
        target = Path(filename)
        download.setDownloadDirectory(str(target.parent))
        download.setDownloadFileName(target.name)
        download.accept()

    def closeEvent(self, event):
        for popup in self._popups:
            popup.close()
        event.accept()

    def dispose(self):
        """Delete web pages before their profile; called during desktop teardown."""
        if self._disposed:
            return
        self._disposed = True
        from shiboken6 import delete
        self.close()
        for popup in self._popups:
            delete(popup.centralWidget().page())
        self._popups.clear()
        self.view.stop()
        delete(self.view.page())
        delete(self.profile)
