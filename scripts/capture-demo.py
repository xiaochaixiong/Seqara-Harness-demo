"""Render actual application widgets using an isolated, synthetic profile."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
home=tempfile.TemporaryDirectory(prefix='seqara-public-screenshot-')
data=Path(home.name)
(data/'network.json').write_text(json.dumps({'offline':True}),'utf-8')
os.environ.update(NV_DESKTOP_ROOT=str(ROOT),NV_DESKTOP_DATA=str(data),QT_QPA_PLATFORM='offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu')
sys.path.insert(0,str(ROOT/'native'))
import desktop
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLineEdit

app=desktop.old.QApplication(sys.argv)
# The offscreen platform does not automatically enumerate Windows CJK fonts.
font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
if font_path.exists():QFontDatabase.addApplicationFont(str(font_path))
app.setFont(desktop.old.ui_font('body'))
window=desktop.Window()
window.resize(1440,900)
window.show()
out=ROOT/'docs/images'
out.mkdir(parents=True,exist_ok=True)

def capture(page,name,dark=False):
    window.select_page(page)
    # Present the untouched file chooser, not the developer's current directory.
    for field in window.stack.widget(page).findChildren(QLineEdit):
        if str(ROOT).lower() in field.text().lower():field.clear()
    if dark:window.toggle_theme()
    def save():
        if not window.grab().save(str(out/name)):raise RuntimeError('Screenshot save failed')
    QTimer.singleShot(700,save)

QTimer.singleShot(2000,lambda:capture(0,'dashboard-light.png'))
QTimer.singleShot(3500,lambda:capture(1,'data-tools-light.png'))
QTimer.singleShot(5000,lambda:capture(4,'invoice-dark.png',True))
QTimer.singleShot(6500,window.close)
app.exec()
# Qt WebEngine may hold its cache until process teardown. The temporary profile
# is outside the repository and contains only synthetic, offline state.
try:home.cleanup()
except PermissionError:pass
