"""
工具集「工作台日历」界面：与主程序同一套字阶、栅格、卡片与配色（Qt Widgets）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import nv_work_calendar as nwc
from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QModelIndex,
    QPoint,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    QTime,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTimeEdit,
    QToolTip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

WEEKDAY_H = ("一", "二", "三", "四", "五", "六", "日")


def _fmt_clock(mins: int) -> str:
    h, m = divmod(int(mins), 60)
    return f"{h:02d}:{m:02d}"


def _surface_is_dark(hex_color: str) -> bool:
    s = (hex_color or "").strip().lstrip("#")
    if len(s) < 6:
        return False
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140.0


def _month_cell_selected_bg(p: Dict[str, str]) -> str:
    """月历选中格：不用 primary_container（主程序里为深灰，供主按钮渐变用）。"""
    if _surface_is_dark(p.get("surface_lowest", "#ffffff")):
        return "rgba(96, 165, 250, 0.16)"
    return "rgba(37, 99, 235, 0.09)"


def _card(tokens: Dict[str, Any], radius_key: str = "lg") -> QFrame:
    f = QFrame()
    f.setObjectName("wc_card")
    return f


def _section_title(text: str, ui_font_fn: Callable[..., QFont]) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("wc_section_title")
    lb.setFont(ui_font_fn("title", QFont.Weight.DemiBold))
    return lb


class MonthCellButton(QPushButton):
    """自绘月格：日期大字，事项计数小字，层级清晰。"""
    doubleClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._day_text = ""
        self._meta_text = ""
        self._day_color = QColor("#111111")
        self._meta_color = QColor("#666666")
        self.setText("")

    def set_content(
        self,
        day_text: str,
        meta_text: str,
        day_color: str,
        meta_color: str,
    ) -> None:
        self._day_text = str(day_text or "")
        self._meta_text = str(meta_text or "")
        self._day_color = QColor(day_color)
        self._meta_color = QColor(meta_color)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 顶部日期作为主信息，底部计数作为次信息，拉开视觉层级
        top_pad = 12
        left_pad = 12
        bottom_pad = 12

        p.setPen(self._day_color)
        f_day = QFont(self.font())
        f_day.setPointSize(max(11, f_day.pointSize() + 1))
        f_day.setWeight(QFont.Weight.Medium)
        p.setFont(f_day)
        p.drawText(left_pad, top_pad + 20, self._day_text)
        if self._meta_text:
            p.setPen(self._meta_color)
            f_meta = QFont(self.font())
            f_meta.setPointSize(max(8, f_meta.pointSize() - 1))
            f_meta.setWeight(QFont.Weight.Normal)
            p.setFont(f_meta)
            p.drawText(left_pad, self.height() - bottom_pad, self._meta_text)

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class WcCalendarDialog(QDialog):
    """与「设置」等无边框弹窗一致：单一边框壳（stitch_frameless_dlg），无半透明外圈叠层。"""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        *,
        buttons: str = "yes_no",
        palette_provider: Callable[[], dict[str, str]],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stitch_frameless_dlg")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        p = palette_provider()
        bg = p.get("surface_lowest", "#ffffff")
        text_c = p.get("text", "#111111")
        border = p.get("outline_variant", "#e5e5e5")
        accent = p.get("focus_accent", "#2563eb")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Import when the dialog opens, after the main toolkit has initialized.
        from toolkit import stitch_dialog_prepend_chrome_topbar
        stitch_dialog_prepend_chrome_topbar(self, outer, title, on_traffic_close=self.reject)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 4, 16, 18)
        bl.setSpacing(14)
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {text_c}; font-size: 14px;")
        bl.addWidget(msg)

        btn_style = f"""
            QPushButton {{
                min-width: 84px;
                min-height: 34px;
                border-radius: 10px;
                border: 1px solid {border};
                background: {bg};
                color: {text_c};
                padding: 0px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border: 1px solid {accent};
                background: rgba(127,127,127,0.06);
            }}
        """
        row = QHBoxLayout()
        row.addStretch(1)
        if buttons == "yes_no":
            btn_no = QPushButton("否")
            btn_yes = QPushButton("是")
            btn_no.setStyleSheet(btn_style)
            btn_yes.setStyleSheet(btn_style)
            btn_no.setDefault(True)
            btn_no.setAutoDefault(True)
            btn_no.clicked.connect(self.reject)
            btn_yes.clicked.connect(self.accept)
            row.addWidget(btn_no)
            row.addWidget(btn_yes)
        else:
            btn_ok = QPushButton("确定")
            btn_ok.setStyleSheet(btn_style)
            btn_ok.setDefault(True)
            btn_ok.setAutoDefault(True)
            btn_ok.clicked.connect(self.accept)
            row.addWidget(btn_ok)
        bl.addLayout(row)
        outer.addWidget(body)

        self.setMinimumWidth(320)
        self.setMaximumWidth(480)

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self.reject)


class WorkCalendarIntegratedWidget(QWidget):
    """单页工作台：聚焦日历排程，支持滚轮滚动。"""

    def __init__(
        self,
        bundle_dir: Path,
        main_window: Any,
        *,
        tokens: Dict[str, Any],
        ui_font_fn: Callable[..., QFont],
        palette_provider: Callable[[], Dict[str, str]],
    ) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = tokens
        self._ui_font = ui_font_fn
        self._palette_provider = palette_provider

        (
            self._db_path,
            self.task_model,
            self.calendar,
            self._quad0,
            self._quad1,
            self._quad2,
            self._quad3,
            self._pomodoro,
            self.bridge,
        ) = nwc.build_calendar_context(bundle_dir)

        sp = self._tokens["space"]
        self._sp = sp
        self._quad_tag_mode = "short_cn"
        self._quad_tag_sets: dict[str, tuple[str, str, str, str]] = {
            "q": ("Q1", "Q2", "Q3", "Q4"),
            "short_cn": ("重急", "重缓", "轻急", "轻缓"),
        }

        self._day_list = QListWidget(self)
        self._day_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._day_list.setAlternatingRowColors(True)
        self._day_list.setSpacing(2)
        self._day_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._day_list.setMinimumHeight(280)
        self._day_list.setMaximumHeight(440)

        self._week_lists: list[QListWidget] = []
        self._week_head_labels: list[QLabel] = []
        self._quad_lists: list[QListWidget] = []
        self._quad_stat_labels: list[QLabel] = []

        self._cal_stack = QStackedWidget()
        self._seg_btns: list[QPushButton] = []
        self._collapse_anims: list[QParallelAnimationGroup] = []
        self._stack_fade_anim: QPropertyAnimation | None = None
        self._month_grid_dirty = False
        self._shortcuts: list[QShortcut] = []
        self._pm_time: QLabel | None = None
        self._pm_state: QLabel | None = None
        self._pm_bind: QLabel | None = None
        self._pm_btn_start: QPushButton | None = None
        self._pm_btn_stop: QPushButton | None = None
        self._pm_sound_chk: QCheckBox | None = None
        self._exec_filter_combo: QComboBox | None = None
        self._exec_filter_mode = "all"
        self._syncing_cross_select = False
        self._syncing_day_hour = False
        self._syncing_task_check = False
        self._pm_prev_running = False
        self._pm_prev_remaining = int(self._pomodoro.remainingSeconds)

        self._build_ui()
        self._wire()
        self._install_shortcuts()
        self.apply_theme(self._palette_provider())

    def _build_ui(self) -> None:
        sp = self._sp
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._content_scroll = QScrollArea(self)
        self._content_scroll.setObjectName("page_scroll")
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        page = QWidget()
        page.setObjectName("page_root")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.setSpacing(0)
        self._content_scroll.viewport().setObjectName("page_viewport")

        canvas = QWidget()
        canvas.setObjectName("page_canvas")
        canvas.setMaximumWidth(16777215)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas_l = QVBoxLayout(canvas)
        canvas_l.setContentsMargins(40, 14, 40, 14)
        canvas_l.setSpacing(10)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addWidget(self._build_calendar_panel(), 1)
        canvas_l.addLayout(body, 0)
        page_l.addWidget(canvas, 1)
        self._content_scroll.setWidget(page)
        outer.addWidget(self._content_scroll, 1)

    def _setup_section_toggle(
        self,
        btn: QPushButton,
        collapsed_title: str,
        expanded_title: str,
    ) -> None:
        btn.setObjectName("section_toggle")
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(36)
        btn.setFont(self._ui_font("body", QFont.Weight.DemiBold))
        btn.setText(f"+  {collapsed_title}")
        btn.toggled.connect(
            lambda on: btn.setText(f"{'-' if on else '+'}  {expanded_title if on else collapsed_title}")
        )

    def _setup_date_edit(self, edit: QDateEdit, *, value: QDate | None = None) -> None:
        edit.setObjectName("wc_date_input")
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setCalendarPopup(True)
        edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        edit.setAccelerated(True)
        edit.setWrapping(False)
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setKeyboardTracking(False)
        edit.setToolTip("点击右侧按钮打开日历，或使用上下按钮微调日期")
        cal = QCalendarWidget(edit)
        cal.setObjectName("wc_popup_calendar")
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        cal.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.SingleLetterDayNames)
        cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        cal.setMinimumSize(340, 286)
        edit.setCalendarWidget(cal)
        if value is not None:
            edit.setDate(value)

    def _on_month_range_start_changed(self, d: QDate) -> None:
        if not hasattr(self, "_mo_e"):
            return
        if d > self._mo_e.date():
            self._mo_e.setDate(d)

    def _on_month_range_end_changed(self, d: QDate) -> None:
        if not hasattr(self, "_mo_s"):
            return
        if d < self._mo_s.date():
            self._mo_s.setDate(d)

    def _bind_collapsible(self, toggle_btn: QPushButton, card: QWidget, *, animated: bool = True) -> None:
        if not animated:
            card.setVisible(False)
            card.setMaximumHeight(16777215)

            def _on_toggle_instant(on: bool) -> None:
                card.setVisible(bool(on))

            toggle_btn.toggled.connect(_on_toggle_instant)
            return
        card.setVisible(False)
        card.setMaximumHeight(0)
        op = QGraphicsOpacityEffect(card)
        op.setOpacity(0.0)
        card.setGraphicsEffect(op)

        a_h = QPropertyAnimation(card, b"maximumHeight", card)
        a_h.setDuration(180)
        a_h.setEasingCurve(QEasingCurve.Type.OutCubic)
        a_o = QPropertyAnimation(op, b"opacity", card)
        a_o.setDuration(150)
        a_o.setEasingCurve(QEasingCurve.Type.OutCubic)
        g = QParallelAnimationGroup(card)
        g.addAnimation(a_h)
        g.addAnimation(a_o)
        self._collapse_anims.append(g)

        def _on_toggle(on: bool) -> None:
            g.stop()
            target_h = max(1, card.sizeHint().height())
            if on:
                card.setVisible(True)
                a_h.setStartValue(max(0, card.maximumHeight()))
                a_h.setEndValue(target_h)
                a_o.setStartValue(float(op.opacity()))
                a_o.setEndValue(1.0)
            else:
                a_h.setStartValue(max(1, card.maximumHeight()))
                a_h.setEndValue(0)
                a_o.setStartValue(float(op.opacity()))
                a_o.setEndValue(0.0)
            g.start()

        def _on_finished() -> None:
            if not toggle_btn.isChecked():
                card.setVisible(False)

        g.finished.connect(_on_finished)
        toggle_btn.toggled.connect(_on_toggle)

    def _fade_in_current_stack_page(self) -> None:
        return

    def _install_shortcuts(self) -> None:
        sc_today = QShortcut(QKeySequence("T"), self)
        sc_today.activated.connect(self._jump_to_today_tasks)
        sc_new = QShortcut(QKeySequence("N"), self)
        sc_new.activated.connect(self._focus_new_day_task)
        sc_left = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        sc_left.activated.connect(lambda: self._move_selected_date(-1))
        sc_right = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        sc_right.activated.connect(lambda: self._move_selected_date(1))
        sc_up = QShortcut(QKeySequence(Qt.Key.Key_Up), self)
        sc_up.activated.connect(lambda: self._move_selected_date(-7))
        sc_down = QShortcut(QKeySequence(Qt.Key.Key_Down), self)
        sc_down.activated.connect(lambda: self._move_selected_date(7))
        self._shortcuts.extend([sc_today, sc_new, sc_left, sc_right, sc_up, sc_down])

    def _focus_new_day_task(self) -> None:
        self._seg_btns[0].setChecked(True)
        self._on_calendar_tab_changed(0)
        if not self._day_form_toggle.isChecked():
            self._day_form_toggle.setChecked(True)
        self._day_title.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._day_title.selectAll()

    def _move_selected_date(self, delta_days: int) -> None:
        if self._cal_stack.currentIndex() != 2:
            return
        d = self.calendar.selected_date().addDays(int(delta_days))
        iso = d.toString(Qt.DateFormat.ISODate)
        self.calendar.selectedDateIso = iso
        self.calendar.weekStartIso = d.addDays(-(d.dayOfWeek() - 1)).toString(Qt.DateFormat.ISODate)
        self.calendar.monthAnchorIso = QDate(d.year(), d.month(), 1).toString(Qt.DateFormat.ISODate)

    def _toast(self, msg: str, ms: int = 1600) -> None:
        QToolTip.showText(QCursor.pos(), msg, self, self.rect(), max(800, int(ms)))

    def _on_quad_tag_mode_changed(self, _idx: int) -> None:
        return

    def _quad_tag(self, v: Any) -> str:
        try:
            q = int(v)
        except (TypeError, ValueError):
            q = 0
        qi = max(0, min(3, q))
        tags = self._quad_tag_sets.get(self._quad_tag_mode, self._quad_tag_sets["q"])
        return tags[qi]

    def _task_snapshot_by_id(self, task_id: int) -> Optional[dict]:
        return self.task_model.task_snapshot(int(task_id))

    def _item_task_id(self, it: QListWidgetItem | None) -> Optional[int]:
        if it is None:
            return None
        tid = it.data(Qt.ItemDataRole.UserRole)
        if tid is None:
            return None
        try:
            return int(tid)
        except (TypeError, ValueError):
            return None

    def _task_is_completed(self, task_id: int) -> bool:
        snap = self._task_snapshot_by_id(task_id) or {}
        return bool(snap.get("completed", False))

    def _completed_snapshots(self) -> list[dict]:
        out: list[dict] = []
        for r in range(self.task_model.rowCount()):
            ix = self.task_model.index(r, 0)
            tid = self.task_model.data(ix, nwc.TaskModel.IdRole)
            if tid is None:
                continue
            if not bool(self.task_model.data(ix, nwc.TaskModel.CompletedRole)):
                continue
            snap = self._task_snapshot_by_id(int(tid))
            if snap:
                out.append(snap)
        return out

    def _line_from_snapshot_for_day(self, snap: dict) -> tuple[str, bool]:
        title = str(snap.get("title") or "")
        quad = snap.get("quadrant", 0)
        qtag = self._quad_tag(quad)
        st = nwc._parse_local_iso(str(snap.get("start_datetime") or ""))
        ed = nwc._parse_local_iso(str(snap.get("end_datetime") or ""))
        due = str(snap.get("due_date") or "").strip()
        if st and ed and ed > st:
            if st.date() != ed.date() or bool(snap.get("all_day", False)):
                return f"{qtag} · 全天  {title}", False
            start_m = st.hour * 60 + st.minute
            end_m = ed.hour * 60 + ed.minute
            return f"{qtag} · {_fmt_clock(start_m)}-{_fmt_clock(end_m)}  {title}", False
        if due:
            return f"{qtag} · 截止  {title}", True
        return f"{qtag} · 任务  {title}", True

    def _calendar_alert(self, title: str, text: str) -> None:
        d = WcCalendarDialog(
            self,
            title,
            text,
            buttons="ok",
            palette_provider=self._palette_provider,
        )
        d.exec()

    def _ask_yes_no(self, title: str, text: str) -> bool:
        d = WcCalendarDialog(
            self,
            title,
            text,
            buttons="yes_no",
            palette_provider=self._palette_provider,
        )
        return d.exec() == int(QDialog.DialogCode.Accepted)

    def _apply_task_item_state(self, it: QListWidgetItem, completed: bool) -> None:
        flags = it.flags() | Qt.ItemFlag.ItemIsUserCheckable
        it.setFlags(flags)
        it.setCheckState(
            Qt.CheckState.Checked if completed else Qt.CheckState.Unchecked
        )
        f = it.font()
        f.setStrikeOut(bool(completed))
        it.setFont(f)
        it.setForeground(
            QColor("#9ca3af") if completed else QColor(self._palette_provider().get("text", "#111111"))
        )

    def _on_task_item_check_changed(self, it: QListWidgetItem) -> None:
        if self._syncing_task_check:
            return
        tid = self._item_task_id(it)
        if tid is None:
            return
        checked = it.checkState() == Qt.CheckState.Checked
        old = self._task_is_completed(int(tid))
        if checked == old:
            return
        self.bridge.completeTask(int(tid), checked)
        self._toast("已标记完成" if checked else "已恢复为未完成", 1200)

    def _confirm_conflicts(self, start_dt: str, end_dt: str, exclude_task_id: int = -1) -> bool:
        rows = self.bridge.detectConflicts(start_dt, end_dt, int(exclude_task_id))
        if not rows:
            return True
        top = ", ".join(str(r.get("title", "")).strip() or "未命名任务" for r in rows[:3])
        more = "" if len(rows) <= 3 else f" 等 {len(rows)} 项"
        return self._ask_yes_no(
            "检测到时间冲突",
            f"该时段与已有任务重叠：{top}{more}\n是否仍继续保存？",
        )

    def _open_edit_basic_dialog(self, task_id: int) -> bool:
        snap = self._task_snapshot_by_id(task_id)
        if not snap:
            self._calendar_alert("任务不存在", "该任务已不存在，列表将刷新。")
            self.calendar.refresh()
            return False
        title, ok = QInputDialog.getText(
            self,
            "编辑任务标题",
            "标题：",
            text=str(snap.get("title") or ""),
        )
        if not ok:
            return False
        title = (title or "").strip()
        if not title:
            self._calendar_alert("标题为空", "请输入任务标题。")
            return False
        quad_items = ["重要且紧急", "重要不紧急", "不重要但紧急", "不重要不紧急"]
        cur_q = int(snap.get("quadrant") or 0)
        q_name, ok_q = QInputDialog.getItem(
            self,
            "编辑任务象限",
            "象限：",
            quad_items,
            max(0, min(3, cur_q)),
            False,
        )
        if not ok_q:
            return False
        q_idx = quad_items.index(q_name)
        self.bridge.updateTaskBasic(int(task_id), title, int(q_idx))
        return True

    def _open_reschedule_dialog(self, task_id: int) -> bool:
        snap = self._task_snapshot_by_id(task_id)
        if not snap:
            self._calendar_alert("任务不存在", "该任务已不存在，列表将刷新。")
            self.calendar.refresh()
            return False

        d = QDialog(self)
        d.setWindowTitle("调整排程")
        dl = QVBoxLayout(d)
        form = QGridLayout()
        form.setHorizontalSpacing(self._sp["sm"])
        form.setVerticalSpacing(self._sp["sm"])
        title = QLabel("日期")
        date_edit = QDateEdit()
        self._setup_date_edit(date_edit)
        t0 = QTimeEdit()
        t0.setDisplayFormat("HH:mm")
        t1 = QTimeEdit()
        t1.setDisplayFormat("HH:mm")
        form.addWidget(title, 0, 0)
        form.addWidget(date_edit, 0, 1, 1, 3)
        form.addWidget(QLabel("开始"), 1, 0)
        form.addWidget(t0, 1, 1)
        form.addWidget(QLabel("结束"), 1, 2)
        form.addWidget(t1, 1, 3)
        dl.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dl.addWidget(btns)
        btns.accepted.connect(d.accept)
        btns.rejected.connect(d.reject)

        selected = self.calendar.selected_date()
        date_edit.setDate(selected)
        t0.setTime(QTime(9, 0))
        t1.setTime(QTime(10, 0))
        st = nwc._parse_local_iso(str(snap.get("start_datetime") or ""))
        ed = nwc._parse_local_iso(str(snap.get("end_datetime") or ""))
        if st and ed and ed > st:
            date_edit.setDate(QDate(st.year, st.month, st.day))
            t0.setTime(QTime(st.hour, st.minute))
            t1.setTime(QTime(ed.hour, ed.minute))

        if d.exec() != QDialog.DialogCode.Accepted:
            return False

        qd = date_edit.date()
        h0 = t0.time().hour()
        m0 = t0.time().minute()
        h1 = t1.time().hour()
        m1 = t1.time().minute()
        start = f"{qd.toString(Qt.DateFormat.ISODate)}T{h0:02d}:{m0:02d}:00"
        end = f"{qd.toString(Qt.DateFormat.ISODate)}T{h1:02d}:{m1:02d}:00"
        sdt = nwc._parse_local_iso(start)
        edt = nwc._parse_local_iso(end)
        if not sdt or not edt or edt <= sdt:
            self._calendar_alert("时间无效", "结束时间必须晚于开始时间。")
            return False
        if not self._confirm_conflicts(start, end, task_id):
            return False
        self.bridge.updateTaskSchedule(int(task_id), start, end, False)
        return True

    def _open_task_context_menu(self, source_list: QListWidget, pos) -> None:
        it = source_list.itemAt(pos)
        tid = self._item_task_id(it)
        if tid is None:
            return
        snap = self._task_snapshot_by_id(tid) or {}
        is_completed = bool(snap.get("completed", False))
        is_due_only = bool(it.data(Qt.ItemDataRole.UserRole + 1)) if it is not None else False
        m = QMenu(source_list)
        act_edit = m.addAction("编辑标题/象限")
        act_res = m.addAction("调整排程")
        act_done = m.addAction("恢复为未完成" if is_completed else "标记完成")
        act_del = m.addAction("删除任务")
        act_clr = m.addAction("清除排程")
        act_clr.setEnabled(not is_due_only)
        sub_q = m.addMenu("移动到象限")
        q_actions = []
        for i, n in enumerate(("重要且紧急", "重要不紧急", "不重要但紧急", "不重要不紧急")):
            a = sub_q.addAction(n)
            a.setData(i)
            q_actions.append(a)
        chosen = m.exec(source_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_edit:
            if self._open_edit_basic_dialog(tid):
                self._toast("任务信息已更新")
            return
        if chosen == act_res:
            if self._open_reschedule_dialog(tid):
                self._toast("排程已调整")
            return
        if chosen == act_done:
            self.bridge.completeTask(int(tid), not is_completed)
            self._toast("已恢复为未完成" if is_completed else "已标记完成")
            return
        if chosen == act_del:
            if self._ask_yes_no("确认删除", "删除后不可恢复，是否继续？"):
                self.bridge.removeTask(int(tid))
                self._toast("任务已删除")
            return
        if chosen == act_clr:
            self.bridge.clearSchedule(int(tid))
            self._toast("排程已清除")
            return
        if chosen in q_actions:
            qv = int(chosen.data())
            self.bridge.setQuadrant(int(tid), qv)
            self._toast(f"已移动到 {self._quad_tag(qv)}")

    def _build_calendar_panel(self) -> QWidget:
        sp = self._sp
        h_key = 40
        h_ctrl = 36
        w_seg = 84
        w_top = 120
        w_action = 96
        w_nav = 96
        root = QWidget()
        root.setObjectName("wc_calendar_root")
        root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vl = QVBoxLayout(root)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)

        overview = QFrame()
        overview.setObjectName("wc_overview_card")
        overview.setFixedHeight(80)
        ovl = QHBoxLayout(overview)
        # 右侧统计按钮组整体微调向右（缩小右内边距）
        ovl.setContentsMargins(sp["md"], sp["sm"], max(0, sp["md"] - 10), sp["sm"])
        ovl.setSpacing(sp["md"])
        ovl.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        ov_text = QVBoxLayout()
        ov_text.setSpacing(2)
        self._ov_title = QLabel("")
        self._ov_title.setObjectName("wc_overview_title")
        self._ov_title.setFont(self._ui_font("display", QFont.Weight.Bold))
        self._ov_sub = QLabel("点击“今日任务”可直达当日时间轴；点击月历日期可跳转。")
        self._ov_sub.setObjectName("wc_overview_sub")
        self._ov_sub.setFont(self._ui_font("caption"))
        ov_text.addWidget(self._ov_title)
        ov_text.addWidget(self._ov_sub)
        ovl.addLayout(ov_text, 1)

        self._ov_chip_total = QPushButton("今日任务 0")
        self._ov_chip_total.setObjectName("wc_stat_chip_btn")
        self._ov_chip_total.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ov_chip_total.clicked.connect(self._jump_to_today_tasks)
        self._ov_chip_total.setFixedSize(w_top, h_key)
        ovl.addWidget(self._ov_chip_total, 0)

        self._ov_btn_today = QPushButton("回到今天")
        self._ov_btn_today.setObjectName("primary")
        self._ov_btn_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ov_btn_today.clicked.connect(self.calendar.goToday)
        self._ov_btn_today.setFixedSize(w_top, h_key)
        ovl.addWidget(self._ov_btn_today, 0)
        vl.addWidget(overview)

        # 分段控件：日 | 周 | 月
        seg_row = QHBoxLayout()
        seg_row.setSpacing(0)
        self._seg_btns.clear()
        for i, lab in enumerate(("日", "周", "月")):
            btn = QPushButton(lab)
            btn.setObjectName("wc_seg")
            btn.setCheckable(True)
            btn.setFixedSize(w_seg, h_ctrl)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(self._ui_font("label", QFont.Weight.Medium))
            if i == 2:
                btn.setChecked(True)
            self._seg_btns.append(btn)
            seg_row.addWidget(btn)
        seg_wrap = QFrame()
        seg_wrap.setObjectName("wc_seg_wrap")
        sw_l = QHBoxLayout(seg_wrap)
        sw_l.setContentsMargins(4, 4, 4, 4)
        sw_l.setSpacing(4)
        for b in self._seg_btns:
            sw_l.addWidget(b)
        seg_row_w = QHBoxLayout()
        seg_row_w.addWidget(seg_wrap, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        seg_row_w.addStretch(1)
        self._month_nav_wrap = QFrame()
        self._month_nav_wrap.setObjectName("wc_seg_wrap")
        self._month_nav_wrap.setVisible(False)
        self._month_nav_l = QHBoxLayout(self._month_nav_wrap)
        self._month_nav_l.setContentsMargins(4, 4, 4, 4)
        self._month_nav_l.setSpacing(4)
        seg_row_w.addWidget(
            self._month_nav_wrap,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        vl.addLayout(seg_row_w)

        self._seg_group = QButtonGroup(self)
        self._seg_group.setExclusive(True)
        for i, btn in enumerate(self._seg_btns):
            self._seg_group.addButton(btn, i)
        self._seg_group.idClicked.connect(self._on_calendar_tab_changed)
        self._cal_stack.setCurrentIndex(2)

        vl.addWidget(self._cal_stack, 1)

        # —— 日 ——
        day_page = QWidget()
        dl = QVBoxLayout(day_page)
        dl.setContentsMargins(0, sp["sm"], 0, 0)
        dl.setSpacing(sp["sm"])
        nav = QHBoxLayout()
        self._btn_prev_d = QPushButton("◀")
        self._btn_next_d = QPushButton("▶")
        self._btn_prev_d.setObjectName("secondary")
        self._btn_next_d.setObjectName("secondary")
        self._btn_prev_d.setFixedSize(48, h_ctrl)
        self._btn_next_d.setFixedSize(48, h_ctrl)
        self._lbl_day = QLabel("")
        self._lbl_day.setObjectName("wc_date_hero")
        self._lbl_day.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_prev_d.clicked.connect(self.calendar.prevDay)
        self._btn_next_d.clicked.connect(self.calendar.nextDay)
        nav.addWidget(self._btn_prev_d)
        nav.addWidget(self._lbl_day, 1)
        nav.addWidget(self._btn_next_d)
        dl.addLayout(nav)

        dl.addWidget(self._day_list, 1)
        self._day_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._day_list.customContextMenuRequested.connect(
            lambda p: self._open_task_context_menu(self._day_list, p)
        )
        self._day_list.itemClicked.connect(
            lambda it: self._focus_task_everywhere(self._item_task_id(it), jump_calendar=False)
        )

        self._day_form_toggle = QPushButton("展开快速排程")
        self._setup_section_toggle(self._day_form_toggle, "快速排程", "快速排程")
        dl.addWidget(self._day_form_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        add_card = _card(self._tokens, "md")
        ac_l = QVBoxLayout(add_card)
        ac_l.setContentsMargins(12, 12, 12, 12)
        ac_l.setSpacing(8)
        row_add = QHBoxLayout()
        self._day_title = QLineEdit()
        self._day_title.setPlaceholderText("任务标题")
        self._day_title.setMinimumHeight(36)
        self._day_quad = QComboBox()
        self._day_quad.setObjectName("wc_quad_select")
        for i, n in enumerate(("Q1 重要且紧急", "Q2 重要不紧急", "Q3 不重要但紧急", "Q4 不重要不紧急")):
            self._day_quad.addItem(n, i)
        self._day_quad.setCurrentIndex(1)
        self._t0 = QComboBox()
        self._t0.setObjectName("wc_hour_input")
        for h in range(24):
            self._t0.addItem(f"{h:02d}:00", h)
        self._t0.setCurrentIndex(9)
        self._t1 = QComboBox()
        self._t1.setObjectName("wc_hour_input")
        for h in range(1, 25):
            self._t1.addItem(f"{h:02d}:00" if h < 24 else "24:00", h)
        self._t1.setCurrentIndex(11)
        self._t0.currentIndexChanged.connect(self._on_day_start_hour_changed)
        self._t1.currentIndexChanged.connect(self._on_day_end_hour_changed)
        b_add = QPushButton("添加")
        b_add.setObjectName("primary")
        b_add.setFixedSize(w_action, h_key)
        b_add.clicked.connect(self._on_add_day_slot)
        row_add.addWidget(self._day_title, 2)
        row_add.addWidget(self._day_quad)
        row_add.addWidget(QLabel("从"))
        row_add.addWidget(self._t0)
        row_add.addWidget(QLabel("时 至"))
        row_add.addWidget(self._t1)
        row_add.addWidget(QLabel("时"))
        row_add.addWidget(b_add)
        ac_l.addLayout(row_add)
        self._bind_collapsible(self._day_form_toggle, add_card)
        dl.addWidget(add_card)

        # —— 周 ——
        week_page = QWidget()
        wl = QVBoxLayout(week_page)
        wl.setContentsMargins(0, sp["sm"], 0, 0)
        wl.setSpacing(sp["md"])
        wnav = QHBoxLayout()
        self._btn_pw = QPushButton("上一周")
        self._btn_nw = QPushButton("下一周")
        self._btn_cw = QPushButton("本周")
        for b in (self._btn_pw, self._btn_nw, self._btn_cw):
            b.setObjectName("secondary")
            b.setFixedSize(w_nav, h_ctrl)
        self._lbl_week = QLabel("")
        self._lbl_week.setObjectName("wc_date_hero")
        self._lbl_week.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_pw.clicked.connect(self.calendar.prevWeek)
        self._btn_nw.clicked.connect(self.calendar.nextWeek)
        self._btn_cw.clicked.connect(self.calendar.goThisWeek)
        wnav.addWidget(self._btn_pw)
        wnav.addWidget(self._lbl_week, 1)
        wnav.addWidget(self._btn_nw)
        wnav.addWidget(self._btn_cw)
        wl.addLayout(wnav)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        week_inner = QWidget()
        hl = QHBoxLayout(week_inner)
        hl.setSpacing(sp["sm"])
        for d in range(7):
            col = QVBoxLayout()
            col.setSpacing(sp["xs"])
            lab = QLabel("")
            lab.setObjectName("wc_week_head")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lw = QListWidget()
            lw.setMinimumWidth(148)
            lw.setAlternatingRowColors(True)
            lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lw.customContextMenuRequested.connect(
                lambda p, w=lw: self._open_task_context_menu(w, p)
            )
            lw.itemClicked.connect(
                lambda it: self._focus_task_everywhere(self._item_task_id(it), jump_calendar=False)
            )
            self._week_head_labels.append(lab)
            self._week_lists.append(lw)
            col.addWidget(lab)
            col.addWidget(lw, 1)
            hl.addLayout(col)
        scroll.setWidget(week_inner)
        wl.addWidget(scroll, 1)

        self._wk_form_toggle = QPushButton("展开本周批量添加")
        self._setup_section_toggle(self._wk_form_toggle, "本周批量添加", "本周批量添加")
        wl.addWidget(self._wk_form_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        wk_card = _card(self._tokens, "md")
        wk_l = QVBoxLayout(wk_card)
        wk_l.setContentsMargins(12, 12, 12, 12)
        wk_l.setSpacing(8)
        wk_l.addWidget(_section_title("本周全日程（按工作日区间）", self._ui_font))
        wk_add = QHBoxLayout()
        self._wk_title = QLineEdit()
        self._wk_title.setPlaceholderText("任务标题")
        self._wk_quad = QComboBox()
        self._wk_quad.setObjectName("wc_quad_select")
        for i, n in enumerate(("Q1 重要且紧急", "Q2 重要不紧急", "Q3 不重要但紧急", "Q4 不重要不紧急")):
            self._wk_quad.addItem(n, i)
        self._wk_quad.setCurrentIndex(1)
        self._wk_d0 = QComboBox()
        self._wk_d1 = QComboBox()
        for i, name in enumerate(WEEKDAY_H):
            self._wk_d0.addItem("周" + name, i)
            self._wk_d1.addItem("周" + name, i)
        self._wk_d1.setCurrentIndex(4)
        b_wk = QPushButton("添加")
        b_wk.setObjectName("primary")
        b_wk.setFixedSize(w_action, h_key)
        b_wk.clicked.connect(self._on_add_week_range)
        wk_add.addWidget(self._wk_title, 2)
        wk_add.addWidget(self._wk_quad)
        wk_add.addWidget(self._wk_d0)
        wk_add.addWidget(QLabel("至"))
        wk_add.addWidget(self._wk_d1)
        wk_add.addWidget(b_wk)
        wk_l.addLayout(wk_add)
        self._bind_collapsible(self._wk_form_toggle, wk_card)
        wl.addWidget(wk_card)

        # —— 月 ——
        month_page = QWidget()
        ml = QVBoxLayout(month_page)
        ml.setContentsMargins(0, sp["sm"], 0, 0)
        ml.setSpacing(sp["sm"])
        self._btn_pm = QPushButton("上月")
        self._btn_cm = QPushButton("本月")
        self._btn_nm = QPushButton("下月")
        self._btn_pm.setObjectName("wc_seg")
        self._btn_cm.setObjectName("wc_seg")
        self._btn_nm.setObjectName("wc_seg")
        self._btn_cm.setCheckable(True)
        self._btn_cm.setChecked(True)
        for b in (self._btn_pm, self._btn_nm):
            b.setFixedSize(w_seg, h_ctrl)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(self._ui_font("label", QFont.Weight.Medium))
            self._month_nav_l.addWidget(b)
        self._btn_cm.setFixedSize(w_seg, h_ctrl)
        self._btn_cm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cm.setFont(self._ui_font("label", QFont.Weight.Medium))
        self._month_nav_l.insertWidget(1, self._btn_cm)
        self._btn_pm.clicked.connect(self.calendar.prevMonth)
        self._btn_nm.clicked.connect(self.calendar.nextMonth)
        self._btn_cm.clicked.connect(self.calendar.goTodayMonth)

        grid_w = QWidget()
        grid_w.setObjectName("wc_month_canvas")
        grid_w.setMinimumWidth(0)
        grid_w.setMaximumWidth(16777215)
        grid_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid_w.setMinimumHeight(520)
        self._month_layout = QGridLayout(grid_w)
        self._month_layout.setContentsMargins(0, 0, 0, 0)
        self._month_layout.setHorizontalSpacing(0)
        self._month_layout.setVerticalSpacing(0)
        for cc in range(7):
            self._month_layout.setColumnStretch(cc, 1)
        self._month_layout.setRowStretch(0, 0)
        for rr in range(1, 7):
            self._month_layout.setRowStretch(rr, 1)
        for c, h in enumerate(WEEKDAY_H):
            lab = QLabel(h)
            lab.setFixedHeight(32)
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lab.setObjectName("wc_month_weekday")
            if c >= 5:
                lab.setProperty("weekend", True)
            self._month_layout.addWidget(lab, 0, c)
        self._month_cells: list[MonthCellButton] = []
        for r in range(6):
            for c in range(7):
                b = MonthCellButton()
                b.setObjectName("wc_month_cell")
                b.setMinimumHeight(80)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.setProperty("weekend", c >= 5)
                self._month_cells.append(b)
                self._month_layout.addWidget(b, r + 1, c)
        ml.addWidget(grid_w, 1)

        self._mo_form_toggle = QPushButton("展开跨日任务添加")
        self._setup_section_toggle(self._mo_form_toggle, "跨日任务添加", "跨日任务添加")
        ml.addWidget(self._mo_form_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        mo_card = _card(self._tokens, "md")
        mo_l = QVBoxLayout(mo_card)
        mo_l.setContentsMargins(12, 12, 12, 12)
        mo_l.setSpacing(8)
        r1 = QHBoxLayout()
        self._mo_title = QLineEdit()
        self._mo_title.setPlaceholderText("任务标题")
        self._mo_quad = QComboBox()
        self._mo_quad.setObjectName("wc_quad_select")
        for i, n in enumerate(("Q1 重要且紧急", "Q2 重要不紧急", "Q3 不重要但紧急", "Q4 不重要不紧急")):
            self._mo_quad.addItem(n, i)
        self._mo_quad.setCurrentIndex(1)
        self._mo_s = QDateEdit()
        self._setup_date_edit(self._mo_s, value=self.calendar.selected_date())
        self._mo_e = QDateEdit()
        self._setup_date_edit(self._mo_e, value=self.calendar.selected_date())
        self._mo_s.dateChanged.connect(self._on_month_range_start_changed)
        self._mo_e.dateChanged.connect(self._on_month_range_end_changed)
        b_mo = QPushButton("添加")
        b_mo.setObjectName("primary")
        b_mo.setFixedSize(w_action, h_key)
        b_mo.clicked.connect(self._on_add_month_range)
        r1.addWidget(self._mo_title, 2)
        r1.addWidget(self._mo_quad)
        r1.addWidget(self._mo_s)
        r1.addWidget(self._mo_e)
        r1.addWidget(b_mo)
        mo_l.addLayout(r1)
        self._bind_collapsible(self._mo_form_toggle, mo_card, animated=False)
        ml.addWidget(mo_card)

        self._month_preview_toggle = QPushButton("展开所选日期任务速览")
        self._setup_section_toggle(self._month_preview_toggle, "所选日期任务速览", "所选日期任务速览")
        ml.addWidget(self._month_preview_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        preview_card = _card(self._tokens, "md")
        preview_card.setObjectName("wc_preview_card")
        preview_card.setMinimumHeight(212)
        preview_l = QVBoxLayout(preview_card)
        preview_l.setContentsMargins(12, 12, 12, 12)
        preview_l.setSpacing(0)
        self._month_day_preview = QListWidget()
        self._month_day_preview.setObjectName("wc_month_day_preview")
        self._month_day_preview.setMinimumHeight(176)
        self._month_day_preview.setAlternatingRowColors(False)
        self._month_day_preview.setFrameShape(QFrame.Shape.NoFrame)
        self._month_day_preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._month_day_preview.customContextMenuRequested.connect(
            lambda p: self._open_task_context_menu(self._month_day_preview, p)
        )
        self._month_day_preview.itemClicked.connect(
            lambda it: self._focus_task_everywhere(self._item_task_id(it), jump_calendar=False)
        )
        preview_l.addWidget(self._month_day_preview)
        self._bind_collapsible(self._month_preview_toggle, preview_card, animated=False)
        ml.addWidget(preview_card, 0)

        self._cal_stack.addWidget(day_page)
        self._cal_stack.addWidget(week_page)
        self._cal_stack.addWidget(month_page)

        return root

    def _build_execution_panel(self) -> QWidget:
        sp = self._sp
        wrap = QWidget()
        wrap.setObjectName("wc_exec_wrap")
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)

        pm_card = _card(self._tokens, "md")
        pm_card.setObjectName("wc_pm_card")
        pm_card.setMinimumHeight(340)
        pm_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pm_l = QVBoxLayout(pm_card)
        pm_l.setContentsMargins(16, 12, 16, 14)
        pm_l.setSpacing(8)
        pm_l.addWidget(_section_title("番茄钟", self._ui_font))
        self._pm_time = QLabel("25:00")
        self._pm_time.setObjectName("wc_pm_time")
        self._pm_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pm_time.setFont(self._ui_font("headline", QFont.Weight.Bold))
        self._pm_state = QLabel("待开始")
        self._pm_state.setObjectName("wc_pm_state")
        self._pm_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pm_bind = QLabel("未绑定任务")
        self._pm_bind.setObjectName("wc_pm_bind")
        self._pm_bind.setWordWrap(True)
        self._pm_bind.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm_l.addWidget(self._pm_time)
        pm_l.addWidget(self._pm_state)
        pm_l.addWidget(self._pm_bind)
        pm_btn_row = QHBoxLayout()
        self._pm_btn_start = QPushButton("开始专注")
        self._pm_btn_start.setObjectName("primary")
        self._pm_btn_stop = QPushButton("停止")
        self._pm_btn_stop.setObjectName("secondary")
        pm_btn_reset = QPushButton("重置")
        pm_btn_reset.setObjectName("secondary")
        pm_btn_row.addWidget(self._pm_btn_start, 1)
        pm_btn_row.addWidget(self._pm_btn_stop, 1)
        pm_btn_row.addWidget(pm_btn_reset, 1)
        pm_l.addLayout(pm_btn_row)
        self._pm_sound_chk = QCheckBox("专注结束提示音")
        self._pm_sound_chk.setChecked(True)
        pm_l.addWidget(self._pm_sound_chk)
        pm_l.addSpacing(2)

        pm_bind_row = QHBoxLayout()
        b_bind = QPushButton("绑定当前选中任务")
        b_bind.setObjectName("secondary")
        b_unbind = QPushButton("清空绑定")
        b_unbind.setObjectName("secondary")
        pm_bind_row.addWidget(b_bind, 1)
        pm_bind_row.addWidget(b_unbind, 1)
        pm_l.addLayout(pm_bind_row)
        b_jump = QPushButton("跳转到绑定任务日期")
        b_jump.setObjectName("secondary")
        pm_l.addWidget(b_jump)
        pm_l.addStretch(1)
        hl.addWidget(pm_card, 5)

        q_card = _card(self._tokens, "md")
        q_card.setObjectName("wc_quad_card")
        q_l = QVBoxLayout(q_card)
        q_l.setContentsMargins(16, 12, 16, 14)
        q_l.setSpacing(8)
        q_hd = QHBoxLayout()
        q_hd.addWidget(_section_title("四象限任务", self._ui_font), 1)
        self._exec_filter_combo = QComboBox()
        self._exec_filter_combo.setObjectName("wc_exec_filter")
        self._exec_filter_combo.addItem("全部", "all")
        self._exec_filter_combo.addItem("仅今日相关", "today")
        self._exec_filter_combo.addItem("仅本周相关", "week")
        self._exec_filter_combo.currentIndexChanged.connect(self._on_exec_filter_changed)
        q_hd.addWidget(self._exec_filter_combo, 0)
        q_l.addLayout(q_hd)
        for i, n in enumerate(("重要且紧急", "重要不紧急", "不重要但紧急", "不重要不紧急")):
            row = QHBoxLayout()
            lb = QLabel(f"{n} 0")
            lb.setObjectName("wc_quad_title")
            row.addWidget(lb, 1)
            b_new = QPushButton("新建")
            b_new.setObjectName("secondary")
            b_new.clicked.connect(lambda _=False, qi=i: self._quick_add_quadrant_task(qi))
            row.addWidget(b_new, 0)
            q_l.addLayout(row)
            lw = QListWidget()
            lw.setObjectName("wc_quad_list")
            lw.setMinimumHeight(78)
            lw.setAlternatingRowColors(True)
            lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lw.customContextMenuRequested.connect(
                lambda p, q=i, w=lw: self._open_quadrant_context_menu(q, w, p)
            )
            lw.itemClicked.connect(lambda it: self._focus_task_everywhere(self._item_task_id(it), jump_calendar=True))
            lw.itemDoubleClicked.connect(lambda it, q=i: self._schedule_from_quadrant_item(q, it))
            q_l.addWidget(lw, 0)
            self._quad_stat_labels.append(lb)
            self._quad_lists.append(lw)
        hl.addWidget(q_card, 7)

        self._pm_btn_start.clicked.connect(self._pomodoro_start)
        self._pm_btn_stop.clicked.connect(self._pomodoro_stop)
        pm_btn_reset.clicked.connect(self._pomodoro_reset)
        b_bind.clicked.connect(self._pomodoro_bind_from_selection)
        b_unbind.clicked.connect(self._pomodoro_unbind)
        b_jump.clicked.connect(self._pomodoro_jump_to_bound)
        return wrap

    def _quadrant_models(self) -> tuple[Any, Any, Any, Any]:
        return (self._quad0, self._quad1, self._quad2, self._quad3)

    def _on_exec_filter_changed(self, _idx: int) -> None:
        if self._exec_filter_combo is None:
            return
        self._exec_filter_mode = str(self._exec_filter_combo.currentData() or "all")
        self._fill_quadrants()

    def _task_hits_date(self, snap: dict, day_qd: QDate) -> bool:
        ds = day_qd.toString(Qt.DateFormat.ISODate)
        st = nwc._parse_local_iso(str(snap.get("start_datetime") or ""))
        ed = nwc._parse_local_iso(str(snap.get("end_datetime") or ""))
        if st and ed and ed > st:
            start_day = st.date().isoformat()
            end_day = ed.date().isoformat()
            return start_day <= ds <= end_day
        due = str(snap.get("due_date") or "").strip()
        return bool(due and due[:10] == ds)

    def _task_hits_week(self, snap: dict, week_start: QDate, week_end: QDate) -> bool:
        a = week_start.toString(Qt.DateFormat.ISODate)
        b = week_end.toString(Qt.DateFormat.ISODate)
        st = nwc._parse_local_iso(str(snap.get("start_datetime") or ""))
        ed = nwc._parse_local_iso(str(snap.get("end_datetime") or ""))
        if st and ed and ed > st:
            start_day = st.date().isoformat()
            end_day = ed.date().isoformat()
            return not (end_day < a or start_day > b)
        due = str(snap.get("due_date") or "").strip()
        if due:
            d = due[:10]
            return a <= d <= b
        return False

    def _fill_quadrants(self) -> None:
        keep_tid = None
        cur_sel = self._selected_quadrant_task()
        if cur_sel:
            keep_tid = int(cur_sel[0])
        today_qd = QDate.currentDate()
        week_start = today_qd.addDays(-(today_qd.dayOfWeek() - 1))
        week_end = week_start.addDays(6)
        for i, m in enumerate(self._quadrant_models()):
            if i >= len(self._quad_lists):
                continue
            lw = self._quad_lists[i]
            lb = self._quad_stat_labels[i]
            lw.clear()
            for r in range(m.rowCount()):
                ix = m.index(r, 0)
                tid = m.data(ix, nwc.TaskModel.IdRole)
                title = str(m.data(ix, nwc.TaskModel.TitleRole) or "")
                done = bool(m.data(ix, nwc.TaskModel.CompletedRole))
                if done:
                    continue
                if self._exec_filter_mode == "today":
                    snap = self._task_snapshot_by_id(int(tid)) or {}
                    if not self._task_hits_date(snap, today_qd):
                        continue
                if self._exec_filter_mode == "week":
                    snap = self._task_snapshot_by_id(int(tid)) or {}
                    if not self._task_hits_week(snap, week_start, week_end):
                        continue
                it = QListWidgetItem(title)
                it.setData(Qt.ItemDataRole.UserRole, int(tid))
                lw.addItem(it)
            base = lb.text().split(" ", 1)[0]
            lb.setText(f"{base} {lw.count()}")
        if keep_tid is not None:
            self._select_task_in_quad_lists(int(keep_tid))

    def _quick_add_quadrant_task(self, quadrant: int) -> None:
        title, ok = QInputDialog.getText(self, "新建象限任务", "任务标题：")
        if not ok:
            return
        title = (title or "").strip()
        if not title:
            self._calendar_alert("标题为空", "请输入任务标题。")
            return
        self.bridge.addTask(title, int(quadrant))
        self._toast(f"已添加到 {self._quad_tag(quadrant)}")

    def _schedule_from_quadrant_item(self, quadrant: int, item: QListWidgetItem) -> None:
        tid = self._item_task_id(item)
        if tid is None:
            return
        d = self.calendar.selected_date().toString(Qt.DateFormat.ISODate)
        sh, ok = QInputDialog.getInt(self, "快速排程", "开始小时（0-23）", 9, 0, 23, 1)
        if not ok:
            return
        eh, ok2 = QInputDialog.getInt(self, "快速排程", "结束小时（1-24）", min(24, sh + 1), 1, 24, 1)
        if not ok2 or eh <= sh:
            self._calendar_alert("时间无效", "结束时间必须晚于开始时间。")
            return
        snap = self._task_snapshot_by_id(tid) or {}
        title = str(snap.get("title") or item.text()).strip()
        start = f"{d}T{sh:02d}:00:00"
        end = f"{d}T{eh:02d}:00:00" if eh < 24 else f"{QDate.fromString(d, Qt.DateFormat.ISODate).addDays(1).toString(Qt.DateFormat.ISODate)}T00:00:00"
        if not self._confirm_conflicts(start, end, tid):
            return
        self.bridge.updateTaskSchedule(int(tid), start, end, False)
        self._toast("已将象限任务加入日程")

    def _selected_quadrant_task(self) -> tuple[int, str] | None:
        for lw in self._quad_lists:
            it = lw.currentItem()
            tid = self._item_task_id(it)
            if tid is None:
                continue
            return tid, str(it.text() or "")
        return None

    def _selected_task_anywhere(self) -> tuple[int, str] | None:
        it = self._day_list.currentItem()
        tid = self._item_task_id(it)
        if tid is not None:
            snap = self._task_snapshot_by_id(tid) or {}
            return tid, str(snap.get("title") or it.text() or "")
        for lw in self._week_lists:
            it = lw.currentItem()
            tid = self._item_task_id(it)
            if tid is not None:
                snap = self._task_snapshot_by_id(tid) or {}
                return tid, str(snap.get("title") or it.text() or "")
        qsel = self._selected_quadrant_task()
        if qsel is not None:
            tid, txt = qsel
            snap = self._task_snapshot_by_id(tid) or {}
            return tid, str(snap.get("title") or txt or "")
        return None

    def _select_task_in_list(self, lw: QListWidget, task_id: int) -> bool:
        for i in range(lw.count()):
            it = lw.item(i)
            tid = self._item_task_id(it)
            if tid == int(task_id):
                lw.setCurrentItem(it)
                lw.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                return True
        return False

    def _select_task_in_quad_lists(self, task_id: int) -> bool:
        for lw in self._quad_lists:
            if self._select_task_in_list(lw, task_id):
                return True
        return False

    def _select_task_in_day_week(self, task_id: int) -> bool:
        if self._select_task_in_list(self._day_list, task_id):
            return True
        for lw in self._week_lists:
            if self._select_task_in_list(lw, task_id):
                return True
        return False

    def _focus_task_everywhere(self, task_id: Optional[int], *, jump_calendar: bool = False) -> None:
        if task_id is None or self._syncing_cross_select:
            return
        self._syncing_cross_select = True
        try:
            if jump_calendar:
                self.bridge.jumpToTaskInCalendar(int(task_id))
                self._seg_btns[0].setChecked(True)
                self._on_calendar_tab_changed(0)
                self._content_scroll.ensureWidgetVisible(self._day_list, 0, 24)
            self._select_task_in_day_week(int(task_id))
            self._select_task_in_quad_lists(int(task_id))
        finally:
            self._syncing_cross_select = False

    def _open_quadrant_context_menu(self, quadrant: int, source_list: QListWidget, pos) -> None:
        it = source_list.itemAt(pos)
        tid = self._item_task_id(it)
        if tid is None:
            return
        m = QMenu(source_list)
        act_bind = m.addAction("绑定到番茄钟")
        act_jump = m.addAction("跳转并高亮")
        act_sched = m.addAction("快速排程到当前日期")
        act_done = m.addAction("标记完成")
        act_del = m.addAction("删除任务")
        sub_q = m.addMenu("移动到象限")
        q_actions = []
        for i, n in enumerate(("重要且紧急", "重要不紧急", "不重要但紧急", "不重要不紧急")):
            a = sub_q.addAction(n)
            a.setData(i)
            q_actions.append(a)
        chosen = m.exec(source_list.mapToGlobal(pos))
        if chosen is None:
            return
        snap = self._task_snapshot_by_id(int(tid)) or {}
        title = str(snap.get("title") or (it.text() if it else "") or "").strip()
        if chosen == act_bind:
            self._pomodoro.setCurrentTask(int(tid), title)
            self._toast("已绑定番茄任务")
            return
        if chosen == act_jump:
            self._focus_task_everywhere(int(tid), jump_calendar=True)
            return
        if chosen == act_sched and it is not None:
            self._schedule_from_quadrant_item(quadrant, it)
            return
        if chosen == act_done:
            self.bridge.completeTask(int(tid), True)
            self._toast("已标记完成")
            return
        if chosen == act_del:
            if self._ask_yes_no("确认删除", "删除后不可恢复，是否继续？"):
                self.bridge.removeTask(int(tid))
                self._toast("任务已删除")
            return
        if chosen in q_actions:
            qv = int(chosen.data())
            self.bridge.setQuadrant(int(tid), qv)
            self._toast(f"已移动到 {self._quad_tag(qv)}")

    def _pomodoro_bind_from_selection(self) -> None:
        sel = self._selected_task_anywhere()
        if not sel:
            self._calendar_alert("未选中任务", "请先在日/周/四象限任意列表中选中一条任务。")
            return
        tid, title = sel
        self._pomodoro.setCurrentTask(int(tid), title)
        self._toast("已绑定番茄任务")

    def _pomodoro_unbind(self) -> None:
        self._pomodoro.clearCurrentTask()
        self._toast("已清空番茄绑定")

    def _pomodoro_start(self) -> None:
        self._pomodoro.startFocus()
        self._refresh_pomodoro()

    def _pomodoro_stop(self) -> None:
        self._pomodoro.stop()
        self._refresh_pomodoro()

    def _pomodoro_reset(self) -> None:
        self._pomodoro.reset()
        self._refresh_pomodoro()
        self._toast("番茄钟已重置")

    def _pomodoro_jump_to_bound(self) -> None:
        tid = int(self._pomodoro.currentTaskId)
        if tid < 0:
            self._calendar_alert("未绑定任务", "请先绑定一个任务。")
            return
        self._focus_task_everywhere(tid, jump_calendar=True)

    def _refresh_pomodoro(self) -> None:
        if self._pm_time is None or self._pm_state is None or self._pm_bind is None:
            return
        rem = int(self._pomodoro.remainingSeconds)
        mm, ss = divmod(max(0, rem), 60)
        self._pm_time.setText(f"{mm:02d}:{ss:02d}")
        running = bool(self._pomodoro.running)
        if self._pm_prev_running and not running and self._pm_prev_remaining <= 1:
            self._toast("专注完成，休息一下吧", 2200)
            if self._pm_sound_chk is not None and self._pm_sound_chk.isChecked():
                QApplication.beep()
        self._pm_state.setText("专注中" if running else "待开始")
        title = str(self._pomodoro.currentTaskTitle or "").strip()
        self._pm_bind.setText(f"已绑定：{title}" if title else "未绑定任务")
        if self._pm_btn_start is not None:
            self._pm_btn_start.setEnabled(not running)
        if self._pm_btn_stop is not None:
            self._pm_btn_stop.setEnabled(running)
        self._pm_prev_running = running
        self._pm_prev_remaining = rem

    def _wire(self) -> None:

        self.calendar.selectedDateChanged.connect(self._sync_day_labels)
        self.calendar.selectedDateChanged.connect(self._request_month_grid_refresh)
        self.calendar.weekStartChanged.connect(self._sync_week_labels)
        self.calendar.monthAnchorChanged.connect(self._sync_month_labels)
        self.calendar.layoutChanged.connect(self._fill_week)
        self.calendar.layoutChanged.connect(self._fill_day_agenda)
        self.calendar.layoutChanged.connect(self._sync_calendar_overview)
        self.calendar.monthAnchorChanged.connect(self._request_month_grid_refresh)

        self.calendar.monthModel.modelReset.connect(self._request_month_grid_refresh)
        self.calendar.dayModel.modelReset.connect(self._fill_day_agenda)
        self.calendar.dayModel.modelReset.connect(self._sync_calendar_overview)
        self.calendar.dayModel.modelReset.connect(self._fill_month_day_preview)
        self._day_list.itemChanged.connect(self._on_task_item_check_changed)
        self._month_day_preview.itemChanged.connect(self._on_task_item_check_changed)
        for lw in self._week_lists:
            lw.itemChanged.connect(self._on_task_item_check_changed)

        self._sync_day_labels()
        self._sync_week_labels()
        self._sync_month_labels()
        self._on_calendar_tab_changed(2)
        self._fill_day_agenda()
        self._fill_month_day_preview()
        self._fill_week()
        self._fill_month_grid()
        self._sync_calendar_overview()

    def _sync_day_labels(self) -> None:
        d = self.calendar.selected_date()
        wd = WEEKDAY_H[max(0, d.dayOfWeek() - 1)]
        self._lbl_day.setText(f"{d.year()}年{d.month()}月{d.day()}日  周{wd}")
        self._lbl_day.setFont(self._ui_font("headline", QFont.Weight.DemiBold))
        self._fill_day_agenda()
        self._fill_month_day_preview()
        self._sync_calendar_overview()

    def _sync_week_labels(self) -> None:
        ws = self.calendar.week_start_date()
        we = ws.addDays(6)
        self._lbl_week.setText(
            f"{ws.year()}年{ws.month()}月{ws.day()}日 - {we.month()}月{we.day()}日"
        )
        self._lbl_week.setFont(self._ui_font("headline", QFont.Weight.DemiBold))
        self._fill_week()

    def _sync_month_labels(self) -> None:
        return

    def _on_calendar_tab_changed(self, idx: int) -> None:
        self._cal_stack.setCurrentIndex(int(idx))
        self._month_nav_wrap.setVisible(int(idx) == 2)
        if int(idx) == 2 and self._month_grid_dirty:
            self._fill_month_grid()

    def _jump_to_today_tasks(self) -> None:
        self._seg_btns[0].setChecked(True)
        self._on_calendar_tab_changed(0)
        self.calendar.goToday()
        self._content_scroll.ensureWidgetVisible(self._day_list, 0, 24)

    def _open_day_from_month_cell(self, cell_iso: str) -> None:
        self.calendar.pickMonthCell(cell_iso)
        self._seg_btns[0].setChecked(True)
        self._on_calendar_tab_changed(0)
        self._content_scroll.ensureWidgetVisible(self._day_list, 0, 24)

    def _fill_day_agenda(self) -> None:
        self._day_list.clear()
        dm = self.calendar.dayModel
        D = nwc.DayAgendaModel
        rows: list[tuple[bool, QListWidgetItem]] = []
        exist_ids: set[int] = set()
        selected_qd = self.calendar.selected_date()
        self._syncing_task_check = True
        for i in range(dm.rowCount()):
            ix = dm.index(i, 0)
            tid = dm.data(ix, D.TaskIdRole)
            title = str(dm.data(ix, D.TitleRole) or "")
            quad = dm.data(ix, D.QuadrantRole)
            qtag = self._quad_tag(quad)
            due_only = bool(dm.data(ix, D.IsDueOnlyRole))
            full_day = bool(dm.data(ix, D.FullDayRole))
            sm = dm.data(ix, D.StartMinuteRole)
            dur = dm.data(ix, D.DurationMinuteRole)
            if due_only:
                line = f"{qtag} · 截止  {title}"
            elif full_day:
                line = f"{qtag} · 全天  {title}"
            else:
                start_m = int(sm or 0)
                end_m = start_m + int(dur or 0)
                line = f"{qtag} · {_fmt_clock(start_m)}-{_fmt_clock(end_m)}  {title}"
            it = QListWidgetItem(line)
            if tid is not None:
                it.setData(Qt.ItemDataRole.UserRole, int(tid))
                exist_ids.add(int(tid))
                done = self._task_is_completed(int(tid))
                self._apply_task_item_state(it, done)
            else:
                done = False
            it.setData(Qt.ItemDataRole.UserRole + 1, due_only)
            rows.append((done, it))
        for snap in self._completed_snapshots():
            tid = int(snap.get("id") or -1)
            if tid < 0 or tid in exist_ids:
                continue
            if not self._task_hits_date(snap, selected_qd):
                continue
            line, due_only = self._line_from_snapshot_for_day(snap)
            it = QListWidgetItem(line)
            it.setData(Qt.ItemDataRole.UserRole, tid)
            it.setData(Qt.ItemDataRole.UserRole + 1, due_only)
            self._apply_task_item_state(it, True)
            rows.append((True, it))
        for _done, it in sorted(rows, key=lambda x: int(x[0])):
            self._day_list.addItem(it)
        self._syncing_task_check = False

    def _sync_calendar_overview(self) -> None:
        d = self.calendar.selected_date()
        wd = WEEKDAY_H[max(0, d.dayOfWeek() - 1)]
        self._ov_title.setText(f"{d.year()}年{d.month()}月{d.day()}日 · 周{wd}")
        dm = self.calendar.dayModel
        total = dm.rowCount()
        scheduled = 0
        due_only = 0
        for i in range(total):
            ix = dm.index(i, 0)
            if dm.data(ix, nwc.DayAgendaModel.IsDueOnlyRole):
                due_only += 1
            else:
                scheduled += 1
        completed_cnt = sum(1 for snap in self._completed_snapshots() if self._task_hits_date(snap, d))
        self._ov_chip_total.setText(f"今日任务 {total + completed_cnt}")
        self._ov_sub.setText(
            f"已排程{scheduled} · 截止{due_only} · 已完成 {completed_cnt}"
        )

    def _fill_month_day_preview(self) -> None:
        if not hasattr(self, "_month_day_preview"):
            return
        self._month_day_preview.clear()
        dm = self.calendar.dayModel
        D = nwc.DayAgendaModel
        rows: list[tuple[bool, QListWidgetItem]] = []
        exist_ids: set[int] = set()
        selected_qd = self.calendar.selected_date()
        self._syncing_task_check = True
        for i in range(dm.rowCount()):
            ix = dm.index(i, 0)
            tid = dm.data(ix, D.TaskIdRole)
            title = str(dm.data(ix, D.TitleRole) or "")
            quad = dm.data(ix, D.QuadrantRole)
            qtag = self._quad_tag(quad)
            due_only = bool(dm.data(ix, D.IsDueOnlyRole))
            full_day = bool(dm.data(ix, D.FullDayRole))
            sm = dm.data(ix, D.StartMinuteRole)
            dur = dm.data(ix, D.DurationMinuteRole)
            if due_only:
                line = f"{qtag} · 截止  {title}"
            elif full_day:
                line = f"{qtag} · 全天  {title}"
            else:
                start_m = int(sm or 0)
                end_m = start_m + int(dur or 0)
                line = f"{qtag} · {_fmt_clock(start_m)}-{_fmt_clock(end_m)}  {title}"
            it = QListWidgetItem(line)
            if tid is not None:
                it.setData(Qt.ItemDataRole.UserRole, int(tid))
                exist_ids.add(int(tid))
                done = self._task_is_completed(int(tid))
                self._apply_task_item_state(it, done)
            else:
                done = False
            it.setData(Qt.ItemDataRole.UserRole + 1, due_only)
            rows.append((done, it))
        for snap in self._completed_snapshots():
            tid = int(snap.get("id") or -1)
            if tid < 0 or tid in exist_ids:
                continue
            if not self._task_hits_date(snap, selected_qd):
                continue
            line, due_only = self._line_from_snapshot_for_day(snap)
            it = QListWidgetItem(line)
            it.setData(Qt.ItemDataRole.UserRole, tid)
            it.setData(Qt.ItemDataRole.UserRole + 1, due_only)
            self._apply_task_item_state(it, True)
            rows.append((True, it))
        for _done, it in sorted(rows, key=lambda x: int(x[0])):
            self._month_day_preview.addItem(it)
        self._syncing_task_check = False

    def _fill_week(self) -> None:
        for lw in self._week_lists:
            lw.clear()
        wm = self.calendar.weekModel
        W = nwc.WeekScheduleModel
        day_rows: list[list[tuple[bool, QListWidgetItem]]] = [[] for _ in range(7)]
        week_existing_ids: set[int] = set()
        self._syncing_task_check = True
        for i in range(wm.rowCount()):
            ix = wm.index(i, 0)
            di = wm.data(ix, W.DayIndexRole)
            title = wm.data(ix, W.TitleRole)
            sm = wm.data(ix, W.StartMinuteRole)
            quad = wm.data(ix, W.QuadrantRole)
            tid = wm.data(ix, W.TaskIdRole)
            if di is None or title is None:
                continue
            line = f"{self._quad_tag(quad)} · {_fmt_clock(int(sm))}  {title}"
            it = QListWidgetItem(line)
            it.setData(Qt.ItemDataRole.UserRole, int(tid))
            week_existing_ids.add(int(tid))
            done = self._task_is_completed(int(tid))
            self._apply_task_item_state(it, done)
            day_rows[int(di)].append((done, it))

        am = self.calendar.weekAllDayModel
        A = nwc.WeekAllDayModel
        for i in range(am.rowCount()):
            ix = am.index(i, 0)
            di = am.data(ix, A.DayIndexRole)
            title = am.data(ix, A.TitleRole)
            quad = am.data(ix, A.QuadrantRole)
            tid = am.data(ix, A.TaskIdRole)
            if di is None:
                continue
            it = QListWidgetItem(f"{self._quad_tag(quad)} · 全天  {title}")
            it.setData(Qt.ItemDataRole.UserRole, int(tid))
            week_existing_ids.add(int(tid))
            done = self._task_is_completed(int(tid))
            self._apply_task_item_state(it, done)
            day_rows[int(di)].append((done, it))

        ws = self.calendar.week_start_date()
        we = ws.addDays(6)
        for snap in self._completed_snapshots():
            tid = int(snap.get("id") or -1)
            if tid < 0 or tid in week_existing_ids:
                continue
            if not self._task_hits_week(snap, ws, we):
                continue
            for di in range(7):
                qd = ws.addDays(di)
                if not self._task_hits_date(snap, qd):
                    continue
                line, _due_only = self._line_from_snapshot_for_day(snap)
                it = QListWidgetItem(line)
                it.setData(Qt.ItemDataRole.UserRole, tid)
                self._apply_task_item_state(it, True)
                day_rows[di].append((True, it))

        for di, rows in enumerate(day_rows):
            for _done, it in sorted(rows, key=lambda x: int(x[0])):
                self._week_lists[di].addItem(it)
        self._syncing_task_check = False

        a = self.calendar.week_start_date()
        for d in range(7):
            qd = a.addDays(d)
            if d < len(self._week_head_labels):
                self._week_head_labels[d].setText(
                    f"{WEEKDAY_H[d]}\n{qd.month()}/{qd.day()}"
                )

    def _fill_month_grid(self) -> None:
        if self._cal_stack.currentIndex() != 2:
            self._month_grid_dirty = True
            return
        self._month_grid_dirty = False
        m = self.calendar.monthModel
        p = self._palette_provider()
        accent = p.get("focus_accent", "#2563eb")
        selected_bg = _month_cell_selected_bg(p)
        weekend_tone = p.get("danger", "#dc2626")
        selected_iso = self.calendar.selected_date().toString(Qt.DateFormat.ISODate)
        for i, btn in enumerate(self._month_cells):
            if i >= m.rowCount():
                btn.setVisible(False)
                continue
            ix = m.index(i, 0)
            ds = m.data(ix, nwc.MonthGridModel.CellDateRole)
            in_m = m.data(ix, nwc.MonthGridModel.InMonthRole)
            cnt = m.data(ix, nwc.MonthGridModel.TaskCountRole)
            is_today = m.data(ix, nwc.MonthGridModel.IsTodayRole)
            btn.setVisible(True)
            day_txt = str(m.data(ix, Qt.ItemDataRole.DisplayRole) or "")
            count = int(cnt or 0)
            meta_txt = f"{'●' * min(3, count)} {count}" if count > 0 else ""
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            try:
                btn.doubleClicked.disconnect()
            except TypeError:
                pass
            iso = str(ds or "")
            btn.clicked.connect(lambda _=False, s=iso: self.calendar.pickMonthCell(s))
            btn.doubleClicked.connect(lambda s=iso: self._open_day_from_month_cell(s))
            is_weekend = (i % 7) >= 5
            weekend_color = weekend_tone if is_weekend else p.get("text", "#111")
            day_color = weekend_color
            meta_color = p.get("muted", "#888")
            is_selected = iso == selected_iso
            # 动态样式：今天 / 非本月
            if is_selected:
                day_color = p.get("text", "#111")
                meta_color = p.get("text", "#111")
                btn.setStyleSheet(
                    "QPushButton#wc_month_cell {"
                    f"background: {selected_bg};"
                    f"border-right: 1px solid rgba(198,198,198,0.12); border-bottom: 1px solid rgba(198,198,198,0.12);"
                    "border-radius: 0px; }"
                )
            elif is_today:
                day_color = p.get("text", "#111") if not is_weekend else weekend_color
                meta_color = p.get("text", "#111")
                btn.setStyleSheet(
                    "QPushButton#wc_month_cell {"
                    f"background: {p.get('surface_lowest', '#fff')};"
                    f"border-right: 1px solid rgba(198,198,198,0.12); border-bottom: 1px solid rgba(198,198,198,0.12);"
                    "border-radius: 0px; }"
                )
            elif not in_m:
                day_color = p.get("muted", "#888")
                meta_color = p.get("muted", "#a3a3a3")
                btn.setStyleSheet(
                    "QPushButton#wc_month_cell {"
                    f"background: {p.get('surface_low', '#f3f3f4')};"
                    "border-right: 1px solid rgba(198,198,198,0.12); border-bottom: 1px solid rgba(198,198,198,0.12);"
                    "border-radius: 0px; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton#wc_month_cell {"
                    f"background: {p.get('surface_lowest', '#fff')};"
                    "border-right: 1px solid rgba(198,198,198,0.12); border-bottom: 1px solid rgba(198,198,198,0.12);"
                    "border-radius: 0px; }"
                )
            # 今天：仅用日期数字颜色区分（无额外底块）
            if is_today:
                day_color = (
                    p.get("on_primary_container", "#1e40af")
                    if is_selected
                    else accent
                )
            btn.set_content(day_txt, meta_txt, day_color, meta_color)

    def _request_month_grid_refresh(self) -> None:
        self._month_grid_dirty = True
        if self._cal_stack.currentIndex() != 2:
            return
        QTimer.singleShot(0, self._fill_month_grid)

    def _on_add_day_slot(self) -> None:
        title = self._day_title.text().strip()
        if not title:
            self._calendar_alert("标题为空", "请输入任务标题。")
            return
        h0 = int(self._t0.currentData())
        h1 = int(self._t1.currentData())
        qv = int(self._day_quad.currentData())
        if h1 <= h0:
            self._calendar_alert("时间无效", "结束时间必须晚于开始时间。")
            return
        iso = str(self.calendar.property("selectedDateIso") or "")
        start = f"{iso}T{h0:02d}:00:00"
        end = f"{iso}T{h1:02d}:00:00" if h1 < 24 else f"{QDate.fromString(iso, Qt.DateFormat.ISODate).addDays(1).toString(Qt.DateFormat.ISODate)}T00:00:00"
        if not self._confirm_conflicts(start, end):
            return
        self.bridge.addDayHourPeriodTask(
            title,
            qv,
            iso,
            h0,
            h1,
        )
        self._day_title.clear()
        self._toast("已添加日程")

    def _set_hour_combo_data(self, combo: QComboBox, value: int) -> bool:
        for i in range(combo.count()):
            if int(combo.itemData(i)) == int(value):
                combo.setCurrentIndex(i)
                return True
        return False

    def _on_day_start_hour_changed(self, _idx: int) -> None:
        if self._syncing_day_hour:
            return
        self._syncing_day_hour = True
        try:
            h0 = int(self._t0.currentData())
            h1 = int(self._t1.currentData())
            if h1 <= h0:
                target = min(24, h0 + 1)
                self._set_hour_combo_data(self._t1, target)
        finally:
            self._syncing_day_hour = False

    def _on_day_end_hour_changed(self, _idx: int) -> None:
        if self._syncing_day_hour:
            return
        self._syncing_day_hour = True
        try:
            h0 = int(self._t0.currentData())
            h1 = int(self._t1.currentData())
            if h1 <= h0:
                target = max(0, h1 - 1)
                self._set_hour_combo_data(self._t0, target)
        finally:
            self._syncing_day_hour = False

    def _on_add_week_range(self) -> None:
        title = self._wk_title.text().strip()
        if not title:
            self._calendar_alert("标题为空", "请输入任务标题。")
            return
        qv = int(self._wk_quad.currentData())
        a = min(self._wk_d0.currentIndex(), self._wk_d1.currentIndex())
        b = max(self._wk_d0.currentIndex(), self._wk_d1.currentIndex())
        ws = self.calendar.week_start_date()
        s = ws.addDays(a).toString(Qt.DateFormat.ISODate)
        e = ws.addDays(b).toString(Qt.DateFormat.ISODate)
        start = f"{s}T00:00:00"
        end = f"{QDate.fromString(e, Qt.DateFormat.ISODate).addDays(1).toString(Qt.DateFormat.ISODate)}T00:00:00"
        if not self._confirm_conflicts(start, end):
            return
        self.bridge.addDateRangeTask(title, qv, s, e)
        self._wk_title.clear()
        self._toast("已添加本周区间任务")

    def _on_add_month_range(self) -> None:
        title = self._mo_title.text().strip()
        s = self._mo_s.date().toString(Qt.DateFormat.ISODate)
        e = self._mo_e.date().toString(Qt.DateFormat.ISODate)
        qv = int(self._mo_quad.currentData())
        if not title:
            self._calendar_alert("标题为空", "请输入任务标题。")
            return
        a = min(s, e)
        b = max(s, e)
        start = f"{a}T00:00:00"
        end = f"{QDate.fromString(b, Qt.DateFormat.ISODate).addDays(1).toString(Qt.DateFormat.ISODate)}T00:00:00"
        if not self._confirm_conflicts(start, end):
            return
        self.bridge.addDateRangeTask(title, qv, s, e)
        self._mo_title.clear()
        self._toast("已添加跨日任务")

    def apply_theme(self, p: Dict[str, str]) -> None:
        """与 MainWindow 的 palette + 卡片/按钮语义对齐。"""
        r = self._tokens["radius"]["lg"]
        rsm = self._tokens["radius"]["md"]
        slw = p["surface_lowest"]
        sh = p["surface_high"]
        text = p["text"]
        muted = p["muted"]
        border = p["outline_variant"]
        accent = p["focus_accent"]
        primary = p["primary"]
        pc = p["primary_container"]
        on_primary = p.get("on_primary_container", "#ffffff")
        danger = p.get("danger", "#ef4444")

        ss = f"""
        QWidget {{ color: {text}; }}
        QLabel#hero_title {{ color: {text}; }}
        QLabel#hero_subtitle {{ color: {muted}; }}
        QLabel#wc_muted, QLabel#wc_hint {{ color: {muted}; }}
        QLabel#wc_section_title {{ color: {text}; font-size: 11pt; font-weight: 600; }}
        QLabel#wc_date_hero {{ color: {text}; }}
        QLabel#wc_overview_title {{ color: {text}; font-weight: 700; font-size: 15pt; }}
        QLabel#wc_overview_sub {{ color: {muted}; font-size: 12px; }}
        QLabel#wc_month_kicker {{ color: {muted}; font-weight: 700; letter-spacing: 1px; }}
        QLabel#wc_month_hero {{ color: {text}; font-weight: 900; }}
        QLabel#wc_month_sub {{ color: {muted}; font-weight: 600; }}
        QLabel#wc_month_weekday {{ color: {muted}; font-weight: 700; padding: 8px 12px; border-bottom: 1px solid rgba(198,198,198,0.18); }}
        QLabel#wc_month_weekday[weekend="true"] {{ color: {danger}; }}
        QLabel#wc_week_head {{ color: {muted}; font-weight: 700; }}
        QLabel#wc_pm_time {{ color: {text}; font-size: 40px; font-weight: 800; letter-spacing: 1px; }}
        QLabel#wc_pm_state {{ color: {muted}; font-size: 13px; font-weight: 600; }}
        QLabel#wc_pm_bind {{ color: {muted}; font-size: 12px; }}
        QLabel#wc_quad_title {{ color: {text}; font-size: 10pt; font-weight: 600; }}

        QFrame#wc_card {{
            background: {slw};
            border: 1px solid {border};
            border-radius: {r}px;
        }}
        QFrame#wc_overview_card {{
            background: transparent;
            border: none;
            border-radius: 0px;
        }}
        QFrame#wc_seg_wrap {{
            background: {sh};
            border: 1px solid {border};
            border-radius: {rsm}px;
        }}
        QWidget#wc_calendar_root {{
            background: transparent;
            border: none;
        }}
        QWidget#wc_month_canvas {{
            background: {slw};
            border: none;
            border-radius: 0px;
        }}
        QWidget#wc_exec_wrap {{
            background: transparent;
            border: none;
        }}
        QFrame#wc_pm_card {{
            background: {slw};
            border: 1px solid rgba(198,198,198,0.30);
            border-radius: {r}px;
        }}
        QFrame#wc_quad_card {{
            background: {slw};
            border: 1px solid {border};
            border-radius: {r}px;
        }}
        QFrame#wc_preview_card {{
            background: {slw};
            border: 1px solid rgba(198,198,198,0.30);
            border-radius: 12px;
        }}

        QPushButton#wc_seg {{
            min-width: 84px;
            min-height: 36px;
            border-radius: 10px;
            border: none;
            background: transparent;
            color: {muted};
            font-weight: 600;
        }}
        QPushButton#wc_seg:hover {{ background: rgba(127,127,127,0.08); color: {text}; }}
        QPushButton#wc_seg:checked {{
            background: {slw};
            color: {text};
            font-weight: 700;
            border: 1px solid {border};
        }}
        QLabel#wc_stat_chip {{
            background: {slw};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 0px 12px;
            font-weight: 700;
            min-width: 104px;
            min-height: 40px;
        }}
        QPushButton#wc_stat_chip_btn {{
            background: {slw};
            color: {text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 0px 12px;
            font-weight: 700;
            min-width: 120px;
            min-height: 40px;
        }}
        QPushButton#wc_stat_chip_btn:hover {{
            border: 1px solid {accent};
            background: rgba(127,127,127,0.06);
        }}

        QPushButton#primary {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {primary}, stop:1 {pc});
            color: {on_primary};
            border: none;
            border-radius: 10px;
            padding: 0px 16px;
            min-width: 96px;
            min-height: 40px;
            font-weight: 700;
        }}
        QPushButton#primary:hover {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {pc}, stop:1 {primary});
        }}
        QPushButton#secondary {{
            background: {slw};
            color: {text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 0px 12px;
            min-width: 96px;
            min-height: 36px;
            font-weight: 600;
        }}
        QPushButton#secondary:hover {{
            background: rgba(127,127,127,0.06);
            border: 1px solid {accent};
        }}
        QPushButton#section_toggle {{
            background: transparent;
            color: {text};
            border: none;
            border-radius: 8px;
            padding: 0px 2px;
            min-height: 36px;
            font-weight: 700;
            text-align: left;
        }}
        QPushButton#section_toggle:hover {{
            color: {accent};
            background: rgba(127,127,127,0.06);
        }}
        QPushButton#section_toggle:checked {{
            color: {text};
            background: rgba(127,127,127,0.04);
        }}
        QLineEdit, QComboBox, QDateEdit, QTimeEdit {{
            background: {slw};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 0px 10px;
            min-height: 36px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 22px;
            border-left: 1px solid {border};
            background: transparent;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
        }}
        QComboBox::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QDateEdit#wc_date_input {{
            min-height: 36px;
            padding: 0px 10px;
            border-radius: 10px;
            border: 1px solid {border};
            background: {slw};
            font-weight: 600;
        }}
        QDateEdit#wc_date_input:focus {{
            border: 1px solid {accent};
            background: rgba(127,127,127,0.04);
        }}
        QDateEdit#wc_date_input::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 24px;
            border-left: 1px solid {border};
            background: {sh};
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
        }}
        QDateEdit#wc_date_input::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QDateEdit#wc_date_input::up-button, QDateEdit#wc_date_input::down-button {{
            width: 14px;
        }}
        QComboBox#wc_hour_input {{
            min-width: 108px;
            min-height: 36px;
            padding: 0px 10px;
            border-radius: 10px;
            border: 1px solid {border};
            background: {slw};
            font-weight: 600;
        }}
        QComboBox#wc_hour_input:focus {{
            border: 1px solid {accent};
        }}
        QComboBox#wc_hour_input::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 22px;
            border-left: 1px solid {border};
            background: {sh};
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
        }}
        QComboBox#wc_hour_input::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QComboBox#wc_quad_select {{
            min-width: 146px;
            min-height: 36px;
            padding: 0px 10px;
            border-radius: 10px;
            border: 1px solid {border};
            background: {slw};
            font-weight: 600;
        }}
        QComboBox#wc_quad_select::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 22px;
            border-left: 1px solid {border};
            background: {sh};
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
        }}
        QMenu {{
            background: {slw};
            color: {text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 12px;
            border-radius: 6px;
            margin: 1px 0px;
        }}
        QMenu::item:selected {{
            background: rgba(37,99,235,0.12);
            color: {text};
        }}
        QMenu::separator {{
            height: 1px;
            background: rgba(198,198,198,0.28);
            margin: 6px 4px;
        }}
        QMenu::right-arrow {{
            width: 8px;
            height: 8px;
            margin-right: 4px;
        }}
        QMenu::icon {{
            margin-left: 4px;
        }}

        QListView, QListWidget {{
            background: {slw};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 4px;
            outline: none;
        }}
        QListWidget#wc_quad_list {{
            min-height: 72px;
        }}
        QListWidget#wc_month_day_preview {{
            background: transparent;
            border: none;
            border-radius: 0px;
            padding: 0px;
        }}
        QListWidget#wc_month_day_preview::item {{
            padding: 8px 10px;
            min-height: 36px;
            border-radius: 6px;
        }}
        QListWidget#wc_month_day_preview::item:selected {{
            background: rgba(37,99,235,0.10);
            border: 1px solid rgba(37,99,235,0.35);
            color: {text};
        }}
        QListWidget#wc_month_day_preview::item:hover {{
            background: rgba(127,127,127,0.05);
        }}
        QListView::item, QListWidget::item {{
            padding: 7px 9px;
            min-height: 34px;
            border-radius: 6px;
        }}
        QListView::item:selected, QListWidget::item:selected {{
            background: rgba(37,99,235,0.12);
            border: 1px solid {accent};
            color: {text};
        }}
        QListView::item:hover, QListWidget::item:hover {{
            background: rgba(127,127,127,0.06);
        }}
        QListWidget::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {border};
            border-radius: 2px;
            background: {slw};
        }}
        QListWidget::indicator:checked {{
            background: {primary};
            border: 1px solid {primary};
        }}

        QPushButton#wc_month_cell {{
            background: {slw};
            border: none;
            border-right: 1px solid rgba(198,198,198,0.08);
            border-bottom: 1px solid rgba(198,198,198,0.08);
            border-radius: 0px;
            font-weight: 500;
            text-align: left top;
            padding: 12px 14px;
            line-height: 1.35;
        }}
        QPushButton#wc_month_cell:hover {{
            background: rgba(127,127,127,0.05);
        }}
        QPushButton#wc_month_cell[weekend="true"] {{
            color: {danger};
        }}

        /* QDateEdit 弹出的日历统一主题，避免系统原生风格割裂 */
        QDateEdit::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 22px;
            border-left: 1px solid {border};
        }}
        QDateEdit::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QCalendarWidget#wc_popup_calendar QWidget {{
            alternate-background-color: {slw};
            color: {text};
        }}
        QCalendarWidget#wc_popup_calendar QWidget#qt_calendar_navigationbar {{
            background: transparent;
            border: none;
            min-height: 32px;
            padding: 1px 2px;
        }}
        QCalendarWidget#wc_popup_calendar QToolButton {{
            background: transparent;
            color: {text};
            border: none;
            border-radius: 6px;
            min-height: 26px;
            padding: 1px 8px;
            margin: 1px 3px;
            font-weight: 600;
        }}
        QCalendarWidget#wc_popup_calendar QToolButton:hover {{
            background: rgba(127,127,127,0.08);
        }}
        QCalendarWidget#wc_popup_calendar QToolButton#qt_calendar_prevmonth,
        QCalendarWidget#wc_popup_calendar QToolButton#qt_calendar_nextmonth {{
            min-width: 24px;
            padding: 0px;
        }}
        QCalendarWidget#wc_popup_calendar QToolButton#qt_calendar_monthbutton {{
            min-width: 78px;
        }}
        QCalendarWidget#wc_popup_calendar QToolButton#qt_calendar_yearbutton {{
            min-width: 82px;
        }}
        QCalendarWidget#wc_popup_calendar QMenu {{
            background: {slw};
            color: {text};
            border: 1px solid {border};
        }}
        QCalendarWidget#wc_popup_calendar QSpinBox {{
            background: {slw};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            min-width: 92px;
            min-height: 26px;
            padding: 0px 6px;
        }}
        QCalendarWidget#wc_popup_calendar QAbstractItemView:enabled {{
            background: {slw};
            color: {text};
            selection-background-color: rgba(37,99,235,0.18);
            selection-color: {text};
            border: 1px solid {border};
            border-radius: 10px;
            outline: none;
        }}
        QCalendarWidget#wc_popup_calendar QAbstractItemView:disabled {{
            color: {muted};
        }}
        QCalendarWidget#wc_popup_calendar QAbstractItemView::item {{
            border-radius: 6px;
            padding: 4px 2px;
            min-height: 30px;
        }}
        QCalendarWidget#wc_popup_calendar QAbstractItemView::item:hover {{
            background: rgba(127,127,127,0.08);
        }}
        QCalendarWidget#wc_popup_calendar QTableView {{
            gridline-color: rgba(198,198,198,0.18);
        }}
        QCalendarWidget#wc_popup_calendar QTableView QHeaderView::section {{
            background: {sh};
            color: {muted};
            border: none;
            padding: 5px 0px;
            font-weight: 600;
        }}

        QScrollArea {{ background: transparent; border: none; }}
        """
        self.setStyleSheet(ss)
        self._fill_month_grid()
