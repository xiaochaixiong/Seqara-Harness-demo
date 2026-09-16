import html
import json
import math
import os
import re
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

# Frozen releases use the same executable for isolated business-tool workers.
# Dispatch before Qt, configuration seeding, or any window is initialized.
if __name__ == "__main__" and "--harness-tool-worker" in sys.argv:
    import nv_harness_tools
    raise SystemExit(nv_harness_tools.main(sys.argv[sys.argv.index("--harness-tool-worker") + 1:]))


def open_local_folder(owner, target) -> bool:
    """Validate and report OS failures for every local folder button."""
    try:
        if not str(target).strip():
            raise ValueError('请先选择文件夹。')
        folder = Path(target).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError('文件夹不存在或已被移动，请重新选择。')
        if sys.platform == 'win32':
            os.startfile(str(folder))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            raise OSError('系统文件管理器未能打开该文件夹。')
        return True
    except (OSError, ValueError) as exc:
        stitch_msg_warning(owner, '无法打开文件夹', str(exc))
        return False


def _resolve_app_dirs() -> tuple[Path, Path]:
    """(资源根目录, 用户数据目录)。

    开发：均为脚本所在目录。PyInstaller **单文件**：资源在临时解压目录 ``sys._MEIPASS``，
    配置/数据必须与 ``sys.executable`` 同目录，否则重启后丢失。
    """
    native_data = os.environ.get("NV_NATIVE_DATA")
    if native_data:
        resource = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        data = Path(native_data).resolve()
        data.mkdir(parents=True, exist_ok=True)
        return resource, data
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        resource = Path(meipass).resolve() if meipass else Path(sys.executable).resolve().parent
        data = Path(sys.executable).resolve().parent
        return resource, data
    root = Path(__file__).resolve().parent
    data = Path(os.environ.get('APPDATA', Path.home())) / 'SeqaraHarnessDemo' / 'native'
    data.mkdir(parents=True, exist_ok=True)
    return root, data


_RESOURCE_DIR, _DATA_DIR = _resolve_app_dirs()
if str(_RESOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(_RESOURCE_DIR))


def _seed_data_from_bundle() -> None:
    """单文件首次运行：把打包内的默认 json 复制到 exe 同目录（若目标尚不存在）。"""
    if not getattr(sys, "frozen", False):
        return
    for name in (
        "api_config.json",
        "ui_config.json",
        "invoice_classify_defaults.json",
    ):
        dst = _DATA_DIR / name
        if dst.is_file():
            continue
        src = _RESOURCE_DIR / name
        if src.is_file():
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass


_seed_data_from_bundle()


def _load_ui_preferences() -> dict:
    path = _DATA_DIR / "ui_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_ui_preferences(**changes: object) -> None:
    path = _DATA_DIR / "ui_config.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = _load_ui_preferences()
    data.update(changes)
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _pyside6_preload_dll_paths() -> None:
    """Windows：将 PySide6 根目录及常见 QML 插件目录加入 DLL 搜索路径。

    加载 ``qml/QtQuick/qtquick2plugin.dll`` 时若未包含含 ``Qt6Quick.dll`` 等的路径，
    会报「找不到指定的模块」（实为依赖 DLL 未解析）。须在首次 ``from PySide6.Qt*`` 之前调用。
    """
    if sys.platform != "win32":
        return
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return
    root = Path(PySide6.__file__).resolve().parent
    candidates = [
        root,
        root / "qml",
        root / "qml" / "QtQuick",
        root / "qml" / "QtQml",
    ]
    seen: set[str] = set()
    for d in candidates:
        if not d.is_dir():
            continue
        s = str(d)
        if s in seen:
            continue
        seen.add(s)
        try:
            os.add_dll_directory(s)
        except (OSError, FileNotFoundError):
            pass


_FOLD_QML_FALLBACK_LOGGED = False

# 与 MainWindow.stack.addWidget / 侧栏 items 枚举顺序一致（后台任务左侧闪烁条按此索引对齐）
NAV_PAGE_DASHBOARD = 0
NAV_PAGE_ACTIVITY_MATCH = 1
NAV_PAGE_PROJECT_STAT = 2
NAV_PAGE_BRIEFING = 3
NAV_PAGE_CLASSIFY = 4
NAV_PAGE_ACTIVITY_PLAN = 5
NAV_PAGE_AUTO_PRINT = 6
NAV_PAGE_HARNESS = 7

import nv_activity_plan_batch as nv_act_batch
import nv_activity_plan_core as nv_plan
import nv_activity_plan_docx as nv_ap_docx
import nv_app_defaults as nv_ad
import nv_briefing_core as nv_brief
import nv_business_core as nv_biz
import nv_classify_core as nv_cls
import nv_cover_fill_core as nv_cf
import nv_auto_print_core as nv_aprint
import nv_deepseek_core as nv_ds

nv_ds.set_deepseek_config_dir(str(_DATA_DIR))
nv_cls.set_classify_config_dir(str(_DATA_DIR))
nv_cf.set_cover_fill_config_dir(str(_DATA_DIR))
nv_ad.set_bundle_dir(str(_DATA_DIR))

_pyside6_preload_dll_paths()
try:
    from PySide6.QtCore import (
        QEvent,
        QObject,
        QEasingCurve,
        QPoint,
        QPointF,
        Property,
        QPropertyAnimation,
        QRect,
        QRectF,
        QSize,
        QSequentialAnimationGroup,
        Qt,
        QThread,
        QTimer,
        QUrl,
        QVariantAnimation,
        Signal,
        Slot,
    )
    from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
    from PySide6.QtGui import (
        QColor,
        QDesktopServices,
        QDoubleValidator,
        QFont,
        QFontMetrics,
        QGuiApplication,
        QIcon,
        QIntValidator,
        QKeySequence,
        QMouseEvent,
        QPainter,
        QPen,
        QPixmap,
        QPolygonF,
        QRegion,
        QShortcut,
        QTextCursor,
    )
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsDropShadowEffect,
        QGraphicsOpacityEffect,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QAbstractButton,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTabBar,
        QTextBrowser,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise RuntimeError(
        "缺少 PySide6 图形界面组件。请使用完整发布包，或在开发环境中预先安装项目依赖。"
    ) from exc

import nv_dashboard_widgets as nv_dashboard_ui


TOKENS = {
    "radius": {"sm": 8, "md": 10, "lg": 14, "xl": 16},
    # 8pt 栅格：间距取 8 的倍数，减少「随手写」边距
    "space": {"xs": 8, "sm": 8, "md": 16, "lg": 16, "xl": 24, "xxl": 32},
    "layout": {"canvas_max_width": 1320},
    "font": {
        "display": 15,
        "headline": 10,
        "title": 11,
        "body": 10,
        "label": 9,
        "caption": 9,
    },
    "motion": {
        "micro": 120,
        "fast": 150,
        "base": 200,
        "slow": 260,
        # 抽屉：略拉长 + 分向缓动，中间帧更多（配合 QAbstractAnimation 更新间隔）
        "fold_expand": 260,
        "fold_collapse": 210,
        "fold": 260,
        "fold_fade": 160,
        "button_hover": 165,
    },
    "interaction": {
        "footer_button_min_h": 42,
        "path_browse_min_h": 40,
        "path_browse_w": 88,
        "line_edit_min_h": 38,
        "icon_footer": 18,
        "icon_path_button": 16,
        "icon_nav": 16,
        "form_row_spacing": 16,
    },
}


_ANIMATIONS_ENABLED: Optional[bool] = None


def animations_enabled() -> bool:
    """Respect the app override and the Windows client-animation accessibility setting."""
    global _ANIMATIONS_ENABLED
    if _ANIMATIONS_ENABLED is not None:
        return _ANIMATIONS_ENABLED
    override = os.environ.get("NV_TOOLKIT_REDUCE_MOTION", "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        _ANIMATIONS_ENABLED = False
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            enabled = ctypes.c_int(1)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x1042, 0, ctypes.byref(enabled), 0
            )
            if ok:
                _ANIMATIONS_ENABLED = bool(enabled.value)
                return _ANIMATIONS_ENABLED
        except (AttributeError, OSError):
            pass
    _ANIMATIONS_ENABLED = True
    return True


def palette(dark: bool) -> dict:
    return {
        "surface": "#0E1116" if dark else "#f9f9f9",
        "surface_low": "#151A21" if dark else "#f3f3f4",
        "surface_lowest": "#0f141c" if dark else "#ffffff",
        "surface_high": "#23262B" if dark else "#e9e9ea",
        "text": "#E5E7EB" if dark else "#1a1c1c",
        "muted": "#B8BEC8" if dark else "#3F4146",
        "outline_variant": "#30363d" if dark else "#c6c6c6",
        "primary": "#111827" if not dark else "#2563eb",
        "primary_container": "#374151" if not dark else "#1d4ed8",
        "focus_accent": "#2563eb" if not dark else "#60a5fa",
        "success": "#15803d" if not dark else "#4ade80",
        "danger": "#b91c1c" if not dark else "#f87171",
        "warning": "#a16207" if not dark else "#fbbf24",
    }


def dashboard_palette(dark: bool) -> dict:
    """把应用设计令牌映射为独立看板组件使用的语义色。"""
    source = palette(dark)
    return {
        "canvas": source["surface"],
        "panel": source["surface_lowest"],
        "panel_alt": source["surface_low"],
        "surface_high": source["surface_high"],
        "text": source["text"],
        "muted": source["muted"],
        "outline": source["outline_variant"],
        "primary": source["primary"],
        "focus": source["focus_accent"],
        "on_focus": "#0E1116" if dark else "#ffffff",
        "success": source["success"],
        "warning": source["warning"],
        "danger": source["danger"],
    }


def ui_font(role: str, weight: int = QFont.Weight.Normal, letter_spacing: float = 0.0) -> QFont:
    """字阶：display / headline / title / body；辅助用 label、caption（caption 建议 Regular）。"""
    size = TOKENS["font"].get(role, TOKENS["font"]["body"])
    f = QFont("Microsoft YaHei UI", size, weight)
    f.setFamilies(
        [
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "PingFang SC",
            "Noto Sans SC",
            "Noto Sans CJK SC",
        ]
    )
    f.setStyleStrategy(QFont.StyleStrategy.PreferDefault)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    if role in ("display", "headline", "title", "label", "caption"):
        letter_spacing = 0.0
    if abs(letter_spacing) > 0.0001:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + letter_spacing * 100)
    return f


class _StitchFoldQmlEngineHolder:
    """全应用共用一个 QQmlEngine，避免每个折叠区各启引擎。"""

    _engine: Optional[QQmlEngine] = None

    @classmethod
    def instance(cls) -> QQmlEngine:
        if cls._engine is None:
            cls._engine = QQmlEngine()
        return cls._engine


class FoldClipHeightBridge(QObject):
    """暴露 clipHeight 给 QML NumberAnimation；由控制器写入裁剪高度（动画中用 fixed，避免与 sizeHint 拉扯）。"""

    clip_height_changed = Signal()

    def __init__(self, ctrl: "StitchFoldController", stitch_clip: QWidget) -> None:
        super().__init__(stitch_clip)
        self._ctrl = ctrl
        self._clip = stitch_clip
        self._v = 0.0

    def _get_h(self) -> float:
        return self._v

    def _set_h(self, value: float) -> None:
        self._v = float(value)
        hi = max(0, int(round(self._v)))
        self._ctrl._apply_clip_pixel_height(hi)
        self.clip_height_changed.emit()

    clipHeight = Property(float, _get_h, _set_h, notify=clip_height_changed)


class FoldQmlCtl(QObject):
    """QML Connections 监听，触发展开 / 收起 / 停止（camelCase 信号名便于 onXxx 处理器）。"""

    playExpand = Signal(float)
    playCollapse = Signal(float)
    stopAll = Signal()


class FoldQmlAnimDriver(QObject):
    def __init__(self, ctrl: "StitchFoldController") -> None:
        super().__init__()
        self._c = ctrl

    @Slot()
    def expandDone(self) -> None:
        self._c._on_height_anim_finished()

    @Slot()
    def collapseDone(self) -> None:
        self._c._on_height_anim_finished()


class _FoldClipHost(QWidget):
    """无 QScrollArea：不用滚动条/视口，避免高度动画时滚动区域重算带来的晃动。

    inner 用手动几何铺满宽度、保持自然高度，由本控件当前高度 + setMask 做裁剪与命中区域。
    """

    def __init__(self, controller: "StitchFoldController") -> None:
        super().__init__()
        self._fc = controller
        self.setObjectName("stitch_fold_clip")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        ih = max(self._fc._inner.sizeHint().height(), self._fc._inner.height(), 1)
        return QSize(super().sizeHint().width(), ih)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 高度随折叠动画每帧变化时勿反复 activate 内层布局，否则易抖动；仅宽度变时重算 inner。
        if event.oldSize().width() != self.width():
            self._fc._sync_inner_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.width() > 0:
            self._fc._sync_inner_geometry()


class StitchFoldController(QObject):
    """One reversible Qt animation drives drawer height and indicator rotation."""

    def __init__(
        self,
        inner: QWidget,
        toggle: QPushButton,
        text_collapsed: str,
        text_expanded: str,
        *,
        duration_ms: Optional[int] = None,
    ):
        super().__init__(inner)
        self._inner = inner
        self._toggle = toggle
        self._toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._toggle.setAccessibleName(text_collapsed.lstrip("+- "))
        self._tc = text_collapsed.lstrip("+- ")
        self._te = text_expanded.lstrip("+- ")
        from ui_design import fold_indicator
        self._indicator = QVariantAnimation(self)
        self._indicator.setDuration(160 if animations_enabled() else 1)
        self._indicator.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._indicator.valueChanged.connect(lambda angle: fold_indicator(self._toggle,angle))
        fold_indicator(self._toggle,0)
        if duration_ms is not None:
            d = int(duration_ms)
            self._dur_expand = d
            self._dur_collapse = d
        else:
            self._dur_expand = int(TOKENS["motion"]["fold_expand"])
            self._dur_collapse = int(TOKENS["motion"]["fold_collapse"])
        if not animations_enabled():
            self._dur_expand = 1
            self._dur_collapse = 1
        self._clip = _FoldClipHost(self)
        inner.setParent(self._clip)
        inner.setGeometry(0, 0, 1, 1)
        inner.raise_()
        self._clip_anim_active = False
        self._use_qml = False
        self._bridge: Optional[FoldClipHeightBridge] = None
        self._qctl: Optional[FoldQmlCtl] = None
        self._driver: Optional[FoldQmlAnimDriver] = None
        self._qml_root: Optional[QObject] = None
        self._h_anim: Optional[QVariantAnimation] = None
        # One Qt clock owns both clipping and indicator rotation.
        self._h_anim = QVariantAnimation(self)
        self._h_anim.valueChanged.connect(self._apply_fold_clip_height)
        self._h_anim.finished.connect(self._on_height_anim_finished)
        self._busy = False
        self._collapsing = False

    def _load_fold_qml_or_raise(self) -> None:
        assert self._bridge is not None and self._qctl is not None and self._driver is not None
        qml_path = _RESOURCE_DIR / "stitch_fold_anim.qml"
        if not qml_path.is_file():
            raise FileNotFoundError(f"缺少 QML 动画文件: {qml_path}")
        engine = _StitchFoldQmlEngineHolder.instance()
        comp = QQmlComponent(engine)
        comp.loadUrl(QUrl.fromLocalFile(str(qml_path.resolve())))
        if comp.isError():
            raise RuntimeError(comp.errorString())
        ctx = QQmlContext(engine.rootContext())
        ctx.setContextProperty("foldBridge", self._bridge)
        ctx.setContextProperty("foldCtl", self._qctl)
        ctx.setContextProperty("foldDriver", self._driver)
        ctx.setContextProperty("foldExpandMs", self._dur_expand)
        ctx.setContextProperty("foldCollapseMs", self._dur_collapse)
        root = comp.create(ctx)
        if root is None:
            raise RuntimeError(comp.errorString())
        self._qml_root = root

    def _apply_fold_clip_height(self, value: object) -> None:
        h = max(0, int(round(float(value))))
        self._apply_clip_pixel_height(h)
        from ui_design import fold_indicator
        fold_indicator(self._toggle,90.0*h/max(1,getattr(self,'_full_height',h)))

    def _apply_clip_pixel_height(self, h: int) -> None:
        """折叠裁剪高度：动画中用 fixed，静止态用 max（与 apply_initial / 结束态一致）。"""
        h = max(0, int(h))
        if self._clip_anim_active:
            self._clip.setFixedHeight(h)
        else:
            self._clip.setMinimumHeight(0)
            self._clip.setMaximumHeight(h)
        self._clip.updateGeometry()

    def clip_host(self) -> QWidget:
        return self._clip

    def _return_focus_after_drawer_open(self) -> None:
        """展开/收起后：不把焦点留在 inner 内；去掉行内全选高亮（收起时常见残留）。"""
        app = QApplication.instance()
        if app is None:
            return
        for _ in range(4):
            fw = app.focusWidget()
            if fw is None or not (fw is self._inner or self._inner.isAncestorOf(fw)):
                break
            fw.clearFocus()
        for le in self._inner.findChildren(QLineEdit):
            le.deselect()
        for te in self._inner.findChildren(QTextEdit):
            cur = te.textCursor()
            if cur.hasSelection():
                cur.clearSelection()
                te.setTextCursor(cur)
        self._toggle.setFocus(Qt.FocusReason.OtherFocusReason)

    def _schedule_defocus_inner(self) -> None:
        QTimer.singleShot(0, self._return_focus_after_drawer_open)
        QTimer.singleShot(90, self._return_focus_after_drawer_open)

    def _sync_inner_geometry(self) -> None:
        w = max(self._clip.width(), 1)
        self._inner.updateGeometry()
        lay = self._inner.layout()
        if lay is not None:
            lay.activate()
        h = max(self._inner.sizeHint().height(), 1)
        if self._inner.x() != 0 or self._inner.y() != 0 or self._inner.width() != w or self._inner.height() != h:
            self._inner.setGeometry(0, 0, w, h)
        if self._toggle.isChecked() and not self._clip_anim_active:
            self._clip.setFixedHeight(h)

    def _target_clip_height(self) -> int:
        self._sync_inner_geometry()
        return max(self._inner.height(), 1)

    def apply_initial_collapsed(self) -> None:
        self._clip_anim_active = False
        if self._use_qml:
            assert self._qctl is not None and self._bridge is not None
            self._qctl.stopAll.emit()
            self._bridge.clipHeight = 0.0
        elif self._h_anim is not None:
            self._h_anim.stop()
        self._inner.setVisible(True)
        self._inner.setMinimumHeight(0)
        self._inner.setMaximumHeight(16777215)
        self._clip.setMinimumHeight(0)
        self._clip.setMaximumHeight(0)
        QTimer.singleShot(0, self._sync_inner_geometry)
        self._toggle.blockSignals(True)
        self._toggle.setChecked(False)
        self._toggle.blockSignals(False)
        self._toggle.setText(self._tc)
        from ui_design import fold_indicator
        self._indicator.stop();fold_indicator(self._toggle,0)

    def on_toggled(self, expanded: bool) -> None:
        self._h_anim.stop();self._indicator.stop()
        start_h = self._clip.height()
        self._clip_anim_active = True
        self._busy = True;self._collapsing = not expanded
        self._toggle.setText(self._te if expanded else self._tc)
        self._inner.show();self._sync_inner_geometry()
        self._full_height = self._target_clip_height()
        target = self._full_height if expanded else 0
        # Keep current height on reversal and retain the final constraint.
        self._clip.setFixedHeight(start_h)
        self._h_anim.setDuration(220 if animations_enabled() else 1)
        self._h_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._h_anim.setStartValue(float(start_h));self._h_anim.setEndValue(float(target))
        if not expanded:
            fw=QApplication.focusWidget()
            if fw is not None and self._inner.isAncestorOf(fw):fw.clearFocus()
        self._h_anim.start()

    def _on_height_anim_finished(self) -> None:
        self._clip.setFixedHeight(0 if self._collapsing else self._full_height)
        self._clip_anim_active = False
        self._busy = False



def textedit_append_autoscroll(edit: QTextEdit, text: str) -> None:
    edit.append(text)
    cur = edit.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    edit.setTextCursor(cur)
    edit.ensureCursorVisible()


def _stitch_msg_resolve_dark(parent: Optional[QWidget]) -> bool:
    w = parent
    while w is not None:
        if w.__class__.__name__ == "MainWindow":
            return bool(getattr(w, "dark", False))
        w = w.parentWidget()
    return False


def _stitch_msg_rich_text(text: str) -> str:
    """保留作者分段，让 Qt 按真实可用宽度排中文正文。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    escaped = html.escape(raw).replace("\n", "<br>")
    return f'<div style="line-height: 145%; white-space: pre-wrap;">{escaped}</div>'


def _stitch_msg_body_panel(text: str, title: str) -> QTextBrowser:
    body = QTextBrowser()
    body.setObjectName("stitch_msg_body")
    body.setFont(ui_font("body", QFont.Weight.Normal))
    body.setFrameShape(QFrame.Shape.NoFrame)
    body.setOpenExternalLinks(False)
    body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    body.setAccessibleName(f"{title}内容")
    body.setAccessibleDescription(text)
    longest = max((line for line in (text or "").splitlines()), key=len, default="")
    content_width = max(460, min(620, QFontMetrics(body.font()).horizontalAdvance(longest) + 8))
    body.setFixedWidth(content_width)
    body.document().setDocumentMargin(0)
    body.document().setTextWidth(content_width - 4)
    body.setHtml(_stitch_msg_rich_text(text))
    content_height = math.ceil(body.document().size().height()) + 4
    body.setFixedHeight(max(44, min(360, content_height)))
    body.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return body


class TrafficLightButton(QPushButton):
    """Fixed hit area and a centered circular glyph, independent of dialog QSS."""

    def __init__(self, object_name: str, tooltip: str, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setFixedSize(28, 28)
        self.setStyleSheet('QPushButton { min-width:28px;max-width:28px;min-height:28px;max-height:28px;padding:0;margin:0;border:0;background:transparent; } QPushButton:hover,QPushButton:pressed,QPushButton:focus { background:transparent;border:0; }')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(tooltip)
        self.setToolTip(tooltip)
        self.clicked.connect(on_click)


    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen
        from PySide6.QtCore import QRectF
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors={'traffic_close':'#ff5f57','traffic_minimize':'#febc2e','traffic_zoom':'#28c840'}
        color=colors.get(self.objectName(),'#a8a8ad') if self.window().isActiveWindow() else '#b8b8bd'
        painter.translate(self.width()/2-14,self.height()/2-14)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(color));painter.drawEllipse(QRectF(8,8,12,12))
        if self.underMouse() and self.window().isActiveWindow():
            painter.setPen(QPen(QColor('#482820'),1.2))
            if self.objectName()=='traffic_close':painter.drawLine(12,12,16,16);painter.drawLine(12,16,16,12)
            elif self.objectName()=='traffic_minimize':painter.drawLine(11,14,17,14)
            else:painter.drawLine(11,16,16,11);painter.drawLine(12,11,16,11);painter.drawLine(16,11,16,15)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#5870c7'),1.5));painter.drawEllipse(QRectF(4,4,20,20))


class _DialogChromeEventFilter(QObject):
    """顶栏拖拽移动无边框对话框（与 MainWindow 顶栏逻辑一致）。"""

    def __init__(self, dlg: QDialog, topbar: QFrame) -> None:
        super().__init__(dlg)
        self._dlg = dlg
        self._topbar = topbar
        self._drag_offset: Optional[QPoint] = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._topbar:
            return False
        et = event.type()
        if et == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                child = self._topbar.childAt(pos)
                if child is not None and isinstance(child, QAbstractButton):
                    self._drag_offset = None
                    return False
                self._drag_offset = event.globalPosition().toPoint() - self._dlg.frameGeometry().topLeft()
            return False
        if et == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                self._drag_offset = None
            elif self._drag_offset is not None:
                self._dlg.move(event.globalPosition().toPoint() - self._drag_offset)
            return False
        if et == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            self._drag_offset = None
            return False
        return False


def _stitch_dialog_change_event(dlg: QDialog, event: QEvent) -> None:
    if event.type() == QEvent.Type.WindowStateChange:
        tw = getattr(dlg, "_stitch_traffic_zoom", None)
        if tw is not None:
            tw.setToolTip("还原窗口" if dlg.isMaximized() else "最大化")


def stitch_dialog_prepend_chrome_topbar(
    dlg: QDialog,
    root_layout: QVBoxLayout,
    title: str,
    *,
    on_traffic_close: Optional[Callable[[], None]] = None,
) -> None:
    """在根垂直布局顶部插入可拖拽顶栏 + 三圆点（最小化/最大化/关闭）。根布局建议 contentsMargins 全 0。"""
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.FramelessWindowHint)
    close_fn = on_traffic_close if on_traffic_close is not None else dlg.close
    topbar = QFrame()
    topbar.setObjectName("topbar")
    top_l = QHBoxLayout(topbar)
    top_l.setContentsMargins(12, 6, 12, 6)
    top_l.setSpacing(12)
    topbar.setFixedHeight(44)
    menu = QLabel(title)
    menu.setObjectName("topbar_menu")
    menu.setProperty("dialogTitle", True)
    menu.setFont(ui_font("title", QFont.Weight.DemiBold))
    top_l.addWidget(menu, 1)
    traffic_wrap = QWidget()
    traffic_wrap.setObjectName("traffic_lights_wrap")
    tw = QHBoxLayout(traffic_wrap)
    tw.setContentsMargins(0, 0, 0, 0)
    tw.setSpacing(0)

    def _toggle_max() -> None:
        if dlg.isMaximized():
            dlg.showNormal()
        else:
            dlg.showMaximized()

    traffic_min = TrafficLightButton("traffic_minimize", "最小化", dlg.showMinimized)
    traffic_zoom = TrafficLightButton("traffic_zoom", "最大化", _toggle_max)
    traffic_close = TrafficLightButton("traffic_close", "关闭窗口", close_fn)
    tw.addWidget(traffic_min)
    tw.addWidget(traffic_zoom)
    tw.addWidget(traffic_close)
    top_l.addWidget(traffic_wrap)
    # A shadow on the entire title bar also rasterizes its small control glyphs.
    filt = _DialogChromeEventFilter(dlg, topbar)
    topbar.installEventFilter(filt)
    dlg._stitch_chrome_filter = filt  # type: ignore[attr-defined]
    dlg._stitch_traffic_zoom = traffic_zoom  # type: ignore[attr-defined]
    root_layout.insertWidget(0, topbar)


def apply_stitch_msg_shell_style(
    shell: QDialog, dark: bool, *, severity: str = "information", choice_buttons: bool = False
) -> None:
    """信息/警告/错误弹窗外壳样式（与原先 QMessageBox 版一致）。choice_buttons 为 True 时增加「否」按钮样式。"""
    p = palette(dark)
    border = "rgba(255,255,255,0.14)" if dark else "rgba(0,0,0,0.10)"
    hairline = "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.08)"
    if severity == "critical":
        default_block = f"""
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default {{
            background: {p["danger"]};
            color: #ffffff;
            border: 1px solid {p["danger"]};
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default:hover {{
            background: #b91c1c;
            border: 1px solid #b91c1c;
        }}
        """
    elif severity == "warning":
        default_block = f"""
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default {{
            background: {p["surface_high"]};
            color: {p["text"]};
            border: 1px solid {p["warning"]};
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default:hover {{
            background: {p["surface_low"]};
        }}
        """
    else:
        default_block = f"""
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default {{
            background: {p["surface_high"]};
            color: {p["text"]};
            border: 1px solid {hairline};
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:default:hover {{
            background: {p["surface_low"]};
            border: 1px solid {p["outline_variant"]};
        }}
        """

    cancel_block = ""
    if choice_buttons:
        cancel_block = f"""
        QDialog#stitch_msg_shell QPushButton#stitch_msg_cancel {{
            background: {p["surface_low"]};
            color: {p["text"]};
            border: 1px solid {border};
            border-radius: 8px;
            min-height: 34px;
            min-width: 72px;
            padding: 0px 16px;
            font-weight: 600;
            font-size: 9pt;
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_cancel:hover {{
            background: {p["surface_high"]};
            border: 1px solid {p["outline_variant"]};
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_cancel:focus {{
            border: 2px solid {p["focus_accent"]};
        }}
        """

    shell.setStyleSheet(
        f"""
        QDialog#stitch_msg_shell {{
            background: {p["surface_lowest"]};
            border: 1px solid {border};
            border-radius: 12px;
            min-width: 508px;
        }}
        QDialog#stitch_msg_shell QLabel#topbar_menu {{
            color: {p["text"]};
            font-size: 11pt;
            font-weight: 600;
            letter-spacing: 0.15px;
        }}
        QDialog#stitch_msg_shell QTextBrowser#stitch_msg_body {{
            color: {p["text"]};
            background: transparent;
            border: none;
            font-size: 10pt;
            font-weight: 400;
            padding: 0px;
        }}
        QDialog#stitch_msg_shell QTextBrowser#stitch_msg_body QScrollBar:vertical {{
            width: 6px;
            background: transparent;
            margin-left: 2px;
        }}
        QDialog#stitch_msg_shell QTextBrowser#stitch_msg_body QScrollBar::handle:vertical {{
            background: {p["outline_variant"]};
            border-radius: 3px;
            min-height: 24px;
        }}
        QDialog#stitch_msg_shell QTextBrowser#stitch_msg_body QScrollBar::add-line:vertical,
        QDialog#stitch_msg_shell QTextBrowser#stitch_msg_body QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok {{
            background: {p["surface_low"]};
            color: {p["text"]};
            border: 1px solid {border};
            border-radius: 8px;
            min-height: 34px;
            min-width: 72px;
            padding: 0px 16px;
            font-weight: 600;
            font-size: 9pt;
        }}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:!default:hover {{
            background: {p["surface_high"]};
            border: 1px solid {p["outline_variant"]};
        }}
        {default_block}
        QDialog#stitch_msg_shell QPushButton#stitch_msg_ok:focus {{
            border: 2px solid {p["focus_accent"]};
        }}
        {cancel_block}
        """
    )


class _StitchMsgShellDialog(QDialog):
    """带顶栏三圆点的信息弹窗，同步最大化按钮提示。"""

    def changeEvent(self, event: QEvent) -> None:
        _stitch_dialog_change_event(self, event)
        super().changeEvent(event)


def _stitch_msg_configure_and_show(
    parent: Optional[QWidget],
    title: str,
    text: str,
    *,
    severity: str,
    ok_text: str,
) -> None:
    dark = _stitch_msg_resolve_dark(parent)
    shell = _StitchMsgShellDialog(parent)
    shell.setObjectName("stitch_msg_shell")
    shell.setWindowTitle(title)
    shell.setModal(True)
    outer = QVBoxLayout(shell)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    stitch_dialog_prepend_chrome_topbar(shell, outer, title, on_traffic_close=shell.accept)
    body_wrap = QWidget()
    bw = QVBoxLayout(body_wrap)
    bw.setContentsMargins(24, 20, 24, 18)
    bw.setSpacing(16)
    body_panel = _stitch_msg_body_panel(text, title)
    bw.addWidget(body_panel)
    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.addStretch(1)
    ok_btn = QPushButton(ok_text)
    ok_btn.setObjectName("stitch_msg_ok")
    ok_btn.setDefault(True)
    ok_btn.setAutoDefault(True)
    ok_btn.clicked.connect(shell.accept)
    btn_row.addWidget(ok_btn)
    bw.addLayout(btn_row)
    outer.addWidget(body_wrap, 1)
    apply_stitch_msg_shell_style(shell, dark, severity=severity)
    shell.setMinimumWidth(508)
    shell.setMaximumWidth(668)
    shell.exec()


def stitch_msg_information(parent: Optional[QWidget], title: str, text: str) -> None:
    _stitch_msg_configure_and_show(parent, title, text, severity="information", ok_text="好的")


def stitch_msg_warning(parent: Optional[QWidget], title: str, text: str) -> None:
    _stitch_msg_configure_and_show(parent, title, text, severity="warning", ok_text="知道了")


def stitch_msg_critical(parent: Optional[QWidget], title: str, text: str) -> None:
    _stitch_msg_configure_and_show(parent, title, text, severity="critical", ok_text="关闭")


def stitch_msg_question(
    parent: Optional[QWidget],
    title: str,
    text: str,
    *,
    severity: str = "warning",
    yes_text: str = "是",
    no_text: str = "否",
    default_yes: bool = True,
) -> bool:
    """无边框双按钮确认弹窗，样式与 stitch_msg_information / warning 一致。返回是否选择「是」。"""
    dark = _stitch_msg_resolve_dark(parent)
    shell = _StitchMsgShellDialog(parent)
    shell.setObjectName("stitch_msg_shell")
    shell.setWindowTitle(title)
    shell.setModal(True)
    outer = QVBoxLayout(shell)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    stitch_dialog_prepend_chrome_topbar(shell, outer, title, on_traffic_close=shell.reject)
    body_wrap = QWidget()
    bw = QVBoxLayout(body_wrap)
    bw.setContentsMargins(24, 20, 24, 18)
    bw.setSpacing(16)
    body_panel = _stitch_msg_body_panel(text, title)
    bw.addWidget(body_panel)
    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(10)
    btn_row.addStretch(1)
    no_btn = QPushButton(no_text)
    no_btn.setObjectName("stitch_msg_cancel")
    yes_btn = QPushButton(yes_text)
    yes_btn.setObjectName("stitch_msg_ok")
    if default_yes:
        yes_btn.setDefault(True)
        yes_btn.setAutoDefault(True)
    else:
        no_btn.setDefault(True)
        no_btn.setAutoDefault(True)
    no_btn.clicked.connect(shell.reject)
    yes_btn.clicked.connect(shell.accept)
    btn_row.addWidget(no_btn)
    btn_row.addWidget(yes_btn)
    bw.addLayout(btn_row)
    outer.addWidget(body_wrap, 1)
    apply_stitch_msg_shell_style(shell, dark, severity=severity, choice_buttons=True)
    shell.setMinimumWidth(508)
    shell.setMaximumWidth(668)
    return shell.exec() == QDialog.DialogCode.Accepted


SVG_ICON_PATHS = {
    "broom": '<path d="M4 18h10M10 6l8 8M7 9l8 8M14 3l7 7"/>',
    "chart": '<path d="M4 19h16M7 16v-5M12 16V7M17 16v-8"/>',
    "dashboard": '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="4" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="10" width="7" height="10" rx="1"/>',
    "doc": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M9 12h7M9 15h7"/>',
    "invoice": '<rect x="6" y="3" width="12" height="18" rx="1"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "puzzle": '<path d="M9 6h3a2 2 0 1 1 4 0h2v4a2 2 0 1 1 0 4v4H6v-4a2 2 0 1 0 0-4V6h3"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 13l2 2 4-4"/>',
    "files": '<rect x="3" y="6" width="8" height="12" rx="1"/><rect x="9" y="3" width="12" height="16" rx="1"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>',
    "ruler": '<path d="M4 18L18 4l2 2L6 20zM9 13l2 2M12 10l2 2M15 7l2 2"/>',
    "folder": '<path d="M3 7h7l2 2h9v10H3z"/>',
    "play": '<path d="M9 7l8 5-8 5z"/>',
    # 射线与 settings 同源，保证相对 (12,12) 轴对称；旧版对角端点 5.4/17/18.6/7 不成轴对称，缩放后会显“歪”
    "sun": '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>',
    "moon": '<path d="M20 12.8A8 8 0 1 1 11.2 4 6.3 6.3 0 0 0 20 12.8z"/>',
    "notify": '<path d="M12 3a4 4 0 0 1 4 4v2.3c0 .8.2 1.5.6 2.2l1 1.5v1H6.4v-1l1-1.5c.4-.7.6-1.4.6-2.2V7a4 4 0 0 1 4-4z"/><path d="M10 18a2 2 0 0 0 4 0"/>',
    "cloud_done": '<path d="M7.5 18h9a3.5 3.5 0 0 0 .8-6.9A4.8 4.8 0 0 0 8.5 8a4 4 0 0 0-1 7.9z"/><path d="M10 13.2l1.7 1.7 3-3"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.8 9.2a2.4 2.4 0 1 1 3.8 1.9c-.8.5-1.2 1-1.2 1.9"/><path d="M12 16.6h.01"/>',
    "logout": '<path d="M9 4H6.5A1.5 1.5 0 0 0 5 5.5v13A1.5 1.5 0 0 0 6.5 20H9"/><path d="M14 16l4-4-4-4"/><path d="M18 12H9"/>',
    "calendar": '<rect x="4" y="5" width="16" height="14" rx="1.5"/><path d="M4 9h16M8 5V3M16 5V3M8 13h3M8 17h3M13 13h3M13 17h3"/>',
    "printer": '<rect x="7" y="3" width="10" height="7" rx="1"/><path d="M6 10h12v8H6zM8 18h8M17 10h2a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-1M7 8V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "stop": '<rect x="8" y="8" width="8" height="8" rx="1.5"/>',
    "copy": '<rect x="8" y="8" width="11" height="11" rx="1.5"/><path d="M5 15V6.5A1.5 1.5 0 0 1 6.5 5H15"/>',
    "external": '<path d="M9 5H5v14h14v-4"/><path d="M13 5h6v6M19 5l-8 8"/>',
    "trash": '<path d="M5 7h14M10 11v6M14 11v6M8 7l1-3h6l1 3M7 7l1 14h8l1-14"/>',
}


def _gui_device_pixel_ratio() -> float:
    """主屏缩放倍率；用于按物理像素绘制图标再 setDevicePixelRatio，避免高分屏上糊边。"""
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    scr = app.primaryScreen()
    if scr is None:
        return 1.0
    return max(1.0, float(scr.devicePixelRatio()))


def mono_svg_pixmap(
    name: str,
    size: int,
    color: str = "#1a1c1c",
    *,
    dpr: Optional[float] = None,
) -> QPixmap:
    logical = max(1, int(size))
    if dpr is None:
        dpr = _gui_device_pixel_ratio()
    dpr = max(1.0, float(dpr))
    phys = max(1, int(round(logical * dpr)))
    pixmap = QPixmap(phys, phys)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    hand_drawn = {"broom", "chart", "doc", "invoice", "puzzle", "report", "folder", "play", "gear"}
    if name in hand_drawn:
        unit = float(phys) / 24.0
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.5 * unit, 1.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        def p(x: float, y: float) -> QPointF:
            return QPointF(x * unit, y * unit)

        if name == "broom":
            painter.drawLine(p(6, 5), p(18, 17))
            painter.drawLine(p(4.5, 9.5), p(8.3, 5.7))
            painter.drawLine(p(6.3, 11.3), p(10.1, 7.5))
            painter.drawLine(p(8.1, 13.1), p(11.9, 9.3))
            painter.drawLine(p(5, 19), p(14, 19))
        elif name == "chart":
            painter.drawLine(p(4, 19), p(20, 19))
            painter.drawLine(p(8, 18), p(8, 12))
            painter.drawLine(p(12, 18), p(12, 8))
            painter.drawLine(p(16, 18), p(16, 10))
        elif name == "doc":
            painter.drawRect(QRectF(6 * unit, 4 * unit, 12 * unit, 16 * unit))
            painter.drawLine(p(14, 4), p(18, 8))
            painter.drawLine(p(10, 12), p(16, 12))
            painter.drawLine(p(10, 15), p(16, 15))
        elif name == "invoice":
            painter.drawRect(QRectF(6 * unit, 4 * unit, 12 * unit, 16 * unit))
            painter.drawLine(p(9, 8), p(15, 8))
            painter.drawLine(p(9, 12), p(15, 12))
            painter.drawLine(p(9, 16), p(13, 16))
        elif name == "puzzle":
            painter.drawRect(QRectF(6 * unit, 6 * unit, 12 * unit, 12 * unit))
            painter.drawLine(p(12, 6), p(12, 18))
            painter.drawLine(p(6, 12), p(18, 12))
            painter.drawEllipse(QRectF(10 * unit, 4.2 * unit, 4 * unit, 3.4 * unit))
            painter.drawEllipse(QRectF(16.2 * unit, 10 * unit, 3.4 * unit, 4 * unit))
        elif name == "report":
            painter.drawRect(QRectF(6 * unit, 4 * unit, 12 * unit, 16 * unit))
            painter.drawLine(p(14, 4), p(18, 8))
            painter.drawLine(p(10, 14), p(12, 16))
            painter.drawLine(p(12, 16), p(16, 12))
        elif name == "folder":
            painter.drawLine(p(4, 9), p(10, 9))
            painter.drawLine(p(10, 9), p(12, 11))
            painter.drawLine(p(12, 11), p(20, 11))
            painter.drawRect(QRectF(4 * unit, 11 * unit, 16 * unit, 8 * unit))
        elif name == "play":
            tri = QPolygonF([p(9, 7), p(17, 12), p(9, 17)])
            painter.drawPolygon(tri)
        elif name == "gear":
            # 锯齿外轮廓 + 中心圆孔，与「太阳」射线图标明确区分
            cx, cy = 12.0, 12.0
            n_teeth = 8
            r_tip = 8.15
            r_root = 5.35
            outer = QPolygonF()
            for k in range(n_teeth * 2):
                ang = (k * math.pi / n_teeth) - math.pi / 2
                rr = r_tip if (k % 2 == 0) else r_root
                outer.append(p(cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            painter.drawPolygon(outer)
            ri = 2.9
            painter.drawEllipse(QRectF((cx - ri) * unit, (cy - ri) * unit, 2 * ri * unit, 2 * ri * unit))
    else:
        path = SVG_ICON_PATHS.get(name, SVG_ICON_PATHS["doc"])
        # stroke 使用 viewBox 单位，随 width/height=phys 自动等比加粗，勿再乘 dpr
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" viewBox="1 1 22 22" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{path}</svg>"""
        renderer = QSvgRenderer(bytearray(svg, encoding="utf-8"))
        pad = 1.5 * dpr
        side = max(1.0, float(phys) - 2.0 * pad)
        renderer.render(painter, QRectF(pad, pad, side, side))

    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def mono_svg_icon(
    name: str,
    size: int,
    color: str = "#1a1c1c",
    *,
    dpr: Optional[float] = None,
) -> QIcon:
    return QIcon(mono_svg_pixmap(name, size, color, dpr=dpr))


def _button_icon_color(dark: bool, color_role: str) -> str:
    if color_role == "primary":
        return "#ffffff"
    if color_role == "danger":
        return palette(dark)["danger"]
    if color_role == "muted":
        return "#9CA3AF" if dark else "#71757D"
    return "#E5E7EB" if dark else "#1a1c1c"


def set_mono_button_icon(
    button: QPushButton,
    name: str,
    size: int,
    *,
    color_role: str = "auto",
    dark: bool = False,
) -> None:
    setattr(button, "_stitch_icon_name", name)
    setattr(button, "_stitch_icon_size", int(size))
    setattr(button, "_stitch_icon_color_role", color_role)
    button.setIcon(mono_svg_icon(name, size, _button_icon_color(dark, color_role)))
    button.setIconSize(QSize(size, size))


def refresh_mono_button_icon(button: QPushButton, dark: bool) -> None:
    name = getattr(button, "_stitch_icon_name", None)
    if not name:
        return
    size = int(getattr(button, "_stitch_icon_size", 16) or 16)
    color_role = str(getattr(button, "_stitch_icon_color_role", "auto") or "auto")
    button.setIcon(mono_svg_icon(str(name), size, _button_icon_color(dark, color_role)))
    button.setIconSize(QSize(size, size))


def _render_placeholder_logo_pixmap(side: int) -> QPixmap:
    """无外部 LOGO 文件时的占位图标：圆角方块 + 三线（表格/整理意象），多尺寸加入 QIcon 供任务栏与标题栏使用。"""
    s = max(16, int(side))
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    m = float(s) * 0.11
    rr = float(s) * 0.2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1a1c1c"))
    painter.drawRoundedRect(QRectF(m, m, float(s) - 2 * m, float(s) - 2 * m), rr, rr)
    pen = QPen(QColor("#f5f5f5"))
    pen.setWidthF(max(float(s) / 14.0, 1.25))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    x0 = float(s) * 0.3
    x1 = float(s) * 0.7
    for i, yn in enumerate((0.36, 0.5, 0.64)):
        y = float(s) * yn
        xe = x1 if i < 2 else float(s) * 0.62
        painter.drawLine(QPointF(x0, y), QPointF(xe, y))
    painter.end()
    return pm


def _fallback_application_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pm = _render_placeholder_logo_pixmap(sz)
        icon.addPixmap(pm, QIcon.Mode.Normal, QIcon.State.Off)
    return icon


def load_application_icon() -> QIcon:
    """窗口 / 任务栏 / 侧栏品牌图标。

    可在程序同目录放置任一方即可自动使用（优先顺序）：
    app_icon.ico、app_icon.png、logo.ico、logo.png
    """
    for fname in ("app_icon.ico", "app_icon.png", "logo.ico", "logo.png"):
        p = _DATA_DIR / fname
        if not p.is_file():
            p = _RESOURCE_DIR / fname
        if p.is_file():
            ic = QIcon(str(p))
            if not ic.isNull():
                return ic
    return _fallback_application_icon()


class CtkLikeStatus:
    """match_and_clean / generate_project_stat_tables 期望的 .configure(text=, text_color=) 接口。"""

    def __init__(self, label: QLabel, dark: bool = False):
        self._label = label
        self._dark = dark

    def configure(self, text=None, text_color=None):
        if text is not None:
            self._label.setText(text)
        if text_color is not None:
            tc = str(text_color).lower()
            p = palette(self._dark)
            if tc == "green":
                self._label.setStyleSheet(f"color: {p['success']}; padding-top: 2px; padding-bottom: 2px;")
            elif tc == "red":
                self._label.setStyleSheet(f"color: {p['danger']}; padding-top: 2px; padding-bottom: 2px;")
            else:
                self._label.setStyleSheet("")


class ThreadSafeStatusAdapter(QObject):
    """子线程里可调用 configure()，经信号回到 GUI 线程更新 QLabel。

    注意：必须在主线程构造（例如在启动 QThread/threading 之前），若在子线程里 new，
    对象归属工作线程，槽会在错误线程执行，界面会永远停在「正在…」。

    父对象须为主窗口等长期存在的 QObject，勿以 QLabel 为 parent（部分环境下跨线程 Queued 投递不稳定）。
    """

    _set_text = Signal(str)
    _set_style_key = Signal(str)

    def __init__(self, owner: QObject, label: QLabel, dark: bool = False):
        super().__init__(owner)
        self._label = label
        self._dark = dark
        self._thread_safe_configure = True
        self._set_text.connect(self._apply_text, Qt.ConnectionType.QueuedConnection)
        self._set_style_key.connect(self._apply_style, Qt.ConnectionType.QueuedConnection)

    @Slot(str)
    def _apply_text(self, t: str) -> None:
        self._label.setText(t)

    @Slot(str)
    def _apply_style(self, key: str) -> None:
        p = palette(self._dark)
        if key == "green":
            self._label.setStyleSheet(
                f"color: {p['success']}; padding-top: 2px; padding-bottom: 2px;"
            )
        elif key == "red":
            self._label.setStyleSheet(f"color: {p['danger']}; padding-top: 2px; padding-bottom: 2px;")
        else:
            self._label.setStyleSheet("")

    def configure(self, text=None, text_color=None) -> None:
        if text is not None:
            self._set_text.emit(str(text))
        if text_color is not None:
            tc = str(text_color).lower()
            self._set_style_key.emit(tc if tc in ("green", "red") else "")


class _QtBackgroundJob(QObject):
    """在 QThread 中执行 Python 可调用对象；结束时发 finished（供与 Qt 信号/事件循环正确协作）。"""

    finished = Signal()

    def __init__(self, fn: Callable[[], None]):
        super().__init__(None)
        self._fn = fn

    @Slot()
    def execute(self) -> None:
        try:
            self._fn()
        finally:
            self.finished.emit()


def _start_qt_background_job(fn: Callable[[], None], thread_parent: QObject) -> None:
    """用 QThread 替代 threading.Thread，避免非 Qt 线程 emit 时主界面不刷新、永远停在「正在…」。"""
    th = QThread(thread_parent)
    job = _QtBackgroundJob(fn)
    # 持有线程与任务引用，避免 Python GC 提前回收导致任务未执行/信号不回调。
    bag = getattr(thread_parent, "_qt_bg_jobs", None)
    if bag is None:
        bag = set()
        setattr(thread_parent, "_qt_bg_jobs", bag)
    bag.add(th)
    bag.add(job)

    def _cleanup_refs() -> None:
        try:
            bag.discard(job)
            bag.discard(th)
        except Exception:
            pass

    job.moveToThread(th)
    th.started.connect(job.execute)
    job.finished.connect(th.quit)
    job.finished.connect(job.deleteLater)
    th.finished.connect(_cleanup_refs)
    th.finished.connect(th.deleteLater)
    th.start()


def _start_python_background_job(fn: Callable[[], None], owner: QObject) -> None:
    """启动并登记标准 Python 后台线程，便于窗口退出时等待文件写入完成。"""
    bag = getattr(owner, "_python_bg_threads", None)
    if bag is None:
        bag = set()
        setattr(owner, "_python_bg_threads", bag)

    def _run() -> None:
        try:
            fn()
        finally:
            bag.discard(threading.current_thread())

    th = threading.Thread(target=_run, daemon=True)
    bag.add(th)
    th.start()


class AnimatedButton(QPushButton):
    def setText(self,text):
        super().setText(text)
    def __init__(self, text: str, role: str = "secondary", parent=None):
        super().__init__(text, parent)
        self.role = role
        self.setObjectName(role)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(int(TOKENS["motion"]["button_hover"]))
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._hover_anim.valueChanged.connect(self._update_hover_progress)
        self._hover = 0.0
        self.setMouseTracking(True)

    def _update_hover_progress(self, value):
        self._hover = float(value)
        self.setProperty("hoverProgress", self._hover)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._hover <= 0.001 or not self.isEnabled() or self.role not in ("primary", "secondary", "danger"):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.role == "primary":
            color = QColor(255, 255, 255, int(48 * self._hover))
        elif self.role == "danger":
            color = QColor(185, 28, 28, int(88 * self._hover))
        else:
            color = QColor(128, 132, 140, int(72 * self._hover))
        painter.setPen(QPen(color, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.drawRoundedRect(rect, 7.0, 7.0)

    def enterEvent(self, event):
        if not animations_enabled():
            self._update_hover_progress(1.0)
            super().enterEvent(event)
            return
        self._hover_anim.stop()
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not animations_enabled():
            self._update_hover_progress(0.0)
            super().leaveEvent(event)
            return
        self._hover_anim.stop()
        self._hover_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)


class FadeStack(QStackedWidget):
    def __init__(self):
        super().__init__()

    def switch_to(self, index: int):
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)


def _hex_lineedit_preview_color(text: str, fallback: str) -> str:
    """从输入框文本解析用于预览的 #RRGGBB；无法解析时用 fallback。"""
    fb = (fallback or "#888888").strip()
    if not fb.startswith("#"):
        fb = "#" + fb.lstrip("#")
    if not QColor(fb).isValid():
        fb = "#888888"
    digits = "".join(c for c in (text or "") if c in "0123456789abcdefABCDEF")
    if len(digits) >= 6:
        cand = "#" + digits[:6].lower()
    elif len(digits) == 3:
        cand = "#" + "".join(c * 2 for c in digits.lower())
    elif 1 <= len(digits) <= 5:
        cand = "#" + (digits + "000000")[:6].lower()
    else:
        return fb
    return cand if QColor(cand).isValid() else fb


def _color_swatch_style_sheet(css_hex: str) -> str:
    return (
        f"QFrame#color_swatch {{ background-color: {css_hex}; border-radius: 4px; "
        f"border: 1px solid rgba(198,198,198,0.34); }}"
    )


class PathLineEdit(QLineEdit):
    """支持拖入文件或文件夹的路径输入框。"""

    def __init__(self, is_dir: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._expects_dir = bool(is_dir)
        self._drop_state = ""
        self.setAcceptDrops(True)

    def _set_drop_state(self, state: str) -> None:
        if self._drop_state == state:
            return
        self._drop_state = state
        self.setProperty("dropState", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def _first_usable_path(self, event) -> Optional[Path]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if (self._expects_dir and path.is_dir()) or (not self._expects_dir and path.is_file()):
                return path
        return None

    def dragEnterEvent(self, event) -> None:
        if self._first_usable_path(event) is not None:
            self._set_drop_state("accept")
            event.acceptProposedAction()
        else:
            self._set_drop_state("")
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._first_usable_path(event) is not None:
            self._set_drop_state("accept")
            event.acceptProposedAction()
        else:
            self._set_drop_state("")
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_state("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        path = self._first_usable_path(event)
        self._set_drop_state("")
        if path is None:
            event.ignore()
            return
        self.setText(str(path))
        event.acceptProposedAction()


class TaskStatusPanel(QFrame):
    """统一的任务状态与进度反馈；兼容原 QLabel 的常用调用。"""

    _BUSY_WORDS = ("正在", "处理中", "生成中", "测试中", "监听中", "加载中")
    _DONE_WORDS = (
        "完成",
        "失败",
        "取消",
        "停止",
        "结束",
        "待命",
        "请选择",
        "未选择",
        "不存在",
        "不正确",
        "就绪",
    )
    _ERROR_WORDS = ("❌", "失败", "错误", "异常", "无法")
    _WARNING_WORDS = ("⚠️", "请选择", "请先", "未选择", "不存在", "不可用", "不完整", "尚无")
    _SUCCESS_WORDS = ("✅", "完成", "已生成", "已保存", "已加载", "已带入", "正常")
    _STATE_LABELS = {
        "ready": "就绪",
        "busy": "进行中",
        "success": "完成",
        "warning": "注意",
        "error": "错误",
    }

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("task_status_panel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TOKENS["space"]["sm"])
        self._badge = QLabel(self._STATE_LABELS["ready"])
        self._badge.setObjectName("status_badge")
        self._badge.setFont(ui_font("caption", QFont.Weight.DemiBold))
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedWidth(54)
        self._label = QLabel(self._clean_status_text(text))
        self._label.setObjectName("status_hint")
        self._label.setFont(ui_font("body"))
        self._label.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setObjectName("task_progress")
        self._progress.setAccessibleName("任务进度")
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(180)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._label, 1)
        lay.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignVCenter)
        self._apply_state(self._infer_state(text))

    def text(self) -> str:
        return self._label.text()

    def setText(self, text: str) -> None:
        value = str(text)
        display = self._clean_status_text(value)
        self._label.setText(display)
        state = self._infer_state(value)
        self._apply_state(state)
        if state == "busy" or any(word in value for word in self._BUSY_WORDS):
            self.set_busy(True)
        elif state in ("error", "warning", "success") or any(word in value for word in self._DONE_WORDS):
            self.set_busy(False)

    def setStyleSheet(self, style_sheet: str) -> None:
        self._label.setStyleSheet(style_sheet)

    @classmethod
    def _clean_status_text(cls, text: str) -> str:
        value = (text or "").strip()
        for prefix in ("❌", "⚠️", "✅", "⏳"):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
        value = re.sub(r"^状态[:：]\s*", "", value)
        if value in ("待命", "就绪"):
            return ""
        return value

    @classmethod
    def _infer_state(cls, text: str) -> str:
        value = str(text or "")
        if any(word in value for word in cls._ERROR_WORDS):
            return "error"
        if any(word in value for word in cls._WARNING_WORDS):
            return "warning"
        if any(word in value for word in cls._BUSY_WORDS):
            return "busy"
        if any(word in value for word in cls._SUCCESS_WORDS):
            return "success"
        return "ready"

    def _apply_state(self, state: str) -> None:
        if state not in self._STATE_LABELS:
            state = "ready"
        self.setProperty("state", state)
        self._badge.setText(self._STATE_LABELS[state])
        self._badge.setProperty("state", state)
        for widget in (self, self._badge):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._apply_state("busy")
            self._progress.setRange(0, 0)
            self._progress.show()
        else:
            self._progress.hide()
            self._progress.setRange(0, 100)
            self._progress.setValue(0)

    def set_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.set_busy(True)
            return
        self._apply_state("busy")
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(done, total)))
        self._progress.show()


def bind_setting_summary(layout, toggle, describe, *controls):
    """Show current values while advanced settings are collapsed."""
    label = QLabel()
    label.setObjectName("settings_summary")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setFont(ui_font("caption"))
    layout.insertWidget(layout.indexOf(toggle) + 1, label)

    def refresh(*_):
        text = describe()
        label.setText(text)
        label.setToolTip(text)
        label.hide()
        toggle.setToolTip(text)
        toggle.setAccessibleDescription(text)
    for control in controls:
        if isinstance(control, QComboBox):
            control.currentTextChanged.connect(refresh)
        elif isinstance(control, QSpinBox):
            control.valueChanged.connect(refresh)
        elif isinstance(control, QCheckBox):
            control.toggled.connect(refresh)
        else:
            control.textChanged.connect(refresh)
    toggle.toggled.connect(refresh)
    refresh()
    return label


class BasePage(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        # 子类可设为 (QWidget,)：后台任务进行时禁用底栏按钮，避免重复点击
        self._footer_busy_widgets: tuple = ()

    def _footer_busy_set(self, busy: bool) -> None:
        for w in getattr(self, "_footer_busy_widgets", ()):
            if w is not None:
                w.setEnabled(not busy)

    def _footer_busy_release_safe(self) -> None:
        """工作线程 finally 中调用，经主线程队列恢复 `_footer_busy_widgets`。"""
        m = getattr(self, "main", None)
        if m is None:
            self._footer_busy_set(False)
        else:
            m._invoke_on_gui.emit(lambda p=self: p._footer_busy_set(False))

    @staticmethod
    def _set_widgets_busy(busy: bool, *widgets: Optional[QWidget]) -> None:
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(not busy)

    @staticmethod
    def _set_path_entry_busy(entry: Optional[QLineEdit], busy: bool) -> None:
        if entry is None:
            return
        entry.setEnabled(not busy)
        browse = getattr(entry, "_stitch_browse_button", None)
        if browse is not None:
            browse.setEnabled(not busy)
        clear = getattr(entry, "_stitch_clear_button", None)
        if clear is not None:
            clear.setEnabled((not busy) and bool(entry.text().strip()))

    @staticmethod
    def _clear_field_error(entry: QLineEdit) -> None:
        if entry.property("validationState") != "error":
            return
        entry.setProperty("validationState", "")
        entry.style().unpolish(entry)
        entry.style().polish(entry)

    @staticmethod
    def _bind_validation_fold(controller: StitchFoldController, *roots: object) -> None:
        def _bind(obj: object) -> None:
            if isinstance(obj, QLineEdit):
                setattr(obj, "_stitch_fold_controller", controller)
            elif isinstance(obj, QWidget):
                for child in obj.findChildren(QLineEdit):
                    setattr(child, "_stitch_fold_controller", controller)
            elif isinstance(obj, (tuple, list)):
                for item in obj:
                    _bind(item)

        for root in roots:
            _bind(root)

    @staticmethod
    def _focus_field_later(entry: QLineEdit) -> None:
        entry.setFocus(Qt.FocusReason.OtherFocusReason)
        entry.selectAll()

    def _mark_field_error(self, entry: QLineEdit) -> None:
        entry.setProperty("validationState", "error")
        entry.style().unpolish(entry)
        entry.style().polish(entry)
        ctrl = getattr(entry, "_stitch_fold_controller", None)
        toggle = getattr(ctrl, "_toggle", None)
        if isinstance(toggle, QPushButton) and not toggle.isChecked():
            toggle.setChecked(True)
            QTimer.singleShot(
                int(TOKENS["motion"]["fold_expand"]) + 30,
                lambda e=entry: self._focus_field_later(e),
            )
        self._focus_field_later(entry)

    def _configure_number_field(
        self,
        entry: QLineEdit,
        minimum: float,
        maximum: float,
        *,
        decimals: int = 0,
    ) -> None:
        if decimals <= 0:
            validator = QIntValidator(int(minimum), int(maximum), entry)
        else:
            validator = QDoubleValidator(float(minimum), float(maximum), decimals, entry)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        entry.setValidator(validator)
        entry.textEdited.connect(lambda _text, e=entry: self._clear_field_error(e))

    def _read_number_field(
        self,
        entry: QLineEdit,
        label: str,
        minimum: float,
        maximum: float,
        *,
        integer: bool = False,
    ) -> float | int:
        raw = entry.text().strip().replace(",", "")
        try:
            value = float(raw)
        except ValueError as exc:
            value = math.nan
            parse_error = exc
        else:
            parse_error = None
        if parse_error is not None or not math.isfinite(value) or value < minimum or value > maximum:
            self._mark_field_error(entry)
            raise ValueError(f"{label}应在 {minimum:g}～{maximum:g} 之间")
        self._clear_field_error(entry)
        return int(value) if integer else value

    def _read_hex_color(self, entry: QLineEdit, label: str) -> str:
        value = entry.text().strip().lstrip("#")
        if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
            self._mark_field_error(entry)
            raise ValueError(f"{label}应为 6 位十六进制颜色，例如 4F81BD")
        self._clear_field_error(entry)
        return value.upper()

    def make_title_card(self, title: str, subtitle: str):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(TOKENS["space"]["xl"], TOKENS["space"]["lg"], TOKENS["space"]["xl"], TOKENS["space"]["lg"])
        lay.setSpacing(TOKENS["space"]["xs"])
        t1 = QLabel(title)
        t1.setFont(ui_font("headline", QFont.Weight.DemiBold))
        t2 = QLabel(subtitle)
        t2.setObjectName("muted")
        t2.setFont(ui_font("body"))
        lay.addWidget(t1)
        lay.addWidget(t2)
        return card

    def build_stitch_scaffold(
        self,
        title: str,
        subtitle: str,
        *,
        fill_viewport: bool = False,
        pinned_footer: bool = False,
    ) -> Tuple[QVBoxLayout, Optional[QVBoxLayout]]:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        page_scroll = QScrollArea()
        page_scroll.setObjectName("page_scroll")
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 垂直条始终占位，避免「刚好不滚动 → 展开折叠后出现滚动条」时视口变窄，整页按钮被横向推挤产生抖动感
        page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if pinned_footer:
            outer.addWidget(page_scroll, 1)
            pin = QFrame()
            pin.setObjectName("stitch_pinned_bar")
            pin_l = QVBoxLayout(pin)
            pin_l.setContentsMargins(
                TOKENS["space"]["xl"],
                TOKENS["space"]["md"],
                TOKENS["space"]["xxl"],
                TOKENS["space"]["lg"],
            )
            pin_l.setSpacing(TOKENS["space"]["md"])
            outer.addWidget(pin, 0)
            footer_layout: Optional[QVBoxLayout] = pin_l
        else:
            outer.addWidget(page_scroll)
            footer_layout = None

        page = QWidget()
        page.setObjectName("page_root")
        page_scroll.setWidget(page)
        page_scroll.viewport().setObjectName("page_viewport")

        root = QVBoxLayout(page)
        root.setContentsMargins(
            TOKENS["space"]["xl"],
            TOKENS["space"]["md"],
            TOKENS["space"]["xl"],
            TOKENS["space"]["lg"],
        )
        root.setSpacing(0)

        canvas = QWidget()
        canvas.setObjectName("page_canvas")
        canvas.setMaximumWidth(TOKENS["layout"]["canvas_max_width"])
        if fill_viewport:
            canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            root.addWidget(canvas, 1)
        else:
            canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            root.addWidget(canvas)
            root.addStretch(1)

        content = QVBoxLayout(canvas)
        content.setContentsMargins(
            TOKENS["space"]["md"],
            TOKENS["space"]["md"],
            TOKENS["space"]["md"],
            TOKENS["space"]["lg"],
        )
        content.setSpacing(16)

        t = QLabel(title)
        t.setObjectName("hero_title")
        t.setFont(ui_font("display", QFont.Weight.Bold))
        s = QLabel(subtitle)
        s.setObjectName("hero_subtitle")
        s.setFont(ui_font("body"))
        t.setWordWrap(True)
        s.setWordWrap(True)
        heading = QWidget()
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(8)
        heading_layout.addWidget(t)
        heading_layout.addWidget(s)
        content.addWidget(heading)
        # Hero 与表单区之间留白，强化「一屏一焦点」
        content.addSpacing(0)
        return content, footer_layout

    def stitch_section(self, parent_l, title):
        section = QFrame()
        section.setObjectName("stitch_settings")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("stitch_settings_title")
        layout.addWidget(label)
        parent_l.addWidget(section)
        return layout

    def stitch_path_row(
        self,
        parent_l: QVBoxLayout,
        label: str,
        value: str,
        is_dir: bool,
        placeholder: str,
        *,
        framed: bool = True,
    ) -> QLineEdit:
        card = QFrame()
        card.setObjectName("stitch_file_card" if framed else "stitch_inline_path")
        cl = QVBoxLayout(card)
        if framed:
            cl.setContentsMargins(16, 8, 16, 8)
        else:
            cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        lb = QLabel(label)
        lb.setObjectName("stitch_label")
        lb.setFont(ui_font("caption", QFont.Weight.DemiBold, 0.12))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(TOKENS["interaction"]["form_row_spacing"])
        e = PathLineEdit(is_dir)
        e.setText(value)
        e.setFont(ui_font("body"))
        e.setAccessibleName(label)
        e.setPlaceholderText(placeholder)
        e.setToolTip("可点击浏览，也可把文件或文件夹直接拖到这里")
        e.setMinimumHeight(TOKENS["interaction"]["line_edit_min_h"])
        lb.setBuddy(e)
        cl.addWidget(lb)
        ib = TOKENS["interaction"]["icon_path_button"]
        bw, bh = TOKENS["interaction"]["path_browse_w"], TOKENS["interaction"]["path_browse_min_h"]
        b = AnimatedButton("选择文件夹…" if is_dir else "选择文件…", "secondary")
        b.setAccessibleName(f"选择{label}")
        set_mono_button_icon(b, "folder", ib)
        b.setFixedSize(max(bw, 126 if is_dir else 112), bh)
        b.setFont(ui_font("caption", QFont.Weight.DemiBold, 0.08))
        b.clicked.connect(lambda: self._browse_into(e, is_dir))
        setattr(e, "_stitch_browse_button", b)
        b_clear = AnimatedButton("", "ghost")
        b_clear.setAccessibleName(f"清空{label}")
        b_clear.setToolTip("清空当前路径")
        set_mono_button_icon(b_clear, "x", 14, color_role="muted")
        b_clear.setFixedSize(36, bh)
        b_clear.clicked.connect(e.clear)
        setattr(e, "_stitch_clear_button", b_clear)

        def _sync_clear_button(raw: str = "") -> None:
            b_clear.setEnabled(e.isEnabled() and bool((raw or e.text()).strip()))

        e.textChanged.connect(_sync_clear_button)
        QTimer.singleShot(0, _sync_clear_button)
        rl.addWidget(e, 1)
        rl.addWidget(b_clear)
        rl.addWidget(b)
        cl.addWidget(row)
        feedback = QLabel()
        feedback.setObjectName("path_feedback")
        feedback.setFont(ui_font("caption"))
        feedback.hide()
        cl.addWidget(feedback)

        def _refresh_path_feedback(raw: str) -> None:
            text = (raw or "").strip().strip('"')
            if not text:
                feedback.hide()
                return
            try:
                path = Path(os.path.expandvars(text)).expanduser()
                valid = path.is_dir() if is_dir else path.is_file()
            except (OSError, ValueError):
                valid = False
                path = Path(text)
            if valid:
                feedback.setText("文件夹可用" if is_dir else f"已识别文件：{path.name}")
                state = "valid"
            elif is_dir:
                feedback.setText("文件夹尚不存在，请确认路径或重新选择")
                state = "warning"
            else:
                feedback.setText("未找到该文件，请重新选择")
                state = "invalid"
            feedback.setProperty("state", state)
            feedback.style().unpolish(feedback)
            feedback.style().polish(feedback)
            feedback.show()

        e.textChanged.connect(lambda text: e.setToolTip(text or "可浏览选择，或拖入文件／文件夹"))
        e.setToolTip(e.text() or "可浏览选择，或拖入文件／文件夹")
        feedback.setWordWrap(True)
        e.textChanged.connect(_refresh_path_feedback)
        QTimer.singleShot(0, lambda current=e.text(): _refresh_path_feedback(current))
        parent_l.addWidget(card)
        return e

    def _browse_into(self, entry: QLineEdit, is_dir: bool) -> None:
        """stitch_path_row 的默认行为；各页可 override 以限定文件类型等。"""
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "选择文件夹", str(Path.cwd()))
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "选择文件", str(Path.cwd()), "所有文件 (*.*)"
            )
        if p:
            entry.setText(p)

    def add_page_deco(self, parent_l: QVBoxLayout, text: str = "数据"):
        # macOS-style utility screens should keep the task surface quiet; older builds used a large watermark here.
        return None

    def make_status_label(self, text: str) -> TaskStatusPanel:
        return TaskStatusPanel(text)

    def make_action_buttons(self, primary_text: str, primary_slot, secondary_text: str = "打开结果文件夹", secondary_slot=None):
        row = QHBoxLayout()
        row.setSpacing(TOKENS["space"]["md"])
        ic = TOKENS["interaction"]["icon_footer"]
        h = TOKENS["interaction"]["footer_button_min_h"]
        b_secondary = AnimatedButton(secondary_text, "secondary")
        set_mono_button_icon(b_secondary, "folder", ic)
        b_secondary.setFont(ui_font("title", QFont.Weight.DemiBold, 0.10))
        b_secondary.setMinimumHeight(h)
        if secondary_slot:
            b_secondary.clicked.connect(secondary_slot)

        b_primary = AnimatedButton(primary_text, "primary")
        set_mono_button_icon(b_primary, "play", ic, color_role="primary")
        b_primary.setFont(ui_font("title", QFont.Weight.DemiBold, 0.10))
        b_primary.setMinimumHeight(h)
        b_primary.clicked.connect(primary_slot)
        self.register_primary_action(b_primary)
        row.addWidget(b_secondary, 1)
        row.addWidget(b_primary, 2)
        return row, b_secondary, b_primary

    def register_primary_action(self, button: QAbstractButton) -> None:
        """Register the page's safe default action for Ctrl+Enter."""
        self._stitch_primary_action = button
        hint = "快捷键：Ctrl+Enter"
        current = button.toolTip().strip()
        if hint not in current:
            button.setToolTip(f"{current}\n{hint}".strip())
        button.setAccessibleDescription(hint)

    def _stitch_field(self, label: str, value: str):
        """与 ActivityMatchPage 高级区块一致：标签在上、输入在下。"""
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        lb = QLabel(label)
        lb.setObjectName("stitch_field_label")
        lb.setFont(ui_font("caption", QFont.Weight.Normal, 0.12))
        e = QLineEdit(value)
        e.setFont(ui_font("body"))
        e.setAccessibleName(label)
        e.setMinimumHeight(TOKENS["interaction"]["line_edit_min_h"])
        lb.setBuddy(e)
        wl.addWidget(lb)
        wl.addWidget(e)
        return wrap, e

    def _stitch_color_field(self, label: str, value: str):
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(TOKENS["space"]["xs"] // 2)
        lb = QLabel(label)
        lb.setObjectName("stitch_field_label")
        lb.setFont(ui_font("caption", QFont.Weight.Normal, 0.12))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(TOKENS["space"]["sm"])
        sw = QFrame()
        sw.setObjectName("color_swatch")
        fb = value.strip()
        pv = _hex_lineedit_preview_color(fb, fb)
        sw.setStyleSheet(_color_swatch_style_sheet(pv))
        sw.setFixedSize(18, 18)
        e = QLineEdit(value)
        e.setFont(ui_font("body"))
        e.setAccessibleName(label)
        e.setMinimumHeight(TOKENS["interaction"]["line_edit_min_h"])
        lb.setBuddy(e)
        e.textChanged.connect(lambda _t, sw=sw, ed=e, fall=fb: sw.setStyleSheet(
            _color_swatch_style_sheet(_hex_lineedit_preview_color(ed.text(), fall))
        ))
        rl.addWidget(sw)
        rl.addWidget(e, 1)
        wl.addWidget(lb)
        wl.addWidget(row)
        return wrap, e


class ActivityMatchPage(BasePage):
    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self.var_app_path = ""
        self.var_reim_path = ""
        self.var_output_dir = os.getcwd()
        self.var_output_basename = "示例设计产业学院活动整理"
        self.var_fuzzy_threshold = "90"
        self.var_excel_row_height = "38"
        self.var_excel_header_fill = "4F81BD"
        self.var_excel_header_font_color = "FFFFFF"
        self.var_header_font_size = "11"
        self.var_body_font_size = "10"
        self._build_ui()

    def _build_ui(self):
        content, pin = self.build_stitch_scaffold(
            "数据整理",
            "匹配企业微信导出的活动申请与活动报销，生成可继续统计分析的 Excel 和 CSV。",
            pinned_footer=True,
        )
        assert pin is not None

        inputs = self.stitch_section(content, "数据来源")
        self.e_app = self.stitch_path_row(inputs, "活动申请表", self.var_app_path, False, "请选择活动申请文件...", framed=False)
        self.e_reim = self.stitch_path_row(inputs, "活动报销表", self.var_reim_path, False, "请选择活动报销文件...", framed=False)
        self.e_out = self.stitch_path_row(content, "保存位置", self.var_output_dir, True, "选择保存文件夹")

        self.adv_wrap = QFrame()
        self.adv_wrap.setObjectName("stitch_settings")
        adv_outer = QVBoxLayout(self.adv_wrap)
        adv_outer.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        adv_outer.setSpacing(TOKENS["space"]["sm"])

        self._adv_toggle = QPushButton()
        self._adv_toggle.setObjectName("section_toggle")
        self._adv_toggle.setCheckable(True)
        self._adv_toggle.setChecked(False)
        self._adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._adv_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        adv_outer.addWidget(self._adv_toggle)

        self.adv_inner = QFrame()
        adv_il = QVBoxLayout(self.adv_inner)
        adv_il.setContentsMargins(0, 4, 0, 0)
        adv_il.setSpacing(11)

        r1 = QHBoxLayout()
        r1.setSpacing(14)
        self.e_base = self._stitch_field("输出主文件名 (无扩展名)", self.var_output_basename)
        self.e_thr = self._stitch_field("模糊匹配阈值 (%)", self.var_fuzzy_threshold)
        r1.addWidget(self.e_base[0], 1)
        r1.addWidget(self.e_thr[0], 1)
        adv_il.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(14)
        self.e_rowh = self._stitch_field("数据行高 (PX)", self.var_excel_row_height)
        self.e_hfill = self._stitch_color_field("表头背景色 (HEX)", f"#{self.var_excel_header_fill}")
        r2.addWidget(self.e_rowh[0], 1)
        r2.addWidget(self.e_hfill[0], 1)
        adv_il.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(14)
        self.e_hfont = self._stitch_color_field("表头字体色 (HEX)", f"#{self.var_excel_header_font_color}")
        size_wrap = QWidget()
        sw_l = QHBoxLayout(size_wrap)
        sw_l.setContentsMargins(0, 0, 0, 0)
        sw_l.setSpacing(10)
        w_hsz, self.e_hsize = self._stitch_field("表头字号", self.var_header_font_size)
        w_bsz, self.e_bsize = self._stitch_field("正文字号", self.var_body_font_size)
        self._configure_number_field(self.e_thr[1], 0, 100, decimals=1)
        self._configure_number_field(self.e_rowh[1], 10, 200, decimals=1)
        self._configure_number_field(self.e_hsize, 6, 72, decimals=1)
        self._configure_number_field(self.e_bsize, 6, 72, decimals=1)
        sw_l.addWidget(w_hsz, 1)
        sw_l.addWidget(w_bsz, 1)
        r3.addWidget(self.e_hfont[0], 1)
        r3.addWidget(size_wrap, 1)
        adv_il.addLayout(r3)

        self._adv_fold = StitchFoldController(
            self.adv_inner,
            self._adv_toggle,
            "+ 输出与匹配",
            "- 输出与匹配",
        )
        self._adv_toggle.setToolTip(
            "折叠时使用默认输出文件名与 Excel 样式；展开后可改主文件名、匹配阈值与表格样式；修改会反映到生成的 Excel/CSV。"
        )
        self._adv_toggle.toggled.connect(self._adv_fold.on_toggled)
        adv_outer.addWidget(self._adv_fold.clip_host())
        self._adv_fold.apply_initial_collapsed()
        self._advanced_summary = bind_setting_summary(adv_outer, self._adv_toggle,
            lambda: f"匹配阈值 {self.e_thr[1].text()}% · 导出表头 {self.e_hsize.text()}pt / 正文 {self.e_bsize.text()}pt",
            self.e_thr[1], self.e_hsize, self.e_bsize)
        self.e_thr[1].setToolTip("模糊匹配的最低相似度；越高越严格，越低越容易匹配相似名称")
        self.e_hsize.setToolTip("生成的 Excel 表头字号，不改变软件界面字号")
        self.e_bsize.setToolTip("生成的 Excel 正文字号，不改变软件界面字号")
        self._bind_validation_fold(self._adv_fold, self.adv_inner)
        content.addWidget(self.adv_wrap)

        self.status = self.make_status_label("选择数据表和保存位置后，点击「开始整理」。")
        pin.addWidget(self.status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(TOKENS["space"]["md"])
        ic = TOKENS["interaction"]["icon_footer"]
        bh = TOKENS["interaction"]["footer_button_min_h"]
        b_open = AnimatedButton("打开结果文件夹", "secondary")
        set_mono_button_icon(b_open, "folder", ic)
        b_open.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        b_open.setMinimumHeight(bh)
        b_open.clicked.connect(self._open_output)
        b_run = AnimatedButton("开始整理", "primary")
        set_mono_button_icon(b_run, "play", ic, color_role="primary")
        b_run.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        b_run.setMinimumHeight(bh)
        b_run.clicked.connect(self._run_match)
        self.register_primary_action(b_run)
        btn_row.addWidget(b_open, 1)
        btn_row.addWidget(b_run, 2)
        pin.addLayout(btn_row)
        self._footer_busy_widgets = (b_open, b_run)
        self.add_page_deco(content, "数据")

    def _set_match_busy(self, busy: bool) -> None:
        self._footer_busy_set(busy)
        for entry in (self.e_app, self.e_reim, self.e_out):
            self._set_path_entry_busy(entry, busy)
        self._set_widgets_busy(busy, self.adv_wrap)

    def _browse_into(self, entry: QLineEdit, is_dir: bool):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "发票数据表", str(Path.cwd()), "Excel 文件 (*.xlsx)")
        if p:
            entry.setText(p)

    def _open_output(self):
        out_dir = self.e_out.text().strip()
        if not out_dir:
            self.status.setText("❌ 未选择输出目录")
            return
        if os.path.isdir(out_dir):
            open_local_folder(self, out_dir)
        else:
            self.status.setText("⚠️ 输出目录不存在")

    def _run_match(self):
        app_p = self.e_app.text().strip()
        reim_p = self.e_reim.text().strip()
        out_d = self.e_out.text().strip()
        if not app_p:
            self.status.setText("❌ 未选择『活动申请.xlsx』")
            return
        if not reim_p:
            self.status.setText("❌ 未选择『活动报销.xlsx』")
            return
        if not out_d:
            self.status.setText("❌ 未选择输出目录")
            return
        if os.path.normcase(os.path.normpath(app_p)) == os.path.normcase(os.path.normpath(reim_p)):
            self.status.setText(
                "❌ 「活动申请」与「活动报销」不能为同一文件；请分别选择企业微信导出的活动申请表与活动报销表"
            )
            return
        try:
            self._read_number_field(self.e_thr[1], "模糊匹配阈值", 0, 100)
            self._read_number_field(self.e_rowh[1], "数据行高", 10, 200)
            self._read_number_field(self.e_hsize, "表头字号", 6, 72)
            self._read_number_field(self.e_bsize, "正文字号", 6, 72)
            style_header_fill_hex = self._read_hex_color(self.e_hfill[1], "表头背景色")
            style_header_font_color = self._read_hex_color(self.e_hfont[1], "表头字体色")
        except ValueError as exc:
            self.status.setText(f"❌ {exc}")
            return
        self.status.setStyleSheet("")
        self.status.setText("⏳ 正在整理，请稍候…")
        self._set_match_busy(True)
        self.main.nav_task_begin(NAV_PAGE_ACTIVITY_MATCH)

        # QObject 必须在主线程创建，槽才会在 GUI 线程执行；子线程里 new 适配器会导致仍停在「正在…」。
        adapter = ThreadSafeStatusAdapter(self.main, self.status, self.main.dark)
        fuzzy_threshold = self.e_thr[1].text()
        output_basename = self.e_base[1].text()
        style_excel_row_height = self.e_rowh[1].text()
        style_header_font_size = self.e_hsize.text()
        style_body_font_size = self.e_bsize.text()

        def _thr():
            try:
                result_path = nv_biz.match_and_clean(
                    app_p,
                    reim_p,
                    out_d,
                    adapter,
                    fuzzy_threshold=fuzzy_threshold,
                    output_basename=output_basename,
                    style_excel_row_height=style_excel_row_height,
                    style_header_fill_hex=style_header_fill_hex,
                    style_header_font_color=style_header_font_color,
                    style_header_font_size=style_header_font_size,
                    style_body_font_size=style_body_font_size,
                )
                if result_path and Path(result_path).is_file():
                    self.main._invoke_on_gui.emit(
                        lambda p=str(result_path): setattr(self.main, "_last_cleaned_data_path", p)
                    )
            finally:
                mw = self.main
                pi = NAV_PAGE_ACTIVITY_MATCH
                mw._invoke_on_gui.emit(lambda: self._set_match_busy(False))
                mw._nav_task_done.emit(pi)

        # 与统计/简报一致：标准线程 + ThreadSafeStatusAdapter；避免 QThread 与 pandas/openpyxl 在部分环境下卡住或界面不刷新
        _start_python_background_job(_thr, self.main)


class PlaceholderPage(BasePage):
    def __init__(self, title: str):
        super().__init__(None)
        l = QVBoxLayout(self)
        l.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["xl"], TOKENS["space"]["xl"], TOKENS["space"]["xl"]
        )
        lb = QLabel(f"{title}（待迁移）")
        lb.setFont(ui_font("display", QFont.Weight.Bold))
        l.addWidget(lb)
        l.addStretch(1)


class ProjectStatPage(BasePage):
    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self._build_ui()

    def _build_ui(self):
        root, pin = self.build_stitch_scaffold(
            "统计报表",
            "读取整理后的项目数据，生成明细、学校汇总、活动类型透视和专业覆盖统计。",
            pinned_footer=True,
        )
        assert pin is not None

        # 与「活动数据整理」一致：不再套内层 QScrollArea，仅由 build_stitch_scaffold 外层 page_scroll 统一滚动，避免出现版式区嵌套细滚动条。
        inputs = self.stitch_section(root, "输入数据")
        self.e_input = self.stitch_path_row(inputs, "整理后的数据表", "", False, "请选择整理后的数据表...", framed=False)
        self.b_use_previous = AnimatedButton("使用最近整理结果", "secondary")
        self.b_use_previous.setMinimumHeight(36)
        self.b_use_previous.clicked.connect(self._use_previous_cleaned_data)
        inputs.addWidget(self.b_use_previous, 0, Qt.AlignmentFlag.AlignRight)
        outputs = self.stitch_section(root, "输出设置")
        self.e_output = self.stitch_path_row(outputs, "保存位置", "", True, "请选择输出目录...", framed=False)
        self.e_filename = self._stitch_field("文件名称", "示例项目数据统计表.xlsx")
        outputs.addWidget(self.e_filename[0])

        self._stat_adv_wrap = QFrame()
        self._stat_adv_wrap.setObjectName("stitch_settings")
        sav = QVBoxLayout(self._stat_adv_wrap)
        sav.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        sav.setSpacing(TOKENS["space"]["sm"])
        self._stat_adv_toggle = QPushButton()
        self._stat_adv_toggle.setObjectName("section_toggle")
        self._stat_adv_toggle.setCheckable(True)
        self._stat_adv_toggle.setChecked(False)
        self._stat_adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stat_adv_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        sav.addWidget(self._stat_adv_toggle)

        self._stat_adv_inner = QWidget()
        sil = QVBoxLayout(self._stat_adv_inner)
        sil.setContentsMargins(0, 4, 0, 0)
        sil.setSpacing(11)

        grid_r1 = QHBoxLayout()
        grid_r1.setSpacing(14)
        self.e_col_w = self._stitch_field("列宽约", "20")
        self.e_row_h = self._stitch_field("数据行高", "25")
        self._configure_number_field(self.e_col_w[1], 4, 100, decimals=1)
        self._configure_number_field(self.e_row_h[1], 10, 200)
        grid_r1.addWidget(self.e_col_w[0], 1)
        grid_r1.addWidget(self.e_row_h[0], 1)
        sil.addLayout(grid_r1)

        grid_r2 = QHBoxLayout()
        grid_r2.setSpacing(14)
        self.e_hdr_h = self._stitch_field("表头行高", "28")
        size_wrap = QWidget()
        sw_l = QHBoxLayout(size_wrap)
        sw_l.setContentsMargins(0, 0, 0, 0)
        sw_l.setSpacing(10)
        w_hsz, self.e_fhs = self._stitch_field("表头字号", "12")
        w_bsz, self.e_fbs = self._stitch_field("正文字号", "11")
        self._configure_number_field(self.e_hdr_h[1], 10, 200)
        self._configure_number_field(self.e_fhs, 6, 72)
        self._configure_number_field(self.e_fbs, 6, 72)
        sw_l.addWidget(w_hsz, 1)
        sw_l.addWidget(w_bsz, 1)
        grid_r2.addWidget(self.e_hdr_h[0], 1)
        grid_r2.addWidget(size_wrap, 1)
        sil.addLayout(grid_r2)

        hue_hint = QLabel("行底色（6 位十六进制，勿加 #）")
        hue_hint.setObjectName("stitch_field_label")
        hue_hint.setFont(ui_font("caption", QFont.Weight.Normal, 0.12))
        sil.addWidget(hue_hint)

        color_row = QHBoxLayout()
        color_row.setSpacing(14)
        self.e_hf = self._stitch_color_field("表头", "#C5E0B4")
        self.e_sf = self._stitch_color_field("汇总行", "#FFF2CC")
        self.e_tf = self._stitch_color_field("合计/总计行", "#FEDB61")
        color_row.addWidget(self.e_hf[0], 1)
        color_row.addWidget(self.e_sf[0], 1)
        color_row.addWidget(self.e_tf[0], 1)
        sil.addLayout(color_row)

        hint_types = QLabel("活动类型清单（可选，每行一个；留空则用内置列表）")
        hint_types.setObjectName("stitch_field_label")
        hint_types.setFont(ui_font("caption", QFont.Weight.Normal, 0.12))
        sil.addWidget(hint_types)
        self.types_box = QTextEdit()
        self.types_box.setObjectName("types_box")
        self.types_box.setFont(ui_font("body"))
        self.types_box.setFixedHeight(100)
        sil.addWidget(self.types_box)

        self._stat_adv_fold = StitchFoldController(
            self._stat_adv_inner,
            self._stat_adv_toggle,
            "+ 版式与活动类型",
            "- 版式与活动类型",
        )
        self._stat_adv_toggle.setToolTip(
            "折叠时使用默认列宽、行高与配色；展开后可编辑活动类型清单（每行一个，留空用内置列表）。"
            "版式数字可改，非法则回退默认。"
        )
        self._stat_adv_toggle.toggled.connect(self._stat_adv_fold.on_toggled)
        sav.addWidget(self._stat_adv_fold.clip_host())
        self._stat_adv_fold.apply_initial_collapsed()
        self._advanced_summary = bind_setting_summary(sav, self._stat_adv_toggle,
            lambda: f"列宽 {self.e_col_w[1].text()} · 行高 {self.e_row_h[1].text()} · " +
                (f"自定义 {len([x for x in self.types_box.toPlainText().splitlines() if x.strip()])} 项活动类型" if self.types_box.toPlainText().strip() else "内置活动类型"),
            self.e_col_w[1], self.e_row_h[1], self.types_box)
        self.e_col_w[1].setToolTip("输出 Excel 的列宽，使用 Excel 字符宽度单位，不是屏幕像素")
        self.e_row_h[1].setToolTip("输出 Excel 的数据行高度")
        self._bind_validation_fold(self._stat_adv_fold, self._stat_adv_inner)
        root.addWidget(self._stat_adv_wrap)

        self.status = self.make_status_label("选择数据表和保存位置后，点击「生成报表」。")
        pin.addWidget(self.status)

        btn_row, _b_open, _b_run = self.make_action_buttons("生成报表", self._run_generate, "打开结果文件夹", self._open_output)
        pin.addLayout(btn_row)
        self._footer_busy_widgets = (_b_open, _b_run)
        self.add_page_deco(root, "统计")

    def _set_stat_busy(self, busy: bool) -> None:
        self._footer_busy_set(busy)
        self._set_widgets_busy(busy, self.b_use_previous, self.e_filename[0], self._stat_adv_wrap)
        self._set_path_entry_busy(self.e_input, busy)
        self._set_path_entry_busy(self.e_output, busy)

    def _browse_into(self, entry: QLineEdit, is_dir: bool):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "选择整理后的数据表", str(Path.cwd()), "Excel 文件 (*.xlsx)")
        if p:
            entry.setText(p)

    def _use_previous_cleaned_data(self) -> None:
        path = str(getattr(self.main, "_last_cleaned_data_path", "") or "")
        if path and Path(path).is_file():
            self.e_input.setText(path)
            self.status.setText("已带入刚完成的整理结果")
        else:
            self.status.setText("尚无可用的整理结果，请先完成“数据整理”")

    def _open_output(self):
        out_dir = self.e_output.text().strip()
        if not out_dir:
            self.status.setText("❌ 请选择输出文件夹")
            return
        if os.path.isdir(out_dir):
            open_local_folder(self, out_dir)
        else:
            self.status.setText("⚠️ 输出目录不存在")

    def _run_generate(self):
        if not self.e_input.text().strip():
            self.status.setText("❌ 请选择数据表")
            return
        if not self.e_output.text().strip():
            self.status.setText("❌ 请选择输出文件夹")
            return
        if not self.e_filename[1].text().strip():
            self.status.setText("❌ 请填写输出文件名")
            self.e_filename[1].setFocus(Qt.FocusReason.OtherFocusReason)
            return
        try:
            self._read_number_field(self.e_col_w[1], "列宽", 4, 100)
            self._read_number_field(self.e_row_h[1], "数据行高", 10, 200, integer=True)
            self._read_number_field(self.e_hdr_h[1], "表头行高", 10, 200, integer=True)
            self._read_number_field(self.e_fhs, "表头字号", 6, 72, integer=True)
            self._read_number_field(self.e_fbs, "正文字号", 6, 72, integer=True)
            h_hex = self._read_hex_color(self.e_hf[1], "表头底色")
            s_hex = self._read_hex_color(self.e_sf[1], "汇总行底色")
            t_hex = self._read_hex_color(self.e_tf[1], "合计行底色")
        except ValueError as exc:
            self.status.setText(f"❌ {exc}")
            return
        self.status.setStyleSheet("")
        self.status.setText("⏳ 正在生成报表，请稍候…")
        self._set_stat_busy(True)
        self.main.nav_task_begin(NAV_PAGE_PROJECT_STAT)

        adapter = ThreadSafeStatusAdapter(self.main, self.status, self.main.dark)
        inp = self.e_input.text().strip()
        outp = self.e_output.text().strip()
        raw = self.types_box.toPlainText().strip()
        types = list(dict.fromkeys(x.strip() for x in raw.splitlines() if x.strip())) if raw else None
        out_fn = self.e_filename[1].text().strip()
        col_w = self.e_col_w[1].text()
        row_h = self.e_row_h[1].text()
        hdr_h = self.e_hdr_h[1].text()
        fhs = self.e_fhs.text()
        fbs = self.e_fbs.text()

        def _thr():
            try:
                nv_biz.generate_project_stat_tables(
                    inp,
                    outp,
                    adapter,
                    output_filename=out_fn,
                    col_width=col_w,
                    row_height=row_h,
                    header_height=hdr_h,
                    activity_types=types,
                    header_fill_hex=h_hex,
                    sum_fill_hex=s_hex,
                    total_fill_hex=t_hex,
                    font_header_size=fhs,
                    font_body_size=fbs,
                )
            finally:
                mw = self.main
                pi = NAV_PAGE_PROJECT_STAT
                mw._invoke_on_gui.emit(lambda: self._set_stat_busy(False))
                mw._nav_task_done.emit(pi)

        # 与经典合并版一致：轻量统计用标准线程即可；避免 QThread 与数值库在个别环境下的交互差异。
        _start_python_background_job(_thr, self.main)


class BriefingPage(BasePage):
    """后台拆分/生成在子线程中回调 log/dialog，必须用 Qt 信号回主线程（勿用 Signal(object)+lambda，部分环境不投递）。"""

    _brief_worker_log = Signal(str)
    _brief_worker_dialog = Signal(str, str, str)

    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self._brief_worker_log.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        self._brief_worker_dialog.connect(self._on_brief_worker_dialog, Qt.ConnectionType.QueuedConnection)
        self._build_ui()

    @Slot(str, str, str)
    def _on_brief_worker_dialog(self, kind: str, title: str, message: str) -> None:
        if kind == "error":
            stitch_msg_critical(self, title, message)
        elif kind == "warning":
            self._append_log(f"⚠️ {title}：{message}")
            if hasattr(self, "status"):
                self.status.setText(f"状态：{title}，请查看运行日志")
        else:
            self._append_log(f"✅ {title}：{message}")
            if hasattr(self, "status"):
                self.status.setText(f"状态：{title}")

    def _build_ui(self):
        # 视觉与「活动数据整理」首页一致：stitch_path_row + 主按钮 42px + 日志卡片
        root, pin = self.build_stitch_scaffold(
            "活动简报",
            "可先按学校拆分活动总表；已有单个学院活动表时，也可直接生成 Word 简报。",
            pinned_footer=True,
        )
        assert pin is not None

        self.tabs = QTabWidget()
        self.tabs.setObjectName("brief_tabs")
        self.tabs.tabBar().setFont(ui_font("body", QFont.Weight.DemiBold))
        root.addWidget(self.tabs, 1)

        log_frame = QFrame()
        log_frame.setObjectName("card_group")
        log_l = QVBoxLayout(log_frame)
        log_l.setContentsMargins(
            TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"]
        )
        log_l.setSpacing(TOKENS["space"]["sm"])
        lb_log = QLabel("处理详情")
        lb_log.setObjectName("brief_log_title")
        lb_log.setFont(ui_font("label", QFont.Weight.DemiBold, 0.15))
        self.log_text = QTextEdit()
        self.log_text.setObjectName("stitch_run_log")
        self.log_text.setReadOnly(True)
        self.log_text.setFont(ui_font("body"))
        self.log_text.setMinimumHeight(160)
        self.log_text.setMaximumHeight(220)
        log_l.addWidget(lb_log)
        log_l.addWidget(self.log_text, 1)
        self._brief_log_frame = log_frame

        tab_split = QWidget()
        self.split_l = QVBoxLayout(tab_split)
        self.split_l.setContentsMargins(14, 14, 14, 14)
        self.split_l.setSpacing(15)
        self.e_split_excel = self.stitch_path_row(self.split_l, "活动总表", "", False, "请选择 Excel 总表...", framed=False)
        self.e_split_out = self.stitch_path_row(self.split_l, "保存位置", "", True, "选择保存文件夹", framed=False)
        self.h_split = QLabel("按「学校名称」自动拆分总表，并尽可能保留原表样式。完成后可切换到「简报自动生成」选择其中一个文件。")
        self.h_split.setObjectName("muted")
        self.h_split.setWordWrap(True)
        self.h_split.setFont(ui_font("label"))
        self.split_l.addWidget(self.h_split)
        self.split_l.addStretch(1)
        self.tabs.addTab(tab_split, " Excel 表格拆分（可选） ")

        tab_report = QWidget()
        self.report_l = QVBoxLayout(tab_report)
        self.report_l.setContentsMargins(14, 14, 14, 14)
        self.report_l.setSpacing(15)
        self.e_report_excel = self.stitch_path_row(self.report_l, "院校活动表", "", False, "请选择要生成简报的 Excel...", framed=False)
        self.e_report_out = self.stitch_path_row(self.report_l, "保存位置", "", True, "请定义简报输出目录...", framed=False)
        self._brief_fetch_wrap = QFrame()
        self._brief_fetch_wrap.setObjectName("stitch_settings")
        bfw_l = QVBoxLayout(self._brief_fetch_wrap)
        bfw_l.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        bfw_l.setSpacing(8)
        self._brief_fetch_toggle = QPushButton()
        self._brief_fetch_toggle.setObjectName("section_toggle")
        self._brief_fetch_toggle.setCheckable(True)
        self._brief_fetch_toggle.setChecked(False)
        self._brief_fetch_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_fetch_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        bfw_l.addWidget(self._brief_fetch_toggle)

        self._brief_fetch_inner = QWidget()
        bif = QVBoxLayout(self._brief_fetch_inner)
        bif.setContentsMargins(0, 4, 0, 0)
        bif.setSpacing(11)
        bf_form = QFormLayout()
        bf_form.setSpacing(10)
        bf_form.setContentsMargins(0, 0, 0, 0)
        bf_form.setHorizontalSpacing(14)
        bf_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.sp_brief_timeout = QSpinBox()
        self.sp_brief_timeout.setRange(8, 90)
        self.sp_brief_timeout.setValue(18)
        self.sp_brief_timeout.setFont(ui_font("body"))
        bf_form.addRow(_api_settings_field_label("单页超时(秒)", self.sp_brief_timeout), self.sp_brief_timeout)

        self.sp_brief_delay = QSpinBox()
        self.sp_brief_delay.setRange(0, 30)
        self.sp_brief_delay.setValue(4)
        self.sp_brief_delay.setToolTip("每条活动之间的等待时间，减轻对目标站压力；0 表示不等待")
        self.sp_brief_delay.setFont(ui_font("body"))
        bf_form.addRow(_api_settings_field_label("行间隔(×0.1秒)", self.sp_brief_delay), self.sp_brief_delay)

        self.sp_brief_summary = QSpinBox()
        self.sp_brief_summary.setRange(200, 1200)
        self.sp_brief_summary.setValue(420)
        self.sp_brief_summary.setSingleStep(20)
        self.sp_brief_summary.setFont(ui_font("body"))
        bf_form.addRow(_api_settings_field_label("摘要最多字数", self.sp_brief_summary), self.sp_brief_summary)

        self.sp_brief_maximg = QSpinBox()
        self.sp_brief_maximg.setRange(0, 8)
        self.sp_brief_maximg.setValue(3)
        self.sp_brief_maximg.setFont(ui_font("body"))
        bf_form.addRow(_api_settings_field_label("配图张数上限", self.sp_brief_maximg), self.sp_brief_maximg)

        self.cb_brief_nearby_img = QCheckBox("仅正文附近配图（推荐，少混入页眉页脚图）")
        self.cb_brief_nearby_img.setChecked(True)
        self.cb_brief_nearby_img.setFont(ui_font("body"))
        bf_form.addRow(self.cb_brief_nearby_img)

        self.cb_brief_keep_activity_info = QCheckBox(
            "保留活动时间、人数及新闻链接"
        )
        self.cb_brief_keep_activity_info.setChecked(False)
        self.cb_brief_keep_activity_info.setToolTip(
            "不勾选时：每条活动下仅保留小标题、抓取的正文与配图，不写入表格里的时间/人数行，也不写新闻链接行。"
        )
        self.cb_brief_keep_activity_info.setFont(ui_font("body"))
        bf_form.addRow(self.cb_brief_keep_activity_info)

        self.cb_brief_full_content = QCheckBox("抓取完整正文与更多配图")
        self.cb_brief_full_content.setChecked(False)
        self.cb_brief_full_content.setToolTip(
            "勾选后：仅在识别出的「正文区」（如微信 js_content、官网新闻正文容器）内尽量保留全文并多抓配图，"
            "不整页抓取导航、侧栏与页脚。仍有字数与配图上限。可适当提高「单页超时」。"
        )
        self.cb_brief_full_content.setFont(ui_font("body"))
        bf_form.addRow(self.cb_brief_full_content)

        self.cb_brief_split_by_activity = QCheckBox(
            "每个活动单独生成 Word"
        )
        self.cb_brief_split_by_activity.setChecked(False)
        self.cb_brief_split_by_activity.setToolTip(
            "勾选后：不再合并为一个学校总简报，而是为表中每一行有效活动各生成一个 .docx；"
            "文件名取「活动名称」列（自动去除 Windows 非法字符）。若重名则自动追加 _2、_3 等后缀。"
        )
        self.cb_brief_split_by_activity.setFont(ui_font("body"))
        bf_form.addRow(self.cb_brief_split_by_activity)

        bif.addLayout(bf_form)

        self._brief_fetch_fold = StitchFoldController(
            self._brief_fetch_inner,
            self._brief_fetch_toggle,
            "+ 内容抓取设置",
            "- 内容抓取设置",
        )
        self._brief_fetch_toggle.setToolTip(
            "默认折叠。展开后可调单页超时、行间隔、摘要字数、配图及是否保留表格活动信息行与链接行。"
        )
        self._brief_fetch_toggle.toggled.connect(self._brief_fetch_fold.on_toggled)
        bfw_l.addWidget(self._brief_fetch_fold.clip_host())
        self._brief_fetch_fold.apply_initial_collapsed()
        self._advanced_summary = bind_setting_summary(bfw_l, self._brief_fetch_toggle,
            lambda: f"单页超时 {self.sp_brief_timeout.value()} 秒 · 间隔 {self.sp_brief_delay.value()/10:g} 秒 · 摘要最多 {self.sp_brief_summary.value()} 字 · 配图最多 {self.sp_brief_maximg.value()} 张",
            self.sp_brief_timeout, self.sp_brief_delay, self.sp_brief_summary, self.sp_brief_maximg)
        self.sp_brief_maximg.setToolTip("每条活动最多保留的配图数量；0 表示不添加配图")

        self.report_l.addWidget(self._brief_fetch_wrap)
        self.h_report_hint = QLabel(
            "内置「垃圾信息黑名单」，自动过滤来源、发布时间、审核人等杂质。"
            "微信验证页仍可能需人工处理。"
        )
        self.h_report_hint.setObjectName("muted")
        self.h_report_hint.setFont(ui_font("label"))
        self.h_report_hint.setWordWrap(True)
        self.report_l.addWidget(self.h_report_hint)
        self.report_l.addStretch(1)
        self.tabs.addTab(tab_report, " 简报自动生成 ")
        root.addWidget(self._brief_log_frame)

        self.status = self.make_status_label("拆分表格：选择总表和输出文件夹")
        pin.addWidget(self.status)

        bf = QHBoxLayout()
        bf.setSpacing(14)
        self.b_footer_open = AnimatedButton("打开结果文件夹", "secondary")
        set_mono_button_icon(self.b_footer_open, "folder", 18)
        self.b_footer_open.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_footer_open.setMinimumHeight(42)
        self.b_footer_open.clicked.connect(self._open_brief_output)
        bf.addWidget(self.b_footer_open, 1)
        self.b_footer_report = AnimatedButton("拆分表格", "primary")
        set_mono_button_icon(self.b_footer_report, "play", 18, color_role="primary")
        self.b_footer_report.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_footer_report.setMinimumHeight(42)
        self.b_footer_report.clicked.connect(self._run_current_brief_task)
        self.register_primary_action(self.b_footer_report)
        bf.addWidget(self.b_footer_report, 2)
        pin.addLayout(bf)

        self._brief_split_running = False
        self._brief_report_running = False

        self.tabs.currentChanged.connect(self._on_brief_tab_changed)
        self._on_brief_tab_changed(self.tabs.currentIndex())
        self.add_page_deco(root, "简报")

    def _sync_brief_action_buttons(self) -> None:
        """共享日志区域一次只运行一项任务，避免不同步骤的消息交错。"""
        spl = getattr(self, "_brief_split_running", False)
        rep = getattr(self, "_brief_report_running", False)
        available = not spl and not rep
        self.b_footer_open.setEnabled(available)
        self.b_footer_report.setEnabled(available)
        busy = not available
        self.tabs.tabBar().setEnabled(available)
        for entry in (self.e_split_excel, self.e_split_out, self.e_report_excel, self.e_report_out):
            self._set_path_entry_busy(entry, busy)
        self._set_widgets_busy(busy, self._brief_fetch_wrap)

    def _run_current_brief_task(self) -> None:
        if self.tabs.currentIndex() == 0:
            self._run_split()
        else:
            self._run_report()

    def _on_brief_tab_changed(self, index: int) -> None:
        self._relocate_brief_log(index)
        if index == 0:
            self.b_footer_report.setText("拆分表格")
            if not self._brief_split_running and not self._brief_report_running:
                self.status.setText("拆分表格：选择总表和输出文件夹")
        else:
            self.b_footer_report.setText("生成简报")
            if not self._brief_split_running and not self._brief_report_running:
                self.status.setText("简报生成：选择单个学院表和保存位置")

    def _relocate_brief_log(self, index: int):
        # 日志固定在标签页下方，切换步骤时不再重排页面或丢失滚动位置。
        return

    def _open_brief_output(self) -> None:
        idx = self.tabs.currentIndex()
        d = (
            self.e_split_out.text().strip()
            if idx == 0
            else self.e_report_out.text().strip()
        )
        if not d:
            stitch_msg_warning(self, "无法打开文件夹", "请先在当前步骤填写输出文件夹路径，再试一次。")
            return
        if not os.path.isdir(d):
            stitch_msg_warning(self, "无法打开文件夹", "输出路径不存在或不是文件夹，请检查路径后重试。")
            return
        open_local_folder(self, d)

    def _browse_into(self, entry: QLineEdit, is_folder: bool):
        if is_folder:
            p = QFileDialog.getExistingDirectory(self, "选择文件夹")
        elif entry is self.e_split_excel:
            p, _ = QFileDialog.getOpenFileName(
                self, "选择待拆分 Excel", str(Path.cwd()), "Excel 文件 (*.xlsx)"
            )
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "选择 Excel 或 CSV", str(Path.cwd()), "数据文件 (*.xlsx *.csv)"
            )
        if p:
            entry.setText(p)

    def _append_log(self, msg: str):
        textedit_append_autoscroll(self.log_text, msg)

    def _safe_log(self, msg: str):
        self._brief_worker_log.emit(msg)

    def _safe_dialog(self, kind: str, title: str, message: str):
        self._brief_worker_dialog.emit(kind, title, message)

    def _run_split(self):
        excel = self.e_split_excel.text().strip()
        out = self.e_split_out.text().strip()
        if not excel or not out:
            stitch_msg_warning(self, "提示", "请先选择输入文件和输出文件夹！")
            return
        if not os.path.isfile(excel):
            self._append_log("❌ 指定的 Excel 文件不存在。")
            return
        if not os.path.isdir(out):
            try:
                os.makedirs(out, exist_ok=True)
            except OSError as e:
                self._append_log(f"❌ 无法创建输出目录：{e}")
                return
        self._append_log("\n>>> 启动任务：Excel 表格拆分")
        self._brief_split_running = True
        self.status.setText("正在拆分表格，请稍候…")
        self._sync_brief_action_buttons()
        self.main.nav_task_begin(NAV_PAGE_BRIEFING)
        before_files: dict[str, int] = {}
        try:
            before_files = {
                str(p.resolve()): p.stat().st_mtime_ns for p in Path(out).glob("*.xlsx") if p.is_file()
            }
        except OSError:
            before_files = {}

        def _thr():
            generated: list[str] = []
            try:
                splitter = nv_brief.ExcelSplitter(self._safe_log, self._safe_dialog)
                splitter.split(excel, out)
                try:
                    for path in Path(out).glob("*.xlsx"):
                        if not path.is_file():
                            continue
                        key = str(path.resolve())
                        if key not in before_files or path.stat().st_mtime_ns != before_files[key]:
                            generated.append(str(path))
                except OSError:
                    generated = []
            finally:
                mw = self.main
                pi = NAV_PAGE_BRIEFING

                def _done_split(paths=generated):
                    self._brief_split_running = False
                    self._sync_brief_action_buttons()
                    self.e_report_out.setText(out)
                    if len(paths) == 1:
                        self.e_report_excel.setText(paths[0])
                    self.tabs.setCurrentIndex(1)
                    if len(paths) == 1:
                        self.status.setText("简报生成：已带入拆分结果，可直接开始")
                    elif paths:
                        self.status.setText(f"拆分完成：已生成 {len(paths)} 个学院表，请选择其中一个生成简报")
                    else:
                        self.status.setText("拆分完成：请选择输出目录中的学院表生成简报")
                    mw.nav_task_end(pi)

                mw._invoke_on_gui.emit(_done_split)

        # 与经典合并版 BriefingWindow._run_split 一致：标准线程 + 日志/弹窗经 Signal 回主线程
        _start_python_background_job(_thr, self.main)

    def _run_report(self):
        excel = self.e_report_excel.text().strip()
        out = self.e_report_out.text().strip()
        if not excel or not out:
            stitch_msg_warning(self, "提示", "请先选择输入文件和输出文件夹！")
            return
        if not os.path.isfile(excel):
            self._append_log("❌ 指定的 Excel 文件不存在。")
            return
        if not os.path.isdir(out):
            try:
                os.makedirs(out, exist_ok=True)
            except OSError as e:
                self._append_log(f"❌ 无法创建输出目录：{e}")
                return
        self._append_log("\n>>> 启动任务：简报生成")
        self._brief_report_running = True
        self.status.setText("正在抓取活动内容并生成简报…")
        self._sync_brief_action_buttons()
        self.main.nav_task_begin(NAV_PAGE_BRIEFING)
        fetch_timeout = self.sp_brief_timeout.value()
        row_delay_sec = self.sp_brief_delay.value() * 0.1
        summary_max_chars = self.sp_brief_summary.value()
        max_images = self.sp_brief_maximg.value()
        nearby_only = self.cb_brief_nearby_img.isChecked()
        keep_meta = self.cb_brief_keep_activity_info.isChecked()
        full_content = self.cb_brief_full_content.isChecked()
        split_by_activity = self.cb_brief_split_by_activity.isChecked()

        def _thr():
            try:
                gen = nv_brief.ReportGenerator(
                    self._safe_log,
                    self._safe_dialog,
                    fetch_timeout=fetch_timeout,
                    row_delay_sec=row_delay_sec,
                    summary_max_chars=summary_max_chars,
                    max_images_per_article=max_images,
                    nearby_images_only=nearby_only,
                    keep_activity_meta=keep_meta,
                    full_content_mode=full_content,
                    split_by_activity=split_by_activity,
                )
                gen.generate(excel, out)
            finally:
                mw = self.main
                pi = NAV_PAGE_BRIEFING

                def _done_report():
                    self._brief_report_running = False
                    self.status.setText("简报任务已结束，请查看日志和输出文件夹")
                    self._sync_brief_action_buttons()
                    mw.nav_task_end(pi)

                mw._invoke_on_gui.emit(_done_report)

        # 与经典合并版 BriefingWindow._run_report 一致：标准线程（含 requests/抓取）
        _start_python_background_job(_thr, self.main)


class _ClassifyBridge(QObject):
    """发票分类：后台线程日志与完成态回到主线程。"""

    log_line = Signal(str)
    progress = Signal(int, int, str)
    done_ok = Signal(str)
    done_err = Signal(str)


class ClassificationPage(BasePage):
    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self._cancel = threading.Event()
        self._cls_bridge = _ClassifyBridge(self)
        self._cls_bridge.log_line.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        self._cls_bridge.progress.connect(self._on_classify_progress, Qt.ConnectionType.QueuedConnection)
        self._cls_bridge.done_ok.connect(lambda p: self._on_classify_done(True, p), Qt.ConnectionType.QueuedConnection)
        self._cls_bridge.done_err.connect(lambda e: self._on_classify_done(False, e), Qt.ConnectionType.QueuedConnection)
        self._build_ui()

    def _build_ui(self):
        root, pin = self.build_stitch_scaffold(
            "发票整理",
            "按关键词规则整理发票，并生成分组封面与明细表。",
            pinned_footer=True,
        )
        assert pin is not None

        self.e_file = self.stitch_path_row(root, "发票数据表", "", False, "请选择发票 Excel 文件...")

        basic = QFrame()
        basic.setObjectName("stitch_settings")
        bl = QVBoxLayout(basic)
        bl.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["lg"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        bl.setSpacing(11)
        bh = QLabel("基本信息")
        bh.setObjectName("stitch_settings_title")
        bh.setFont(ui_font("title", QFont.Weight.DemiBold, 0.08))
        bl.addWidget(bh)
        r0 = QHBoxLayout()
        r0.setSpacing(14)
        self.e_company = self._stitch_field("公司名称", "示例企业A有限公司")
        self.e_prefix = self._stitch_field("分组名称前缀", "示例设计产业学院产教融合项目")
        r0.addWidget(self.e_company[0], 1)
        r0.addWidget(self.e_prefix[0], 1)
        bl.addLayout(r0)
        root.addWidget(basic)

        self._cls_params_wrap = QFrame()
        self._cls_params_wrap.setObjectName("stitch_settings")
        cpw = QVBoxLayout(self._cls_params_wrap)
        cpw.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        cpw.setSpacing(8)
        self._cls_params_toggle = QPushButton()
        self._cls_params_toggle.setObjectName("section_toggle")
        self._cls_params_toggle.setCheckable(True)
        self._cls_params_toggle.setChecked(False)
        self._cls_params_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cls_params_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        cpw.addWidget(self._cls_params_toggle)

        self._cls_params_inner = QWidget()
        pil = QVBoxLayout(self._cls_params_inner)
        pil.setContentsMargins(0, 4, 0, 0)
        pil.setSpacing(11)
        rules_title = QLabel("分组规则")
        rules_title.setObjectName("stitch_subsection_title")
        pil.addWidget(rules_title)

        r1 = QHBoxLayout()
        r1.setSpacing(14)
        self.e_cover = self._stitch_field("封面序号", "1")
        self.e_start = self._stitch_field("起始序号", "2")
        self._configure_number_field(self.e_cover[1], 1, 100000)
        self._configure_number_field(self.e_start[1], 1, 100000)
        r1.addWidget(self.e_cover[0], 1)
        r1.addWidget(self.e_start[0], 1)
        pil.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(14)
        self.e_base = self._stitch_field("基准金额（元）", "130000")
        self.e_jitter = self._stitch_field("随机波动（元）", "20000")
        self._configure_number_field(self.e_base[1], 0, 1000000000, decimals=2)
        self._configure_number_field(self.e_jitter[1], 0, 1000000000, decimals=2)
        r2.addWidget(self.e_base[0], 1)
        r2.addWidget(self.e_jitter[0], 1)
        pil.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(14)
        self.e_seed = self._stitch_field("随机种子", "42")
        self.e_threshold = self._stitch_field("票据阈值（元）", "700000")
        self._configure_number_field(self.e_seed[1], 0, 2147483647)
        self.e_seed[1].setToolTip("相同输入和参数使用相同随机种子，便于重复检查分组结果")
        self._configure_number_field(self.e_threshold[1], 0, 1000000000, decimals=2)
        r3.addWidget(self.e_seed[0], 1)
        r3.addWidget(self.e_threshold[0], 1)
        pil.addLayout(r3)

        r4 = QHBoxLayout()
        r4.setSpacing(14)
        self.e_group = self._stitch_field("每组票据量（张）", "240")
        self._configure_number_field(self.e_group[1], 1, 1000000)
        r4.addWidget(self.e_group[0], 1)
        r4.addStretch(1)
        pil.addLayout(r4)

        self.cb_color = QCheckBox("明细中为“发票项目”按分类着色")
        self.cb_color.setChecked(True)
        self.cb_color.setFont(ui_font("body"))
        self.cb_hide = QCheckBox("隐藏“预测分类标签”列")
        self.cb_hide.setChecked(True)
        self.cb_hide.setFont(ui_font("body"))
        self.cb_cover_fill = QCheckBox("同步填写封面汇总（会修改封面区域）")
        self.cb_cover_fill.setChecked(False)
        self.cb_cover_fill.setFont(ui_font("body"))
        self.cb_cover_fill.setToolTip(
            "分类保存完成后，按各组「明细」中的开票日期、分类标签等，"
            "自动填写对应「封面」C4～F4（项目类别、服务院校、项目明细占位、时间）。"
            "产教封面「服务院校」为购买方公司名单中随机 2～4 所（不按城市推断）。"
            "仅处理 sheet 名含「产教融合项目」的封面；日志另存为同目录 *_封面汇总日志.jsonl。"
        )
        self.cb_ticket_cover_fill = QCheckBox("同步填写机票封面汇总（会修改机票封面区域）")
        self.cb_ticket_cover_fill.setChecked(False)
        self.cb_ticket_cover_fill.setFont(ui_font("body"))
        self.cb_ticket_cover_fill.setToolTip(
            "在「公司名称」与明细「购买方公司名称」一致前提下，将对应公司的**全部**服务院校名单"
            "写入「机票报销封面」D4；C4/F4 等同原规则。"
            "项目类别固定为：专业调研、人才培养、研学、企业考察；日志另存 *_机票封面汇总日志.jsonl。"
        )
        row_cb = QVBoxLayout()
        row_cb.setSpacing(28)
        col_cb_l = QVBoxLayout()
        col_cb_l.setSpacing(11)
        col_cb_r = QVBoxLayout()
        col_cb_r.setSpacing(11)
        col_cb_l.addWidget(self.cb_color)
        col_cb_l.addWidget(self.cb_hide)
        col_cb_l.addStretch(1)
        col_cb_r.addWidget(self.cb_cover_fill)
        col_cb_r.addWidget(self.cb_ticket_cover_fill)
        row_cb.addLayout(col_cb_l, 1)
        row_cb.addLayout(col_cb_r, 1)
        output_title = QLabel("输出与封面")
        output_title.setObjectName("stitch_subsection_title")
        pil.addWidget(output_title)
        pil.addLayout(row_cb)
        learning_title = QLabel("本地学习维护")
        learning_title.setObjectName("stitch_subsection_title")
        pil.addWidget(learning_title)
        learn_hint = QLabel(
            "持续学习：可在上次生成的结果 Excel 中人工修正「分类标签」，然后对同一路径再次开始处理。"
            "程序会对比预测标签与人工结果，并小幅更新本地关键词权重；学习结果会记录在运行详情中。"
        )
        learn_hint.setObjectName("muted")
        learn_hint.setWordWrap(True)
        learn_hint.setFont(ui_font("caption", QFont.Weight.Normal))
        pil.addWidget(learn_hint)
        learn_row = QHBoxLayout()
        learn_row.setSpacing(10)
        self.lbl_learning_state = QLabel()
        self.lbl_learning_state.setObjectName("muted")
        self.lbl_learning_state.setFont(ui_font("caption"))
        self.lbl_learning_state.setWordWrap(True)
        self.b_reset_learning = AnimatedButton("重置学习记录…", "secondary")
        self.b_reset_learning.setMinimumHeight(32)
        self.b_reset_learning.clicked.connect(self._reset_learning_state)
        learn_row.addWidget(self.lbl_learning_state, 1)
        learn_row.addWidget(self.b_reset_learning, 0)
        pil.addLayout(learn_row)
        self._refresh_learning_state()

        self._cls_params_fold = StitchFoldController(
            self._cls_params_inner,
            self._cls_params_toggle,
            "+ 分组与票据",
            "- 分组与票据",
        )
        self._cls_params_toggle.setToolTip(
            "折叠时使用默认序号、金额波动、票据阈值和分组参数；展开后可按需要调整。"
        )
        self._cls_params_toggle.toggled.connect(self._cls_params_fold.on_toggled)
        cpw.addWidget(self._cls_params_fold.clip_host())
        self._cls_params_fold.apply_initial_collapsed()
        self._advanced_summary = bind_setting_summary(cpw, self._cls_params_toggle,
            lambda: f"每组 {self.e_group[1].text()} 张 · 基准 {self.e_base[1].text()} 元 · 产教封面{'填写' if self.cb_cover_fill.isChecked() else '不填写'} · 机票封面{'填写' if self.cb_ticket_cover_fill.isChecked() else '不填写'}",
            self.e_group[1], self.e_base[1], self.cb_cover_fill, self.cb_ticket_cover_fill)
        self._bind_validation_fold(self._cls_params_fold, self._cls_params_inner)
        root.addWidget(self._cls_params_wrap)

        log = QFrame()
        log.setObjectName("card_group")
        ll = QVBoxLayout(log)
        ll.setContentsMargins(
            TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"]
        )
        ll.setSpacing(TOKENS["space"]["sm"])
        lb_log = QLabel("处理详情")
        lb_log.setObjectName("classify_log_title")
        lb_log.setFont(ui_font("label", QFont.Weight.DemiBold, 0.15))
        self.log = QTextEdit()
        self.log.setObjectName("stitch_run_log")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setMaximumHeight(240)
        ll.addWidget(lb_log)
        ll.addWidget(self.log, 1)
        root.addWidget(log)

        self.status = self.make_status_label("状态：待命")
        pin.addWidget(self.status)

        bf = QHBoxLayout()
        bf.setSpacing(14)
        self.b_start = AnimatedButton("开始整理", "primary")
        set_mono_button_icon(self.b_start, "play", 18, color_role="primary")
        self.b_start.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_start.setMinimumHeight(42)
        self.b_start.clicked.connect(self._run_classify)
        self.register_primary_action(self.b_start)
        self.b_footer_open = AnimatedButton("打开结果文件夹", "secondary")
        set_mono_button_icon(self.b_footer_open, "folder", 18)
        self.b_footer_open.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_footer_open.setMinimumHeight(42)
        self.b_footer_open.clicked.connect(self._open_output)
        self.b_stop = AnimatedButton("停止", "secondary")
        set_mono_button_icon(self.b_stop, "stop", 18)
        self.b_stop.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_stop.setMinimumHeight(42)
        self.b_stop.setEnabled(False)
        self.b_stop.setToolTip("中断处理：在进度推进时生效（底层每次上报进度都会检测取消）")
        self.b_stop.clicked.connect(self._stop_classify)
        bf.addWidget(self.b_footer_open, 1)
        bf.addWidget(self.b_stop, 1)
        bf.addWidget(self.b_start, 2)
        pin.addLayout(bf)

        root.addStretch(1)
        self.add_page_deco(root, "发票")
        self.apply_classify_defaults_from_disk()

    def apply_classify_defaults_from_disk(self) -> None:
        d = nv_ad.load_classify_form_defaults()
        self.e_company[1].setText(d["company_name"])
        self.e_prefix[1].setText(d["group_prefix"])

    def _refresh_learning_state(self) -> None:
        summary = nv_cls.keyword_learning_summary()
        count = int(summary.get("feedback_count", 0))
        changed = int(summary.get("changed_weights", 0)) + int(summary.get("changed_thresholds", 0))
        if count or changed:
            self.lbl_learning_state.setText(f"学习状态：已记录 {count} 条人工反馈，调整 {changed} 项规则")
        else:
            self.lbl_learning_state.setText("学习状态：尚无人工反馈，当前使用内置规则")

    def _reset_learning_state(self) -> None:
        if not stitch_msg_question(
            self,
            "重置学习记录",
            "将清除本机保存的人工反馈和关键词权重，恢复内置分类规则。此操作不会删除 Excel 文件。",
            severity="warning",
            yes_text="重置",
            no_text="取消",
            default_yes=False,
        ):
            return
        try:
            nv_cls.reset_keyword_learning_state()
        except OSError as exc:
            stitch_msg_warning(self, "无法重置", str(exc))
            return
        self._refresh_learning_state()
        self.status.setText("状态：学习记录已重置")

    def _set_classify_busy(self, busy: bool) -> None:
        self._set_path_entry_busy(self.e_file, busy)
        self._set_widgets_busy(busy, self.e_company[0], self.e_prefix[0], self._cls_params_wrap)
        self.b_start.setEnabled(not busy)
        self.b_stop.setEnabled(busy)
        self.b_footer_open.setEnabled(not busy)

    def _browse_into(self, entry: QLineEdit, is_dir: bool):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "选择文件夹")
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "发票数据表", str(Path.cwd()), "Excel 文件 (*.xlsx *.xls)"
            )
        if p:
            entry.setText(p)

    def _open_output(self):
        p = self.e_file.text().strip()
        if p and os.path.isfile(p):
            open_local_folder(self, os.path.dirname(os.path.abspath(p)))
        else:
            stitch_msg_warning(self, '无法打开文件夹', '请先选择存在的发票数据文件，再打开其所在文件夹。')

    def _append_log(self, msg: str):
        textedit_append_autoscroll(self.log, msg)

    def _safe_log(self, msg: str):
        self._cls_bridge.log_line.emit(msg)

    @Slot(int, int, str)
    def _on_classify_progress(self, done: int, total: int, message: str) -> None:
        detail = f" · {message}" if message else ""
        if total > 0:
            self.status.setText(f"状态：处理中 {done}/{total}{detail}")
            self.status.set_progress(done, total)
        else:
            self.status.setText(f"状态：处理中{detail}")

    def _stop_classify(self):
        self._cancel.set()
        self._safe_log(">>> 已请求停止（将在当前步骤结束后退出）…")

    def _run_classify(self):
        path = self.e_file.text().strip()
        if not path or not os.path.isfile(path):
            self.status.setText("状态：请先选择有效的 Excel 文件")
            return
        try:
            base = float(self._read_number_field(self.e_base[1], "基准金额", 0, 1000000000))
            jitter = float(self._read_number_field(self.e_jitter[1], "随机波动", 0, 1000000000))
            seed = int(self._read_number_field(self.e_seed[1], "随机种子", 0, 2147483647, integer=True))
            th = float(self._read_number_field(self.e_threshold[1], "票据阈值", 0, 1000000000))
            gs = int(self._read_number_field(self.e_group[1], "每组票据量", 1, 1000000, integer=True))
            cover_series = int(self._read_number_field(self.e_cover[1], "封面序号", 1, 100000, integer=True))
            start_index = int(self._read_number_field(self.e_start[1], "起始序号", 1, 100000, integer=True))
        except ValueError as exc:
            self.status.setText(f"状态：{exc}")
            return

        color_cell = self.cb_color.isChecked()
        hide_pred = self.cb_hide.isChecked()
        sync_cover_fill = self.cb_cover_fill.isChecked()
        sync_ticket_cover_fill = self.cb_ticket_cover_fill.isChecked()
        company = self.e_company[1].text().strip()
        prefix = self.e_prefix[1].text().strip()

        self._cancel.clear()
        self._set_classify_busy(True)
        self.status.setStyleSheet("")
        self.status.setText("状态：处理中…")
        self._safe_log("\n>>> 启动任务：发票分类处理")
        self._safe_log("（可随时点击「停止」中断；在底层进度上报时生效。）")
        self.main.nav_task_begin(NAV_PAGE_CLASSIFY)

        def progress_cb(_done, _total, msg):
            message = str(msg)
            self._cls_bridge.log_line.emit(message)
            self._cls_bridge.progress.emit(int(_done or 0), int(_total or 0), message)

        def work():
            try:
                out = nv_cls.process(
                    Path(path),
                    base=base,
                    jitter=jitter,
                    seed=seed,
                    insert_blank_between_groups=True,
                    enable_amount_fallback=True,
                    color_category_cell=color_cell,
                    hide_pred_label=hide_pred,
                    ticket_split_threshold=th,
                    ticket_group_size=gs,
                    output_dir=None,
                    progress_cb=progress_cb,
                    cancel_flag=self._cancel,
                    company_name=company or None,
                    group_cover_prefix=prefix or None,
                    cover_series=cover_series,
                    start_index_for_group=start_index,
                )
                out_path = Path(out)
                if sync_cover_fill:
                    self._cls_bridge.log_line.emit("\n>>> 同步填写封面汇总（明细 → 封面 C4～F4）…")
                    log_cf = out_path.with_name(out_path.stem + "_封面汇总日志.jsonl")
                    try:
                        nv_cf.run(
                            out_path,
                            log_cf,
                            output_xlsx=None,
                            settings_overrides={
                                "category_mode": "rules",
                                "random_seed": seed,
                            },
                            ui_company_name=company or None,
                        )
                        self._cls_bridge.log_line.emit(f"✅ 封面汇总已写入同一 xlsx；JSONL：{log_cf}")
                    except Exception as e:
                        self._cls_bridge.log_line.emit(
                            f"⚠️ 封面汇总填写失败（分类结果文件已保存，可取消勾选后单独排查）：{e}"
                        )
                if sync_ticket_cover_fill:
                    self._cls_bridge.log_line.emit("\n>>> 同步填写机票封面汇总（明细 → 机票封面 C4～F4）…")
                    log_tk = out_path.with_name(out_path.stem + "_机票封面汇总日志.jsonl")
                    try:
                        nv_cf.run_ticket_cover_fill(
                            out_path,
                            log_tk,
                            ui_company_name=company or None,
                            output_xlsx=None,
                        )
                        self._cls_bridge.log_line.emit(
                            f"✅ 机票封面汇总已写入同一 xlsx；JSONL：{log_tk}"
                        )
                    except Exception as e:
                        self._cls_bridge.log_line.emit(
                            f"⚠️ 机票封面汇总填写失败（可取消勾选后单独排查）：{e}"
                        )
                self._cls_bridge.done_ok.emit(str(out_path))
            except Exception as e:
                self._cls_bridge.done_err.emit(str(e))

        _start_qt_background_job(work, self.main)

    def _on_classify_done(self, ok: bool, msg: str):
        self.main.nav_task_end(NAV_PAGE_CLASSIFY)
        self._set_classify_busy(False)
        self._refresh_learning_state()
        if ok:
            self.main._last_classified_output_path = msg
            self._append_log(f"\n✅ 已完成：{msg}")
            self.status.setText("状态：完成，结果已生成")
        else:
            self._append_log(f"\n❌ {msg}")
            if "用户已取消" in msg or msg.strip() == "用户已取消":
                self.status.setText("状态：已停止，任务未继续保存结果")
            else:
                self.status.setText("状态：失败")
                nv_biz.show_error("发票分类失败", msg)


def _api_settings_field_label(text: str, buddy: Optional[QWidget] = None) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("stitch_field_label")
    lb.setFont(ui_font("label", QFont.Weight.Medium, 0.12))
    lb.setMinimumWidth(128)
    if buddy is not None:
        lb.setBuddy(buddy)
        if not buddy.accessibleName():
            buddy.setAccessibleName(text)
    return lb


class CompanySchoolsEditor(QWidget):
    """面向业务用户的公司与服务院校表格编辑器。"""

    def __init__(self, mapping: dict[str, list[str]], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("company_schools_table")
        self.table.setHorizontalHeaderLabels(("公司名称", "服务院校（多个院校用逗号分隔）"))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(260)
        lay.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_btn = AnimatedButton("添加公司", "secondary")
        add_btn.clicked.connect(self.add_empty_row)
        remove_btn = AnimatedButton("删除选中", "danger")
        remove_btn.clicked.connect(self.remove_selected_rows)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.set_mapping(mapping)

    def set_mapping(self, mapping: dict[str, list[str]]) -> None:
        self.table.setRowCount(0)
        for company, schools in mapping.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(company)))
            self.table.setItem(row, 1, QTableWidgetItem("、".join(str(x) for x in schools)))

    def add_empty_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def remove_selected_rows(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows and self.table.currentRow() >= 0:
            rows.add(self.table.currentRow())
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)

    def mapping(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for row in range(self.table.rowCount()):
            company_item = self.table.item(row, 0)
            schools_item = self.table.item(row, 1)
            company = (company_item.text() if company_item else "").strip()
            raw_schools = (schools_item.text() if schools_item else "").strip()
            if not company and not raw_schools:
                continue
            if not company:
                raise ValueError(f"第 {row + 1} 行缺少公司名称")
            schools = [
                value.strip()
                for value in re.split(r"[、,，;；\n]+", raw_schools)
                if value.strip()
            ]
            if not schools:
                raise ValueError(f"“{company}”尚未填写服务院校")
            if company in result:
                raise ValueError(f"公司名称重复：{company}")
            result[company] = schools
        if not result:
            raise ValueError("请至少保留一条公司与院校对应关系")
        return result


def _company_school_mapping_from_raw(raw: str, fallback_raw: str) -> dict[str, list[str]]:
    for candidate in (raw, fallback_raw):
        try:
            return nv_cf.parse_ticket_company_schools_obj(json.loads(candidate))
        except Exception:
            continue
    return {}


class AppSettingsDialog(QDialog):
    """设置：DeepSeek API、公司→院校（机票/产教）、分类页默认公司与分组（无边框 + 顶栏拖移）。"""

    connection_checked = Signal(bool, str)

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self.setObjectName("stitch_frameless_dlg")
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(600, 680)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        stitch_dialog_prepend_chrome_topbar(self, outer, "设置", on_traffic_close=self.reject)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 16, 24, 20)
        lay.setSpacing(12)
        outer.addWidget(body, 1)

        tabs = QTabWidget()
        tabs.setObjectName("settings_tabs")
        tabs.setDocumentMode(True)
        lay.addWidget(tabs, 1)

        # --- Tab: DeepSeek API ---
        tab_api = QWidget()
        api_lay = QVBoxLayout(tab_api)
        api_lay.setContentsMargins(8, 8, 8, 8)
        api_lay.setSpacing(10)
        snap = nv_ds.get_deepseek_api_settings_for_dialog()
        hint_lines = [
            "填写DeepSeek API 密钥 后，活动方案即可使用 AI 生成功能。",
            "可选择 deepseek-v4-flash 或 deepseek-v4-pro，默认使用 Flash。",
            "此处配置用于活动方案；Agent 工作台的模型在 Harness 设置中配置。",
        ]
        if snap.get("env_key_configured"):
            hint_lines.append(
                "已检测到环境变量 DEEPSEEK_API_KEY：下方 Key 留空时，仍可使用环境变量中的 Key。"
            )
        hint_api = QLabel("\n".join(hint_lines))
        hint_api.setObjectName("muted")
        hint_api.setWordWrap(True)
        hint_api.setFont(ui_font("body"))
        api_lay.addWidget(hint_api)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._e_key = QLineEdit()
        self._e_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._e_key.setPlaceholderText("sk-…（可留空以仅用环境变量）")
        self._e_key.setText(str(snap.get("deepseek_api_key") or ""))
        self._e_key.setFont(ui_font("body"))
        show_key = QCheckBox("显示")
        show_key.setFont(ui_font("label"))
        show_key.toggled.connect(
            lambda c: self._e_key.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
            )
        )
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self._e_key, 1)
        key_row.addWidget(show_key)
        key_w = QWidget()
        key_w.setLayout(key_row)
        form.addRow(_api_settings_field_label("DeepSeek API 密钥", self._e_key), key_w)

        self._cb_model = QComboBox()
        self._cb_model.setObjectName("stitch_combo")
        self._cb_model.setEditable(True)
        self._cb_model.setFont(ui_font("body"))
        for m in nv_ds.MODELS:
            self._cb_model.addItem(m)
        cur_model = str(snap.get("deepseek_model") or nv_ds.DEFAULT_MODEL).strip() or nv_ds.DEFAULT_MODEL
        if self._cb_model.findText(cur_model, Qt.MatchFlag.MatchExactly) < 0:
            self._cb_model.insertItem(0, cur_model)
        self._cb_model.setCurrentText(cur_model)
        form.addRow(_api_settings_field_label("DeepSeek模型", self._cb_model), self._cb_model)

        api_lay.addLayout(form)
        connection_row = QHBoxLayout()
        self._connection_button = AnimatedButton("测试连接", "secondary")
        self._connection_button.setToolTip("仅查询可用模型，不生成内容，也不保存当前填写的设置")
        self._connection_status = QLabel("尚未测试连接")
        self._connection_status.setWordWrap(True)
        self._connection_status.setObjectName("path_feedback")
        connection_row.addWidget(self._connection_button)
        connection_row.addWidget(self._connection_status, 1)
        api_lay.addLayout(connection_row)
        self._connection_button.clicked.connect(self._test_connection)
        self.connection_checked.connect(self._connection_done)
        self._e_key.textChanged.connect(self._reset_connection_status)
        self._cb_model.currentTextChanged.connect(self._reset_connection_status)
        self._api_advanced_toggle = QPushButton("高级连接设置")
        self._api_advanced_toggle.setObjectName("section_toggle")
        self._api_advanced_toggle.setCheckable(True)
        api_lay.addWidget(self._api_advanced_toggle)
        self._api_advanced = QWidget()
        form = QFormLayout(self._api_advanced)
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._api_advanced.setVisible(False)
        self._api_advanced_toggle.toggled.connect(self._api_advanced.setVisible)
        self._sp_max = QSpinBox()
        self._sp_max.setRange(1, nv_ds.CHAT_COMPLETION_MAX_TOKENS_CEILING)
        self._sp_max.setSingleStep(128)
        self._sp_max.setValue(int(snap.get("max_tokens") or 2000))
        self._sp_max.setFont(ui_font("body"))
        self._sp_max.setToolTip("控制单次生成内容的长度上限；通常保持默认即可")
        form.addRow(_api_settings_field_label("最大输出长度（Token）", self._sp_max), self._sp_max)

        self._sp_conn = QSpinBox()
        self._sp_conn.setRange(1, 600)
        self._sp_conn.setSuffix(" 秒")
        self._sp_conn.setValue(int(snap.get("connect_timeout") or 30))
        self._sp_conn.setFont(ui_font("body"))
        form.addRow(_api_settings_field_label("连接超时", self._sp_conn), self._sp_conn)

        self._sp_read = QSpinBox()
        self._sp_read.setRange(1, 7200)
        self._sp_read.setSuffix(" 秒")
        self._sp_read.setValue(int(snap.get("read_timeout") or 480))
        self._sp_read.setFont(ui_font("body"))
        form.addRow(_api_settings_field_label("读取超时", self._sp_read), self._sp_read)

        self._sp_net = QSpinBox()
        self._sp_net.setRange(1, 30)
        self._sp_net.setValue(int(snap.get("net_retry_times") or 3))
        self._sp_net.setFont(ui_font("body"))
        form.addRow(_api_settings_field_label("网络重试次数", self._sp_net), self._sp_net)

        self._sp_srv = QSpinBox()
        self._sp_srv.setRange(1, 30)
        self._sp_srv.setValue(int(snap.get("server_retry_times") or 3))
        self._sp_srv.setFont(ui_font("body"))
        form.addRow(_api_settings_field_label("服务重试次数", self._sp_srv), self._sp_srv)

        api_lay.addWidget(self._api_advanced)
        self._advanced_summary = bind_setting_summary(api_lay, self._api_advanced_toggle,
            lambda: f"连接 {self._sp_conn.value()} 秒 · 读取 {self._sp_read.value()} 秒 · 网络重试 {self._sp_net.value()} 次 · 服务重试 {self._sp_srv.value()} 次",
            self._sp_conn, self._sp_read, self._sp_net, self._sp_srv)
        api_lay.addStretch(1)
        tabs.addTab(tab_api, "DeepSeek API")

        # --- Tab: 公司对应学校（机票）— ticket_company_schools.json ---
        tab_ticket = QWidget()
        t_lay = QVBoxLayout(tab_ticket)
        t_lay.setContentsMargins(8, 8, 8, 8)
        t_lay.setSpacing(8)
        hint_t = QLabel(
            "维护购买方公司与服务院校的对应关系，用于机票封面汇总和批量方案。"
            "每行填写一家公司；多个院校可用逗号或顿号分隔。"
        )
        hint_t.setObjectName("muted")
        hint_t.setWordWrap(True)
        hint_t.setFont(ui_font("body"))
        t_lay.addWidget(hint_t)
        ticket_mapping = _company_school_mapping_from_raw(
            nv_cf.read_ticket_company_schools_file_raw(),
            nv_cf.default_ticket_company_schools_json_text(),
        )
        self._ticket_editor = CompanySchoolsEditor(ticket_mapping)
        t_lay.addWidget(self._ticket_editor, 1)
        t_btn_row = QHBoxLayout()
        t_btn_row.setSpacing(10)
        b_reset_ticket = AnimatedButton("恢复内置默认", "secondary")
        b_reset_ticket.setMinimumHeight(34)
        b_reset_ticket.clicked.connect(self._reset_ticket_json_editor)
        t_btn_row.addWidget(b_reset_ticket)
        t_btn_row.addStretch(1)
        t_lay.addLayout(t_btn_row)
        tabs.addTab(tab_ticket, "机票院校配置")

        # --- Tab: 公司对应学校（产教）— project_company_schools.json ---
        tab_proj = QWidget()
        p_lay = QVBoxLayout(tab_proj)
        p_lay.setContentsMargins(8, 8, 8, 8)
        p_lay.setSpacing(8)
        hint_p = QLabel(
            "维护产教融合封面使用的公司与院校范围。生成封面时，程序会从对应公司的院校中抽取 2～4 所；"
            "没有匹配公司时，服务院校将留空。"
        )
        hint_p.setObjectName("muted")
        hint_p.setWordWrap(True)
        hint_p.setFont(ui_font("body"))
        p_lay.addWidget(hint_p)
        project_mapping = _company_school_mapping_from_raw(
            nv_cf.read_project_company_schools_file_raw(),
            nv_cf.default_project_company_schools_json_text(),
        )
        self._project_editor = CompanySchoolsEditor(project_mapping)
        p_lay.addWidget(self._project_editor, 1)
        p_btn_row = QHBoxLayout()
        p_btn_row.setSpacing(10)
        b_reset_proj = AnimatedButton("恢复内置默认", "secondary")
        b_reset_proj.setMinimumHeight(34)
        b_reset_proj.clicked.connect(self._reset_project_json_editor)
        p_btn_row.addWidget(b_reset_proj)
        p_btn_row.addStretch(1)
        p_lay.addLayout(p_btn_row)
        tabs.addTab(tab_proj, "产教院校配置")

        # --- Tab: 分类页默认（非院校表）— invoice_classify_defaults.json ---
        tab_cls = QWidget()
        c_lay = QVBoxLayout(tab_cls)
        c_lay.setContentsMargins(8, 8, 8, 8)
        c_lay.setSpacing(10)
        hint_c = QLabel(
            "设置打开「发票整理」时自动填入的公司名称与分组名称前缀。"
            "公司对应的服务院校请分别在「机票院校」和「产教院校」页维护。"
        )
        hint_c.setObjectName("muted")
        hint_c.setWordWrap(True)
        hint_c.setFont(ui_font("body"))
        c_lay.addWidget(hint_c)
        c_form = QFormLayout()
        c_form.setSpacing(10)
        c_form.setHorizontalSpacing(12)
        c_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        defs = nv_ad.load_classify_form_defaults()
        self._e_def_company = QLineEdit()
        self._e_def_company.setText(defs["company_name"])
        self._e_def_company.setFont(ui_font("body"))
        c_form.addRow(_api_settings_field_label("默认公司名称", self._e_def_company), self._e_def_company)
        self._e_def_prefix = QLineEdit()
        self._e_def_prefix.setText(defs["group_prefix"])
        self._e_def_prefix.setFont(ui_font("body"))
        c_form.addRow(_api_settings_field_label("默认分组名称前缀", self._e_def_prefix), self._e_def_prefix)
        c_lay.addLayout(c_form)
        c_lay.addStretch(1)
        tabs.addTab(tab_cls, "发票默认设置")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        b_cancel = AnimatedButton("取消", "secondary")
        b_cancel.setMinimumHeight(38)
        b_cancel.clicked.connect(self.reject)
        b_save = AnimatedButton("保存", "primary")
        b_save.setMinimumHeight(38)
        b_save.clicked.connect(self._save)
        b_save.setDefault(True)
        b_save.setAutoDefault(True)
        btn_row.addStretch(1)
        btn_row.addWidget(b_cancel)
        btn_row.addWidget(b_save)
        lay.addLayout(btn_row)

    def changeEvent(self, event: QEvent) -> None:
        _stitch_dialog_change_event(self, event)
        super().changeEvent(event)

    def _reset_connection_status(self):
        self._connection_status.setText("配置已更改，尚未测试")
        self._connection_status.setProperty("state", "")
        self._connection_status.style().unpolish(self._connection_status)
        self._connection_status.style().polish(self._connection_status)

    def _test_connection(self):
        key, model = self._e_key.text(), self._cb_model.currentText()
        self._connection_button.setEnabled(False)
        self._e_key.setEnabled(False)
        self._cb_model.setEnabled(False)
        self._connection_status.setText("正在查询可用模型…")
        self._connection_status.setProperty("state", "")
        self._connection_status.style().unpolish(self._connection_status)
        self._connection_status.style().polish(self._connection_status)

        def work():
            ok, message = nv_ds.test_api_connection(key, model)
            try:
                self.connection_checked.emit(ok, message)
            except RuntimeError:
                pass  # Dialog was destroyed while the bounded request finished.
        _start_python_background_job(work, self)

    def _connection_done(self, ok, message):
        self._connection_button.setEnabled(True)
        self._e_key.setEnabled(True)
        self._cb_model.setEnabled(True)
        self._connection_status.setText(message)
        self._connection_status.setProperty("state", "valid" if ok else "invalid")
        self._connection_status.style().unpolish(self._connection_status)
        self._connection_status.style().polish(self._connection_status)

    def _reset_ticket_json_editor(self) -> None:
        mapping = nv_cf.parse_ticket_company_schools_obj(
            json.loads(nv_cf.default_ticket_company_schools_json_text())
        )
        self._ticket_editor.set_mapping(mapping)

    def _reset_project_json_editor(self) -> None:
        mapping = nv_cf.parse_ticket_company_schools_obj(
            json.loads(nv_cf.default_project_company_schools_json_text())
        )
        self._project_editor.set_mapping(mapping)

    def _save(self) -> None:
        try:
            parsed_ticket = self._ticket_editor.mapping()
        except Exception as e:
            stitch_msg_critical(self, "机票院校设置不完整", str(e))
            return
        try:
            parsed_project = self._project_editor.mapping()
        except Exception as e:
            stitch_msg_critical(self, "产教院校设置不完整", str(e))
            return
        try:
            nv_ds.save_deepseek_api_settings_from_dialog(
                deepseek_api_key=self._e_key.text(),
                deepseek_model=self._cb_model.currentText().strip(),
                max_tokens=self._sp_max.value(),
                connect_timeout=self._sp_conn.value(),
                read_timeout=self._sp_read.value(),
                net_retry_times=self._sp_net.value(),
                server_retry_times=self._sp_srv.value(),
            )
        except Exception as e:
            stitch_msg_critical(self, "API 设置保存失败", str(e))
            return
        try:
            nv_cf.save_ticket_company_schools_file(parsed_ticket)
            nv_cf.save_project_company_schools_file(parsed_project)
            nv_ad.save_classify_form_defaults(
                self._e_def_company.text(), self._e_def_prefix.text()
            )
        except Exception as e:
            stitch_msg_critical(self, "规则文件写入失败", str(e))
            return
        mw = self.parentWidget()
        if mw is not None:
            w = mw.stack.widget(NAV_PAGE_CLASSIFY)
            if hasattr(w, "apply_classify_defaults_from_disk"):
                w.apply_classify_defaults_from_disk()
        stitch_msg_information(
            self,
            "已保存",
            "DeepSeek配置、公司院校关系和发票分类默认值已保存。",
        )
        self.accept()


class _ActivityPlanWorkerBridge(QObject):
    """后台线程只 emit 信号，由主线程槽函数更新界面（避免 QTimer 在工作线程误触 UI）。"""

    log_line = Signal(str)
    finished_ok = Signal(str)
    finished_err = Signal(str)
    batch_finished_ok = Signal(object)
    batch_finished_err = Signal(str)


class ActivityPlanPreviewDialog(QDialog):
    """与 CTK「活动方案预览与保存」一致：大窗口编辑、Markdown 导出、按原规则生成 Word 封面与正文。"""

    body_changed = Signal(str)

    def __init__(
        self,
        main: "MainWindow",
        initial_body: str,
        service_college: str = "",
        activity_type: str = "",
        activity_time: str = "",
    ):
        super().__init__(main)
        self._service_college = (service_college or "").strip()
        self._activity_type = (activity_type or "").strip()
        self._activity_time = (activity_time or "").strip()

        self.setObjectName("stitch_frameless_dlg")
        self.setWindowTitle("活动方案预览与保存")
        self.resize(960, 780)
        self.setMinimumSize(720, 560)
        self.setModal(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        stitch_dialog_prepend_chrome_topbar(self, outer, "活动方案预览与保存")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 16, 24, 20)
        lay.setSpacing(12)
        outer.addWidget(body, 1)

        hint = QLabel(
            "正文支持 Markdown（# 一级节、## 二级、- 列表等）。保存 Word 时封面主标题优先从正文「项目名称：/活动名称：」识别；"
            "也可在下方填写「封面主标题」覆盖识别结果。关闭窗口后，正文会同步回主界面。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setFont(ui_font("body"))
        hint.setMaximumWidth(760)
        lay.addWidget(hint)

        cover_row = QHBoxLayout()
        cover_row.setSpacing(10)
        lb_cover = QLabel("封面主标题（可选）")
        lb_cover.setObjectName("stitch_field_label")
        lb_cover.setFont(ui_font("label", QFont.Weight.Medium, 0.12))
        lb_cover.setFixedWidth(120)
        self._e_cover = QLineEdit()
        self._e_cover.setPlaceholderText("留空则根据正文自动识别；填写则保存 Word 时以此为准")
        self._e_cover.setFont(ui_font("body"))
        cover_row.addWidget(lb_cover, 0)
        cover_row.addWidget(self._e_cover, 1)
        lay.addLayout(cover_row)

        self._lbl_detect = QLabel("")
        self._lbl_detect.setObjectName("muted")
        self._lbl_detect.setWordWrap(True)
        self._lbl_detect.setFont(ui_font("label"))
        lay.addWidget(self._lbl_detect)

        lb = QLabel("活动策划方案正文（可编辑）")
        lb.setFont(ui_font("title", QFont.Weight.DemiBold))
        lay.addWidget(lb)

        self._edit = QTextEdit()
        self._edit.setObjectName("types_box")
        self._edit.setFont(ui_font("body"))
        self._edit.setPlainText(initial_body or "")
        self._edit.textChanged.connect(self._refresh_detected_title)
        self._edit.textChanged.connect(self._emit_body_changed)
        lay.addWidget(self._edit, 1)
        self._refresh_detected_title()

        row = QHBoxLayout()
        row.setSpacing(10)
        b_close = AnimatedButton("关闭", "secondary")
        b_close.setMinimumHeight(38)
        b_close.clicked.connect(self.close)
        b_export = AnimatedButton("导出 Markdown…", "secondary")
        b_export.setMinimumHeight(38)
        b_export.clicked.connect(self._export_md)
        b_word = AnimatedButton("保存为 Word 文档…", "primary")
        b_word.setMinimumHeight(38)
        b_word.clicked.connect(self._save_docx)
        row.addWidget(b_close)
        row.addStretch(1)
        row.addWidget(b_export)
        row.addWidget(b_word)
        lay.addLayout(row)

    def changeEvent(self, event: QEvent) -> None:
        _stitch_dialog_change_event(self, event)
        super().changeEvent(event)

    def _refresh_detected_title(self) -> None:
        raw = nv_ap_docx.extract_project_title_from_body(self._edit.toPlainText())
        if raw:
            full = nv_ap_docx.normalize_cover_activity_title(raw)
            self._lbl_detect.setText(f"从正文识别：{raw} → 封面将显示为「{full}」")
        else:
            self._lbl_detect.setText("从正文识别：未找到「项目名称：」或「活动名称：」，将使用「活动策划方案」或您填写的封面主标题。")

    def _emit_body_changed(self) -> None:
        self.body_changed.emit(self._edit.toPlainText() or "")

    def body_text(self) -> str:
        return self._edit.toPlainText() or ""

    def set_body(self, text: str) -> None:
        self._edit.blockSignals(True)
        self._edit.setPlainText(text or "")
        self._edit.blockSignals(False)
        self._refresh_detected_title()

    def set_context(self, service_college: str, activity_type: str, activity_time: str) -> None:
        self._service_college = (service_college or "").strip()
        self._activity_type = (activity_type or "").strip()
        self._activity_time = (activity_time or "").strip()

    def _export_md(self):
        body = self._edit.toPlainText()
        if not (body or "").strip():
            return
        default = f"活动方案_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        p, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", str(Path.cwd() / default), "Markdown (*.md)")
        if not p:
            return
        try:
            Path(p).write_text(body, encoding="utf-8")
            nv_biz.show_info("导出成功", p)
        except OSError as e:
            nv_biz.show_error("导出失败", str(e))

    def _save_docx(self) -> None:
        body_text = self._edit.toPlainText().strip()
        if not body_text:
            nv_biz.show_error("保存失败", "正文为空。")
            return
        override = self._e_cover.text().strip()
        ext = nv_ap_docx.extract_project_title_from_body(body_text)
        stem = nv_ap_docx.normalize_cover_activity_title(override or ext or "")
        default = nv_ap_docx.safe_filename(f"{stem}_活动方案_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        p, _ = QFileDialog.getSaveFileName(
            self, "保存活动方案", str(Path.cwd() / f"{default}.docx"), "Word 文档 (*.docx)"
        )
        if not p:
            return
        try:
            nv_ap_docx.save_activity_plan_to_docx(
                p,
                "",
                self._service_college,
                self._activity_type,
                self._activity_time,
                "",
                body_text,
                cover_title_override=override or None,
            )
            nv_biz.show_info("保存成功", p)
        except Exception as e:
            nv_biz.show_error("保存失败", str(e))


class ActivityPlanPage(BasePage):
    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self._plan_body = ""
        self._plan_body_before_run = ""
        self._last_plan_context: tuple[str, str, str] = ("", "", "")
        self._preview_dlg: Optional[ActivityPlanPreviewDialog] = None
        self._plan_cancel = threading.Event()
        self._batch_cancel = threading.Event()
        self._plan_bridge = _ActivityPlanWorkerBridge(self)
        self._plan_bridge.log_line.connect(self._append_plan_output_line)
        self._plan_bridge.finished_ok.connect(self._on_plan_done_ok)
        self._plan_bridge.finished_err.connect(self._on_plan_done_err)
        self._plan_bridge.batch_finished_ok.connect(
            self._on_batch_plan_done_ok, Qt.ConnectionType.QueuedConnection
        )
        self._plan_bridge.batch_finished_err.connect(
            self._on_batch_plan_done_err, Qt.ConnectionType.QueuedConnection
        )
        self._build_ui()

    def _build_ui(self):
        root, pin = self.build_stitch_scaffold(
            "活动方案",
            "填写活动信息生成单份方案，也可从发票分类结果中批量生成 Word 方案。",
            fill_viewport=True,
            pinned_footer=True,
        )
        assert pin is not None

        form = QFrame()
        form.setObjectName("stitch_settings")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["lg"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        fl.setSpacing(11)
        fh = QLabel("活动信息")
        fh.setObjectName("stitch_settings_title")
        fh.setFont(ui_font("title", QFont.Weight.DemiBold, 0.08))
        fl.addWidget(fh)

        # 与 CTK「活动方案生成助手」一致：活动类型 → 专业名称 → 活动时间（周期）→ 服务院校
        r1 = QHBoxLayout()
        r1.setSpacing(14)
        self.e_type = self._stitch_field("活动类型", "专业讲座、论坛、师资培训、访企拓岗")
        self.e_major = self._stitch_field("专业名称", "艺术设计")
        r1.addWidget(self.e_type[0], 1)
        r1.addWidget(self.e_major[0], 1)
        fl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(14)
        self.e_time = self._stitch_field("活动时间（周期）", "2026年4月")
        self.e_college = self._stitch_field("服务院校", "示例院校15")
        r2.addWidget(self.e_time[0], 1)
        r2.addWidget(self.e_college[0], 1)
        fl.addLayout(r2)

        self.mode_tabs = QTabBar()
        self.mode_tabs.setDrawBase(False)
        self.mode_tabs.setObjectName("plan_modes")
        self.mode_tabs.setExpanding(False)
        self.mode_tabs.addTab("单份生成")
        self.mode_tabs.addTab("批量生成")
        root.addWidget(self.mode_tabs)
        self._plan_heading = root.itemAt(0).widget()
        self._plan_form = form
        self._reading_toggle = QPushButton("返回修改活动信息")
        self._reading_toggle.setObjectName("section_toggle")
        self._reading_toggle.setCheckable(True)
        self._reading_toggle.setAccessibleName("切换方案阅读与参数编辑")
        self._reading_toggle.toggled.connect(self._set_reading_mode)
        root.addWidget(self._reading_toggle)
        self._reading_toggle.hide()
        root.addWidget(form)

        self._plan_opts_wrap = QFrame()
        self._plan_opts_wrap.setObjectName("stitch_settings")
        pow_l = QVBoxLayout(self._plan_opts_wrap)
        pow_l.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        pow_l.setSpacing(8)
        self._plan_opts_toggle = QPushButton()
        self._plan_opts_toggle.setObjectName("section_toggle")
        self._plan_opts_toggle.setCheckable(True)
        self._plan_opts_toggle.setChecked(False)
        self._plan_opts_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plan_opts_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        pow_l.addWidget(self._plan_opts_toggle)

        self._plan_opts_inner = QWidget()
        poi = QVBoxLayout(self._plan_opts_inner)
        poi.setContentsMargins(0, 4, 0, 0)
        poi.setSpacing(11)

        mr = QHBoxLayout()
        mr.setSpacing(14)
        lb_m = QLabel("DeepSeek模型")
        lb_m.setObjectName("stitch_field_label")
        lb_m.setFont(ui_font("label", QFont.Weight.Medium, 0.12))
        lb_m.setFixedWidth(120)
        lb_m.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.combo_model = QComboBox()
        self.combo_model.setObjectName("stitch_combo")
        for m in nv_ds.MODELS:
            self.combo_model.addItem(m)
        dm = nv_ds.get_default_deepseek_model()
        if self.combo_model.findText(dm) < 0:
            self.combo_model.insertItem(0, dm)
        self.combo_model.setCurrentText(dm)
        self.combo_model.setFont(ui_font("body"))
        mr.addWidget(lb_m, 0)
        mr.addWidget(self.combo_model, 1)
        poi.addLayout(mr)

        sr = QHBoxLayout()
        sr.setSpacing(14)
        lb_s = QLabel("生成文风")
        lb_s.setObjectName("stitch_field_label")
        lb_s.setFont(ui_font("label", QFont.Weight.Medium, 0.12))
        lb_s.setFixedWidth(120)
        lb_s.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.combo_style = QComboBox()
        self.combo_style.setObjectName("stitch_combo")
        self.combo_style.addItem("自然表达", "豆包")
        self.combo_style.addItem("正式公文", "标准")
        self.combo_style.setFont(ui_font("body"))
        self.combo_style.setMinimumHeight(38)
        sr.addWidget(lb_s, 0)
        sr.addWidget(self.combo_style, 1)
        poi.addLayout(sr)

        self._plan_opts_fold = StitchFoldController(
            self._plan_opts_inner,
            self._plan_opts_toggle,
            "+ 模型与文风",
            "- 模型与文风",
        )
        self._plan_opts_toggle.setToolTip(
            "折叠时使用当前DeepSeek默认模型与已选文风；展开后可切换模型或文风（豆包/公文等）。"
        )
        self._plan_opts_toggle.toggled.connect(self._plan_opts_fold.on_toggled)
        pow_l.addWidget(self._plan_opts_fold.clip_host())
        self._plan_opts_fold.apply_initial_collapsed()
        self._advanced_summary = bind_setting_summary(pow_l, self._plan_opts_toggle,
            lambda: f"{self.combo_model.currentText()} · {self.combo_style.currentText()}",
            self.combo_model, self.combo_style)
        root.addWidget(self._plan_opts_wrap)

        self._batch_wrap = QFrame()
        self._batch_wrap.setObjectName("stitch_settings")
        bw_l = QVBoxLayout(self._batch_wrap)
        bw_l.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["md"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        bw_l.setSpacing(8)
        self._batch_toggle = QPushButton()
        self._batch_toggle.setObjectName("section_toggle")
        self._batch_toggle.setCheckable(True)
        self._batch_toggle.setChecked(False)
        self._batch_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._batch_toggle.setFont(ui_font("body", QFont.Weight.DemiBold))
        bw_l.addWidget(self._batch_toggle)

        self._batch_inner = QWidget()
        bil = QVBoxLayout(self._batch_inner)
        bil.setContentsMargins(0, 4, 0, 0)
        bil.setSpacing(11)
        self.e_batch_xlsx = self.stitch_path_row(
            bil,
            "发票分类导出 Excel",
            "",
            False,
            "选择「xxx_处理结果.xlsx」等工作簿（须已含封面 C～F 汇总）…",
            framed=False,
        )
        self.b_use_classified = AnimatedButton("使用刚完成的发票分类结果", "secondary")
        self.b_use_classified.setMinimumHeight(36)
        self.b_use_classified.clicked.connect(self._use_previous_classified_output)
        bil.addWidget(self.b_use_classified, 0, Qt.AlignmentFlag.AlignRight)
        self.e_batch_out = self.stitch_path_row(
            bil,
            "方案输出文件夹",
            "",
            True,
            "Word 与回填后的 xlsx 将保存到此文件夹",
            framed=False,
        )
        batch_hint = QLabel(
            "批量模式只会使用上方活动信息中的「专业名称」，其余信息从每张封面自动读取。\n"
            "流程：识别名称含「产教融合项目」的封面 → 读取 C4 项目类别、D4 服务院校、F4 时间（须已填写）→"
            " 逐个调用DeepSeek生成正文（提示词不含明细表）→ 导出 Word、写回各封面 E4。"
            " 不向 API 上传 Excel；勾选脱敏时仅在保存前从输出副本中删除所有「明细」sheet。"
        )
        batch_hint.setObjectName("muted")
        batch_hint.setWordWrap(True)
        batch_hint.setFont(ui_font("caption", QFont.Weight.Normal))
        template_help = QPushButton("查看模板要求与处理说明")
        template_help.setObjectName("section_toggle")
        template_help.setCheckable(True)
        template_help.toggled.connect(batch_hint.setVisible)
        bil.addWidget(template_help)
        batch_hint.hide()
        bil.addWidget(batch_hint)
        self.cb_batch_strip = QCheckBox("输出表格脱敏")
        self.cb_batch_strip.setChecked(False)
        self.cb_batch_strip.setFont(ui_font("body"))
        bil.addWidget(self.cb_batch_strip)
        br2 = QHBoxLayout()
        br2.setSpacing(14)
        self.b_batch_run = AnimatedButton("批量生成方案", "primary")
        self.b_batch_run.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_batch_run.setMinimumHeight(42)
        self.b_batch_run.clicked.connect(self._run_batch_from_covers)
        self.b_batch_stop = AnimatedButton("停止批量", "secondary")
        set_mono_button_icon(self.b_batch_stop, "stop", 18)
        self.b_batch_stop.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_batch_stop.setMinimumHeight(42)
        self.b_batch_stop.setEnabled(False)
        self.b_batch_stop.setToolTip("在当前封面处理完成后停止后续封面")
        self.b_batch_stop.clicked.connect(self._stop_batch_plan)
        # 互换位置：停止在左，生成在右
        br2.addWidget(self.b_batch_stop, 1)
        br2.addWidget(self.b_batch_run, 2)
        self._batch_actions = QWidget()
        self._batch_actions.setLayout(br2)
        pin.addWidget(self._batch_actions)

        self._batch_fold = StitchFoldController(
            self._batch_inner,
            self._batch_toggle,
            "+ 自发票封面批量生成",
            "- 自发票封面批量生成",
        )
        self._batch_toggle.setToolTip(
            "使用发票整理导出文件：产教融合封面逐张生成；若存在成对「机票报销封面/明细」，"
            "整本再合并生成 1 份方案（全部院校 + 各机票封面 F4 时间之最小～最大）。不弹出大窗口预览。"
        )
        self._batch_toggle.toggled.connect(self._batch_fold.on_toggled)
        bw_l.addWidget(self._batch_fold.clip_host())
        self._batch_fold.apply_initial_collapsed()
        root.addWidget(self._batch_wrap)

        self.output = QTextEdit()
        self.output.setObjectName("types_box")
        self.output.setReadOnly(True)
        self.output.setFont(ui_font("body"))
        self.output.setMinimumHeight(260)
        self.output.setPlaceholderText("生成后的活动方案会显示在这里")
        root.addWidget(self.output, 1)

        self.status = self.make_status_label("状态：待命")
        pin.addWidget(self.status)

        br = QHBoxLayout()
        br.setSpacing(14)
        self.b_export = AnimatedButton("导出 Markdown…", "secondary")
        self.b_export.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_export.setMinimumHeight(42)
        self.b_export.clicked.connect(self._export_markdown)
        self.b_export.setEnabled(False)
        result_tools = QHBoxLayout()
        result_tools.setContentsMargins(0, 0, 0, 0)
        root.removeWidget(self._reading_toggle)
        result_tools.addWidget(self._reading_toggle)
        result_tools.addWidget(self.b_export)
        self.b_preview = AnimatedButton("预览与导出 Word…", "secondary")
        self.b_preview.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_preview.setMinimumHeight(42)
        self.b_preview.clicked.connect(self._open_preview_from_button)
        self.b_preview.setEnabled(False)
        result_tools.addWidget(self.b_preview)
        result_tools.addStretch(1)
        self._result_tools = QWidget()
        self._result_tools.setLayout(result_tools)
        root.insertWidget(root.indexOf(self.output), self._result_tools)
        self.b_plan_stop = AnimatedButton("停止生成", "secondary")
        set_mono_button_icon(self.b_plan_stop, "stop", 18)
        self.b_plan_stop.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_plan_stop.setMinimumHeight(42)
        self.b_plan_stop.setEnabled(False)
        self.b_plan_stop.clicked.connect(self._stop_plan)
        br.addWidget(self.b_plan_stop, 1)
        self.b_plan_run = AnimatedButton("生成方案", "primary")
        set_mono_button_icon(self.b_plan_run, "play", 18, color_role="primary")
        self.b_plan_run.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_plan_run.setMinimumHeight(42)
        self.b_plan_run.clicked.connect(self._run_plan)
        self.register_primary_action(self.b_plan_run)
        br.addWidget(self.b_plan_run, 2)
        self._single_actions = QWidget()
        self._single_actions.setLayout(br)
        pin.addWidget(self._single_actions)
        self.mode_tabs.currentChanged.connect(self._change_plan_mode)
        pin.removeWidget(self._batch_actions)
        pin.addWidget(self._batch_actions)
        self._mode_outputs = ["", ""]
        self._visible_plan_mode = 0
        self.b_export.setVisible(False)
        self.b_preview.setVisible(False)
        self.output.textChanged.connect(self._sync_plan_result_actions)
        self._change_plan_mode(0)

        self.add_page_deco(root, "方案")

    def _set_reading_mode(self, reading):
        self._plan_heading.setVisible(not reading)
        self._plan_form.setVisible(not reading)
        self._plan_opts_wrap.setVisible(not reading)
        self._reading_toggle.setText("返回修改活动信息" if reading else "展开阅读方案")
        self.output.setMinimumHeight(240 if reading else 260)
        scroll = self.findChild(QScrollArea, "page_scroll")
        if scroll:
            QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))

    def _change_plan_mode(self, index):
        self._mode_outputs[self._visible_plan_mode] = self.output.toPlainText()
        self._visible_plan_mode = index
        self.output.setPlainText(self._mode_outputs[index])
        batch = index == 1
        self._reading_toggle.setChecked(False)
        self._reading_toggle.setVisible(not batch and bool(self._plan_body.strip()))
        self._result_tools.setVisible(not batch)
        self._batch_wrap.setVisible(batch)
        self._batch_toggle.setChecked(batch)
        self._batch_toggle.hide()
        for field in (self.e_type, self.e_time, self.e_college):
            field[0].setVisible(not batch)
        self._single_actions.setVisible(not batch)
        self._batch_actions.setVisible(batch)
        self.output.setPlaceholderText("批量处理进度会显示在这里" if batch else "生成后的活动方案会显示在这里")
        self.register_primary_action(self.b_batch_run if batch else self.b_plan_run)

    def _sync_plan_result_actions(self):
        has_result = bool(self._plan_body.strip())
        self._reading_toggle.setVisible(has_result and self._visible_plan_mode == 0)
        self.b_export.setVisible(has_result)
        self.b_preview.setVisible(has_result)

    def _set_plan_busy(self, busy: bool):
        self.mode_tabs.setEnabled(not busy)
        self._set_widgets_busy(
            busy,
            self.e_type[0],
            self.e_major[0],
            self.e_time[0],
            self.e_college[0],
            self._plan_opts_wrap,
            self._batch_wrap,
        )
        self.b_plan_run.setEnabled(not busy)
        self.combo_style.setEnabled(not busy)
        self.combo_model.setEnabled(not busy)
        has_output = bool((self._plan_body or "").strip())
        self.b_export.setEnabled(not busy and has_output)
        self.b_preview.setEnabled(not busy and has_output)
        self.b_batch_run.setEnabled(not busy)
        self.b_plan_stop.setEnabled(busy)
        if not busy:
            self.b_batch_stop.setEnabled(False)
        if busy:
            self.main.nav_task_begin(NAV_PAGE_ACTIVITY_PLAN)
        else:
            self.main.nav_task_end(NAV_PAGE_ACTIVITY_PLAN)

    def _set_batch_plan_busy(self, busy: bool):
        self.mode_tabs.setEnabled(not busy)
        self._set_widgets_busy(
            busy,
            self.e_type[0],
            self.e_major[0],
            self.e_time[0],
            self.e_college[0],
            self._plan_opts_wrap,
            self._batch_toggle,
            self.b_use_classified,
            self.cb_batch_strip,
        )
        self._set_path_entry_busy(self.e_batch_xlsx, busy)
        self._set_path_entry_busy(self.e_batch_out, busy)
        self.b_batch_run.setEnabled(not busy)
        self.b_batch_stop.setEnabled(busy)
        self.b_plan_run.setEnabled(not busy)
        self.b_plan_stop.setEnabled(False)
        self.combo_style.setEnabled(not busy)
        self.combo_model.setEnabled(not busy)
        has_output = bool((self._plan_body or "").strip())
        self.b_export.setEnabled(not busy and has_output)
        self.b_preview.setEnabled(not busy and has_output)
        if busy:
            self.main.nav_task_begin(NAV_PAGE_ACTIVITY_PLAN)
        else:
            self.main.nav_task_end(NAV_PAGE_ACTIVITY_PLAN)

    def _append_plan_output_line(self, msg: str) -> None:
        textedit_append_autoscroll(self.output, msg)

    def _on_plan_done_ok(self, body: str) -> None:
        self._on_plan_done(body, None)

    def _on_plan_done_err(self, err: str) -> None:
        self._on_plan_done("", err)

    def _show_plan_preview(
        self, body: str, context: Optional[tuple[str, str, str]] = None
    ) -> None:
        college, atype, atime = context or self._last_plan_context
        if self._preview_dlg is not None:
            try:
                if self._preview_dlg.isVisible():
                    self._preview_dlg.set_context(college, atype, atime)
                    self._preview_dlg.set_body(body)
                    self._preview_dlg.raise_()
                    self._preview_dlg.activateWindow()
                    return
            except RuntimeError:
                self._preview_dlg = None
        dlg = ActivityPlanPreviewDialog(self.main, body, college, atype, atime)
        dlg.body_changed.connect(self._on_plan_preview_body_changed)
        dlg.finished.connect(self._on_plan_preview_finished)
        self._preview_dlg = dlg
        dlg.show()

    def _on_plan_preview_body_changed(self, text: str) -> None:
        self._plan_body = text
        self._mode_outputs[0] = text
        if self._visible_plan_mode == 0:
            self.output.setPlainText(text)

    def _on_plan_preview_finished(self, _result: int = 0) -> None:
        dlg = self._preview_dlg
        if dlg is None:
            return
        text = dlg.body_text()
        self._plan_body = text
        self._mode_outputs[0] = text
        if self._visible_plan_mode == 0:
            self.output.setPlainText(text)
        self._preview_dlg = None

    def _open_preview_from_button(self) -> None:
        if not (self._plan_body or "").strip():
            self.status.setText("状态：请先生成方案")
            return
        self._show_plan_preview(self._plan_body)

    def _stop_plan(self) -> None:
        self._plan_cancel.set()
        self.b_plan_stop.setEnabled(False)
        self.status.setText("状态：已请求停止，等待当前网络请求返回…")

    def _run_plan(self):
        college = self.e_college[1].text().strip()
        major = self.e_major[1].text().strip()
        act_type = self.e_type[1].text().strip()
        act_time = self.e_time[1].text().strip()
        model = (self.combo_model.currentText() or "").strip() or None
        style_mode = str(self.combo_style.currentData() or "豆包")
        if not college or not major or not act_type or not act_time:
            self.status.setText("状态：请填写完整活动信息")
            return
        self._last_plan_context = (college, act_type, act_time)
        self._plan_cancel.clear()
        self._plan_body_before_run = self._plan_body
        self._set_plan_busy(True)
        self.status.setText("状态：正在调用DeepSeek生成方案…")
        self.output.setPlainText("")

        def work():
            try:
                body = nv_plan.generate_activity_plan_body(
                    act_type,
                    major,
                    act_time,
                    college,
                    style_mode=style_mode,
                    log_cb=lambda m: self._plan_bridge.log_line.emit(m),
                    model=model,
                )
                if self._plan_cancel.is_set():
                    self._plan_bridge.finished_err.emit("用户已取消")
                else:
                    self._plan_bridge.finished_ok.emit(body)
            except Exception as e:
                self._plan_bridge.finished_err.emit("用户已取消" if self._plan_cancel.is_set() else str(e))

        _start_qt_background_job(work, self.main)

    def _on_plan_done(self, body: str, err: Optional[str]):
        self._set_plan_busy(False)
        if err:
            if err == "用户已取消":
                self.status.setText("状态：生成已停止")
                self.output.setPlainText(self._plan_body_before_run or "本次生成已停止。")
            else:
                self.status.setText("状态：生成失败")
                self.output.setPlainText(self._plan_body_before_run or err)
                nv_biz.show_error("活动方案", err)
            return
        self._plan_body = body
        self.output.setPlainText(body)
        self.b_export.setEnabled(True)
        self.b_preview.setEnabled(True)
        self.status.setText("状态：方案已生成，可预览、编辑或导出 Word")
        self._reading_toggle.setChecked(True)

    def _export_markdown(self):
        if not (self._plan_body or "").strip():
            self.status.setText("状态：请先生成方案")
            return
        default = f"活动方案_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        p, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", str(Path.cwd() / default), "Markdown (*.md)")
        if not p:
            return
        try:
            Path(p).write_text(self._plan_body, encoding="utf-8")
            self.status.setText(f"状态：已保存 {p}")
        except OSError as e:
            nv_biz.show_error("导出失败", str(e))

    def _use_previous_classified_output(self) -> None:
        path = str(getattr(self.main, "_last_classified_output_path", "") or "")
        if path and Path(path).is_file():
            self.e_batch_xlsx.setText(path)
            self.status.setText("状态：已带入刚完成的发票分类结果")
        else:
            self.status.setText("状态：尚无可用结果，请先完成“发票整理”")

    def _browse_into(self, entry: QLineEdit, is_dir: bool) -> None:
        if not is_dir and getattr(self, "e_batch_xlsx", None) is entry:
            p, _ = QFileDialog.getOpenFileName(
                self, "发票数据表", str(Path.cwd()), "Excel (*.xlsx *.xlsm)"
            )
            if p:
                entry.setText(p)
            return
        super()._browse_into(entry, is_dir)

    def _stop_batch_plan(self) -> None:
        self._batch_cancel.set()
        self._append_plan_output_line(">>> 已请求停止批量（当前封面完成后生效）…")

    def _run_batch_from_covers(self) -> None:
        xlsx = self.e_batch_xlsx.text().strip()
        out_dir = self.e_batch_out.text().strip()
        major = self.e_major[1].text().strip()
        if not xlsx or not os.path.isfile(xlsx):
            self.status.setText("状态：请选择有效的 Excel 文件")
            return
        if not out_dir or not os.path.isdir(out_dir):
            self.status.setText("状态：请选择已存在的输出文件夹")
            return
        if not major:
            self.status.setText("状态：请填写「专业名称」")
            return
        low = xlsx.lower()
        if not low.endswith((".xlsx", ".xlsm")):
            self.status.setText("状态：批量模式请使用 .xlsx / .xlsm")
            return
        model = (self.combo_model.currentText() or "").strip() or None
        style_mode = str(self.combo_style.currentData() or "豆包")
        strip_d = self.cb_batch_strip.isChecked()
        self._batch_cancel.clear()
        self._set_batch_plan_busy(True)
        self.status.setText("状态：批量生成中…")
        self.output.setPlainText("")

        def work():
            try:
                result = nv_act_batch.run_batch_from_invoice_workbook(
                    Path(xlsx),
                    Path(out_dir),
                    major_name=major,
                    style_mode=style_mode,
                    model=model,
                    strip_detail_sheets=strip_d,
                    log_cb=lambda m: self._plan_bridge.log_line.emit(m),
                    cancel_event=self._batch_cancel,
                )
                self._plan_bridge.batch_finished_ok.emit(result)
            except Exception as e:
                self._plan_bridge.batch_finished_err.emit(str(e))

        _start_qt_background_job(work, self.main)

    def _on_batch_plan_done_ok(self, result: object) -> None:
        self._set_batch_plan_busy(False)
        if not isinstance(result, dict):
            self.status.setText("状态：批量结束")
            return
        ok_n = int(result.get("ok") or 0)
        sk = int(result.get("skipped") or 0)
        tot = int(result.get("covers_total") or 0)
        wb_out = result.get("output_workbook") or ""
        self.status.setText(f"状态：批量完成（成功 {ok_n}/{tot}，跳过 {sk}）")
        err_list = result.get("errors") or []
        err_tail = "\n".join(err_list[:5]) if err_list else ""
        if err_tail and len(err_list) > 5:
            err_tail += "\n…"
        self._append_plan_output_line(
            f">>> 批量活动方案完成：成功 {ok_n} 个封面；跳过 {sk}。"
        )
        if wb_out:
            self._append_plan_output_line(f">>> 输出工作簿：{wb_out}")
        if err_tail:
            self._append_plan_output_line(">>> 提示：\n" + err_tail)

    def _on_batch_plan_done_err(self, err: str) -> None:
        self._set_batch_plan_busy(False)
        self.status.setText("状态：批量失败")
        self.output.setPlainText(err)
        nv_biz.show_error("批量活动方案", err)


class _AutoPrintLogBridge(QObject):
    log_line = Signal(str)
    job_state = Signal(int, str, str)


class AutoPrintWorkflowPage(BasePage):
    """监听临时目录并按「极速打印 1.4.1」相同逻辑自动静默打印。"""

    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self._bridge = _AutoPrintLogBridge(self)
        self._bridge.log_line.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        self._bridge.job_state.connect(self._receive_print_job_state, Qt.ConnectionType.QueuedConnection)
        self._print_generation = 0
        self._observer: Optional[object] = None
        self._handler: Optional[object] = None
        self._retired_handlers: list[object] = []
        self._lock = threading.Lock()
        self.session_dir: Optional[Path] = None
        self._watching = False
        self._print_seen: set[str] = set()
        self._print_success: set[str] = set()
        self._print_failed: set[str] = set()
        self._print_states: dict[str, str] = {}
        self._print_rows: dict[str, int] = {}
        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_app_quit)

    def _append_log(self, msg: str) -> None:
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(msg + "\n")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _build_ui(self) -> None:
        root, pin = self.build_stitch_scaffold(
            "自动打印",
            "手动启动后监听指定目录，新加入的 Word、PDF、图片和压缩包将按类型进入打印流程。",
            pinned_footer=True,
        )
        assert pin is not None

        hint = QLabel("打印任务只会在您点击「启用自动打印」后启动；停止自动打印不会删除目录中的文件。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setFont(ui_font("caption"))
        root.addWidget(hint)

        path_card = QFrame()
        path_card.setObjectName("stitch_file_card")
        pl = QVBoxLayout(path_card)
        pl.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["lg"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        pl.setSpacing(TOKENS["space"]["md"])
        plb = QLabel("打印临时目录")
        plb.setObjectName("stitch_label")
        plb.setFont(ui_font("caption", QFont.Weight.DemiBold, 0.12))
        pl.addWidget(plb)
        row = QHBoxLayout()
        row.setSpacing(TOKENS["interaction"]["form_row_spacing"])
        self._path_edit = QLineEdit("（点击「启用自动打印」后在桌面创建临时目录）")
        self._path_edit.setReadOnly(True)
        self._path_edit.setFont(ui_font("body"))
        self._path_edit.setMinimumHeight(TOKENS["interaction"]["line_edit_min_h"])
        row.addWidget(self._path_edit, 1)
        pl.addLayout(row)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        b_copy = AnimatedButton("复制路径", "secondary")
        set_mono_button_icon(b_copy, "copy", 15)
        b_copy.setMinimumHeight(34)
        b_copy.clicked.connect(self._copy_path)
        b_open = AnimatedButton("打开文件夹", "secondary")
        set_mono_button_icon(b_open, "external", 15)
        b_open.setMinimumHeight(34)
        b_open.clicked.connect(self._open_folder)
        b_ch = AnimatedButton("更换临时目录…", "secondary")
        b_ch.setMinimumHeight(34)
        b_ch.clicked.connect(self._choose_folder)
        self.b_copy_path = b_copy
        self.b_open_folder = b_open
        self.b_choose_folder = b_ch
        self.b_clear = AnimatedButton("清空并重建文件夹…", "danger")
        set_mono_button_icon(self.b_clear, "trash", 15, color_role="danger")
        self.b_clear.setMinimumHeight(34)
        self.b_clear.clicked.connect(self._clear_session_folder)
        b_copy.setEnabled(False)
        b_open.setEnabled(False)
        self.b_clear.setEnabled(False)
        btn_row.addWidget(b_copy)
        btn_row.addWidget(b_open)
        btn_row.addWidget(b_ch)
        btn_row.addStretch(1)
        pl.addLayout(btn_row)
        maintenance_toggle = QPushButton("目录维护")
        maintenance_toggle.setObjectName("section_toggle")
        maintenance_toggle.setCheckable(True)
        self.b_clear.hide()
        maintenance_toggle.toggled.connect(self.b_clear.setVisible)
        pl.addWidget(maintenance_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        pl.addWidget(self.b_clear, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(path_card)

        opt = QFrame()
        opt.setObjectName("stitch_settings")
        ol = QVBoxLayout(opt)
        ol.setContentsMargins(
            TOKENS["space"]["xl"], TOKENS["space"]["lg"], TOKENS["space"]["xl"], TOKENS["space"]["lg"]
        )
        ol.setSpacing(10)
        oh = QLabel("Word 文件处理方式")
        oh.setObjectName("stitch_settings_title")
        oh.setFont(ui_font("title", QFont.Weight.DemiBold, 0.08))
        ol.addWidget(oh)
        self.combo_word_mode = QComboBox()
        self.combo_word_mode.setObjectName("stitch_combo")
        self.combo_word_mode.addItem("自动兼容（推荐）", "mixed")
        self.combo_word_mode.addItem("全部使用 WPS", "wps_all")
        self.combo_word_mode.addItem("优先 Microsoft Word", "word")
        self.combo_word_mode.setFont(ui_font("body"))
        self.combo_word_mode.setMinimumHeight(38)
        ol.addWidget(self.combo_word_mode)
        kw_hint = QLabel("文件名包含以下关键词时，自动改用 WPS 处理（多个词用逗号分隔）")
        kw_hint.setObjectName("muted")
        kw_hint.setWordWrap(True)
        kw_hint.setFont(ui_font("caption"))
        ol.addWidget(kw_hint)
        self.e_receipt_kw = QLineEdit("签收单")
        self.e_receipt_kw.setFont(ui_font("body"))
        ol.addWidget(self.e_receipt_kw)
        root.addWidget(opt)
        self._print_settings_toggle = QPushButton("打印规则与 PDF 支持")
        self._print_settings_toggle.setObjectName("section_toggle")
        self._print_settings_toggle.setCheckable(True)
        self._print_settings_toggle.setChecked(True)
        self._print_settings_toggle.toggled.connect(opt.setVisible)
        root.insertWidget(root.indexOf(opt), self._print_settings_toggle)

        self.lbl_sumatra = QLabel()
        self.lbl_sumatra.setObjectName("path_feedback")
        self.lbl_sumatra.setWordWrap(True)
        self.lbl_sumatra.setFont(ui_font("caption"))
        ol.addWidget(self.lbl_sumatra)
        pdf_actions = QHBoxLayout()
        self.b_pdf_setup = AnimatedButton("选择 SumatraPDF…", "secondary")
        self.b_pdf_setup.clicked.connect(self._choose_sumatra)
        self.b_pdf_detect = AnimatedButton("重新检测", "secondary")
        self.b_pdf_detect.clicked.connect(self._refresh_sumatra_label)
        pdf_actions.addWidget(self.b_pdf_setup)
        pdf_actions.addWidget(self.b_pdf_detect)
        self.b_pdf_auto = AnimatedButton("恢复自动检测", "secondary")
        self.b_pdf_auto.clicked.connect(self._reset_sumatra)
        pdf_actions.addWidget(self.b_pdf_auto)
        pdf_actions.addStretch(1)
        ol.addLayout(pdf_actions)
        pdf_hint = QLabel("标准安装会自动识别；使用便携版时，请选择 SumatraPDF.exe。运行中修改将在下次启动监听时生效。")
        pdf_hint.setObjectName("muted")
        pdf_hint.setWordWrap(True)
        ol.addWidget(pdf_hint)
        self.lbl_printer = QLabel()
        self.lbl_printer.setObjectName("muted")
        self.lbl_printer.setWordWrap(True)
        self.lbl_printer.setFont(ui_font("caption"))
        root.addWidget(self.lbl_printer)
        self._refresh_sumatra_label()
        self._refresh_printer_label()
        self._print_settings_summary = bind_setting_summary(root, self._print_settings_toggle,
            lambda: f"Word：{self.combo_word_mode.currentText()} · PDF：{'可用' if self._find_sumatra() else '需要配置'}",
            self.combo_word_mode)
        self.lbl_print_summary = QLabel("本次监听：尚未开始")
        self.lbl_print_summary.setObjectName("muted")
        self.lbl_print_summary.setFont(ui_font("caption", QFont.Weight.DemiBold))
        root.addWidget(self.lbl_print_summary)
        self.print_queue = QTableWidget(0, 2)
        self.print_queue.setObjectName("print_queue")
        self.print_queue.setFont(ui_font("body"))
        self.print_queue.setAccessibleName("本次打印任务")
        self.print_queue.setHorizontalHeaderLabels(["文件", "处理状态"])
        self.print_queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.print_queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.print_queue.verticalHeader().hide()
        self.print_queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.print_queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.print_queue.setMinimumHeight(150)
        root.addWidget(self.print_queue)
        queue_hint = QLabel("“已提交打印”表示打印调用成功返回，不代表纸张已实际输出；ZIP 按压缩包汇总。失败详情见下方日志。")
        queue_hint.setObjectName("muted")
        queue_hint.setWordWrap(True)
        root.addWidget(queue_hint)

        logf = QFrame()
        logf.setObjectName("card_group")
        ll = QVBoxLayout(logf)
        ll.setContentsMargins(
            TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"], TOKENS["space"]["md"]
        )
        ll.setSpacing(TOKENS["space"]["sm"])
        tl = QLabel("日志")
        tl.setFont(ui_font("label", QFont.Weight.DemiBold, 0.15))
        ll.addWidget(tl)
        self._log = QTextEdit()
        self._log.setObjectName("stitch_run_log")
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        ll.addWidget(self._log, 1)
        root.addWidget(logf, 1)

        self.status = self.make_status_label("状态：未启动，请确认目录后点击「启用自动打印」")
        pin.addWidget(self.status)

        bf = QHBoxLayout()
        bf.setSpacing(14)
        ic = TOKENS["interaction"]["icon_footer"]
        bh = TOKENS["interaction"]["footer_button_min_h"]
        self.b_start_w = AnimatedButton("启用自动打印", "primary")
        set_mono_button_icon(self.b_start_w, "play", ic, color_role="primary")
        self.b_start_w.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_start_w.setMinimumHeight(bh)
        self.b_start_w.clicked.connect(self._start_watch)
        self.register_primary_action(self.b_start_w)
        self.b_stop_w = AnimatedButton("停止自动打印", "secondary")
        set_mono_button_icon(self.b_stop_w, "stop", ic)
        self.b_stop_w.setFont(ui_font("title", QFont.Weight.DemiBold, 0.12))
        self.b_stop_w.setMinimumHeight(bh)
        self.b_stop_w.setEnabled(False)
        self.b_stop_w.clicked.connect(self._stop_watch)
        bf.addWidget(self.b_stop_w, 1)
        bf.addWidget(self.b_start_w, 2)
        pin.addLayout(bf)

        root.addStretch(1)
        self.add_page_deco(root, "打印")

        self._append_log("监听尚未启动。请选择或确认临时目录，然后点击「启用自动打印」。")

    def _ensure_session_dir(self) -> Path:
        if self.session_dir is not None and self.session_dir.is_dir():
            return self.session_dir
        self.session_dir = nv_aprint.new_session_folder()
        self._path_edit.setText(str(self.session_dir))
        self._append_log(f"已创建：{self.session_dir}")
        self._sync_session_buttons()
        return self.session_dir

    def _sync_session_buttons(self) -> None:
        available = self.session_dir is not None and self.session_dir.is_dir()
        self.b_copy_path.setEnabled(available)
        self.b_open_folder.setEnabled(available)
        self.b_clear.setEnabled(available and not self._watching)

    def _on_app_quit(self) -> None:
        self._stop_watch_quiet()

    def _print_jobs_active(self) -> bool:
        alive: list[object] = []
        for handler in self._retired_handlers:
            try:
                if not handler.is_idle():
                    alive.append(handler)
            except Exception:
                continue
        self._retired_handlers = alive
        if self._handler is not None and hasattr(self._handler, "is_idle"):
            try:
                return not self._handler.is_idle() or bool(alive)
            except Exception:
                pass
        return bool(alive)

    def _find_sumatra(self):
        try:
            settings = json.loads((_DATA_DIR / "print_settings.json").read_text(encoding="utf-8"))
            custom = settings.get("sumatra_path", "")
            if custom:
                path = Path(custom)
                return path if path.is_file() and path.name.lower() == "sumatrapdf.exe" else None
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return nv_aprint.find_sumatra_pdf()

    def _reset_sumatra(self):
        target = _DATA_DIR / "print_settings.json"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text("{}", encoding="utf-8")
            temporary.replace(target)
        except OSError as exc:
            stitch_msg_warning(self, "未保存", f"无法保存打印设置：{exc}")
            return
        self._refresh_sumatra_label()

    def _choose_sumatra(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择 SumatraPDF.exe", "", "SumatraPDF (SumatraPDF.exe)")
        if not filename:
            return
        path = Path(filename)
        if not path.is_file() or path.name.lower() != "sumatrapdf.exe":
            stitch_msg_warning(self, "未保存", "请选择现有的 SumatraPDF.exe 文件。")
            return
        target = _DATA_DIR / "print_settings.json"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(".json.tmp")
            temp.write_text(json.dumps({"sumatra_path": str(path)}, ensure_ascii=False), encoding="utf-8")
            temp.replace(target)
        except OSError as exc:
            stitch_msg_warning(self, "未保存", f"无法保存打印设置：{exc}")
            return
        self._refresh_sumatra_label()

    def _refresh_sumatra_label(self) -> None:
        s = self._find_sumatra()
        self._print_settings_toggle.setChecked(not bool(s))
        self.lbl_sumatra.setProperty("state", "valid" if s else "warning")
        if s:
            self.lbl_sumatra.setText(
                "SumatraPDF 已就绪（打印 PDF；Word 转 PDF 路由与备用）。"
            )
        else:
            self.lbl_sumatra.setText(
                "未检测到 SumatraPDF：无法走 PDF 静默打印路由；Word 将尽量直打或经 WPS。"
            )
        self.lbl_sumatra.setToolTip(str(s) if s else "安装后点击重新检测，或选择便携版 SumatraPDF.exe；已配置的文件也可能已被移动。")
        self.lbl_sumatra.style().unpolish(self.lbl_sumatra)
        self.lbl_sumatra.style().polish(self.lbl_sumatra)

    def _refresh_printer_label(self) -> None:
        name = ""
        if sys.platform == "win32":
            try:
                import win32print  # type: ignore

                name = str(win32print.GetDefaultPrinter() or "").strip()
            except Exception:
                name = ""
        self.lbl_printer.setText(
            f"输出设备：系统默认打印机「{name}」" if name else "输出设备：系统默认打印机"
        )

    def _refresh_print_summary(self) -> None:
        total = len(self._print_seen)
        success = len(self._print_success)
        failed = len(self._print_failed)
        cancelled = sum(state == "cancelled" for state in self._print_states.values())
        pending = sum(state in ("queued", "processing", "retrying") for state in self._print_states.values())
        self.lbl_print_summary.setText(
            f"本次监听：发现 {total} · 已提交 {success} · 失败 {failed} · 取消 {cancelled} · 待处理 {pending}"
        )
        self.lbl_print_summary.setWordWrap(True)

    def _receive_print_job_state(self, generation, state, path):
        if generation == self._print_generation:
            self._on_print_job_state(state, path)

    def _on_print_job_state(self, state: str, path: str) -> None:
        labels = {"queued": "排队中", "processing": "处理中", "retrying": "等待重试", "success": "已提交打印", "failed": "失败，请查看日志", "cancelled": "已取消", "missing": "文件已移走"}
        if state not in labels:
            return
        self._print_states[path] = state
        self._print_seen.add(path)
        if state in ("queued", "processing", "retrying"):
            self._print_seen.add(path)
            self._print_failed.discard(path)
            self._print_success.discard(path)
        elif state == "success":
            self._print_seen.add(path)
            self._print_success.add(path)
            self._print_failed.discard(path)
        elif state in ("failed", "missing"):
            self._print_seen.add(path)
            self._print_failed.add(path)
            self._print_success.discard(path)
        elif state == "cancelled":
            self._print_success.discard(path)
            self._print_failed.discard(path)
        row = self._print_rows.get(path)
        if row is None:
            row = self.print_queue.rowCount()
            self.print_queue.insertRow(row)
            self._print_rows[path] = row
            item = QTableWidgetItem(Path(path).name)
            item.setToolTip(path)
            self.print_queue.setItem(row, 0, item)
        self.print_queue.setItem(row, 1, QTableWidgetItem(labels[state]))
        self._refresh_print_summary()

    def _existing_session_dir(self) -> Optional[Path]:
        if self.session_dir is not None and self.session_dir.is_dir():
            return self.session_dir
        self.status.setText("状态：尚未创建临时目录，请先选择目录或启用自动打印")
        return None

    def _copy_path(self) -> None:
        d = self._existing_session_dir()
        if d is None:
            return
        cb = QGuiApplication.clipboard()
        if cb is None:
            self._append_log('复制失败：系统剪贴板不可用，请重试。')
            return
        cb.setText(str(d))
        self._append_log("已复制路径到剪贴板")

    def _open_folder(self) -> None:
        d = self._existing_session_dir()
        if d is None:
            return
        open_local_folder(self, d)

    def _choose_folder(self) -> None:
        parent = (
            str(self.session_dir.parent)
            if self.session_dir is not None
            else str(nv_aprint.desktop_dir())
        )
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", parent)
        if not d:
            return
        was_watching = self._watching
        if was_watching:
            self._stop_watch()
        self.session_dir = Path(d)
        self._path_edit.setText(str(self.session_dir))
        self._sync_session_buttons()
        self._append_log(f"已切换监听目录：{self.session_dir}")
        if was_watching:
            self.status.setText("状态：目录已更换，请重新点击「启用自动打印」")

    def _clear_session_folder(self) -> None:
        if self.session_dir is None:
            self._append_log("[清除] 尚未创建临时目录。")
            return
        d = self.session_dir
        if not d.is_dir():
            self._append_log("[清除] 当前路径不是有效文件夹。")
            return
        if not stitch_msg_question(
            self.main,
            "确认清除",
            "将停止自动打印并永久删除整个临时文件夹，包括其中尚未处理的文件。\n"
            "删除成功后会创建一个空目录，但不会自动启动监听。\n\n"
            f"{d}",
            severity="warning",
            yes_text="删除并重建",
            no_text="取消",
            default_yes=False,
        ):
            return
        self._stop_watch()
        try:
            shutil.rmtree(d)
        except OSError as e:
            self._append_log(f"[清除] 删除文件夹失败：{e}")
            stitch_msg_warning(self.main, "清除失败", str(e))
            return
        self._append_log(f"[清除] 已删除临时目录：{d}")
        self.session_dir = nv_aprint.new_session_folder()
        self._path_edit.setText(str(self.session_dir))
        self._sync_session_buttons()
        self._append_log(f"已新建临时目录：{self.session_dir}")
        self.status.setText("状态：已重建空目录，请点击「启用自动打印」")

    def _stop_watch_quiet(self) -> None:
        handler = self._handler
        if handler is not None and hasattr(handler, "stop"):
            try:
                handler.stop()
            except Exception:
                pass
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                pass
            self._observer = None
        if handler is not None and hasattr(handler, "is_idle"):
            try:
                if not handler.is_idle():
                    self._retired_handlers.append(handler)
            except Exception:
                pass
        self._handler = None
        self._watching = False

    def _stop_watch(self) -> None:
        was_watching = self._watching
        handler = self._handler
        if handler is not None and hasattr(handler, "stop"):
            try:
                handler.stop()
            except Exception as e:
                self._append_log(f"停止待处理打印任务时出现提示：{e}")
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        if handler is not None and hasattr(handler, "is_idle"):
            try:
                if not handler.is_idle():
                    self._retired_handlers.append(handler)
                    self._append_log("已有文件进入系统打印调用，将等待该调用返回；不会再接收新文件。")
            except Exception:
                pass
        self._handler = None
        self._watching = False
        if was_watching:
            self.main.nav_task_end(NAV_PAGE_AUTO_PRINT)
        self._set_watch_controls(False)
        self._append_log("监听已停止。")
        self.status.setText("状态：已停止")

    def _set_watch_controls(self, watching: bool) -> None:
        self.b_start_w.setEnabled(not watching)
        self.b_stop_w.setEnabled(watching)
        self.combo_word_mode.setEnabled(not watching)
        self.e_receipt_kw.setEnabled(not watching)
        self.b_choose_folder.setEnabled(not watching)
        self._sync_session_buttons()

    def _start_watch(self) -> None:
        if self._watching:
            return
        if self._print_jobs_active():
            self.status.setText("请等待上一轮打印调用结束，再开始新的监听")
            return
        session = self._ensure_session_dir()
        if not nv_aprint.WATCHDOG_AVAILABLE:
            self.status.setText("状态：缺少文件监听组件，无法启动")
            stitch_msg_critical(
                self.main,
                "缺少依赖",
                "当前程序缺少文件监听组件，暂时无法启动自动打印。请联系维护人员更新完整安装包。",
            )
            return
        sumatra = self._find_sumatra()
        receipt_keywords = self.e_receipt_kw.text() or ""
        word_mode = str(self.combo_word_mode.currentData() or "mixed")
        self._print_seen.clear()
        self._print_success.clear()
        self._print_failed.clear()
        self._print_states.clear()
        self._print_generation += 1
        self._print_rows.clear()
        self.print_queue.setRowCount(0)
        self._refresh_print_summary()
        self._handler = nv_aprint._PrintHandler(
            session,
            sumatra,
            lambda: None,
            lambda: True,
            lambda: "noscale",
            lambda: True,
            lambda: "word",
            lambda: True,
            lambda value=receipt_keywords: value,
            lambda mode=word_mode: mode == "mixed",
            lambda mode=word_mode: mode == "wps_all",
            lambda m: self._bridge.log_line.emit(m),
            self._lock,
            lambda state, path, generation=self._print_generation: self._bridge.job_state.emit(generation, state, path),
        )
        self._observer = nv_aprint.Observer()
        self._observer.schedule(self._handler, str(session), recursive=False)
        self._observer.start()
        self._print_settings_toggle.setChecked(False)
        self._watching = True
        self.main.nav_task_begin(NAV_PAGE_AUTO_PRINT)
        self._set_watch_controls(True)
        self._refresh_printer_label()
        self.status.setText("状态：监听中")
        self._append_log(
            f"监听已开始。Word 处理方式={self.combo_word_mode.currentText()}；"
            f"关键词={self.e_receipt_kw.text()!r}；"
            f"（未勾全 WPS 时）图片走 WPS 嵌入、PDF 走 Sumatra；"
            f".zip 将自动解压并打印包内 Word/PDF/图片（有大小与条目上限）。"
        )


class NavItem(QPushButton):
    def __init__(self, icon_name: str, title: str):
        super().__init__(title)
        self._icon_name = icon_name
        self.setObjectName("navitem")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(41)
        self.setIconSize(QSize(16, 16))
        self.setFont(ui_font("label", QFont.Weight.Medium, 0.12))
        self.setStyleSheet("text-align:left; padding-left:14px;")

    def set_selected(self, selected: bool):
        self.setChecked(selected)

    def refresh_icon(self, color: str):
        self.setIcon(mono_svg_icon(self._icon_name, 16, color))


class MainWindow(QMainWindow):
    """后台线程 → 主线程：优先用强类型 Signal(str/int/…)，避免 Signal(object)+lambda 在部分环境不投递。"""

    _invoke_on_gui = Signal(object)
    show_info_requested = Signal(str, str)
    show_error_requested = Signal(str, str)
    _nav_task_done = Signal(int)

    def __init__(self):
        super().__init__()
        self.dark = str(_load_ui_preferences().get("theme") or "light").lower() == "dark"
        self.setWindowIcon(load_application_icon())
        self.setWindowTitle("数据整理工具集  Ver 6.0")
        self._last_cleaned_data_path = ""
        self._last_classified_output_path = ""
        self.resize(1260, 820)
        self.setMinimumSize(900, 620)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self._frame_drag_offset: Optional[QPoint] = None
        self._topbar_frame: Optional[QFrame] = None
        self._close_when_idle = False
        self._allow_close = False
        self._invoke_on_gui.connect(self._exec_invoke_on_gui, Qt.ConnectionType.QueuedConnection)
        self.show_info_requested.connect(self._gui_show_info, Qt.ConnectionType.QueuedConnection)
        self.show_error_requested.connect(self._gui_show_error, Qt.ConnectionType.QueuedConnection)
        self._nav_task_done.connect(self.nav_task_end, Qt.ConnectionType.QueuedConnection)
        self._build_ui()
        self._hook_nv_business_core()
        self.apply_theme()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32" and not getattr(self, '_native_resize_ready', False):
            import ctypes
            user32 = ctypes.windll.user32
            getter = user32.GetWindowLongPtrW
            setter = user32.SetWindowLongPtrW
            getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            hwnd = int(self.winId())
            setter(hwnd, -16, getter(hwnd, -16) | 0x00040000 | 0x00010000 | 0x00020000 | 0x00080000)
            self._native_resize_ready = True

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE: retain custom chrome.
                return True, 0
            if msg.message == 0x0084 and not self.isMaximized() and not self.isFullScreen():
                # Native hit-test coordinates are physical pixels, including negative monitor origins.
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(wintypes.HWND(msg.hWnd), ctypes.byref(rect))
                x = ctypes.c_short(msg.lParam & 0xffff).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value
                border = max(6, round(7 * self.devicePixelRatioF()))
                left, right = x < rect.left + border, x >= rect.right - border
                top, bottom = y < rect.top + border, y >= rect.bottom - border
                hit = (13 if left else 14 if right else 12) if top else (
                    (16 if left else 17 if right else 15) if bottom else (10 if left else 11 if right else 0))
                if hit:
                    return True, hit
        return super().nativeEvent(event_type, message)

    @Slot(object)
    def _exec_invoke_on_gui(self, fn: object) -> None:
        if callable(fn):
            fn()

    @Slot(str, str)
    def _gui_show_info(self, title: str, message: str) -> None:
        stitch_msg_information(self, title, message)

    @Slot(str, str)
    def _gui_show_error(self, title: str, message: str) -> None:
        stitch_msg_critical(self, title, message)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        nav = QFrame()
        nav.setObjectName("nav")
        nav.setMinimumWidth(204)
        nav.setMaximumWidth(224)
        nav_l = QVBoxLayout(nav)
        nav_l.setContentsMargins(14, 16, 14, 12)
        nav_l.setSpacing(8)

        brand_row = QWidget()
        br = QHBoxLayout(brand_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(10)
        self._brand_logo = QLabel()
        self._brand_logo.setObjectName("nav_brand_logo")
        # 略大于绘制内容区，避免高 DPR 下 pixmap 贴边被裁掉一角
        self._brand_logo.setFixedSize(44, 44)
        self._brand_logo.setScaledContents(False)
        self._brand_logo.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        br.addWidget(self._brand_logo, 0, Qt.AlignmentFlag.AlignTop)
        brand_text_col = QWidget()
        btc = QVBoxLayout(brand_text_col)
        btc.setContentsMargins(0, 0, 0, 0)
        btc.setSpacing(2)
        brand = QLabel("数据整理工具集")
        brand.setObjectName("nav_brand")
        brand.setFont(ui_font("title", QFont.Weight.Bold))
        btc.addWidget(brand)
        brand_sub = QLabel(" Ver6.0")
        brand_sub.setObjectName("nav_brand_sub")
        brand_sub.setFont(ui_font("label", QFont.Weight.DemiBold, 0.2))
        btc.addWidget(brand_sub)
        br.addWidget(brand_text_col, 1)
        nav_l.addWidget(brand_row)

        scroll = QScrollArea()
        scroll.setObjectName("nav_scroll")
        self._nav_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_content = QWidget()
        nav_content.setObjectName("nav_content")
        self.nav_list = QVBoxLayout(nav_content)
        self.nav_list.setContentsMargins(0, 0, 0, 0)
        self.nav_list.setSpacing(0)
        scroll.setWidget(nav_content)
        scroll.viewport().setObjectName("nav_viewport")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_l.addWidget(scroll, 1)

        self.left_theme = QCheckBox("日间模式")
        self.left_theme.setObjectName("left_theme")
        self.left_theme.setChecked(True)
        self.left_theme.stateChanged.connect(self._sync_theme_from_left)
        self.left_theme.setFont(QFont("Microsoft YaHei", 9))
        self.left_theme.setVisible(False)
        nav_l.addWidget(self.left_theme, 0, Qt.AlignmentFlag.AlignLeft)

        help_btn = AnimatedButton("帮助", "nav_foot")
        set_mono_button_icon(help_btn, "help", 14, color_role="muted")
        help_btn.setFont(ui_font("label", QFont.Weight.DemiBold, 0.08))
        help_btn.setToolTip("查看简要说明（F1）")
        help_btn.clicked.connect(self._show_help_overview)
        api_btn = AnimatedButton("设置", "nav_foot")
        set_mono_button_icon(api_btn, "gear", 14, color_role="muted")
        api_btn.setFont(ui_font("label", QFont.Weight.DemiBold, 0.08))
        api_btn.setToolTip(
            "DeepSeek API、公司对应学校（机票/产教）、分类页默认公司与分组（api_config.json 等）"
        )
        api_btn.clicked.connect(self._show_settings_dialog)

        self.stack = FadeStack()
        self.stack.addWidget(
            nv_dashboard_ui.DashboardPage(
                self,
                _DATA_DIR / "dashboard_state.sqlite3",
                palette_provider=lambda: dashboard_palette(self.dark),
                task_begin=lambda: self.nav_task_begin(NAV_PAGE_DASHBOARD),
                task_end=lambda: self.nav_task_end(NAV_PAGE_DASHBOARD),
                last_cleaned_path_provider=lambda: self._last_cleaned_data_path,
                button_icon_setter=lambda button, name, size, color_role: set_mono_button_icon(
                    button,
                    name,
                    size,
                    color_role=color_role,
                    dark=self.dark,
                ),
                show_information=lambda title, text: stitch_msg_information(self, title, text),
                show_warning=lambda title, text: stitch_msg_warning(self, title, text),
                show_critical=lambda title, text: stitch_msg_critical(self, title, text),
                ask_confirmation=lambda title, text: stitch_msg_question(
                    self,
                    title,
                    text,
                    yes_text="继续",
                    no_text="取消",
                ),
            )
        )
        self.stack.addWidget(ActivityMatchPage(self))
        self.stack.addWidget(ProjectStatPage(self))
        self.stack.addWidget(BriefingPage(self))
        self.stack.addWidget(ClassificationPage(self))
        self.stack.addWidget(ActivityPlanPage(self))
        self.stack.addWidget(AutoPrintWorkflowPage(self))

        import nv_harness_widgets
        from types import SimpleNamespace
        self.harness_page = nv_harness_widgets.create_page(
            self, SimpleNamespace(BasePage=BasePage, AnimatedButton=AnimatedButton,
                ui_font=ui_font, stitch_msg_information=stitch_msg_information,
                stitch_msg_warning=stitch_msg_warning), _RESOURCE_DIR, _DATA_DIR)
        self.stack.addWidget(self.harness_page)

        self.nav_items = []
        self._nav_busy_stripes: list[QFrame] = []
        self._nav_busy_blink: list[QSequentialAnimationGroup] = []
        self._nav_busy_count: list[int] = []
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        items = [
            ("dashboard", "数据看板"),
            ("broom", "数据整理"),
            ("chart", "统计报表"),
            ("doc", "活动简报"),
            ("invoice", "发票整理"),
            ("puzzle", "活动方案"),
            ("printer", "自动打印"),
            ("puzzle", "Agent 工作台"),
        ]
        self._nav_titles = [title for _icon, title in items]
        group_labels = {0: "核心功能", 1: "项目流程", 4: "材料与交付", 6: "实用工具"}
        for i, (icon, t) in enumerate(items):
            if i in group_labels:
                group_label = QLabel(group_labels[i])
                group_label.setObjectName("nav_group_label")
                group_label.setFont(ui_font("caption", QFont.Weight.DemiBold))
                self.nav_list.addWidget(group_label)
            item = NavItem(icon, t)
            row = QWidget()
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.setFixedHeight(41)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(8, 0, 6, 0)
            hl.setSpacing(8)
            busy_line = QFrame()
            busy_line.setObjectName("nav_busy_line")
            busy_line.setFixedSize(2, 20)
            busy_line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            busy_line.hide()
            op_eff = QGraphicsOpacityEffect(busy_line)
            op_eff.setOpacity(1.0)
            busy_line.setGraphicsEffect(op_eff)
            blink_out = QPropertyAnimation(op_eff, b"opacity", busy_line)
            blink_out.setDuration(650)
            blink_out.setStartValue(1.0)
            blink_out.setEndValue(0.55)
            blink_out.setEasingCurve(QEasingCurve.Type.InOutSine)
            blink_in = QPropertyAnimation(op_eff, b"opacity", busy_line)
            blink_in.setDuration(650)
            blink_in.setStartValue(0.55)
            blink_in.setEndValue(1.0)
            blink_in.setEasingCurve(QEasingCurve.Type.InOutSine)
            blink = QSequentialAnimationGroup(busy_line)
            blink.addAnimation(blink_out)
            blink.addAnimation(blink_in)
            blink.setLoopCount(-1)
            hl.addWidget(busy_line, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(item, 1)
            self.nav_items.append(item)
            self.nav_list.addWidget(row)
            self._nav_busy_stripes.append(busy_line)
            self._nav_busy_blink.append(blink)
            self._nav_busy_count.append(0)
            self.nav_group.addButton(item, i)
            item.clicked.connect(lambda checked, idx=i: self.select_page(idx))
            item.setToolTip(f"{t}（Ctrl+{i + 1}）")
        self.nav_list.addStretch(1)
        nav_l.addWidget(help_btn)
        nav_l.addWidget(api_btn)

        main_wrap = QWidget()
        main_l = QVBoxLayout(main_wrap)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        self._topbar_frame = topbar
        topbar.installEventFilter(self)
        top_l = QHBoxLayout(topbar)
        top_l.setContentsMargins(20, 9, 20, 9)
        top_l.setSpacing(10)
        self.topbar_title = QLabel(self._nav_titles[0])
        self.topbar_title.setObjectName("topbar_menu")
        self.topbar_title.setFont(ui_font("body", QFont.Weight.Medium))
        top_l.addWidget(self.topbar_title, 1)
        self.mode_chip = QLabel("日间")
        self.mode_chip.setObjectName("mode_chip")
        self.mode_chip.setFont(ui_font("label", QFont.Weight.DemiBold, 0.14))
        self.mode_toggle = AnimatedButton("", "mode_toggle")
        self.mode_toggle.setFixedSize(28, 28)
        self.mode_toggle.setAccessibleName("切换显示主题")
        self.mode_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_toggle.clicked.connect(self.toggle_theme)
        self.mode_toggle.setToolTip("切换日间/夜间模式")
        top_l.addWidget(self.mode_chip)
        top_l.addWidget(self.mode_toggle)
        traffic_wrap = QWidget()
        traffic_wrap.setObjectName("traffic_lights_wrap")
        tw = QHBoxLayout(traffic_wrap)
        tw.setContentsMargins(0, 0, 0, 0)
        tw.setSpacing(8)
        self._traffic_min = TrafficLightButton("traffic_minimize", "最小化", self.showMinimized)
        self._traffic_zoom = TrafficLightButton("traffic_zoom", "最大化", self._traffic_toggle_maximize)
        self._traffic_close = TrafficLightButton("traffic_close", "关闭窗口", self.close)
        tw.addWidget(self._traffic_min)
        tw.addWidget(self._traffic_zoom)
        tw.addWidget(self._traffic_close)
        top_l.addWidget(traffic_wrap)
        self._topbar_shadow = QGraphicsDropShadowEffect(self)
        self._topbar_shadow.setBlurRadius(24)
        self._topbar_shadow.setOffset(0, 2)
        self._topbar_shadow.setColor(QColor(0, 0, 0, 26))
        topbar.setGraphicsEffect(self._topbar_shadow)
        main_l.addWidget(topbar)
        main_l.addWidget(self.stack, 1)

        body.addWidget(nav)
        body.addWidget(main_wrap, 1)
        self.select_page(0)
        self._page_shortcuts: list[QShortcut] = []
        for idx in range(len(self.nav_items)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{idx + 1}"), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda page_idx=idx: self.select_page(page_idx))
            self._page_shortcuts.append(shortcut)
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(self._trigger_current_primary_action)
            self._page_shortcuts.append(shortcut)
        _help_sc = QShortcut(QKeySequence(Qt.Key.Key_F1), self)
        _help_sc.activated.connect(self._show_help_overview)
        self._page_shortcuts.append(_help_sc)

    def _trigger_current_primary_action(self) -> None:
        page = self.stack.currentWidget()
        button = getattr(page, "_stitch_primary_action", None)
        if not isinstance(button, QAbstractButton):
            return
        if not button.isVisible() or not button.isEnabled():
            return
        button.setFocus(Qt.FocusReason.ShortcutFocusReason)
        button.click()

    def _show_help_overview(self) -> None:
        stitch_msg_information(
            self,
            "帮助",
            "建议按以下顺序完成日常工作：\n\n"
            "• 核心入口｜数据看板（支持原始审批或整理结果）\n"
            "• 数据准备｜数据整理 → 统计报表 → 活动简报\n"
            "• 材料交付｜发票整理 → 活动方案\n\n"
            "文件路径可直接拖入，底部状态区会持续显示任务进度。\n"
            "左下角「设置」用于维护DeepSeek配置、公司院校和分类默认值。\n"
            "自动打印不会自行启动；请确认目录后手动点击「启用自动打印」。",
        )

    def _show_settings_dialog(self) -> None:
        dlg = AppSettingsDialog(self)
        dlg.exec()

    def _traffic_toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.ActivationChange,QEvent.Type.WindowActivate,QEvent.Type.WindowDeactivate):
            for button in self.findChildren(TrafficLightButton):button.update()
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, "_traffic_zoom"):
                self._traffic_zoom.setToolTip("还原窗口" if self.isMaximized() else "最大化")
        super().changeEvent(event)

    def _background_work_active(self) -> bool:
        if any(count > 0 for count in getattr(self, "_nav_busy_count", ())):
            return True
        for th in tuple(getattr(self, "_python_bg_threads", ())):
            if th.is_alive():
                return True
        for obj in tuple(getattr(self, "_qt_bg_jobs", ())):
            if isinstance(obj, QThread):
                try:
                    if obj.isRunning():
                        return True
                except RuntimeError:
                    continue
        if hasattr(self, "stack"):
            auto_page = self.stack.widget(NAV_PAGE_AUTO_PRINT)
            if hasattr(auto_page, "_print_jobs_active") and auto_page._print_jobs_active():
                return True
        return False

    def _request_background_cancellation(self) -> None:
        for page_index in (NAV_PAGE_CLASSIFY, NAV_PAGE_ACTIVITY_PLAN):
            page = self.stack.widget(page_index)
            for attr in ("_cancel", "_plan_cancel", "_batch_cancel"):
                flag = getattr(page, attr, None)
                if isinstance(flag, threading.Event):
                    flag.set()
        auto_page = self.stack.widget(NAV_PAGE_AUTO_PRINT)
        if getattr(auto_page, "_watching", False):
            auto_page._stop_watch()

    def _poll_deferred_close(self) -> None:
        if not self._close_when_idle:
            return
        if self._background_work_active():
            QTimer.singleShot(250, self._poll_deferred_close)
            return
        self._allow_close = True
        self.close()

    def closeEvent(self, event) -> None:
        harness_page = getattr(self, "harness_page", None)
        if harness_page is not None and harness_page.controller.active:
            harness_page.stop_for_close()
            event.ignore()
            return
        auto_page = self.stack.widget(NAV_PAGE_AUTO_PRINT) if hasattr(self, "stack") else None
        if self._allow_close or not self._background_work_active():
            if harness_page is not None:
                harness_page.dispose_workbench()
            if auto_page is not None and hasattr(auto_page, "_stop_watch_quiet"):
                auto_page._stop_watch_quiet()
            event.accept()
            super().closeEvent(event)
            return
        if not self._close_when_idle:
            confirmed = stitch_msg_question(
                self,
                "任务仍在运行",
                "当前仍有整理、生成、联网或打印任务。现在退出可能损坏正在写入的文件。\n\n"
                "选择“等待后退出”后，程序会停止自动打印、请求可取消任务结束，并在其余步骤安全完成后自动关闭。",
                severity="warning",
                yes_text="等待后退出",
                no_text="继续使用",
                default_yes=False,
            )
            if confirmed:
                self._close_when_idle = True
                self._request_background_cancellation()
                if self.centralWidget() is not None:
                    self.centralWidget().setEnabled(False)
                QTimer.singleShot(100, self._poll_deferred_close)
        event.ignore()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._topbar_frame and self._topbar_frame is not None:
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    pos = event.position().toPoint()
                    child = self._topbar_frame.childAt(pos)
                    if child is not None and isinstance(child, QPushButton):
                        self._frame_drag_offset = None
                        return False
                    self._frame_drag_offset = (
                        event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    )
                return False
            if et == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    self._frame_drag_offset = None
                elif self._frame_drag_offset is not None:
                    self.move(event.globalPosition().toPoint() - self._frame_drag_offset)
                return False
            if et == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
                self._frame_drag_offset = None
                return False
        return super().eventFilter(obj, event)

    def _hook_nv_business_core(self):
        win = self

        def post_ui(fn):
            win._invoke_on_gui.emit(fn)

        nv_biz.post_ui = post_ui
        nv_biz.show_info = lambda t, m, w=win: w.show_info_requested.emit(t, m)
        nv_biz.show_error = lambda t, m, w=win: w.show_error_requested.emit(t, m)

    def nav_task_begin(self, page_index: int) -> None:
        """某功能页有后台任务开始时调用；支持同页多任务重叠（引用计数）。"""
        if page_index < 0 or page_index >= len(self._nav_busy_count):
            return
        self._nav_busy_count[page_index] += 1
        if self._nav_busy_count[page_index] == 1:
            self._nav_show_busy_pulse(page_index)

    def nav_task_end(self, page_index: int) -> None:
        if page_index < 0 or page_index >= len(self._nav_busy_count):
            return
        self._nav_busy_count[page_index] = max(0, self._nav_busy_count[page_index] - 1)
        if self._nav_busy_count[page_index] == 0:
            self._nav_hide_busy_pulse(page_index)

    def _nav_show_busy_pulse(self, idx: int) -> None:
        stripe = self._nav_busy_stripes[idx]
        grp = self._nav_busy_blink[idx]
        eff = stripe.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            eff.setOpacity(1.0)
        stripe.show()
        if animations_enabled():
            grp.start()

    def _nav_hide_busy_pulse(self, idx: int) -> None:
        grp = self._nav_busy_blink[idx]
        grp.stop()
        stripe = self._nav_busy_stripes[idx]
        eff = stripe.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            eff.setOpacity(1.0)
        stripe.hide()

    def _refresh_nav_icon_states(self) -> None:
        selected = "#E5E7EB" if self.dark else "#1a1c1c"
        idle = "#9CA3AF" if self.dark else "#71757D"
        for item in getattr(self, "nav_items", ()):
            item.refresh_icon(selected if item.isChecked() else idle)

    def select_page(self, idx: int):
        if idx < 0 or idx >= len(self.nav_items):
            return
        self.stack.switch_to(idx)
        btn = self.nav_group.button(idx)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        if btn and hasattr(self, "_nav_scroll"):
            QTimer.singleShot(0, lambda b=btn: self._nav_scroll.ensureWidgetVisible(b, 0, 8))
        if hasattr(self, "topbar_title") and idx < len(getattr(self, "_nav_titles", ())):
            self.topbar_title.setText(self._nav_titles[idx])
        self._refresh_nav_icon_states()

    def _sync_theme_from_left(self):
        checked = self.left_theme.isChecked()
        self.dark = not checked
        _save_ui_preferences(theme="dark" if self.dark else "light")
        self.apply_theme()
        self._sync_theme_controls()

    def toggle_theme(self):
        self.dark = not self.dark
        _save_ui_preferences(theme="dark" if self.dark else "light")
        self.apply_theme()

    def _sync_theme_controls(self):
        is_light = not self.dark
        self.left_theme.blockSignals(True)
        self.left_theme.setChecked(is_light)
        self.left_theme.setText("日间模式" if is_light else "夜间模式")
        self.left_theme.blockSignals(False)
        self.mode_chip.setText("日间" if is_light else "夜间")
        self.mode_toggle.setText("")
        icon_name = "moon" if self.dark else "sun"
        icon_color = "#E5E7EB" if self.dark else "#1a1c1c"
        self.mode_toggle.setIcon(mono_svg_icon(icon_name, 16, icon_color))
        self.mode_toggle.setIconSize(QSize(16, 16))
        self.mode_toggle.setProperty("light", is_light)
        self.mode_toggle.setToolTip("切换到日间模式" if self.dark else "切换到夜间模式")
        self.mode_toggle.style().unpolish(self.mode_toggle)
        self.mode_toggle.style().polish(self.mode_toggle)

    def apply_theme(self):
        p = palette(self.dark)
        topbar_bg = "rgba(18,20,24,0.78)" if self.dark else "rgba(255,255,255,0.84)"
        topbar_border = "rgba(255,255,255,0.11)" if self.dark else "rgba(198,198,198,0.34)"
        mode_toggle_icon_hover_lt = "rgba(0,0,0,0.07)"
        mode_toggle_icon_hover_dk = "rgba(255,255,255,0.12)"
        mode_toggle_icon_press_lt = "rgba(0,0,0,0.11)"
        mode_toggle_icon_press_dk = "rgba(255,255,255,0.18)"
        nav_active_border = "rgba(255,255,255,0.12)" if self.dark else "rgba(0,0,0,0.08)"
        nav_active_bg = "rgba(255,255,255,0.06)" if self.dark else p["surface_lowest"]
        nav_hover_bg = "rgba(255,255,255,0.05)" if self.dark else "rgba(0,0,0,0.03)"
        capsule_bg = "rgba(255,255,255,0.10)" if self.dark else "rgba(0,0,0,0.03)"
        capsule_hover_bg = "rgba(255,255,255,0.16)" if self.dark else "rgba(0,0,0,0.06)"
        capsule_border = "rgba(255,255,255,0.22)" if self.dark else "rgba(0,0,0,0.10)"
        capsule_text = "#D4D7DD" if self.dark else p["text"]
        capsule_collapsed_bg = "rgba(255,255,255,0.06)" if self.dark else "rgba(0,0,0,0.02)"
        capsule_collapsed_text = "#9CA3AF" if self.dark else p["muted"]
        deco_word_color = "rgba(0,0,0,0.032)" if not self.dark else "rgba(255,255,255,0.04)"
        primary_dis_bg = "rgba(0,0,0,0.11)" if not self.dark else "rgba(255,255,255,0.10)"
        primary_dis_fg = "#666870" if not self.dark else "#9299a3"
        secondary_hover_bg = "#202630" if self.dark else "#eceeef"
        secondary_pressed_bg = "#2a313c" if self.dark else "#e1e4e7"
        secondary_border_hover = "rgba(255,255,255,0.30)" if self.dark else "rgba(0,0,0,0.20)"
        ghost_hover_border = "rgba(255,255,255,0.14)" if self.dark else "rgba(0,0,0,0.10)"
        ghost_pressed_border = "rgba(255,255,255,0.18)" if self.dark else "rgba(0,0,0,0.14)"
        stitch_card_border = "rgba(198,198,198,0.11)" if not self.dark else "rgba(255,255,255,0.09)"
        status_ready_bg = "rgba(255,255,255,0.08)" if self.dark else "rgba(0,0,0,0.045)"
        status_ready_fg = "#C7CCD4" if self.dark else "#555960"
        status_busy_bg = "rgba(96,165,250,0.16)" if self.dark else "rgba(37,99,235,0.10)"
        status_busy_fg = "#93C5FD" if self.dark else "#1D4ED8"
        status_success_bg = "rgba(74,222,128,0.16)" if self.dark else "rgba(21,128,61,0.10)"
        status_success_fg = "#86EFAC" if self.dark else "#15803D"
        status_warning_bg = "rgba(251,191,36,0.18)" if self.dark else "rgba(161,98,7,0.10)"
        status_warning_fg = "#FDE68A" if self.dark else "#92400E"
        status_error_bg = "rgba(248,113,113,0.18)" if self.dark else "rgba(185,28,28,0.10)"
        status_error_fg = "#FCA5A5" if self.dark else "#B91C1C"
        page_v_groove = "rgba(0,0,0,0.06)" if not self.dark else "rgba(255,255,255,0.08)"
        page_v_handle = "rgba(0,0,0,0.20)" if not self.dark else "rgba(255,255,255,0.22)"
        page_v_handle_h = "rgba(0,0,0,0.34)" if not self.dark else "rgba(255,255,255,0.36)"
        global_scroll_handle = "rgba(0,0,0,0.26)" if not self.dark else "rgba(255,255,255,0.24)"
        global_scroll_handle_h = "rgba(0,0,0,0.42)" if not self.dark else "rgba(255,255,255,0.40)"
        frameless_outline = "rgba(0,0,0,0.14)" if not self.dark else "rgba(255,255,255,0.14)"
        traffic_idle = "rgba(0,0,0,0.16)" if not self.dark else "rgba(255,255,255,0.30)"
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: {p["surface"]}; color: {p["text"]}; border: 1px solid {frameless_outline}; }}
            QDialog#stitch_frameless_dlg {{ background: {p["surface"]}; color: {p["text"]}; border: 1px solid {frameless_outline}; }}
            QWidget {{ color: {p["text"]}; }}
            QWidget#harness_tab {{ background: {p["surface_lowest"]}; }}
            QScrollArea#page_scroll, QWidget#page_root, QWidget#page_viewport {{ background: {p["surface"]}; }}
            QScrollArea#nav_scroll QScrollBar:vertical {{
                width: 0px; max-width: 0px; background: transparent; margin: 0px; border: none;
            }}
            QScrollArea#nav_scroll QScrollBar:horizontal {{
                height: 0px; max-height: 0px; background: transparent; margin: 0px; border: none;
            }}
            QScrollArea#nav_scroll QScrollBar::handle, QScrollArea#nav_scroll QScrollBar::add-line, QScrollArea#nav_scroll QScrollBar::sub-line,
            QScrollArea#nav_scroll QScrollBar::add-page, QScrollArea#nav_scroll QScrollBar::sub-page {{
                background: transparent; border: none; width: 0px; height: 0px;
            }}
            QScrollArea#page_scroll QScrollBar:vertical {{
                width: 5px; background: transparent; margin: 0px 1px 0px 0px; border: none;
            }}
            QScrollArea#page_scroll QScrollBar::groove:vertical {{
                background: {page_v_groove}; border-radius: 2px; width: 3px; margin: 4px 1px 4px 1px;
            }}
            QScrollArea#page_scroll QScrollBar::handle:vertical {{
                background: {page_v_handle};
                border-radius: 2px;
                min-height: 28px;
                margin: 0px 1px 0px 1px;
                max-width: 3px;
            }}
            QScrollArea#page_scroll QScrollBar::handle:vertical:hover {{
                background: {page_v_handle_h};
            }}
            QScrollArea#page_scroll QScrollBar::add-line:vertical, QScrollArea#page_scroll QScrollBar::sub-line:vertical {{
                height: 0px; width: 0px; border: none; background: transparent;
            }}
            QScrollArea#page_scroll QScrollBar::add-page:vertical, QScrollArea#page_scroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollArea#page_scroll QScrollBar:horizontal {{
                height: 5px; background: transparent; margin: 0px 0px 1px 0px; border: none;
            }}
            QScrollArea#page_scroll QScrollBar::groove:horizontal {{
                background: {page_v_groove}; border-radius: 2px; height: 3px; margin: 1px 4px 1px 4px;
            }}
            QScrollArea#page_scroll QScrollBar::handle:horizontal {{
                background: {page_v_handle};
                border-radius: 2px;
                min-width: 28px;
                margin: 1px 0px 1px 0px;
                max-height: 3px;
            }}
            QScrollArea#page_scroll QScrollBar::handle:horizontal:hover {{
                background: {page_v_handle_h};
            }}
            QScrollArea#page_scroll QScrollBar::add-line:horizontal, QScrollArea#page_scroll QScrollBar::sub-line:horizontal {{
                width: 0px; height: 0px; border: none; background: transparent;
            }}
            QScrollArea#page_scroll QScrollBar::add-page:horizontal, QScrollArea#page_scroll QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
            QWidget#page_canvas {{ background: transparent; }}
            QFrame#nav {{ background: {p["surface_low"]}; }}
            QScrollArea#nav_scroll, QWidget#nav_viewport, QWidget#nav_content {{ background: {p["surface_low"]}; }}
            QFrame#topbar {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {topbar_bg}, stop:1 rgba(255,255,255,0.00));
                border-bottom: 1px solid {topbar_border};
            }}
            QLabel#topbar_menu {{ color: #7c7c7c; letter-spacing: 0.7px; font-size: 10pt; }}
            QDialog#stitch_frameless_dlg QLabel#topbar_menu[dialogTitle="true"] {{
                color: {p["text"]};
                letter-spacing: 0.15px;
                font-size: 11pt;
                font-weight: 600;
            }}
            QDialog#stitch_frameless_dlg QPushButton {{ font-size: 10pt; font-weight: 600; }}
            QDialog#stitch_frameless_dlg QLineEdit,
            QDialog#stitch_frameless_dlg QSpinBox,
            QDialog#stitch_frameless_dlg QComboBox,
            QDialog#stitch_frameless_dlg QTextEdit {{ font-size: 10pt; }}
            QLabel#mode_chip {{ color: {p["text"]}; background: transparent; border: none; padding: 0; }}
            QFrame#card {{ background: {p["surface_lowest"]}; border: 1px solid rgba(198,198,198,0.12); border-radius: 14px; }}
            QFrame#card_group {{ background: {p["surface_lowest"]}; border: 1px solid rgba(198,198,198,0.14); border-radius: 14px; }}
            QFrame#card_soft {{ background: {p["surface_lowest"]}; border: 1px solid rgba(198,198,198,0.06); border-radius: 16px; }}
            QLabel#muted {{ color: {p["muted"]}; }}
            QLabel#settings_summary {{ color: {p["muted"]}; font-size: 9pt; }}
            QTableWidget#print_queue {{ background: {p["surface_lowest"]}; color: {p["text"]}; border: 1px solid {p["outline_variant"]}; border-radius: 7px; gridline-color: {p["outline_variant"]}; selection-background-color: {p["surface_high"]}; selection-color: {p["text"]}; }}
            QTableWidget#print_queue QHeaderView::section {{ background: {p["surface_low"]}; color: {p["text"]}; padding: 8px; border: none; font-size: 9pt; font-weight: 600; }}
            QLabel#status_hint {{ color: {p["muted"]}; padding-top: 2px; padding-bottom: 2px; }}
            QFrame#task_status_panel {{ background: transparent; border: none; }}
            QLabel#status_badge {{
                border-radius: 9px;
                padding: 2px 8px;
                min-height: 18px;
                max-height: 20px;
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#status_badge[state="ready"] {{
                background: {status_ready_bg};
                color: {status_ready_fg};
                border: 1px solid rgba(127,127,127,0.12);
            }}
            QLabel#status_badge[state="busy"] {{
                background: {status_busy_bg};
                color: {status_busy_fg};
                border: 1px solid rgba(37,99,235,0.16);
            }}
            QLabel#status_badge[state="success"] {{
                background: {status_success_bg};
                color: {status_success_fg};
                border: 1px solid rgba(21,128,61,0.16);
            }}
            QLabel#status_badge[state="warning"] {{
                background: {status_warning_bg};
                color: {status_warning_fg};
                border: 1px solid rgba(161,98,7,0.16);
            }}
            QLabel#status_badge[state="error"] {{
                background: {status_error_bg};
                color: {status_error_fg};
                border: 1px solid rgba(185,28,28,0.18);
            }}
            QProgressBar#task_progress {{
                background: {p["surface_high"]};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar#task_progress::chunk {{
                background: {p["focus_accent"]};
                border-radius: 3px;
            }}
            QLabel#footer {{ color: {p["muted"]}; background: transparent; }}
            QLabel#nav_brand_logo {{ background: transparent; border: none; border-radius: 10px; padding: 2px 3px 2px 4px; }}
            QLabel#nav_brand {{ color: {p["text"]}; padding-top: 2px; letter-spacing: 0.2px; font-size: 19px; font-weight: 700; }}
            QLabel#nav_brand_sub {{ color: #9b9b9b; padding-bottom: 8px; font-size: 10px; letter-spacing: 1.6px; }}
            QLabel#section_icon {{ color: {p["text"]}; min-width: 16px; }}
            QLabel#section_title {{ color: {p["text"]}; }}
            QLabel#section_mid_title {{ color: {p["muted"]}; padding: 2px 0 2px 0; }}
            QLabel#hero_title {{ color: {p["text"]}; font-size: 15pt; font-weight: 700; }}
            QLabel#hero_subtitle {{ color: {p["muted"]}; font-size: 10pt; }}
            QLabel#deco_word {{ color: {deco_word_color}; font-size: 72px; letter-spacing: 1.5px; padding-right: 6px; }}
            QFrame#stitch_file_card {{
                background: {p["surface_lowest"]};
                border: 1px solid rgba(198,198,198,0.14);
                border-radius: 9px;
            }}
            QFrame#stitch_inner_muted {{
                background: rgba(127,127,127,0.04);
                border: 1px solid rgba(198,198,198,0.12);
                border-radius: 8px;
            }}
            QLabel#stitch_label {{ color: {p["muted"]}; font-size: 9pt; font-weight: 600; letter-spacing: 0px; }}
            QLabel#path_feedback {{ font-size: 9pt; padding-top: 1px; }}
            QLabel#path_feedback[state="valid"] {{ color: {p["success"]}; }}
            QLabel#path_feedback[state="warning"] {{ color: {p["warning"]}; }}
            QLabel#path_feedback[state="invalid"] {{ color: {p["danger"]}; }}
            QFrame#stitch_settings {{
                background: {p["surface_low"]};
                border: 1px solid {stitch_card_border};
                border-radius: 11px;
            }}
            QFrame#stitch_pinned_bar {{
                background: {p["surface_low"]};
                border-top: 1px solid rgba(198,198,198,0.22);
            }}
            QLabel#stitch_settings_title {{ color: {p["text"]}; font-size: 11pt; font-weight: 600; letter-spacing: 0px; }}
            QLabel#stitch_field_label {{ color: {p["muted"]}; font-size: 9pt; font-weight: 600; }}
            QLabel#stitch_subsection_title {{ color: {p["text"]}; font-size: 10pt; font-weight: 600; letter-spacing: 0px; }}
            QFrame#color_swatch {{ border-radius: 4px; border: 1px solid rgba(198,198,198,0.34); }}
            QPushButton#section_toggle {{
                background: transparent;
                border: none;
                color: {p["muted"]};
                padding: 2px 0;
                min-height: 24px;
                text-align: left;
            }}
            QPushButton#section_toggle:checked {{
                color: {p["muted"]};
                background: transparent;
            }}
            QPushButton#section_toggle:focus {{
                color: {p["muted"]};
                border: 1px solid {p["focus_accent"]};
            }}
            QPushButton#section_toggle:checked:focus {{
                color: {p["muted"]};
            }}
            QPushButton#section_toggle:hover {{
                color: {p["text"]};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(127,127,127,0.05), stop:1 rgba(127,127,127,0.00));
            }}
            QPushButton#section_toggle:checked:hover {{
                color: {p["muted"]};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(127,127,127,0.05), stop:1 rgba(127,127,127,0.00));
            }}
            QPushButton#section_toggle:pressed {{ color: {p["text"]}; }}
            QPushButton#section_toggle:checked:pressed {{ color: {p["muted"]}; }}
            QPushButton#section_toggle:disabled {{
                color: {p["muted"]};
                background: transparent;
            }}
            QLineEdit {{ background: {p["surface_lowest"]}; border: 1px solid rgba(198,198,198,0.14); border-radius: 7px; padding: 4px 10px; min-height: 30px; font-size: 10pt; }}
            QLineEdit, QTextEdit {{ placeholder-text-color: {p["muted"]}; }}
            QLineEdit:focus {{ border: 1px solid {p["focus_accent"]}; }}
            QLineEdit[dropState="accept"] {{
                border: 1px solid {p["focus_accent"]};
                background: {status_busy_bg};
            }}
            QLineEdit[validationState="error"] {{
                border: 1px solid {p["danger"]};
                background: rgba(185,28,28,0.06);
            }}
            QSpinBox {{
                background: {p["surface_lowest"]};
                border: 1px solid rgba(198,198,198,0.14);
                border-radius: 7px;
                padding: 4px 10px;
                min-height: 30px;
                font-size: 10pt;
                min-width: 120px;
            }}
            QSpinBox:focus {{ border: 1px solid {p["focus_accent"]}; }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
            QComboBox#stitch_combo {{
                background: {p["surface_lowest"]};
                border: 1px solid rgba(198,198,198,0.14);
                border-radius: 7px;
                padding: 4px 12px;
                min-height: 30px;
                font-size: 10pt;
                color: {p["text"]};
            }}
            QComboBox#stitch_combo:hover {{ border: 1px solid rgba(198,198,198,0.28); }}
            QComboBox#stitch_combo:focus {{ border: 1px solid {p["primary"]}; }}
            QComboBox#stitch_combo:disabled {{
                background: rgba(127,127,127,0.08);
                color: {p["muted"]};
                border: 1px solid rgba(198,198,198,0.10);
            }}
            QComboBox#stitch_combo::drop-down {{ border: none; width: 28px; }}
            QComboBox#stitch_combo QAbstractItemView {{
                background: {p["surface_lowest"]};
                color: {p["text"]};
                selection-background-color: {p["surface_high"]};
                border: 1px solid rgba(198,198,198,0.2);
                border-radius: 6px;
            }}
            QTableWidget#company_schools_table {{
                background: {p["surface_lowest"]};
                alternate-background-color: {p["surface_low"]};
                color: {p["text"]};
                gridline-color: {p["outline_variant"]};
                border: 1px solid rgba(198,198,198,0.20);
                border-radius: 8px;
                selection-background-color: {p["surface_high"]};
                selection-color: {p["text"]};
            }}
            QTableWidget#company_schools_table QLineEdit {{
                border: 1px solid {p["focus_accent"]};
                border-radius: 0;
            }}
            QHeaderView::section {{
                background: {p["surface_low"]};
                color: {p["text"]};
                border: none;
                border-bottom: 1px solid {p["outline_variant"]};
                padding: 8px 10px;
                font-weight: 700;
            }}
            QTextEdit#briefing_file_list, QListWidget#briefing_file_list {{
                background: {p["surface_lowest"]};
                color: {p["text"]};
                border: 1px solid rgba(198,198,198,0.18);
                border-radius: 7px;
                padding: 6px 8px;
            }}
            QListWidget#briefing_file_list::item {{
                min-height: 22px;
                padding: 2px 4px;
                border-radius: 5px;
            }}
            QListWidget#briefing_file_list::item:selected {{
                background: {p["surface_high"]};
                color: {p["text"]};
            }}
            QListWidget#briefing_file_list::item:disabled {{
                color: {p["muted"]};
            }}
            QTextEdit#types_box {{
                background: {p["surface_lowest"]};
                border: 1px solid rgba(198,198,198,0.18);
                border-radius: 9px;
                padding: 8px 10px;
                line-height: 1.45;
            }}
            QTabWidget#brief_tabs::pane {{ border: 1px solid rgba(198,198,198,0.2); border-radius: 10px; background: {p["surface_lowest"]}; }}
            QTabBar#plan_modes::tab,
            QTabWidget#brief_tabs QTabBar::tab {{
                background: {p["surface_low"]};
                color: {p["text"]};
                padding: 9px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
                font-size: 10pt;
                font-weight: 600;
            }}
            QTabBar#plan_modes::tab:selected,
            QTabWidget#brief_tabs QTabBar::tab:selected {{ background: {p["surface_lowest"]}; color: {p["text"]}; }}
            QTabWidget#settings_tabs::pane {{ border: 1px solid rgba(198,198,198,0.2); border-radius: 10px; background: {p["surface_lowest"]}; }}
            QTabWidget#settings_tabs QTabBar::tab {{
                background: {p["surface_low"]};
                color: {p["text"]};
                padding: 9px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
                font-size: 10pt;
                font-weight: 600;
            }}
            QTabWidget#settings_tabs QTabBar::tab:selected {{ background: {p["surface_lowest"]}; color: {p["text"]}; }}
            QTabWidget#settings_tabs QTabBar {{ background: {p["surface_low"]}; }}
            QLabel#brief_log_title {{ color: {p["muted"]}; font-size: 9pt; font-weight: 600; letter-spacing: 0px; }}
            QLabel#classify_log_title {{ color: {p["muted"]}; font-size: 9pt; font-weight: 600; letter-spacing: 0px; }}
            QLabel#industry_log_title {{ color: {p["muted"]}; font-size: 9pt; font-weight: 600; letter-spacing: 0px; }}
            QTextEdit#stitch_run_log {{
                background: {p["surface_low"]};
                border: 1px solid rgba(198,198,198,0.16);
                border-radius: 9px;
                color: {p["text"]};
                font-family: "Cascadia Mono", Consolas, "Microsoft YaHei UI", monospace;
                font-size: 10.5pt;
                line-height: 1.45;
                padding: 8px 10px;
            }}
            QPushButton {{ border: none; border-radius: 7px; min-height: 34px; padding: 0 10px; font-size: 10pt; font-weight: 600; }}
            QPushButton:focus {{ border: 2px solid {p["focus_accent"]}; outline: none; }}
            QPushButton#secondary {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p["surface_lowest"]}, stop:1 rgba(127,127,127,0.08));
                color: {p["text"]};
                border: 1px solid rgba(198,198,198,0.22);
                padding-left: 14px;
                padding-right: 14px;
            }}
            QPushButton#secondary:hover {{
                background: {secondary_hover_bg};
                border: 1px solid {secondary_border_hover};
            }}
            QPushButton#secondary:pressed {{
                background: {secondary_pressed_bg};
                border: 1px solid {secondary_border_hover};
            }}
            QPushButton#secondary:disabled {{
                background: rgba(127,127,127,0.06);
                color: {p["muted"]};
                border: 1px solid rgba(198,198,198,0.12);
            }}
            QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p["primary"]}, stop:1 {p["primary_container"]}); color: #ffffff; min-height: 36px; padding-left: 13px; padding-right: 13px; }}
            QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p["primary_container"]}, stop:1 {p["primary"]}); }}
            QPushButton#primary:pressed {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p["primary_container"]}, stop:1 {p["primary_container"]}); }}
            QPushButton#primary:disabled {{
                background: {primary_dis_bg};
                color: {primary_dis_fg};
                border: 1px solid rgba(198,198,198,0.12);
            }}
            QPushButton#danger {{
                background: transparent;
                color: {p["danger"]};
                border: 1px solid {p["danger"]};
                padding-left: 13px;
                padding-right: 13px;
            }}
            QPushButton#danger:hover {{ background: {p["danger"]}; color: #ffffff; }}
            QPushButton#danger:pressed {{ background: #991b1b; color: #ffffff; }}
            QPushButton#primary:focus,
            QPushButton#secondary:focus,
            QPushButton#danger:focus,
            QPushButton#navitem:focus {{ border: 2px solid {p["focus_accent"]}; }}
            QPushButton#ghost {{
                background: transparent;
                color: {p["muted"]};
                border: 1px solid transparent;
                padding: 0 2px;
                min-height: 22px;
            }}
            QPushButton#ghost:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(127,127,127,0.05), stop:1 rgba(127,127,127,0.02));
                border: 1px solid {ghost_hover_border};
                color: {p["text"]};
            }}
            QPushButton#ghost:pressed {{
                background: rgba(127,127,127,0.10);
                border: 1px solid {ghost_pressed_border};
            }}
            QPushButton#capsule {{ background: {capsule_bg}; color: {capsule_text}; border: 1px solid {capsule_border}; border-radius: 14px; padding: 0 14px; min-height: 32px; }}
            QPushButton#capsule:hover {{ background: {capsule_hover_bg}; border: 1px solid {capsule_border}; }}
            QPushButton#capsule:pressed {{ background: {capsule_hover_bg}; border: 1px solid {capsule_border}; }}
            QPushButton#capsule[expanded="false"] {{ background: {capsule_collapsed_bg}; color: {capsule_collapsed_text}; border: 1px solid {capsule_border}; }}
            QPushButton#navitem {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 10px;
                color: {p["muted"]};
                margin-bottom: 3px;
                padding: 0 10px;
                text-align: left;
            }}
            QPushButton#navitem:hover {{
                background: {nav_hover_bg};
                border: 1px solid transparent;
                color: {p["text"]};
            }}
            QPushButton#navitem:checked {{
                background: {nav_active_bg};
                border: 1px solid {nav_active_border};
                color: {p["text"]};
            }}
            QLabel#nav_group_label {{
                color: {p["muted"]};
                padding: 14px 10px 5px 10px;
                font-size: 10px;
                font-weight: 700;
            }}
            QFrame#nav_divider {{ background: rgba(198,198,198,0.35); margin-left: 12px; margin-right: 12px; }}
            QCheckBox {{ spacing: 6px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid {p["outline_variant"]}; background: {p["surface_lowest"]}; }}
            QCheckBox::indicator:checked {{ background: {p["focus_accent"]}; border-color: {p["focus_accent"]}; }}
            QCheckBox#left_theme {{ color: {p["muted"]}; padding: 6px 8px; background: {p["surface_lowest"]}; border: 1px solid rgba(0,0,0,0.06); border-radius: 10px; margin-top: 4px; margin-bottom: 6px; }}
            QPushButton#mode_toggle {{
                border: none;
                border-radius: 14px;
                padding: 0;
                min-height: 28px;
                max-height: 28px;
                min-width: 28px;
                max-width: 28px;
            }}
            QPushButton#mode_toggle[light="true"] {{
                background: transparent;
                color: {p["text"]};
            }}
            QPushButton#mode_toggle[light="true"]:hover {{
                background: {mode_toggle_icon_hover_lt};
            }}
            QPushButton#mode_toggle[light="true"]:pressed {{
                background: {mode_toggle_icon_press_lt};
            }}
            QPushButton#mode_toggle[light="false"] {{
                background: transparent;
                color: #E5E7EB;
            }}
            QPushButton#mode_toggle[light="false"]:hover {{
                background: {mode_toggle_icon_hover_dk};
            }}
            QPushButton#mode_toggle[light="false"]:pressed {{
                background: {mode_toggle_icon_press_dk};
            }}
            QPushButton#nav_foot {{
                text-align: left;
                background: transparent;
                color: {p["muted"]};
                border-radius: 8px;
                min-height: 30px;
                border: 1px solid transparent;
            }}
            QPushButton#nav_foot:hover {{
                background: rgba(0,0,0,0.05);
                color: {p["text"]};
                border: 1px solid rgba(0,0,0,0.07);
            }}
            QFrame#nav_busy_line {{
                min-width: 2px; max-width: 2px; min-height: 20px; max-height: 20px;
                border-radius: 1px;
                background: {p["focus_accent"]};
            }}
            QWidget#traffic_lights_wrap {{ background: transparent; border: none; }}
            QPushButton#traffic_close, QPushButton#traffic_minimize, QPushButton#traffic_zoom {{
                min-height: 28px; max-height: 28px; min-width: 28px; max-width: 28px;
                padding: 0; border: none; border-radius: 6px; background: transparent;
            }}
            QPushButton#traffic_minimize:hover {{ background: #28c840; }}
            QPushButton#traffic_minimize:pressed {{ background: #24b038; }}
            QPushButton#traffic_zoom:hover {{ background: #febc2e; }}
            QPushButton#traffic_zoom:pressed {{ background: #dea520; }}
            QPushButton#traffic_close:hover {{ background: #ff5f57; }}
            QPushButton#traffic_close:pressed {{ background: #e04b44; }}
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 2px 4px 0; }}
            QScrollBar::handle:vertical {{ background: {global_scroll_handle}; min-height: 38px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {global_scroll_handle_h}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; background: transparent; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        )
        self._refresh_nav_icon_states()
        for btn in self.findChildren(QPushButton):
            refresh_mono_button_icon(btn, self.dark)
        dpr = max(_gui_device_pixel_ratio(), 1.0)
        # 槽位 44×44，样式约 2+4px 水平 padding，内容区约 36px；再略缩小绘制避免尖角贴边被 QLabel 裁切
        logical_draw = 34
        phys = max(16, int(round(logical_draw * dpr)))
        pm = self.windowIcon().pixmap(QSize(phys, phys), QIcon.Mode.Normal, QIcon.State.Off)
        if pm is not None and not pm.isNull():
            tw = max(1, int(round(logical_draw * dpr)))
            pm = pm.scaled(
                tw,
                tw,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pm.setDevicePixelRatio(dpr)
            self._brand_logo.setPixmap(pm)
        if hasattr(self, "stack") and self.stack.count() > NAV_PAGE_DASHBOARD:
            dashboard_page = self.stack.widget(NAV_PAGE_DASHBOARD)
            if hasattr(dashboard_page, "apply_theme"):
                dashboard_page.apply_theme(dashboard_palette(self.dark))
        if hasattr(self, "harness_page"):
            self.harness_page.set_theme(self.dark)
        self._sync_theme_controls()


if __name__ == "__main__":
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            # 保持与系统缩放一致，恢复与开发态接近的界面体感尺寸。
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except (AttributeError, TypeError):
        pass
    app = QApplication(sys.argv)
    app.setFont(ui_font("body"))
    w = MainWindow()
    w.show()
    if "--ui-smoke-test" in sys.argv:
        # Release startup check: build every native page, then close normally.
        QTimer.singleShot(800, w.close)
        QTimer.singleShot(1200, app.quit)
    sys.exit(app.exec())
