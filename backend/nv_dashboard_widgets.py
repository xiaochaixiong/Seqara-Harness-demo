# -*- coding: utf-8 -*-
"""企业微信活动数据看板的 PySide6 组件。

页面只消费 ``nv_dashboard_core`` 的脱敏快照。主程序通过少量回调注入主题和
导航任务状态，因此本模块不会反向导入主程序，也不会形成循环依赖。
"""
from __future__ import annotations

import math
import threading
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from PySide6.QtCharts import (
    QAbstractBarSeries,
    QBarCategoryAxis,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QValueAxis,
)
from PySide6.QtCore import QEasingCurve, QMargins, QObject, Qt, QUrl, QVariantAnimation, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nv_dashboard_core import (
    ActivityRecord,
    DashboardFilter,
    DashboardSnapshot,
    DashboardStateStore,
    DashboardView,
    ExpertProfile,
    build_dashboard_snapshot,
    detect_activity_source_kind,
    filter_dashboard_snapshot,
)
from nv_dashboard_export import export_dashboard_view_xlsx
DEFAULT_PALETTE = {
    "canvas": "#f9f9f9",
    "panel": "#ffffff",
    "panel_alt": "#f3f4f6",
    "surface_high": "#e9e9ea",
    "text": "#1a1c1c",
    "muted": "#5f6368",
    "outline": "#d1d5db",
    "primary": "#111827",
    "focus": "#2563eb",
    "on_focus": "#ffffff",
    "success": "#15803d",
    "warning": "#a16207",
    "danger": "#b91c1c",
}


def _fmt_number(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "异常数值"
    if math.isclose(number, round(number)):
        return f"{int(round(number)):,}"
    return f"{number:,.1f}"


def _fmt_date(value: Optional[date]) -> str:
    return value.isoformat() if value else "暂无"


def _display_month(value: str) -> str:
    if value == "日期缺失":
        return value
    parts = value.split("-")
    return f"{parts[0][2:]}年{parts[1]}月" if len(parts) == 2 else value


def _composite_color(foreground: QColor, background: QColor) -> QColor:
    alpha = foreground.alphaF()
    return QColor(
        round(foreground.red() * alpha + background.red() * (1 - alpha)),
        round(foreground.green() * alpha + background.green() * (1 - alpha)),
        round(foreground.blue() * alpha + background.blue() * (1 - alpha)),
    )


def _relative_luminance(color: QColor) -> float:
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first: QColor, second: QColor) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _table_item(text: object, *, data: object = None, align: Optional[Qt.AlignmentFlag] = None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setToolTip(str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if align is not None:
        item.setTextAlignment(align)
    return item


class _WorkerSignals(QObject):
    loaded = Signal(object)
    failed = Signal(object)
    exported = Signal(object)
    export_failed = Signal(object)


class _SectionTitle(QWidget):
    def __init__(self, title: str, description: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("DashboardSectionTitle")
        layout.addWidget(title_label)
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("DashboardSectionDescription")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)


class _Metric(QWidget):
    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardMetric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.setSpacing(2)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("DashboardMetricValue")
        label_widget = QLabel(label)
        label_widget.setObjectName("DashboardMetricLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(label_widget)

    def set_value(self, value: float | int | str) -> None:
        self.value_label.setText(_fmt_number(value) if isinstance(value, (float, int)) else str(value))


class _FileRow(QWidget):
    changed = Signal()

    def __init__(
        self,
        label: str,
        file_filter: str,
        placeholder: str = "选择企业微信导出的原始 Excel",
        parent: Optional[QWidget] = None,
        *,
        button_icon_setter: Optional[Callable[[QPushButton, str, int, str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.file_filter = file_filter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel(label)
        title.setObjectName("stitch_label")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(placeholder)
        self.path_edit.setClearButtonEnabled(True)
        self.path_edit.setMinimumHeight(38)
        self.path_edit.textChanged.connect(self.changed)
        title.setBuddy(self.path_edit)
        self.browse_button = QPushButton("选择文件…")
        self.browse_button.setObjectName("secondary")
        self.browse_button.setMinimumWidth(112)
        self.browse_button.setAccessibleName(f"选择{label}")
        self.browse_button.setFixedSize(112, 40)
        if button_icon_setter is not None:
            button_icon_setter(self.browse_button, "folder", 16, "text")
        self.browse_button.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse_button)
        layout.addWidget(title)
        layout.addLayout(row)

    @property
    def path(self) -> str:
        return self.path_edit.text().strip()

    def set_path(self, value: str) -> None:
        self.path_edit.setText(value)

    def _browse(self) -> None:
        initial = str(Path(self.path).parent) if self.path else str(Path.home() / "Downloads")
        selected, _ = QFileDialog.getOpenFileName(self, "选择 Excel", initial, self.file_filter)
        if selected:
            self.set_path(selected)


class _HorizontalBarChart(QChartView):
    selected = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        maximum_items: Optional[int] = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self._palette = DEFAULT_PALETTE.copy()
        self._maximum_items = maximum_items
        self._compact = compact
        self._bar_set: Optional[QBarSet] = None
        self._bar_labels: list[str] = []
        self._selection_animation: Optional[QVariantAnimation] = None
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(300)
        self.setAccessibleName("横向排名图")
        self.setAccessibleDescription("按数值从高到低排列。可切换到数据表进行键盘查看。")

    def set_palette(self, colors: dict[str, str]) -> None:
        self._palette = {**DEFAULT_PALETTE, **colors}
        self.setBackgroundBrush(QBrush(QColor(self._palette["panel"])))

    def set_data(self, values: dict[str, float | int], title: str, value_label: str = "") -> None:
        if self._selection_animation is not None:
            self._selection_animation.stop()
        ranked = sorted(values.items(), key=lambda item: (-float(item[1]), item[0]))
        if self._maximum_items is not None:
            ranked = ranked[: self._maximum_items]
        # QBarCategoryAxis 的首项绘制在最下方，因此反转后最大值位于视觉顶部。
        ordered = list(reversed(ranked))
        chart = QChart()
        chart.setTheme(
            QChart.ChartTheme.ChartThemeDark
            if QColor(self._palette["panel"]).lightness() < 128
            else QChart.ChartTheme.ChartThemeLight
        )
        chart.setBackgroundVisible(True)
        chart.setBackgroundBrush(QBrush(QColor(self._palette["panel"])))
        chart.setBackgroundPen(QPen(Qt.PenStyle.NoPen))
        chart.setPlotAreaBackgroundVisible(False)
        chart.setTitle(title)
        chart.setTitleBrush(QColor(self._palette["text"]))
        chart.legend().hide()
        series = QHorizontalBarSeries()
        series.setLabelsVisible(True)
        series.setLabelsFormat("@value")
        series.setLabelsPrecision(12)
        series.setLabelsPosition(QAbstractBarSeries.LabelsPosition.LabelsInsideEnd)
        bar_set = QBarSet(value_label or title)
        label_candidates = (QColor('#ffffff'), QColor('#202328'))
        bar_set.setLabelColor(max(label_candidates, key=lambda color: _contrast_ratio(color, QColor(self._palette['focus']))))
        bar_set.setColor(QColor(self._palette["focus"]))
        bar_set.setBorderColor(QColor(self._palette["focus"]))
        if ordered:
            bar_set.append([float(value) for _, value in ordered])
        series.append(bar_set)
        chart.addSeries(series)
        category_axis = QBarCategoryAxis()
        category_axis.append([key for key, _ in ordered] or ["暂无数据"])
        category_axis.setTruncateLabels(False)
        category_axis.setLabelsBrush(QColor(self._palette["muted"]))
        category_axis.setGridLineVisible(False)
        value_axis = QValueAxis()
        maximum = max((float(value) for _, value in ordered), default=1.0)
        value_axis.setRange(0, maximum * 1.08 if maximum else 1.0)
        value_axis.setLabelFormat("%.0f")
        value_axis.setLabelsBrush(QColor(self._palette["muted"]))
        value_axis.setGridLineColor(QColor(self._palette["outline"]))
        chart.addAxis(category_axis, Qt.AlignmentFlag.AlignLeft)
        chart.addAxis(value_axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(category_axis)
        series.attachAxis(value_axis)
        chart.setMargins(QMargins(0, 0, 8, 0))
        labels = [key for key, _ in ordered]
        self._bar_set = bar_set
        self._bar_labels = labels
        bar_set.clicked.connect(self._activate_bar)
        base_height = 220 if self._compact else 300
        row_height = 19 if self._compact else 24
        self.setMinimumHeight(max(base_height, len(ordered) * row_height + 76))
        self.setChart(chart)

    @Slot(int)
    def _activate_bar(self, index: int) -> None:
        bar_set = self._bar_set
        if bar_set is None or not (0 <= index < len(self._bar_labels)):
            return
        bar_set.deselectAllBars()
        focus = QColor(self._palette["focus"])
        dark_surface = QColor(self._palette["panel"]).lightness() < 128
        pulse_color = focus.lighter(165 if dark_surface else 150)
        selected_color = focus.lighter(145) if dark_surface else focus.darker(140)
        bar_set.setSelectedColor(pulse_color)
        bar_set.selectBar(index)
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(pulse_color)
        animation.setEndValue(selected_color)
        animation.valueChanged.connect(bar_set.setSelectedColor)
        animation.start()
        self._selection_animation = animation
        selected_label = self._bar_labels[index]
        self.selected.emit(selected_label)

    def clear_selection(self) -> None:
        if self._bar_set is not None:
            self._bar_set.deselectAllBars()


class _ChartTableToggle(QWidget):
    def __init__(self, chart: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.chart = chart
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        controls = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setObjectName("DashboardChartSelection")
        self.selection_label.hide()
        self._selection_effect = QGraphicsOpacityEffect(self.selection_label)
        self.selection_label.setGraphicsEffect(self._selection_effect)
        self._selection_feedback_animation: Optional[QVariantAnimation] = None
        controls.addWidget(self.selection_label)
        controls.addStretch(1)
        self.chart_button = QPushButton("图表")
        self.table_button = QPushButton("数据表")
        group = QButtonGroup(self)
        group.setExclusive(True)
        for button in (self.chart_button, self.table_button):
            button.setCheckable(True)
            button.setProperty("kind", "segmented")
            button.setObjectName("DashboardSegmented")
            group.addButton(button)
            controls.addWidget(button)
        self.chart_button.setChecked(True)
        layout.addLayout(controls)
        self.stack = QStackedWidget()
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.setAccessibleName("图表数据表")
        self.stack.addWidget(chart)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack)
        self.chart_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.table_button.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        if isinstance(chart, _HorizontalBarChart):
            chart.selected.connect(self._show_selection_feedback)

    @Slot(str)
    def _show_selection_feedback(self, label: str) -> None:
        self.selection_label.setText(f"已选择：{label}")
        self._selection_effect.setOpacity(0.2)
        self.selection_label.show()
        if self._selection_feedback_animation is not None:
            self._selection_feedback_animation.stop()
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.2)
        animation.setEndValue(1.0)
        animation.valueChanged.connect(self._selection_effect.setOpacity)
        animation.start()
        self._selection_feedback_animation = animation

    def clear_selection_feedback(self) -> None:
        if self._selection_feedback_animation is not None:
            self._selection_feedback_animation.stop()
        self.selection_label.hide()

    def set_table_data(self, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
        self.clear_selection_feedback()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, _table_item(value))
        if headers:
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.resizeColumnsToContents()
        self.table.setMinimumHeight(min(420, max(190, len(rows) * 28 + 62)))


class _DrillBar(QFrame):
    cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("stitch_inner_muted")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 8, 7)
        self.label = QLabel("")
        self.label.setObjectName("DashboardStatus")
        self.clear_button = QPushButton()
        self.clear_button.setText("清除图表筛选")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self.cleared)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.clear_button)
        self.hide()

    def show_state(self, text: str) -> None:
        self.label.setText(text)
        self.setAccessibleName(text)
        self.show()

    def clear_state(self) -> None:
        self.label.clear()
        self.hide()


class _HeatmapTable(QTableWidget):
    cell_selected = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = DEFAULT_PALETTE.copy()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.verticalHeader().setDefaultSectionSize(28)
        self.verticalHeader().setMinimumSectionSize(28)
        self.horizontalHeader().setMinimumSectionSize(68)
        self.cellClicked.connect(self._emit_selection)
        self.cellActivated.connect(self._emit_selection)
        self.setAccessibleName("数据热力表")
        self.setAccessibleDescription("使用方向键移动，按 Enter 查看选中单元格对应的活动明细。")
        self._rows: list[str] = []
        self._columns: list[str] = []

    def set_palette(self, colors: dict[str, str]) -> None:
        self._palette = {**DEFAULT_PALETTE, **colors}

    def set_matrix(
        self,
        rows: Sequence[str],
        columns: Sequence[str],
        values: dict[str, dict[str, float | int]],
        *,
        number_suffix: str = "",
    ) -> None:
        self._rows = list(rows)
        self._columns = list(columns)
        self.setRowCount(len(rows))
        self.setColumnCount(len(columns))
        self.setVerticalHeaderLabels(list(rows))
        self.setHorizontalHeaderLabels([_display_month(col) for col in columns])
        maximum = max((float(values.get(row, {}).get(col, 0)) for row in rows for col in columns), default=0.0)
        accent = QColor(self._palette["focus"])
        for row_index, row in enumerate(rows):
            for col_index, column in enumerate(columns):
                value = float(values.get(row, {}).get(column, 0))
                text = _fmt_number(value) + number_suffix if value else "—"
                item = _table_item(text, data=(row, column), align=Qt.AlignmentFlag.AlignCenter)
                ratio = value / maximum if maximum else 0.0
                if ratio > 0:
                    background = QColor(accent)
                    background.setAlpha(35 + int(155 * math.sqrt(ratio)))
                    item.setBackground(background)
                    composite = _composite_color(background, QColor(self._palette["panel"]))
                    light_text = QColor("#ffffff")
                    dark_text = QColor("#202328")
                    item.setForeground(
                        light_text
                        if _contrast_ratio(light_text, composite) >= _contrast_ratio(dark_text, composite)
                        else dark_text
                    )
                item.setToolTip(f"{row} · {_display_month(column)}：{_fmt_number(value)}{number_suffix}")
                self.setItem(row_index, col_index, item)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.setMinimumHeight(min(560, max(210, len(rows) * 28 + 66)))

    def _emit_selection(self, row: int, column: int) -> None:
        if 0 <= row < len(self._rows) and 0 <= column < len(self._columns):
            self.cell_selected.emit(self._rows[row], self._columns[column])


class _ActivityDetailTable(QTableWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        show_information: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._show_information = show_information
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(
            ["审批编号", "院校", "活动名称", "活动类型", "开始日期", "教师", "学生", "关联详情"]
        )
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(230)
        self.cellClicked.connect(self._open_action_cell)
        self.cellActivated.connect(self._open_action_cell)
        self.setAccessibleName("活动明细")
        self.setAccessibleDescription("在“关联详情”列单击或按 Enter 打开审批详情或新闻链接。")
        self._records: list[ActivityRecord] = []

    def set_records(self, records: Iterable[ActivityRecord]) -> None:
        self._records = list(records)
        self.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            values = (
                record.approval_id,
                record.school,
                record.activity_name,
                " / ".join(record.activity_types),
                _fmt_date(record.start_date),
                _fmt_number(record.teacher_count),
                _fmt_number(record.student_count),
                "打开" if record.detail_url else "无链接",
            )
            for column, value in enumerate(values):
                self.setItem(row, column, _table_item(value, data=record.detail_url if column == 0 else None))
        self.resizeColumnsToContents()

    def _open_action_cell(self, row: int, column: int) -> None:
        if column == 7 and 0 <= row < len(self._records):
            _open_url(self._records[row].detail_url, self, self._show_information)


def _open_url(
    url: str,
    parent: QWidget,
    show_information: Optional[Callable[[str, str], None]] = None,
) -> None:
    if not url:
        if show_information is not None:
            show_information("暂无关联链接", "这条记录没有可打开的审批详情或新闻链接。")
        else:
            QMessageBox.information(parent, "暂无关联链接", "这条记录没有可打开的审批详情或新闻链接。")
        return
    QDesktopServices.openUrl(QUrl(url))


def _scroll_page(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setObjectName("DashboardScroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.viewport().setObjectName("DashboardScrollViewport")
    area.viewport().setAutoFillBackground(False)
    content.setObjectName("DashboardScrollContent")
    content.setAutoFillBackground(False)
    area.setWidget(content)
    return area


class DashboardPage(QWidget):
    """独立数据看板页面。"""

    def __init__(
        self,
        parent: Optional[QWidget],
        state_path: str | Path,
        *,
        palette_provider: Optional[Callable[[], dict[str, str]]] = None,
        task_begin: Optional[Callable[[], None]] = None,
        task_end: Optional[Callable[[], None]] = None,
        last_cleaned_path_provider: Optional[Callable[[], str]] = None,
        button_icon_setter: Optional[Callable[[QPushButton, str, int, str], None]] = None,
        show_information: Optional[Callable[[str, str], None]] = None,
        show_warning: Optional[Callable[[str, str], None]] = None,
        show_critical: Optional[Callable[[str, str], None]] = None,
        ask_confirmation: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName("数据看板")
        self.setAccessibleDescription("企业微信活动申请、活动报销和整理结果的基础业务看板。")
        self.state_store = DashboardStateStore(state_path)
        self.palette_provider = palette_provider or (lambda: DEFAULT_PALETTE.copy())
        self.task_begin = task_begin or (lambda: None)
        self.task_end = task_end or (lambda: None)
        self.last_cleaned_path_provider = last_cleaned_path_provider or (lambda: "")
        self.button_icon_setter = button_icon_setter
        self.show_information = show_information or (
            lambda title, message: QMessageBox.information(self, title, message)
        )
        self.show_warning = show_warning or (lambda title, message: QMessageBox.warning(self, title, message))
        self.show_critical = show_critical or (lambda title, message: QMessageBox.critical(self, title, message))
        self.ask_confirmation = ask_confirmation or (
            lambda title, message: QMessageBox.question(self, title, message)
            == QMessageBox.StandardButton.Yes
        )
        self.snapshot: Optional[DashboardSnapshot] = None
        self._load_error = ""
        self.view: Optional[DashboardView] = None
        self._signals = _WorkerSignals(self)
        self._signals.loaded.connect(self._on_loaded)
        self._signals.failed.connect(self._on_failed)
        self._signals.exported.connect(self._on_exported)
        self._signals.export_failed.connect(self._on_export_failed)
        self._loading = False
        self._exporting = False
        self._load_request_id = 0
        self._loaded_source_paths: tuple[str, str, str] = ("", "", "")
        self._overview_wide: Optional[bool] = None
        self._setting_month_filter = False
        self._coverage_metric = "teacher"
        self._coverage_school: Optional[str] = None
        self._coverage_month: Optional[str] = None
        self._activity_drill_school: Optional[str] = None
        self._activity_drill_month: Optional[str] = None
        self._type_drill_type: Optional[str] = None
        self._expert_profiles: tuple[ExpertProfile, ...] = ()
        self._build_ui()
        self.apply_theme(self.palette_provider())
        self._stitch_primary_action = self.refresh_button
        self._restore_dashboard()

    def _restore_dashboard(self) -> None:
        try:
            snapshot = self.state_store.load_snapshot()
            if snapshot is None:
                return
            self.application_row.set_path(snapshot.source_application_path)
            self.reimbursement_row.set_path(snapshot.source_reimbursement_path)
            self.supplementary_row.set_path(snapshot.source_supplementary_path)
            self._on_loaded(snapshot, restoring=True)
            self.status_label.setText(
                f"已恢复上次看板 · 数据截至 {snapshot.as_of_date.isoformat()} · 点击“更新看板”读取最新表格。")
        except Exception as exc:
            self.snapshot = None
            self.view = None
            self.metric_row.hide()
            self.content_stack.setCurrentWidget(self.empty_state)
            self.status_label.setText(f"上次看板恢复失败，请重新选择表格生成看板。原因：{exc}")

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("page_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas.setObjectName("page_canvas")
        scroll.setWidget(canvas)
        outer.addWidget(scroll)
        root = QVBoxLayout(canvas)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(40, 32, 40, 24)
        root.setSpacing(16)

        self.header_layout = QGridLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setHorizontalSpacing(12)
        self.header_layout.setVerticalSpacing(8)
        self.title_container = QWidget()
        title_box = QVBoxLayout(self.title_container)
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(8)
        title = QLabel("数据看板")
        title.setObjectName("hero_title")
        title.setWordWrap(True)
        self.subtitle_label = QLabel("支持企业微信原始审批或整理结果，生成可追溯的业务视图；源文件始终保持不变。")
        self.subtitle_label.setObjectName("hero_subtitle")
        self.subtitle_label.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle_label)
        self.action_container = QWidget()
        action_layout = QHBoxLayout(self.action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        self.use_cleaned_button = QPushButton("使用最近整理结果")
        self.use_cleaned_button.setObjectName("secondary")
        self.use_cleaned_button.clicked.connect(self._use_last_cleaned_result)
        self.refresh_button = QPushButton("生成看板")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        self.cancel_button = QPushButton("取消等待")
        self.cancel_button.setObjectName("secondary")
        self.cancel_button.clicked.connect(self.cancel_refresh)
        self.cancel_button.hide()
        action_layout.addWidget(self.use_cleaned_button)
        action_layout.addWidget(self.cancel_button)
        action_layout.addWidget(self.refresh_button)
        self.header_layout.addWidget(self.title_container, 0, 0)
        self.header_layout.addWidget(self.action_container, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.header_layout.setColumnStretch(0, 1)
        root.addLayout(self.header_layout)

        self.source_panel = QFrame()
        self.source_panel.setObjectName("stitch_file_card")
        source_layout = QVBoxLayout(self.source_panel)
        source_layout.setContentsMargins(24, 16, 24, 16)
        source_layout.setSpacing(16)
        self.source_expanded_content = QWidget()
        expanded_layout = QVBoxLayout(self.source_expanded_content)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(16)
        self.application_row = _FileRow(
            "活动数据表",
            "活动数据 (*.xlsx *.xls *.csv)",
            "选择活动申请表或数据整理结果",
            button_icon_setter=self.button_icon_setter,
        )
        self.reimbursement_row = _FileRow(
            "活动报销表",
            "Excel 工作簿 (*.xlsx *.xls)",
            "使用整理结果时可不选",
            button_icon_setter=self.button_icon_setter,
        )
        self.application_row.changed.connect(self._on_source_changed)
        self.reimbursement_row.changed.connect(self._on_source_changed)
        self.supplementary_row = _FileRow(
            "补充活动表（可选）", "Excel 工作簿 (*.xlsx *.xls)",
            "补充线下活动数量与分布，视为已报销",
            button_icon_setter=self.button_icon_setter,
        )
        self.supplementary_row.changed.connect(self._on_source_changed)
        expanded_layout.addWidget(self.application_row)
        expanded_layout.addWidget(self.reimbursement_row)
        expanded_layout.addWidget(self.supplementary_row)
        source_layout.addWidget(self.source_expanded_content)

        self.source_summary_label = QLabel("")
        self.source_summary_label.setObjectName("DashboardSourceSummary")
        self.source_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.source_summary_label.hide()
        source_layout.addWidget(self.source_summary_label)

        status_line = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("DashboardStatus")
        self.status_label.setWordWrap(True)
        status_line.addWidget(self.status_label, 1)
        self.quality_summary_label = QLabel("")
        self.quality_summary_label.setObjectName("DashboardQuality")
        self.quality_summary_label.hide()
        status_line.addWidget(self.quality_summary_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.source_toggle_button = QPushButton("更换数据")
        self.source_toggle_button.setObjectName("secondary")
        self.source_toggle_button.setAccessibleName("展开或收起数据来源")
        self.source_toggle_button.clicked.connect(
            lambda: self._set_source_expanded(not self.source_expanded_content.isVisible())
        )
        self.source_toggle_button.hide()
        status_line.addWidget(self.source_toggle_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        source_layout.addLayout(status_line)
        root.addWidget(self.source_panel)

        metric_row = QFrame()
        metric_row.setObjectName("stitch_settings")
        metric_layout = QHBoxLayout(metric_row)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(1)
        self.metrics: dict[str, _Metric] = {}
        for key, label in (
            ("activities", "已通过活动"),
            ("schools", "覆盖院校"),
            ("teachers", "计划教师人次"),
            ("students", "计划学生人次"),
        ):
            metric = _Metric(label)
            self.metrics[key] = metric
            metric_layout.addWidget(metric, 1)
        root.addWidget(metric_row)
        self.metric_row=metric_row
        metric_row.hide()

        self.month_filter_panel = QFrame()
        self.month_filter_panel.setObjectName("stitch_inner_muted")
        self.month_filter_panel.setAccessibleName("统计月份筛选")
        self.month_filter_panel.setAccessibleDescription(
            "按活动开始月份查看全部、单月或连续月份区间的数据，所有指标和专题页同步更新。"
        )
        self.month_filter_layout = QGridLayout(self.month_filter_panel)
        self.month_filter_layout.setContentsMargins(14, 8, 14, 8)
        self.month_filter_layout.setHorizontalSpacing(8)
        self.month_filter_layout.setVerticalSpacing(5)
        self.month_filter_title = QLabel("统计月份")
        self.month_filter_title.setObjectName("DashboardFilterTitle")
        self.month_mode_combo = QComboBox()
        self.month_mode_combo.setObjectName("stitch_combo")
        self.month_mode_combo.addItem("全部月份", "all")
        self.month_mode_combo.addItem("单月", "single")
        self.month_mode_combo.addItem("月份区间", "range")
        self.month_mode_combo.setMinimumWidth(112)
        self.month_mode_combo.setAccessibleName("月份筛选方式")
        self.month_start_caption = QLabel("月份")
        self.month_start_caption.setObjectName("DashboardStatus")
        self.month_start_combo = QComboBox()
        self.month_start_combo.setObjectName("stitch_combo")
        self.month_start_combo.setMinimumWidth(112)
        self.month_start_combo.setAccessibleName("起始月份或单月")
        self.month_separator = QLabel("至")
        self.month_separator.setObjectName("DashboardStatus")
        self.month_end_combo = QComboBox()
        self.month_end_combo.setObjectName("stitch_combo")
        self.month_end_combo.setMinimumWidth(112)
        self.month_end_combo.setAccessibleName("结束月份")
        self.month_filter_status = QLabel("")
        self.month_filter_status.setObjectName("DashboardStatus")
        self.month_filter_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.month_filter_status.setAccessibleName("当前统计月份与活动数量")
        self.export_button = QPushButton("导出重点数据…")
        self.export_button.setObjectName("secondary")
        self.export_button.setEnabled(False)
        self.export_button.setAccessibleName("导出重点数据 Excel")
        self.export_button.setAccessibleDescription(
            "按当前月份筛选导出院校、活动类型和覆盖人次汇总；专家库始终导出本机全量。"
        )
        self.export_button.setToolTip("导出当前时间段的重点汇总和本机全量专家库")
        self.export_button.clicked.connect(self._export_dashboard_excel)
        if self.button_icon_setter is not None:
            self.button_icon_setter(self.export_button, "files", 16, "primary")
        self.month_mode_combo.currentIndexChanged.connect(lambda _index: self._apply_month_filter("mode"))
        self.month_start_combo.currentIndexChanged.connect(lambda _index: self._apply_month_filter("start"))
        self.month_end_combo.currentIndexChanged.connect(lambda _index: self._apply_month_filter("end"))
        for column, widget in enumerate(
            (
                self.month_filter_title,
                self.month_mode_combo,
                self.month_start_caption,
                self.month_start_combo,
                self.month_separator,
                self.month_end_combo,
                self.month_filter_status,
                self.export_button,
            )
        ):
            self.month_filter_layout.addWidget(widget, 0, column)
        self.month_filter_layout.setColumnStretch(6, 1)
        self.month_filter_panel.hide()
        root.addWidget(self.month_filter_panel)

        self.content_stack = QStackedWidget()
        self.empty_state = self._build_empty_state()
        self.loading_state = self._build_loading_state()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("DashboardTabs")
        self.tabs.addTab(self._build_activity_tab(), "院校活动")
        self.tabs.addTab(self._build_type_tab(), "活动类型")
        self.tabs.addTab(self._build_coverage_tab(), "覆盖人次")
        self.tabs.addTab(self._build_unreimbursed_tab(), "未报销活动")
        self.tabs.addTab(self._build_expert_tab(), "专家库")
        self.content_stack.addWidget(self.empty_state)
        self.content_stack.addWidget(self.loading_state)
        self.content_stack.addWidget(self.tabs)
        self.content_stack.setCurrentWidget(self.empty_state)
        root.addWidget(self.content_stack, 1)
        self._update_refresh_enabled()

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addStretch(1)
        label = QLabel("添加数据，生成活动看板")
        label.setObjectName("DashboardEmptyTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel("选择活动数据表，或使用最近整理结果。")
        note.setObjectName("DashboardEmptyText")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_loading_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel("正在解析并归并审批数据…")
        title.setObjectName("DashboardEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel("申请主单、专家子行和报销关联会在后台处理，不会修改源文件。")
        note.setObjectName("DashboardEmptyText")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_activity_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addWidget(
            _SectionTitle("院校活动排名", "图表展示 Top 10；切换数据表可查看全部院校，点击柱形可下钻。")
        )
        self.school_chart = _HorizontalBarChart(maximum_items=10, compact=True)
        self.school_chart.selected.connect(lambda school: self._show_activity_detail(school=school))
        self.school_chart_view = _ChartTableToggle(self.school_chart)
        layout.addWidget(self.school_chart_view)

        layout.addWidget(_SectionTitle("院校 × 活动开始月", "单元格越深表示活动越集中；点击单元格可下钻。"))
        self.school_month_heatmap = _HeatmapTable()
        self.school_month_heatmap.cell_selected.connect(lambda school, month: self._show_activity_detail(school, month))
        layout.addWidget(self.school_month_heatmap)
        self.activity_drill_bar = _DrillBar()
        self.activity_drill_bar.cleared.connect(self._clear_activity_drill)
        layout.addWidget(self.activity_drill_bar)
        self.activity_detail_title = _SectionTitle("活动明细", "使用“关联详情”列打开审批详情或新闻链接。")
        layout.addWidget(self.activity_detail_title)
        self.activity_detail = _ActivityDetailTable(show_information=self.show_information)
        layout.addWidget(self.activity_detail)
        return _scroll_page(content)

    def _build_type_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.addWidget(_SectionTitle("活动类型分布", "多标签活动按明确分隔符拆分，每个类型各计一次。"), 1)
        toolbar.addWidget(QLabel("聚焦院校"))
        self.type_school_combo = QComboBox()
        self.type_school_combo.setObjectName("stitch_combo")
        self.type_school_combo.setMinimumWidth(220)
        self.type_school_combo.currentTextChanged.connect(self._refresh_type_school_view)
        toolbar.addWidget(self.type_school_combo)
        layout.addLayout(toolbar)
        layout.addWidget(_SectionTitle("院校 × 活动类型"))
        self.school_type_heatmap = _HeatmapTable()
        self.school_type_heatmap.cell_selected.connect(self._show_type_detail)
        layout.addWidget(self.school_type_heatmap)
        self.type_school_title = _SectionTitle("选定院校的月份 × 活动类型")
        layout.addWidget(self.type_school_title)
        self.month_type_heatmap = _HeatmapTable()
        self.month_type_heatmap.cell_selected.connect(self._show_month_type_detail)
        layout.addWidget(self.month_type_heatmap)
        self.type_drill_bar = _DrillBar()
        self.type_drill_bar.cleared.connect(self._clear_type_drill)
        layout.addWidget(self.type_drill_bar)
        layout.addWidget(_SectionTitle("活动明细", "使用“关联详情”列打开审批详情或新闻链接。"))
        self.type_detail = _ActivityDetailTable(show_information=self.show_information)
        layout.addWidget(self.type_detail)
        return _scroll_page(content)

    def _build_coverage_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.addWidget(_SectionTitle("覆盖人次", "仅使用活动申请中的计划人数；人工排除只影响看板汇总。"), 1)
        self.teacher_button = QPushButton("教师")
        self.student_button = QPushButton("学生")
        for button in (self.teacher_button, self.student_button):
            button.setCheckable(True)
            button.setProperty("kind", "segmented")
            button.setObjectName("DashboardSegmented")
        self.teacher_button.setChecked(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.teacher_button)
        group.addButton(self.student_button)
        self.teacher_button.clicked.connect(lambda: self._set_coverage_metric("teacher"))
        self.student_button.clicked.connect(lambda: self._set_coverage_metric("student"))
        toolbar.addWidget(self.teacher_button)
        toolbar.addWidget(self.student_button)
        layout.addLayout(toolbar)
        self.coverage_chart = _HorizontalBarChart()
        self.coverage_chart.selected.connect(self._coverage_school_selected)
        self.coverage_chart_view = _ChartTableToggle(self.coverage_chart)
        layout.addWidget(self.coverage_chart_view)
        self.coverage_heatmap = _HeatmapTable()
        self.coverage_heatmap.cell_selected.connect(self._coverage_cell_selected)
        layout.addWidget(self.coverage_heatmap)
        self.coverage_drill_bar = _DrillBar()
        self.coverage_drill_bar.cleared.connect(self._clear_coverage_drill)
        layout.addWidget(self.coverage_drill_bar)
        coverage_detail_bar = QHBoxLayout()
        coverage_detail_bar.addWidget(_SectionTitle("覆盖明细", "勾选“异常排除”后该字段不再计入汇总；可随时恢复。"), 1)
        coverage_detail_bar.addWidget(QLabel("记录范围"))
        self.coverage_record_filter = QComboBox()
        self.coverage_record_filter.setObjectName("stitch_combo")
        self.coverage_record_filter.addItems(["全部记录", "仅已纳入", "仅已排除"])
        self.coverage_record_filter.currentIndexChanged.connect(self._refresh_coverage_detail)
        coverage_detail_bar.addWidget(self.coverage_record_filter)
        layout.addLayout(coverage_detail_bar)
        self.coverage_detail = QTableWidget()
        self.coverage_detail.setColumnCount(9)
        self.coverage_detail.setHorizontalHeaderLabels(
            ["审批编号", "院校", "活动名称", "开始日期", "字段", "计划人次", "异常排除", "状态", "审批详情"]
        )
        self.coverage_detail.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.coverage_detail.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.coverage_detail.setAlternatingRowColors(True)
        self.coverage_detail.verticalHeader().hide()
        self.coverage_detail.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.coverage_detail.setMinimumHeight(260)
        self.coverage_detail.cellClicked.connect(self._open_coverage_action)
        self.coverage_detail.cellActivated.connect(self._open_coverage_action)
        self.coverage_detail.setAccessibleName("覆盖人次活动明细")
        self.coverage_detail.setAccessibleDescription("在“审批详情”列单击或按 Enter 打开审批详情。")
        layout.addWidget(self.coverage_detail)
        return _scroll_page(content)

    def _build_unreimbursed_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.addWidget(_SectionTitle("未报销活动", "截至日期优先取文件名结束日；报销审批中与未开始活动单独区分。"), 1)
        self.unreim_search = QLineEdit()
        self.unreim_search.setPlaceholderText("搜索院校、活动或审批编号")
        self.unreim_search.setClearButtonEnabled(True)
        self.unreim_search.setMinimumWidth(250)
        self.unreim_search.textChanged.connect(self._refresh_unreimbursed)
        self.unreim_state_combo = QComboBox()
        self.unreim_state_combo.setObjectName("stitch_combo")
        self.unreim_state_combo.addItems(["全部状态", "已结束未报销", "报销审批中", "进行中", "未开始"])
        self.unreim_state_combo.currentTextChanged.connect(self._refresh_unreimbursed)
        toolbar.addWidget(self.unreim_search)
        toolbar.addWidget(self.unreim_state_combo)
        layout.addLayout(toolbar)
        self.unreim_result_label = QLabel("")
        self.unreim_result_label.setObjectName("DashboardStatus")
        layout.addWidget(self.unreim_result_label)
        self.unreim_table = QTableWidget()
        self.unreim_table.setColumnCount(9)
        self.unreim_table.setHorizontalHeaderLabels(
            ["审批编号", "院校", "活动名称", "活动类型", "开始日期", "结束日期", "距结束", "业务状态", "审批详情"]
        )
        self.unreim_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.unreim_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.unreim_table.setAlternatingRowColors(True)
        self.unreim_table.verticalHeader().hide()
        self.unreim_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.unreim_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.unreim_table.cellClicked.connect(self._open_unreimbursed_action)
        self.unreim_table.cellActivated.connect(self._open_unreimbursed_action)
        self.unreim_table.setAccessibleName("未报销活动")
        self.unreim_table.setAccessibleDescription("在“审批详情”列单击或按 Enter 打开对应审批详情。")
        layout.addWidget(self.unreim_table, 1)
        return content

    def _build_expert_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        expert_hint = QLabel("按姓名归并专家；简介冲突和多人记录保留核对标记。")
        expert_hint.setWordWrap(True)
        expert_hint.setObjectName("DashboardStatus")
        layout.addWidget(expert_hint)
        self.expert_source_combo = QComboBox()
        self.expert_source_combo.setObjectName("stitch_combo")
        self.expert_source_combo.addItems(["当前文件", "历史归档"])
        self.expert_source_combo.setMinimumWidth(116)
        self.expert_source_combo.setMaximumWidth(144)
        self.expert_source_combo.currentIndexChanged.connect(self._refresh_expert_source)
        self.archive_button = QPushButton("归档本次专家数据")
        self.archive_button.setObjectName("secondary")
        self.archive_button.clicked.connect(self._archive_current_experts)
        self.archive_button.hide()
        self.expert_fee_check = QCheckBox("显示专家费")
        self.expert_fee_check.setToolTip("仅在邀请明细中显示原始费用；多人共用费用不自动平摊。")
        self.expert_fee_check.toggled.connect(self._refresh_expert_detail)
        toolbar.addWidget(self.expert_source_combo)
        toolbar.addWidget(self.archive_button)
        toolbar.addWidget(self.expert_fee_check)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.archive_status = QLabel("")
        self.archive_status.setObjectName("DashboardStatus")
        self.expert_search = QLineEdit()
        self.expert_search.setPlaceholderText("搜索姓名、简介、邀请院校或活动类型")
        self.expert_search.setClearButtonEnabled(True)
        self.expert_search.textChanged.connect(self._refresh_expert_list)
        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        search_row.addWidget(self.expert_search, 1)
        layout.addLayout(search_row)
        self.archive_status.setWordWrap(True)
        layout.addWidget(self.archive_status)
        self.expert_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.expert_splitter.setChildrenCollapsible(False)
        self.expert_table = QTableWidget()
        self.expert_table.setColumnCount(3)
        self.expert_table.setHorizontalHeaderLabels(["专家", "邀请", "最近活动"])
        self.expert_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.expert_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.expert_table.setAlternatingRowColors(True)
        self.expert_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.expert_table.setMinimumWidth(240)
        self.expert_table.verticalHeader().hide()
        self.expert_table.setAccessibleName("专家目录")
        self.expert_table.setAccessibleDescription("选择一位专家后，在右侧查看简介、受邀院校和邀请历史。")
        expert_header = self.expert_table.horizontalHeader()
        expert_header.setStretchLastSection(False)
        expert_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        expert_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        expert_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.expert_table.itemSelectionChanged.connect(self._refresh_expert_detail)
        self.expert_splitter.addWidget(self.expert_table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 0, 0, 0)
        detail_layout.setSpacing(6)
        self.expert_name_label = QLabel("选择一位专家")
        self.expert_name_label.setObjectName("DashboardSectionTitle")
        self.expert_meta_label = QLabel("")
        self.expert_meta_label.setObjectName("DashboardSectionDescription")
        self.expert_meta_label.setWordWrap(True)
        self.expert_school_label = QLabel("")
        self.expert_school_label.setObjectName("DashboardStatus")
        self.expert_school_label.setWordWrap(True)
        self.expert_detail_tabs = QTabWidget()
        self.expert_detail_tabs.setObjectName("DashboardExpertDetailTabs")
        invitation_page = QWidget()
        invitation_layout = QVBoxLayout(invitation_page)
        invitation_layout.setContentsMargins(0, 6, 0, 0)
        invitation_layout.setSpacing(0)
        self.expert_invites = QTableWidget()
        self.expert_invites.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_invites.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.expert_invites.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.expert_invites.setAlternatingRowColors(True)
        self.expert_invites.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.expert_invites.verticalHeader().hide()
        self.expert_invites.cellClicked.connect(self._open_expert_invite_action)
        self.expert_invites.cellActivated.connect(self._open_expert_invite_action)
        self.expert_invites.setAccessibleName("专家邀请历史")
        self.expert_invites.setAccessibleDescription("在“审批详情”列单击或按 Enter 打开活动审批详情。")
        invitation_layout.addWidget(self.expert_invites)
        intro_page = QWidget()
        intro_layout = QVBoxLayout(intro_page)
        intro_layout.setContentsMargins(0, 6, 0, 0)
        intro_layout.setSpacing(0)
        self.expert_intro_label = QPlainTextEdit()
        self.expert_intro_label.setObjectName("DashboardExpertIntro")
        self.expert_intro_label.setReadOnly(True)
        self.expert_intro_label.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.expert_intro_label.setAccessibleName("专家简介")
        self.expert_intro_label.setAccessibleDescription("显示当前专家的全部简介版本，内容较长时可滚动查看。")
        intro_layout.addWidget(self.expert_intro_label)
        self.expert_detail_tabs.addTab(invitation_page, "邀请历史")
        self.expert_detail_tabs.addTab(intro_page, "专家简介")
        detail_layout.addWidget(self.expert_name_label)
        detail_layout.addWidget(self.expert_meta_label)
        detail_layout.addWidget(self.expert_school_label)
        detail_layout.addWidget(self.expert_detail_tabs, 1)
        self.expert_splitter.addWidget(detail)
        self.expert_splitter.setStretchFactor(0, 0)
        self.expert_splitter.setStretchFactor(1, 1)
        self.expert_splitter.setSizes([360, 720])
        self.expert_splitter.setMinimumHeight(340)
        layout.addWidget(self.expert_splitter, 1)
        page = _scroll_page(content)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return page

    def set_source_paths(self, application_path: str, reimbursement_path: str = "", supplementary_path: str = "") -> None:
        self.application_row.set_path(application_path)
        self.reimbursement_row.set_path(reimbursement_path)
        self.supplementary_row.set_path(supplementary_path)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        wide = self.window().width() >= 1100
        self._arrange_responsive_layout(wide)

    def _arrange_responsive_layout(self, wide: bool) -> None:
        if self._overview_wide == wide:
            return
        self._overview_wide = wide
        self.expert_splitter.setOrientation(Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical)
        self.expert_splitter.setMinimumHeight(340 if wide else 500)
        for widget in ((self.title_container,) if getattr(self,'_actions_pinned',False) else (self.title_container, self.action_container)):
            self.header_layout.removeWidget(widget)
        if getattr(self,'_actions_pinned',False):
            self.header_layout.addWidget(self.title_container, 0, 0, 1, 2)
        elif wide:
            self.header_layout.addWidget(self.title_container, 0, 0)
            self.header_layout.addWidget(
                self.action_container, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
            )
            self.use_cleaned_button.setText("使用最近整理结果")
        else:
            self.header_layout.addWidget(self.title_container, 0, 0, 1, 2)
            self.header_layout.addWidget(self.action_container, 1, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
            self.use_cleaned_button.setText("最近整理结果")
        self.month_filter_layout.removeWidget(self.month_filter_status)
        self.month_filter_layout.removeWidget(self.export_button)
        if wide:
            self.month_filter_layout.addWidget(self.month_filter_status, 0, 6)
            self.month_filter_layout.addWidget(self.export_button, 0, 7)
        else:
            self.month_filter_layout.addWidget(self.month_filter_status, 1, 0, 1, 7)
            self.month_filter_layout.addWidget(
                self.export_button, 1, 7, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

    def _configure_month_filter(self, preserve: bool = False) -> None:
        if not self.snapshot:
            self.month_filter_panel.hide()
            return
        months = [month for month in self.snapshot.months if month != "日期缺失"]
        selected_mode = self.month_mode_combo.currentIndex() if preserve else 0
        selected_start = self.month_start_combo.currentData() if preserve else None
        selected_end = self.month_end_combo.currentData() if preserve else None
        if preserve and selected_mode:
            months = sorted(set(months) | {m for m in (selected_start, selected_end) if m})
        self._setting_month_filter = True
        try:
            self.month_mode_combo.setCurrentIndex(selected_mode)
            for combo in (self.month_start_combo, self.month_end_combo):
                combo.clear()
                for month in months:
                    combo.addItem(_display_month(month), month)
            if months:
                self.month_start_combo.setCurrentIndex(0)
                self.month_end_combo.setCurrentIndex(len(months) - 1)
                for combo, value in ((self.month_start_combo, selected_start), (self.month_end_combo, selected_end)):
                    if value in months:
                        combo.setCurrentIndex(combo.findData(value))
        finally:
            self._setting_month_filter = False
        self.month_mode_combo.setEnabled(bool(months))
        self.month_start_combo.setEnabled(bool(months))
        self.month_end_combo.setEnabled(bool(months))
        self.month_filter_panel.show()
        self._update_month_filter_visibility()
        self._update_month_filter_status()

    def _update_month_filter_visibility(self) -> None:
        mode = self.month_mode_combo.currentData() or "all"
        has_months = self.month_start_combo.count() > 0
        show_start = has_months and mode in {"single", "range"}
        show_end = has_months and mode == "range"
        self.month_start_caption.setText("月份" if mode == "single" else "从")
        self.month_start_caption.setVisible(show_start)
        self.month_start_combo.setVisible(show_start)
        self.month_separator.setVisible(show_end)
        self.month_end_combo.setVisible(show_end)

    @staticmethod
    def _month_bounds(month: str) -> tuple[date, date]:
        year, number = (int(value) for value in month.split("-", 1))
        return date(year, number, 1), date(year, number, monthrange(year, number)[1])

    def _apply_month_filter(self, changed: str = "") -> None:
        if self._setting_month_filter or not self.snapshot:
            return
        self._update_month_filter_visibility()
        mode = self.month_mode_combo.currentData() or "all"
        filters = DashboardFilter()
        if mode in {"single", "range"} and self.month_start_combo.count():
            start_month = str(self.month_start_combo.currentData())
            end_month = start_month if mode == "single" else str(self.month_end_combo.currentData())
            if start_month > end_month:
                self._setting_month_filter = True
                try:
                    if changed == "end":
                        start_month = end_month
                        self.month_start_combo.setCurrentIndex(self.month_start_combo.findData(start_month))
                    else:
                        end_month = start_month
                        self.month_end_combo.setCurrentIndex(self.month_end_combo.findData(end_month))
                finally:
                    self._setting_month_filter = False
            start_date, _ = self._month_bounds(start_month)
            _, end_date = self._month_bounds(end_month)
            filters = DashboardFilter(start_date=start_date, end_date=end_date)
        self.view = filter_dashboard_snapshot(self.snapshot, filters)
        self._reset_topic_drills()
        self._populate_snapshot()
        self._update_month_filter_status()

    def _update_month_filter_status(self) -> None:
        if not self.snapshot or not self.view:
            self.month_filter_status.clear()
            return
        mode = self.month_mode_combo.currentData() or "all"
        if not self.month_start_combo.count():
            period = "没有可识别的活动月份"
        elif mode == "single":
            period = _display_month(str(self.month_start_combo.currentData()))
        elif mode == "range":
            start = _display_month(str(self.month_start_combo.currentData()))
            end = _display_month(str(self.month_end_combo.currentData()))
            period = f"{start}—{end}"
        else:
            valid_months = [month for month in self.snapshot.months if month != "日期缺失"]
            period = (
                f"全部 · {_display_month(valid_months[0])}—{_display_month(valid_months[-1])}"
                if valid_months
                else "全部月份"
            )
        missing = sum(activity.start_date is None for activity in self.view.activities)
        missing_note = f" · 含 {missing:,} 条日期缺失" if missing else ""
        self.month_filter_status.setText(f"当前：{period} · {self.view.activity_count:,} 项活动{missing_note}")
        self.month_filter_status.setToolTip("月份按活动开始日归属；月份区间包含起止月份。")

    def _reset_topic_drills(self) -> None:
        self._activity_drill_school = None
        self._activity_drill_month = None
        self._coverage_school = None
        self._coverage_month = None
        self._type_drill_type = None
        for bar in (self.activity_drill_bar, self.coverage_drill_bar, self.type_drill_bar):
            bar.clear_state()
        for chart, toggle in (
            (self.school_chart, self.school_chart_view),
            (self.coverage_chart, self.coverage_chart_view),
        ):
            chart.clear_selection()
            toggle.clear_selection_feedback()

    def _set_source_expanded(self, expanded: bool = True) -> None:
        can_collapse = self.snapshot is not None
        expanded = bool(expanded or not can_collapse)
        self.source_expanded_content.setVisible(expanded)
        self.source_summary_label.setVisible(not expanded and can_collapse)
        self.source_toggle_button.setVisible(can_collapse)
        self.source_toggle_button.setText("收起来源" if expanded else "更换数据")
        self.source_toggle_button.setAccessibleDescription(
            "收起活动数据与报销文件选择区。"
            if expanded
            else "展开活动数据与报销文件选择区。"
        )
        if can_collapse:
            source_label = "原始审批 · 活动申请 + 活动报销" if self.snapshot.source_kind == "raw" else "整理结果"
            if self.snapshot.source_supplementary_path:
                source_label += " + 补充表格"
            summary = f"{source_label} · 截至 {self.snapshot.as_of_date.isoformat()}"
            self.source_summary_label.setText(summary)
            files = [Path(self.snapshot.source_application_path).name]
            if self.snapshot.source_reimbursement_path:
                files.append(Path(self.snapshot.source_reimbursement_path).name)
            if self.snapshot.source_supplementary_path:
                files.append(Path(self.snapshot.source_supplementary_path).name)
            self.source_summary_label.setToolTip("\n".join(files))
        self.use_cleaned_button.show()

    def _on_source_changed(self) -> None:
        self._update_refresh_enabled()
        if not self.snapshot:
            return
        current = (self.application_row.path, self.reimbursement_row.path, self.supplementary_row.path)
        if current != self._loaded_source_paths:
            self._set_source_expanded(True)
            self.status_label.setText("数据来源已更改。点击“更新看板”应用新数据；当前仍显示上一次结果。")

    @Slot()
    def _use_last_cleaned_result(self) -> None:
        path = str(self.last_cleaned_path_provider() or "").strip()
        if not path or not Path(path).is_file():
            self.show_information("暂无整理结果", "请先在“数据整理”完成一次处理，或手动选择已有输出表。")
            return
        self.application_row.set_path(path)
        self.status_label.setText("已带入最近完成的整理结果；可直接生成看板。")

    @Slot()
    def refresh_dashboard(self) -> None:
        if self._loading or self._exporting:
            return
        application = self.application_row.path
        reimbursement = self.reimbursement_row.path
        supplementary = self.supplementary_row.path
        if not application:
            self.show_information("请选择文件", "请先选择活动申请表或数据整理结果。")
            return
        try:
            source_kind = detect_activity_source_kind(application)
        except Exception as exc:
            self.show_warning("活动数据无法识别", str(exc))
            return
        if source_kind == "raw" and not reimbursement:
            self.show_information("请选择活动报销", "原始活动申请模式需要同时选择活动报销 Excel。")
            return
        missing = [path for path in (application, reimbursement, supplementary) if path and not Path(path).is_file()]
        if missing:
            self.show_warning("文件不存在", "找不到以下文件：\n" + "\n".join(missing))
            return
        self._loading = True
        self._load_request_id += 1
        request_id = self._load_request_id
        self.task_begin()
        self.refresh_button.setEnabled(False)
        self.use_cleaned_button.setEnabled(False)
        self.refresh_button.setText("解析中…")
        self.cancel_button.show()
        self.status_label.setText("正在读取活动数据并关联报销记录…")
        if not self.snapshot:
            self.content_stack.setCurrentWidget(self.loading_state)

        def work() -> None:
            try:
                result = build_dashboard_snapshot(application, reimbursement or None, self.state_store, supplementary or None)
                self._signals.loaded.emit((request_id, result))
            except Exception as exc:  # GUI 边界需要把用户文件错误转为可读状态。
                self._signals.failed.emit((request_id, str(exc)))

        threading.Thread(target=work, name="dashboard-loader", daemon=True).start()

    @Slot(object)
    def _on_loaded(self, payload: object, *, restoring: bool = False) -> None:
        request_id, snapshot = payload if isinstance(payload, tuple) else (self._load_request_id, payload)
        if request_id != self._load_request_id:
            return
        self._load_error = ""
        preserve_months = getattr(self, '_loaded_source_paths', None) == (
            snapshot.source_application_path, snapshot.source_reimbursement_path,
            snapshot.source_supplementary_path)
        self.snapshot = snapshot
        self.metric_row.show()
        self._loaded_source_paths = (
            snapshot.source_application_path,
            snapshot.source_reimbursement_path,
            snapshot.source_supplementary_path,
        )
        self._loading = False
        if not restoring:
            self.task_end()
        self.refresh_button.setText("更新看板" if self.snapshot else "生成看板")
        self.cancel_button.hide()
        self._update_refresh_enabled()
        self.content_stack.setCurrentWidget(self.tabs)
        self.view = filter_dashboard_snapshot(snapshot, DashboardFilter())
        self._reset_topic_drills()
        self._configure_month_filter(preserve=preserve_months)
        self._configure_expert_sources()
        self.tabs.setTabEnabled(3, snapshot.supports_reimbursement)
        self.tabs.setTabEnabled(4, snapshot.supports_experts)
        self.tabs.setTabToolTip(3, "" if snapshot.supports_reimbursement else "整理结果不包含报销审批关联")
        self.tabs.setTabToolTip(
            4,
            "整理结果不含专家字段，当前显示自动保存在本机的专家库。"
            if snapshot.source_kind == "cleaned"
            else "",
        )
        if not self.tabs.isTabEnabled(self.tabs.currentIndex()):
            self.tabs.setCurrentIndex(0)
        self._apply_month_filter()
        self._set_source_expanded(False)
        self._update_refresh_enabled()
        if not restoring:
            try:
                self.state_store.save_snapshot(snapshot)
            except Exception as exc:
                self.status_label.setText(f"看板已更新，但自动保存失败，下次启动可能无法恢复本次数据。原因：{exc}")

    @Slot(object)
    def _on_failed(self, payload: object) -> None:
        request_id, message = payload if isinstance(payload, tuple) else (self._load_request_id, str(payload))
        if request_id != self._load_request_id:
            return
        self._load_error = message
        self._loading = False
        self.task_end()
        self.cancel_button.hide()
        self.refresh_button.setText("更新看板" if self.snapshot else "生成看板")
        self._update_refresh_enabled()
        if self.snapshot:
            self.content_stack.setCurrentWidget(self.tabs)
            self.status_label.setText("看板更新失败，已保留上一次结果。原因：" + message)
        else:
            self.content_stack.setCurrentWidget(self.empty_state)
            self.status_label.setText("加载失败：" + message + "；请核对文件后重试。")
        self._set_source_expanded(True)

    @Slot()
    def cancel_refresh(self) -> None:
        if not self._loading:
            return
        self._load_request_id += 1
        self._loading = False
        self.task_end()
        self.cancel_button.hide()
        self.refresh_button.setText("更新看板" if self.snapshot else "生成看板")
        self._update_refresh_enabled()
        self.content_stack.setCurrentWidget(self.tabs if self.snapshot else self.empty_state)
        self.status_label.setText("已取消本次更新，当前看板保持不变。本次后台结果不会应用。")

    def _update_refresh_enabled(self) -> None:
        busy = self._loading or self._exporting
        self.refresh_button.setEnabled(bool(self.application_row.path) and not busy)
        self.use_cleaned_button.setEnabled(not busy)
        self.export_button.setEnabled(bool(self.snapshot and self.view) and not busy)

    def _export_default_path(self) -> Path:
        snapshot = self.snapshot
        view = self.view
        base_dir = Path(snapshot.source_application_path).resolve().parent if snapshot else Path.home()
        start = view.filters.start_date if view else None
        end = view.filters.end_date if view else None
        if start and end and (start.year, start.month) == (end.year, end.month):
            period = f"{start.year:04d}-{start.month:02d}"
        elif start and end:
            period = f"{start.year:04d}-{start.month:02d}_至_{end.year:04d}-{end.month:02d}"
        else:
            period = "全部月份"
        return base_dir / f"数据看板重点数据_{period}.xlsx"

    @Slot()
    def _export_dashboard_excel(self) -> None:
        if self._loading or self._exporting or not self.snapshot or not self.view:
            return
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "导出重点数据",
            str(self._export_default_path()),
            "Excel 工作簿 (*.xlsx)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")

        snapshot = self.snapshot
        view = self.view
        self._exporting = True
        self.task_begin()
        self.export_button.setText("导出中…")
        self.status_label.setText("正在生成重点汇总 Excel；专家库将使用本机全量资料…")
        self._update_refresh_enabled()

        def work() -> None:
            try:
                experts = self.state_store.load_archived_experts()
                if not experts:
                    experts = snapshot.experts
                result = export_dashboard_view_xlsx(
                    snapshot,
                    view,
                    output_path,
                    expert_profiles=experts,
                )
                self._signals.exported.emit(str(result))
            except Exception as exc:
                self._signals.export_failed.emit(str(exc))

        threading.Thread(target=work, name="dashboard-excel-export", daemon=True).start()

    @Slot(object)
    def _on_exported(self, output_path: object) -> None:
        self._exporting = False
        self.task_end()
        self.export_button.setText("导出重点数据…")
        self._update_refresh_enabled()
        path = Path(str(output_path))
        self.status_label.setText(f"重点数据已导出：{path.name}")
        self.show_information(
            "导出完成",
            f"重点汇总已保存到：\n{path}\n\n院校、月份、活动类型和覆盖人次按当前时间段导出；专家库为本机全量。",
        )

    @Slot(object)
    def _on_export_failed(self, message: object) -> None:
        self._exporting = False
        self.task_end()
        self.export_button.setText("导出重点数据…")
        self._update_refresh_enabled()
        self.status_label.setText("导出失败，当前看板数据未受影响。")
        self.show_critical("重点数据导出失败", str(message))

    def _populate_snapshot(self) -> None:
        snapshot = self.snapshot
        view = self.view
        if not snapshot or not view:
            return
        colors = self.palette_provider()
        self.metrics["activities"].set_value(view.activity_count)
        self.metrics["schools"].set_value(view.school_count)
        self.metrics["teachers"].set_value(view.teacher_total)
        self.metrics["students"].set_value(view.student_total)
        source_label = "原始审批" if snapshot.source_kind == "raw" else "整理结果"
        reimbursement_note = (
            f" · 未完成报销 {len(view.unreimbursed):,} 项" if snapshot.supports_reimbursement else ""
        )
        self.status_label.setText(
            f"{source_label}已刷新 · 截至 {snapshot.as_of_date.isoformat()}"
            f"{reimbursement_note} · 人工排除 {view.excluded_teacher_records + view.excluded_student_records:,} 条"
        )
        if self._load_error:
            self.status_label.setText("看板更新失败，已保留上一次结果。原因：" + self._load_error)
        self.quality_summary_label.setText(f"数据质量提示 {snapshot.quality.total_issues:,} 项")
        self.quality_summary_label.show()
        schools = sorted(view.school_counts, key=lambda key: (-view.school_counts[key], key))
        self.school_chart.set_palette(colors)
        self.school_chart.set_data(view.school_counts, "", "活动数")
        self.school_chart_view.set_table_data(
            ["院校", "活动数"],
            [(school, _fmt_number(view.school_counts[school])) for school in schools],
        )
        self.school_month_heatmap.set_palette(colors)
        self.school_month_heatmap.set_matrix(schools, view.months, view.school_month_counts)
        self._show_activity_detail()

        types = sorted({activity_type for values in view.school_type_counts.values() for activity_type in values})
        self.school_type_heatmap.set_palette(colors)
        self.school_type_heatmap.set_matrix(schools, types, view.school_type_counts)
        self.type_school_combo.blockSignals(True)
        current_school = self.type_school_combo.currentText()
        self.type_school_combo.clear()
        self.type_school_combo.addItems(schools)
        if current_school in schools:
            self.type_school_combo.setCurrentText(current_school)
        self.type_school_combo.blockSignals(False)
        self._refresh_type_school_view()

        self.coverage_chart.set_palette(colors)
        self.coverage_heatmap.set_palette(colors)
        self._refresh_coverage()
        self._refresh_unreimbursed()
        self._refresh_expert_source()
        self._update_month_filter_status()

    def _show_activity_detail(self, school: Optional[str] = None, month: Optional[str] = None) -> None:
        if not self.view:
            return
        if school is not None:
            self._activity_drill_school = school
            self._activity_drill_month = month
        records = [
            item
            for item in self.view.activities
            if (not self._activity_drill_school or item.school == self._activity_drill_school)
            and (not self._activity_drill_month or item.month == self._activity_drill_month)
        ]
        self.activity_detail.set_records(records)
        if self._activity_drill_school:
            parts = [self._activity_drill_school]
            if self._activity_drill_month:
                parts.append(_display_month(self._activity_drill_month))
            self.activity_drill_bar.show_state(f"当前查看：{' × '.join(parts)} · {len(records):,} 条活动")
        else:
            self.activity_drill_bar.clear_state()

    def _clear_activity_drill(self) -> None:
        self._activity_drill_school = None
        self._activity_drill_month = None
        self.school_chart.clear_selection()
        self.school_chart_view.clear_selection_feedback()
        self._show_activity_detail()

    def _show_type_detail(self, school: str, activity_type: str) -> None:
        if not self.view:
            return
        self.type_school_combo.blockSignals(True)
        self.type_school_combo.setCurrentText(school)
        self.type_school_combo.blockSignals(False)
        self._type_drill_type = activity_type
        self._update_type_school_matrix(school)
        records = [item for item in self.view.activities if item.school == school and activity_type in item.activity_types]
        self.type_detail.set_records(records)
        self.type_drill_bar.show_state(f"当前查看：{school} × {activity_type} · {len(records):,} 条活动")

    def _refresh_type_school_view(self) -> None:
        if not self.view:
            return
        school = self.type_school_combo.currentText()
        self._type_drill_type = None
        self._update_type_school_matrix(school)
        records = [item for item in self.view.activities if item.school == school]
        self.type_detail.set_records(records)
        self.type_drill_bar.clear_state()

    def _update_type_school_matrix(self, school: str) -> None:
        if not self.view:
            return
        month_map = self.view.school_month_type_counts.get(school, {})
        types = sorted({activity_type for values in month_map.values() for activity_type in values})
        values = {month: month_map.get(month, {}) for month in self.view.months}
        self.month_type_heatmap.set_palette(self.palette_provider())
        self.month_type_heatmap.set_matrix(self.view.months, types, values)

    def _show_month_type_detail(self, month: str, activity_type: str) -> None:
        if not self.view:
            return
        school = self.type_school_combo.currentText()
        self._type_drill_type = activity_type
        records = [
            item
            for item in self.view.activities
            if item.school == school and item.month == month and activity_type in item.activity_types
        ]
        self.type_detail.set_records(records)
        self.type_drill_bar.show_state(
            f"当前查看：{school} × {_display_month(month)} × {activity_type} · {len(records):,} 条活动"
        )

    def _clear_type_drill(self) -> None:
        self._type_drill_type = None
        self._refresh_type_school_view()

    def _clear_coverage_drill(self) -> None:
        self._coverage_school = None
        self._coverage_month = None
        self.coverage_drill_bar.clear_state()
        self._refresh_coverage_detail()

    def _set_coverage_metric(self, metric: str) -> None:
        self._coverage_metric = metric
        self._coverage_school = None
        self._coverage_month = None
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        if not self.view:
            return
        teacher = self._coverage_metric == "teacher"
        label = "教师" if teacher else "学生"
        by_school = self.view.teacher_by_school if teacher else self.view.student_by_school
        by_month = self.view.teacher_by_school_month if teacher else self.view.student_by_school_month
        schools = sorted(by_school, key=lambda key: (-by_school[key], key))
        self.coverage_chart.set_data(by_school, f"院校计划{label}人次排名", "人次")
        self.coverage_chart_view.set_table_data(
            ["院校", f"计划{label}人次"],
            [(school, _fmt_number(by_school[school])) for school in schools],
        )
        self.coverage_heatmap.set_matrix(schools, self.view.months, by_month, number_suffix="")
        self._refresh_coverage_detail()

    def _coverage_school_selected(self, school: str) -> None:
        self._coverage_school = school
        self._coverage_month = None
        self._refresh_coverage_detail()

    def _coverage_cell_selected(self, school: str, month: str) -> None:
        self._coverage_school = school
        self._coverage_month = month
        self._refresh_coverage_detail()

    def _refresh_coverage_detail(self) -> None:
        if not self.view:
            return
        metric = self._coverage_metric
        records = [
            item
            for item in self.view.activities
            if not item.is_supplementary and (not self._coverage_school or item.school == self._coverage_school)
            and (not self._coverage_month or item.month == self._coverage_month)
        ]
        filter_mode = self.coverage_record_filter.currentText()
        if filter_mode != "全部记录":
            want_excluded = filter_mode == "仅已排除"
            records = [
                item
                for item in records
                if (item.teacher_excluded if metric == "teacher" else item.student_excluded) == want_excluded
            ]
        self._coverage_rows = records
        self.coverage_detail.setRowCount(len(records))
        for row, record in enumerate(records):
            value = record.teacher_count if metric == "teacher" else record.student_count
            excluded = record.teacher_excluded if metric == "teacher" else record.student_excluded
            values = (
                record.approval_id,
                record.school,
                record.activity_name,
                _fmt_date(record.start_date),
                "教师" if metric == "teacher" else "学生",
                _fmt_number(value),
            )
            for column, value_text in enumerate(values):
                self.coverage_detail.setItem(row, column, _table_item(value_text))
            check = QCheckBox()
            check.setChecked(excluded)
            check.setAccessibleName(f"{record.activity_name} 异常排除")
            check.toggled.connect(
                lambda checked, approval_id=record.approval_id, current_metric=metric: self._set_coverage_excluded(
                    approval_id, current_metric, checked
                )
            )
            check_box = QWidget()
            check_layout = QHBoxLayout(check_box)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.addWidget(check, 0, Qt.AlignmentFlag.AlignCenter)
            self.coverage_detail.setCellWidget(row, 6, check_box)
            self.coverage_detail.setItem(row, 7, _table_item("已排除" if excluded else "已纳入"))
            self.coverage_detail.setItem(row, 8, _table_item("打开" if record.detail_url else "无链接"))
        self.coverage_detail.resizeColumnsToContents()
        self.coverage_detail.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        if self._coverage_school:
            parts = [self._coverage_school]
            if self._coverage_month:
                parts.append(_display_month(self._coverage_month))
            metric_label = "教师" if metric == "teacher" else "学生"
            self.coverage_drill_bar.show_state(
                f"当前查看：{' × '.join(parts)} · {metric_label} · {len(records):,} 条记录"
            )
        else:
            self.coverage_drill_bar.clear_state()

    def _set_coverage_excluded(self, approval_id: str, metric: str, excluded: bool) -> None:
        self.state_store.set_coverage_excluded(approval_id, metric, excluded)
        self.status_label.setText("已保存人工异常标记，正在刷新汇总…")
        self.refresh_dashboard()

    def _open_coverage_action(self, row: int, column: int) -> None:
        if column == 8 and 0 <= row < len(getattr(self, "_coverage_rows", [])):
            _open_url(self._coverage_rows[row].detail_url, self, self.show_information)

    def _refresh_unreimbursed(self) -> None:
        if not self.view:
            return
        query = self.unreim_search.text().strip().casefold()
        state = self.unreim_state_combo.currentText()
        records = [
            item
            for item in self.view.unreimbursed
            if (state == "全部状态" or item.business_state == state)
            and (
                not query
                or query in item.approval_id.casefold()
                or query in item.school.casefold()
                or query in item.activity_name.casefold()
            )
        ]
        self._unreim_rows = records
        self.unreim_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.approval_id,
                record.school,
                record.activity_name,
                " / ".join(record.activity_types),
                _fmt_date(record.start_date),
                _fmt_date(record.end_date),
                f"{record.days_since_end} 天" if record.days_since_end is not None else "暂无",
                record.business_state,
                "打开审批",
            )
            for column, value in enumerate(values):
                item = _table_item(value)
                if column == 7:
                    item.setData(Qt.ItemDataRole.UserRole, record.business_state)
                self.unreim_table.setItem(row, column, item)
        self.unreim_table.resizeColumnsToContents()
        self.unreim_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.unreim_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.unreim_result_label.setText(
            f"当前文件共 {len(self.view.unreimbursed):,} 项未完成报销 · 当前列表 {len(records):,} 项"
        )

    def _open_unreimbursed_action(self, row: int, column: int) -> None:
        if column == 8 and 0 <= row < len(getattr(self, "_unreim_rows", [])):
            _open_url(self._unreim_rows[row].detail_url, self, self.show_information)

    def _configure_expert_sources(self) -> None:
        if not self.snapshot:
            return
        self.expert_source_combo.blockSignals(True)
        try:
            self.expert_source_combo.clear()
            if self.snapshot.source_kind == "cleaned":
                self.expert_source_combo.addItem("本地专家库", "local")
                self.expert_source_combo.setEnabled(False)
            else:
                self.expert_source_combo.addItem("当前文件", "current")
                self.expert_source_combo.addItem("本地专家库", "local")
                self.expert_source_combo.setEnabled(True)
            self.expert_source_combo.setCurrentIndex(0)
        finally:
            self.expert_source_combo.blockSignals(False)
        self.archive_button.hide()

    def _refresh_expert_source(self) -> None:
        if not self.snapshot or not self.view:
            return
        local_library = self.expert_source_combo.currentData() == "local" or self.snapshot.source_kind == "cleaned"
        source_profiles = self.state_store.load_archived_experts() if local_library else self.view.experts
        # 清洗模式的快照已从同一个本地库读取；保留该副本可兼容独立构建快照的调用方。
        if local_library and not source_profiles and self.snapshot.source_kind == "cleaned":
            source_profiles = self.view.experts
        self._expert_profiles = self._filter_expert_profiles(source_profiles) if local_library else source_profiles
        batches = self.state_store.archive_batches()
        if local_library:
            prefix = "整理结果不含专家字段 · " if self.snapshot.source_kind == "cleaned" else ""
            self.archive_status.setText(
                f"{prefix}本地专家库 {len(self._expert_profiles):,} 位 · {len(batches):,} 次数据更新"
            )
        else:
            sync = self.snapshot.expert_sync
            if sync is None:
                sync_note = "当前文件无可同步专家记录"
            elif sync.duplicate_batch or sync.imported_invitations == 0:
                sync_note = "已自动比对本地库 · 无新增邀请"
            else:
                sync_note = f"已自动加入本地库 · 新增 {sync.imported_invitations:,} 条邀请"
            self.archive_status.setText(f"当前文件 {len(self._expert_profiles):,} 位专家 · {sync_note}")
        self.archive_button.hide()
        self._refresh_expert_list()

    def _filter_expert_profiles(self, profiles: Sequence[ExpertProfile]) -> tuple[ExpertProfile, ...]:
        return tuple(sorted(profiles, key=lambda item: (-item.invitation_count, item.expert_name)))

    def _refresh_expert_list(self) -> None:
        query = self.expert_search.text().strip().casefold()
        profiles = [
            profile
            for profile in self._expert_profiles
            if not query
            or query in profile.expert_name.casefold()
            or any(query in intro.casefold() for intro in profile.intros)
            or any(query in school.casefold() for school in profile.schools)
            or any(query in activity_type.casefold() for activity_type in profile.activity_types)
        ]
        self._visible_experts = profiles
        self.expert_table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            flag = "简介冲突" if profile.has_intro_conflict else ("待核对" if profile.needs_review else "正常")
            values = (
                profile.expert_name,
                _fmt_number(profile.invitation_count),
                _fmt_date(profile.latest_event_date),
            )
            tooltip = f"受邀院校：{'\u3001'.join(profile.schools) or '暂无'}\n记录状态：{flag}"
            for column, value in enumerate(values):
                item = _table_item(value, data=profile.normalized_name if column == 0 else None)
                item.setToolTip(tooltip)
                self.expert_table.setItem(row, column, item)
        if profiles:
            self.expert_table.selectRow(0)
        else:
            local_library = self.expert_source_combo.currentData() == "local" or (
                self.snapshot is not None and self.snapshot.source_kind == "cleaned"
            )
            self.expert_name_label.setText("本地专家库暂无数据" if local_library and not query else "没有匹配的专家")
            self.expert_meta_label.setText(
                "导入一次包含专家信息的原始活动申请后，系统会自动增量保存。"
                if local_library and not query
                else ""
            )
            self.expert_school_label.clear()
            self.expert_intro_label.clear()
            self.expert_detail_tabs.setTabText(0, "邀请历史")
            self.expert_detail_tabs.setTabText(1, "专家简介")
            self.expert_invites.setRowCount(0)

    def _selected_expert(self) -> Optional[ExpertProfile]:
        rows = self.expert_table.selectionModel().selectedRows() if self.expert_table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        return self._visible_experts[row] if 0 <= row < len(getattr(self, "_visible_experts", [])) else None

    def _refresh_expert_detail(self) -> None:
        profile = self._selected_expert()
        if not profile:
            return
        self.expert_name_label.setText(profile.expert_name)
        flags = []
        if profile.has_intro_conflict:
            flags.append(f"{len(profile.intros)} 个简介版本")
        if profile.needs_review:
            flags.append("姓名拆分待核对")
        self.expert_meta_label.setText(
            f"邀请 {profile.invitation_count:,} 次 · 受邀院校 {len(profile.schools):,} 所"
            + (" · " + " / ".join(flags) if flags else "")
        )
        schools_text = "受邀院校：" + ("、".join(profile.schools) if profile.schools else "暂无")
        self.expert_school_label.setText(schools_text)
        self.expert_school_label.setToolTip(schools_text)
        self.expert_intro_label.setPlainText(
            "\n\n".join(f"简介 {index + 1}：{intro}" for index, intro in enumerate(profile.intros))
            if profile.intros
            else "暂无专家简介。"
        )
        self.expert_intro_label.verticalScrollBar().setValue(0)
        self.expert_detail_tabs.setTabText(0, f"邀请历史 · {len(profile.invitations):,}")
        self.expert_detail_tabs.setTabText(1, f"专家简介 · {len(profile.intros):,}")
        show_fee = self.expert_fee_check.isChecked()
        headers = ["日期", "邀请院校", "活动名称", "活动类型", "核对", "审批详情"]
        if show_fee:
            headers.insert(4, "原始专家费")
        self.expert_invites.setColumnCount(len(headers))
        self.expert_invites.setHorizontalHeaderLabels(headers)
        self._expert_invite_rows = list(profile.invitations)
        self.expert_invites.setRowCount(len(profile.invitations))
        for row, invite in enumerate(profile.invitations):
            values = [
                _fmt_date(invite.event_date),
                invite.school,
                invite.activity_name,
                " / ".join(invite.activity_types),
            ]
            if show_fee:
                if invite.fee_amount is None:
                    fee = "暂无"
                else:
                    fee = f"¥{_fmt_number(invite.fee_amount)}" + ("（多人共用）" if invite.fee_shared else "")
                values.append(fee)
            values.append("待核对" if invite.needs_review else "正常")
            values.append("打开" if invite.detail_url else "无链接")
            for column, value in enumerate(values):
                self.expert_invites.setItem(row, column, _table_item(value))
        self.expert_invites.resizeColumnsToContents()
        invite_header = self.expert_invites.horizontalHeader()
        if len(headers) >= 4:
            invite_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            invite_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            invite_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            invite_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            invite_header.setSectionResizeMode(len(headers) - 2, QHeaderView.ResizeMode.ResizeToContents)
            invite_header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.ResizeToContents)

        self._expert_action_column = len(headers) - 1

    def _open_expert_invite_action(self, row: int, column: int) -> None:
        if column == getattr(self, "_expert_action_column", -1) and 0 <= row < len(
            getattr(self, "_expert_invite_rows", [])
        ):
            _open_url(self._expert_invite_rows[row].detail_url, self, self.show_information)

    def _archive_current_experts(self) -> None:
        if not self.snapshot or not self.snapshot.experts:
            return
        answer = self.ask_confirmation(
            "归档专家数据",
            "归档会把当前文件中的专家简介与邀请记录写入本地历史库。重复归档同一文件不会重复累计。是否继续？",
        )
        if not answer:
            return
        try:
            result = self.state_store.archive_experts(self.snapshot.experts, self.snapshot.source_application_path)
        except Exception as exc:
            self.show_critical("归档失败", str(exc))
            return
        if result.duplicate_batch:
            self.archive_status.setText("这份活动申请文件已归档，本次未重复写入。")
        else:
            self.archive_status.setText(f"归档完成：新增 {result.imported_invitations:,} 条专家邀请记录。")

    def apply_theme(self, colors: Optional[dict[str, str]] = None) -> None:
        p = {**DEFAULT_PALETTE, **(colors or {})}
        dark = QColor(p["canvas"]).lightness() < 128
        scroll_groove = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.07)"
        scroll_handle = "rgba(255,255,255,0.22)" if dark else "rgba(0,0,0,0.20)"
        scroll_handle_hover = "rgba(255,255,255,0.36)" if dark else "rgba(0,0,0,0.34)"
        self.setStyleSheet(
            f"""
            QLabel#DashboardSectionDescription,
            QLabel#DashboardEmptyText {{ color: {p['muted']}; }}
            QLabel#DashboardSectionTitle, QLabel#DashboardEmptyTitle {{ font-size: 11pt; font-weight: 600; }}
            QLabel#DashboardMetricLabel {{ color: {p['muted']}; font-size: 9pt; }}
            QLabel#DashboardMetricValue {{ font-size: 21px; font-weight: 700; }}
            QLabel#DashboardStatus {{ color: {p['muted']}; font-size: 9pt; }}
            QLabel#DashboardSourceSummary {{ color: {p['text']}; font-size: 10pt; font-weight: 600; }}
            QLabel#DashboardChartSelection {{ background: {p['focus']}; color: {p['on_focus']}; border: none; border-radius: 7px; padding: 6px 10px; font-size: 9pt; font-weight: 600; }}
            QLabel#DashboardQuality {{ color: {p['warning']}; font-weight: 600; }}
            QWidget#DashboardMetric {{ background: transparent; }}
            QPushButton#DashboardSegmented {{ min-height: 34px; padding: 0 12px; border-radius: 7px; border: 1px solid rgba(198,198,198,0.22); background: {p['panel']}; color: {p['text']}; font-size: 9pt; font-weight: 600; }}
            QPushButton#DashboardSegmented:hover {{ border-color: {p['outline']}; background: {p['panel_alt']}; }}
            QPushButton#DashboardSegmented:checked {{ background: {p['surface_high']}; color: {p['text']}; border-color: {p['outline']}; }}
            QPushButton#DashboardSegmented:focus {{ border: 2px solid {p['focus']}; }}
            QTabWidget#DashboardTabs::pane {{ border: 1px solid rgba(198,198,198,0.20); border-radius: 10px; background: {p['panel']}; }}
            QTabWidget#DashboardTabs QTabBar::tab {{ background: {p['panel_alt']}; color: {p['text']}; padding: 9px 16px; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; font-size: 10pt; font-weight: 600; }}
            QTabWidget#DashboardTabs QTabBar::tab:selected {{ background: {p['panel']}; color: {p['text']}; }}
            QTabWidget#DashboardTabs QTabBar::tab:focus {{ border: 2px solid {p['focus']}; }}
            QTabWidget#DashboardExpertDetailTabs::pane {{ border: none; background: transparent; }}
            QTabWidget#DashboardExpertDetailTabs QTabBar::tab {{ background: {p['panel_alt']}; color: {p['text']}; padding: 6px 12px; border-radius: 6px; margin-right: 4px; font-size: 9pt; font-weight: 600; }}
            QTabWidget#DashboardExpertDetailTabs QTabBar::tab:selected {{ background: {p['surface_high']}; color: {p['text']}; }}
            QTabWidget#DashboardExpertDetailTabs QTabBar::tab:focus {{ border: 2px solid {p['focus']}; }}
            QTableWidget {{ background: {p['panel']}; alternate-background-color: {p['panel_alt']}; border: 1px solid rgba(198,198,198,0.20); border-radius: 8px; gridline-color: {p['outline']}; selection-background-color: {p['surface_high']}; selection-color: {p['text']}; }}
            QTableWidget:focus {{ border: 2px solid {p['focus']}; }}
            QPlainTextEdit#DashboardExpertIntro {{ background: {p['panel_alt']}; color: {p['text']}; border: 1px solid rgba(198,198,198,0.20); border-radius: 8px; padding: 7px 9px; selection-background-color: {p['surface_high']}; selection-color: {p['text']}; }}
            QPlainTextEdit#DashboardExpertIntro:focus {{ border: 2px solid {p['focus']}; }}
            QHeaderView::section {{ background: {p['panel_alt']}; color: {p['text']}; border: none; border-bottom: 1px solid {p['outline']}; padding: 8px 10px; font-weight: 700; }}
            QSplitter::handle {{ background: {p['outline']}; width: 1px; }}
            QScrollArea, QScrollArea#DashboardScroll,
            QWidget#DashboardScrollViewport, QWidget#DashboardScrollContent {{ background: transparent; border: none; }}
            QScrollArea#DashboardScroll QScrollBar:vertical,
            QTableWidget QScrollBar:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar:vertical {{
                width: 5px; background: transparent; margin: 0px 1px 0px 0px; border: none;
            }}
            QScrollArea#DashboardScroll QScrollBar::groove:vertical,
            QTableWidget QScrollBar::groove:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::groove:vertical {{
                background: {scroll_groove}; border-radius: 2px; width: 3px; margin: 4px 1px;
            }}
            QScrollArea#DashboardScroll QScrollBar::handle:vertical,
            QTableWidget QScrollBar::handle:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::handle:vertical {{
                background: {scroll_handle}; border-radius: 2px; min-height: 28px; margin: 0px 1px; max-width: 3px;
            }}
            QScrollArea#DashboardScroll QScrollBar::handle:vertical:hover,
            QTableWidget QScrollBar::handle:vertical:hover,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::handle:vertical:hover {{ background: {scroll_handle_hover}; }}
            QScrollArea#DashboardScroll QScrollBar::add-line:vertical,
            QScrollArea#DashboardScroll QScrollBar::sub-line:vertical,
            QTableWidget QScrollBar::add-line:vertical,
            QTableWidget QScrollBar::sub-line:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::add-line:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::sub-line:vertical {{
                height: 0px; width: 0px; border: none; background: transparent;
            }}
            QScrollArea#DashboardScroll QScrollBar::add-page:vertical,
            QScrollArea#DashboardScroll QScrollBar::sub-page:vertical,
            QTableWidget QScrollBar::add-page:vertical,
            QTableWidget QScrollBar::sub-page:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::add-page:vertical,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollArea#DashboardScroll QScrollBar:horizontal,
            QTableWidget QScrollBar:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar:horizontal {{
                height: 5px; background: transparent; margin: 0px 0px 1px 0px; border: none;
            }}
            QScrollArea#DashboardScroll QScrollBar::groove:horizontal,
            QTableWidget QScrollBar::groove:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::groove:horizontal {{
                background: {scroll_groove}; border-radius: 2px; height: 3px; margin: 1px 4px;
            }}
            QScrollArea#DashboardScroll QScrollBar::handle:horizontal,
            QTableWidget QScrollBar::handle:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::handle:horizontal {{
                background: {scroll_handle}; border-radius: 2px; min-width: 28px; margin: 1px 0px; max-height: 3px;
            }}
            QScrollArea#DashboardScroll QScrollBar::handle:horizontal:hover,
            QTableWidget QScrollBar::handle:horizontal:hover,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::handle:horizontal:hover {{ background: {scroll_handle_hover}; }}
            QScrollArea#DashboardScroll QScrollBar::add-line:horizontal,
            QScrollArea#DashboardScroll QScrollBar::sub-line:horizontal,
            QTableWidget QScrollBar::add-line:horizontal,
            QTableWidget QScrollBar::sub-line:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::add-line:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::sub-line:horizontal {{
                width: 0px; height: 0px; border: none; background: transparent;
            }}
            QScrollArea#DashboardScroll QScrollBar::add-page:horizontal,
            QScrollArea#DashboardScroll QScrollBar::sub-page:horizontal,
            QTableWidget QScrollBar::add-page:horizontal,
            QTableWidget QScrollBar::sub-page:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::add-page:horizontal,
            QPlainTextEdit#DashboardExpertIntro QScrollBar::sub-page:horizontal {{ background: transparent; }}
            """
        )
        for chart in (
            getattr(self, "school_chart", None),
            getattr(self, "coverage_chart", None),
        ):
            if chart:
                chart.set_palette(p)
        for heatmap in (
            getattr(self, "school_month_heatmap", None),
            getattr(self, "school_type_heatmap", None),
            getattr(self, "month_type_heatmap", None),
            getattr(self, "coverage_heatmap", None),
        ):
            if heatmap:
                heatmap.set_palette(p)
        if self.snapshot:
            self._populate_snapshot()


__all__ = ["DashboardPage"]
