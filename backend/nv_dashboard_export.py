# -*- coding: utf-8 -*-
"""数据看板重点汇总 Excel 导出。

只输出用户明确需要的汇总矩阵；不导出活动、审批、报销或专家邀请明细。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from nv_dashboard_core import DashboardSnapshot, DashboardView, ExpertProfile


FONT_NAME = "Microsoft YaHei UI"
TEXT = "1F2933"
MUTED = "667085"
HEADER_FILL = "E9EDF2"
SECTION_FILL = "F5F7F9"
OUTLINE = "D7DCE3"
ACCENT = "2563EB"
WHITE = "FFFFFF"
INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")
VALID_MONTH = re.compile(r"^\d{4}-\d{2}$")


def _format_count(value: float | int) -> int | float:
    number = float(value)
    return int(round(number)) if number.is_integer() else number


def _month_label(month: str) -> str:
    if VALID_MONTH.match(month or ""):
        year, number = month.split("-", 1)
        return f"{year}年{int(number):02d}月"
    return month or "日期缺失"


def _period_label(view: DashboardView) -> str:
    start = view.filters.start_date
    end = view.filters.end_date
    if start is None and end is None:
        return "全部月份"
    if start and end and (start.year, start.month) == (end.year, end.month):
        return f"{start.year}年{start.month:02d}月"
    left = f"{start.year}年{start.month:02d}月" if start else "最早月份"
    right = f"{end.year}年{end.month:02d}月" if end else "最晚月份"
    return f"{left}—{right}"


def _month_range(start: str, end: str) -> list[str]:
    year, month = (int(part) for part in start.split("-", 1))
    end_year, end_month = (int(part) for part in end.split("-", 1))
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def _export_months(snapshot: DashboardSnapshot, view: DashboardView) -> list[str]:
    start = view.filters.start_date
    end = view.filters.end_date
    if start and end:
        return _month_range(f"{start.year:04d}-{start.month:02d}", f"{end.year:04d}-{end.month:02d}")
    valid = sorted(month for month in snapshot.months if VALID_MONTH.match(month))
    months = _month_range(valid[0], valid[-1]) if valid else []
    if "日期缺失" in view.months:
        months.append("日期缺失")
    return months or ["日期缺失"]


def _all_schools(snapshot: DashboardSnapshot, view: DashboardView) -> list[str]:
    schools = set(snapshot.school_counts) | set(view.school_counts)
    return sorted(schools, key=lambda school: (-view.school_counts.get(school, 0), school))


def _all_activity_types(snapshot: DashboardSnapshot) -> list[str]:
    counts: Counter[str] = Counter()
    for values in snapshot.school_type_counts.values():
        counts.update(values)
    return [name for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _source_summary(snapshot: DashboardSnapshot, view: DashboardView) -> str:
    source = "企业微信原始审批" if snapshot.source_kind == "raw" else "清洗整理结果"
    if snapshot.source_supplementary_path:
        source += " + 补充表格（仅计活动数量，视为已报销）"
    return (
        f"统计时间：{_period_label(view)}　｜　数据来源：{source}　｜　"
        f"数据截至：{snapshot.as_of_date.isoformat()}　｜　导出时间：{datetime.now():%Y-%m-%d %H:%M}"
    )


def _thin_border() -> Border:
    side = Side(style="thin", color=OUTLINE)
    return Border(left=side, right=side, top=side, bottom=side)


def _prepare_sheet(ws, *, zoom: int = 90) -> None:
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = zoom
    ws.sheet_view.zoomScaleNormal = zoom
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.oddFooter.center.text = "第 &[Page] 页 / 共 &[Pages] 页"
    ws.oddFooter.center.size = 9
    ws.oddFooter.center.color = MUTED


def _merge_if_needed(ws, row: int, last_column: int) -> None:
    if last_column > 1:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)


def _write_sheet_header(ws, title: str, subtitle: str, last_column: int) -> None:
    _prepare_sheet(ws)
    _merge_if_needed(ws, 1, last_column)
    title_cell = ws.cell(1, 1, title)
    title_cell.font = Font(name=FONT_NAME, size=15, bold=True, color=TEXT)
    title_cell.fill = PatternFill("solid", fgColor=SECTION_FILL)
    title_cell.alignment = Alignment(vertical="center", horizontal="left")
    ws.row_dimensions[1].height = 30
    _merge_if_needed(ws, 2, last_column)
    subtitle_cell = ws.cell(2, 1, subtitle)
    subtitle_cell.font = Font(name=FONT_NAME, size=9, color=MUTED)
    subtitle_cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 24


def _style_header_row(ws, row: int, headers: Sequence[str]) -> None:
    border = _thin_border()
    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row, column, header)
        cell.font = Font(name=FONT_NAME, size=10, bold=True, color=TEXT)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[row].height = 32


def _write_rows(
    ws,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    start_row: int,
    left_columns: Iterable[int] = (1,),
    wrap_columns: Iterable[int] = (),
) -> None:
    left = set(left_columns)
    wrap = set(wrap_columns)
    border = _thin_border()
    for row_index, values in enumerate(rows, start=start_row):
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row_index, column, value)
            cell.font = Font(name=FONT_NAME, size=9, color=TEXT)
            cell.border = border
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            cell.alignment = Alignment(
                vertical="top" if column in wrap else "center",
                horizontal="left" if column in left else ("right" if is_number else "center"),
                wrap_text=column in wrap,
            )
            if isinstance(value, date):
                cell.number_format = "yyyy-mm-dd"
            elif is_number:
                cell.number_format = "#,##0.##"
        ws.row_dimensions[row_index].height = 22


def _set_widths(ws, widths: Sequence[float]) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(8, min(64, width))


def _finish_table(ws, headers: Sequence[str], row_count: int, *, freeze: str = "B5") -> None:
    last_column = get_column_letter(len(headers))
    last_row = max(4, 4 + row_count)
    ws.auto_filter.ref = f"A4:{last_column}{last_row}"
    ws.freeze_panes = freeze
    ws.print_title_rows = "1:4"
    ws.print_area = f"A1:{last_column}{last_row}"


def _write_ranking(workbook: Workbook, snapshot: DashboardSnapshot, view: DashboardView, schools: Sequence[str]) -> None:
    ws = workbook.create_sheet("院校活动排名")
    headers = ("序号", "院校", "活动数", "活动占比")
    _write_sheet_header(ws, "院校活动排名", _source_summary(snapshot, view), len(headers))
    _style_header_row(ws, 4, headers)
    total = sum(view.school_counts.values())
    rows = [
        (index, school, view.school_counts.get(school, 0), view.school_counts.get(school, 0) / total if total else 0)
        for index, school in enumerate(schools, start=1)
    ]
    _write_rows(ws, headers, rows, start_row=5, left_columns=(2,))
    for row in range(5, 5 + len(rows)):
        ws.cell(row, 4).number_format = "0.0%"
    _set_widths(ws, (8, 30, 12, 13))
    _finish_table(ws, headers, len(rows))

    nonzero_count = sum(view.school_counts.get(school, 0) > 0 for school in schools)
    if nonzero_count:
        chart = BarChart()
        chart.type = "bar"
        chart.title = "院校活动排名（非零院校）"
        chart.x_axis.title = "活动数"
        chart.y_axis.title = "院校"
        chart.legend = None
        chart.width = 17
        chart.height = max(7.5, min(42, 2.5 + nonzero_count * 0.43))
        chart.gapWidth = 55
        chart.add_data(Reference(ws, min_col=3, min_row=4, max_row=4 + nonzero_count), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=2, min_row=5, max_row=4 + nonzero_count))
        # Excel 横向柱状图默认会把首个分类放在最下方；反转分类轴后，
        # 工作表与图表都按“活动数从高到低”自上而下展示。
        chart.y_axis.scaling.orientation = "maxMin"
        chart.dataLabels = DataLabelList()
        chart.dataLabels.dLblPos = "outEnd"
        chart.dataLabels.numFmt = "0"
        chart.dataLabels.showLegendKey = False
        chart.dataLabels.showVal = True
        chart.dataLabels.showCatName = False
        chart.dataLabels.showSerName = False
        chart.dataLabels.showPercent = False
        chart.dataLabels.showBubbleSize = False
        chart.dataLabels.showLeaderLines = False
        if chart.series:
            chart.series[0].graphicalProperties.solidFill = ACCENT
            chart.series[0].graphicalProperties.line.solidFill = ACCENT
        ws.add_chart(chart, "F4")


def _write_matrix_sheet(
    workbook: Workbook,
    *,
    title: str,
    subtitle: str,
    row_labels: Sequence[str],
    column_labels: Sequence[str],
    value_getter,
    table_name: str | None = None,
) -> None:
    ws = workbook.create_sheet(title)
    headers = [table_name or "院校"] + [_month_label(label) for label in column_labels] + ["合计"]
    _write_sheet_header(ws, title, subtitle, len(headers))
    _style_header_row(ws, 4, headers)
    rows = []
    for row_label in row_labels:
        values = [_format_count(value_getter(row_label, column_label)) for column_label in column_labels]
        rows.append((row_label, *values, _format_count(sum(float(value) for value in values))))
    _write_rows(ws, headers, rows, start_row=5)
    for row in range(5, 5 + len(rows)):
        for column in range(2, len(headers) + 1):
            ws.cell(row, column).number_format = "#,##0.##"
    _set_widths(ws, [30] + [max(12, min(18, len(label) * 1.7 + 4)) for label in headers[1:-1]] + [12])
    _finish_table(ws, headers, len(rows))


def _unique_sheet_title(school: str, used: set[str]) -> str:
    stem = INVALID_SHEET_CHARS.sub("·", f"月×类型-{school}").strip(" '") or "月×类型-未命名院校"
    stem = stem[:31]
    candidate = stem
    counter = 2
    while candidate.casefold() in used:
        suffix = f"-{counter}"
        candidate = stem[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _write_school_month_type_sheets(
    workbook: Workbook,
    snapshot: DashboardSnapshot,
    view: DashboardView,
    schools: Sequence[str],
    months: Sequence[str],
    activity_types: Sequence[str],
) -> None:
    used = {name.casefold() for name in workbook.sheetnames}
    for school in schools:
        title = _unique_sheet_title(school, used)
        ws = workbook.create_sheet(title)
        headers = ["月份"] + list(activity_types) + ["合计"]
        _write_sheet_header(ws, f"{school}｜月份 × 活动类型", _source_summary(snapshot, view), len(headers))
        _style_header_row(ws, 4, headers)
        month_map = view.school_month_type_counts.get(school, {})
        rows = []
        for month in months:
            values = [month_map.get(month, {}).get(activity_type, 0) for activity_type in activity_types]
            rows.append((_month_label(month), *values, sum(values)))
        type_totals = [
            sum(month_map.get(month, {}).get(activity_type, 0) for month in months)
            for activity_type in activity_types
        ]
        rows.append(("合计", *type_totals, sum(type_totals)))
        _write_rows(ws, headers, rows, start_row=5)
        total_row = 4 + len(rows)
        for cell in ws[total_row]:
            cell.font = Font(name=FONT_NAME, size=9, bold=True, color=TEXT)
            cell.fill = PatternFill("solid", fgColor=SECTION_FILL)
        _set_widths(ws, [16] + [max(12, min(18, len(label) * 1.7 + 4)) for label in activity_types] + [12])
        _finish_table(ws, headers, len(rows))


def _write_coverage(
    workbook: Workbook,
    snapshot: DashboardSnapshot,
    view: DashboardView,
    schools: Sequence[str],
    months: Sequence[str],
) -> None:
    ws = workbook.create_sheet("覆盖人次")
    headers = ["院校", "总计"] + [_month_label(month) for month in months]
    _write_sheet_header(ws, "覆盖人次", _source_summary(snapshot, view), len(headers))

    def section(start_row: int, label: str, totals: dict[str, float], by_month: dict[str, dict[str, float]]) -> int:
        ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=len(headers))
        title_cell = ws.cell(start_row, 1, label)
        title_cell.font = Font(name=FONT_NAME, size=11, bold=True, color=TEXT)
        title_cell.fill = PatternFill("solid", fgColor=SECTION_FILL)
        title_cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[start_row].height = 25
        _style_header_row(ws, start_row + 1, headers)
        rows = [
            (
                school,
                _format_count(totals.get(school, 0)),
                *(_format_count(by_month.get(school, {}).get(month, 0)) for month in months),
            )
            for school in schools
        ]
        _write_rows(ws, headers, rows, start_row=start_row + 2)
        return start_row + 2 + len(rows)

    next_row = section(4, "教师覆盖人次", view.teacher_by_school, view.teacher_by_school_month)
    section(next_row + 1, "学生覆盖人次", view.student_by_school, view.student_by_school_month)
    _set_widths(ws, [30, 12] + [13] * len(months))
    ws.freeze_panes = "C6"
    ws.print_title_rows = "1:5"
    ws.print_area = f"A1:{get_column_letter(len(headers))}{ws.max_row}"


def _write_experts(
    workbook: Workbook,
    snapshot: DashboardSnapshot,
    experts: Sequence[ExpertProfile],
) -> None:
    ws = workbook.create_sheet("专家库")
    headers = (
        "专家",
        "累计邀请次数",
        "最近活动",
        "受邀院校数",
        "受邀院校",
        "活动类型",
        "简介版本",
        "专家简介",
        "记录状态",
    )
    subtitle = (
        f"本机专家库全量导出，共 {len(experts):,} 位专家；不受当前月份筛选影响　｜　"
        f"数据截至：{snapshot.as_of_date.isoformat()}　｜　导出时间：{datetime.now():%Y-%m-%d %H:%M}"
    )
    _write_sheet_header(ws, "专家库", subtitle, len(headers))
    _style_header_row(ws, 4, headers)
    ordered = sorted(experts, key=lambda item: (-item.invitation_count, item.expert_name))
    rows = [
        (
            profile.expert_name,
            profile.invitation_count,
            profile.latest_event_date,
            len(profile.schools),
            "、".join(profile.schools),
            " / ".join(profile.activity_types),
            len(profile.intros),
            "\n\n".join(profile.intros),
            "简介冲突" if profile.has_intro_conflict else ("姓名待核对" if profile.needs_review else "正常"),
        )
        for profile in ordered
    ]
    _write_rows(ws, headers, rows, start_row=5, left_columns=(1, 5, 6, 8), wrap_columns=(5, 6, 8))
    for row_index, profile in enumerate(ordered, start=5):
        longest = max(len("、".join(profile.schools)), len(" / ".join(profile.activity_types)), len("\n\n".join(profile.intros)))
        ws.row_dimensions[row_index].height = min(180, max(22, 22 + 15 * math.ceil(longest / 50)))
    _set_widths(ws, (18, 14, 14, 13, 38, 28, 12, 64, 16))
    _finish_table(ws, headers, len(rows))


def export_dashboard_view_xlsx(
    snapshot: DashboardSnapshot,
    view: DashboardView,
    output_path: str | Path,
    *,
    expert_profiles: Sequence[ExpertProfile] | None = None,
) -> Path:
    """导出当前月份口径的重点汇总；专家库始终使用传入的全量资料。"""
    target = Path(output_path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    from nv_data_safety import new_output_path, staged_outputs
    sources = [value for value in (snapshot.source_application_path, snapshot.source_reimbursement_path,
                                  snapshot.source_supplementary_path) if value]
    target = new_output_path(target.parent, target.name, sources)
    target.parent.mkdir(parents=True, exist_ok=True)

    schools = _all_schools(snapshot, view)
    months = _export_months(snapshot, view)
    activity_types = _all_activity_types(snapshot)
    experts = tuple(expert_profiles) if expert_profiles is not None else snapshot.experts

    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_ranking(workbook, snapshot, view, schools)
    _write_matrix_sheet(
        workbook,
        title="院校×开始活动月",
        subtitle=_source_summary(snapshot, view),
        row_labels=schools,
        column_labels=months,
        value_getter=lambda school, month: view.school_month_counts.get(school, {}).get(month, 0),
    )
    _write_matrix_sheet(
        workbook,
        title="院校×活动类型",
        subtitle=_source_summary(snapshot, view),
        row_labels=schools,
        column_labels=activity_types,
        value_getter=lambda school, activity_type: view.school_type_counts.get(school, {}).get(activity_type, 0),
    )
    _write_school_month_type_sheets(workbook, snapshot, view, schools, months, activity_types)
    _write_coverage(workbook, snapshot, view, schools, months)
    _write_experts(workbook, snapshot, experts)

    workbook.properties.title = "活动看板重点数据"
    workbook.properties.subject = f"{_period_label(view)}重点汇总"
    workbook.properties.description = "院校、月份、活动类型、覆盖人次与全量专家库汇总。"
    workbook.properties.creator = "数据整理工具集"
    workbook.active = 0

    try:
        with staged_outputs(target) as (temporary,):
            workbook.save(temporary)
    finally:
        workbook.close()
    return target


__all__ = ["export_dashboard_view_xlsx"]
