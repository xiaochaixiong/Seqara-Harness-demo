"""One window outline and title-bar contract for all owned Qt windows."""
from PySide6.QtCore import QObject,QEvent,Qt,QTimer,QRectF
from PySide6.QtGui import QPainterPath,QRegion
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QComboBox,QAbstractSpinBox,QAbstractScrollArea
import ui_design

def fit_initial_window(window):
    """Keep the initial window and its controls inside the screen's logical work area."""
    screen=window.screen()
    if screen is None:return
    available=screen.availableGeometry().adjusted(8,8,-8,-8)
    window.setMinimumSize(min(window.minimumWidth(),available.width()),min(window.minimumHeight(),available.height()))
    window.resize(min(window.width(),available.width()),min(window.height(),available.height()))
    window.move(available.x()+(available.width()-window.width())//2,
                available.y()+(available.height()-window.height())//2)

class WindowStyleFilter(QObject):
    def __init__(self,parent):
        super().__init__(parent);self.busy=False

    def eventFilter(self,obj,event):
        if self.busy or not isinstance(obj,QWidget):return False
        kind=event.type()
        if kind == QEvent.Type.Wheel and (
            isinstance(obj,QComboBox) and not obj.view().isVisible()
            or isinstance(obj,QAbstractSpinBox) and not obj.hasFocus()
        ):
            # A wheel gesture over a closed selector belongs to its scrolling page.
            parent=obj.parentWidget()
            while parent is not None and not isinstance(parent,QAbstractScrollArea):
                parent=parent.parentWidget()
            if parent is not None:
                delta=event.angleDelta().y()
                bar=parent.verticalScrollBar()
                bar.setValue(bar.value()-round(delta/120*bar.singleStep()*QApplication.wheelScrollLines()))
            event.accept()
            return True
        if kind in (QEvent.Type.Polish,QEvent.Type.StyleChange):
            css=obj.styleSheet()
            normalized=ui_design.harmonize(css)
            if css!=normalized:
                self.busy=True
                try:obj.setStyleSheet(normalized)
                finally:self.busy=False
        if obj.isWindow() and obj.windowFlags() & Qt.WindowType.FramelessWindowHint:
            if kind in (QEvent.Type.Show,QEvent.Type.Resize,QEvent.Type.WindowStateChange):
                if obj.isMaximized() or obj.isFullScreen():obj.clearMask()
                else:
                    path=QPainterPath();radius=ui_design.TOKENS['layout']['radius']
                    path.addRoundedRect(QRectF(obj.rect()),radius,radius)
                    obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
            if kind in (QEvent.Type.WindowActivate,QEvent.Type.WindowDeactivate):
                for button in obj.findChildren(QWidget):
                    if button.objectName().startswith('traffic_'):button.update()
                if hasattr(obj,'webpage'):
                    obj.webpage.runJavaScript("document.body?.toggleAttribute('data-seqara-window-inactive',"+str(kind==QEvent.Type.WindowDeactivate).lower()+")")
        return False

def install():
    app=QApplication.instance()
    if not hasattr(app,'_seqara_window_style'):
        app._seqara_window_style=WindowStyleFilter(app)
        app.installEventFilter(app._seqara_window_style)
