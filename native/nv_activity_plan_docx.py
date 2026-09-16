# -*- coding: utf-8 -*-
"""活动方案导出 Word（从 CTK 合并版抽出，供 PySide6 / 其他 UI 共用）。"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, List, Optional, Tuple

from nv_activity_plan_core import _strip_activity_plan_editor_artifacts

if TYPE_CHECKING:
    from docx import Document

try:
    from docx import Document as _Document
except ImportError:
    _Document = None  # type: ignore[misc, assignment]


def safe_filename(name: str) -> str:
    name = str(name) if name is not None else ""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "")
    return name[:50]


def extract_project_title_from_body(body_text: str) -> str:
    """从正文中提取项目名称（优先「项目名称：」，其次「活动名称：」）。与 CTK 一致。"""
    txt = (body_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not txt:
        return ""

    def _clean_name(raw: str) -> str:
        s = (raw or "").strip()
        # 标题两端的“”不应被剥离；否则会导致 Excel/Word 中标题缺引号。
        s = re.sub(r'^[\'‘’《》\s]+|[\'‘’《》\s]+$', "", s).strip()
        s = re.sub(r"\s*[（(][^)）]{0,40}[)）]\s*$", "", s).strip()
        s = re.sub(r"\s*(?:。|；|;)\s*$", "", s).strip()
        return s

    lines = txt.split("\n")
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        s = s.replace("**", "")
        s = re.sub(r"^\s*[-*•●▪◦]\s*", "", s)
        s = re.sub(r"^\s*[（(]?[一二三四五六七八九十0-9]+[)）.、]\s*", "", s)
        m = re.search(r"(项目名称|活动名称)\s*[：:]\s*(.+)$", s)
        if not m:
            if re.search(r"(项目名称|活动名称)\s*$", s):
                j = i + 1
                while j < len(lines):
                    nxt = (lines[j] or "").strip().replace("**", "")
                    if not nxt:
                        j += 1
                        continue
                    nxt = re.sub(r"^\s*[-*•●▪◦]\s*", "", nxt).strip()
                    if re.match(r"^[（(]?[一二三四五六七八九十0-9]+[)）.、]\s*", nxt) and re.search(
                        r"(活动|项目|时间|地点|对象|形式|目标|内容)", nxt
                    ):
                        break
                    cand = _clean_name(nxt)
                    if cand and len(cand) >= 2:
                        return cand
                    break
            continue
        cand = _clean_name(m.group(2))
        if cand and len(cand) >= 2:
            return cand

    txt2 = txt.replace("**", "")
    m2 = re.search(r"(项目名称|活动名称)\s*[：:]\s*([^\n\r]+)", txt2)
    if m2:
        cand = _clean_name(m2.group(2))
        if cand and len(cand) >= 2:
            return cand
    return ""


def normalize_cover_activity_title(raw_title: str) -> str:
    """封面主标题规范为「<项目名> 活动方案」，与 CTK 一致。"""
    t = (raw_title or "").strip()
    t = re.sub(r"^[|｜\s]+", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(活动方案|项目方案|策划方案)\s*$", "", t).strip()
    return (t + " 活动方案").strip() if t else "活动策划方案"


def _parse_md_table_line(line: str) -> Optional[List[str]]:
    if not line or not line.strip().startswith("|"):
        return None
    s = line.strip()
    if s.count("|") < 2:
        return None
    parts = s.split("|")
    if len(parts) < 3:
        return None
    cells = [p.strip() for p in parts[1:-1]]
    if not cells:
        return None
    return cells


def _is_md_table_separator_row(cells: List[str]) -> bool:
    if not cells:
        return False
    blob = "".join(cells).replace(" ", "")
    if "-" not in blob:
        return False
    return all(re.match(r"^[\s\-:]*$", c) for c in cells)


def _try_extract_md_table(lines: List[str], start: int) -> Tuple[Optional[List[List[str]]], int]:
    if start >= len(lines):
        return None, start
    first = _parse_md_table_line(lines[start])
    if not first or len(first) < 2:
        return None, start
    rows: List[List[str]] = [list(first)]
    idx = start + 1
    while idx < len(lines):
        raw = lines[idx]
        s = raw.strip()
        if not s:
            break
        parsed = _parse_md_table_line(raw)
        if parsed is None:
            break
        if _is_md_table_separator_row(parsed):
            idx += 1
            continue
        rows.append(list(parsed))
        idx += 1
    if len(rows) < 2:
        return None, start
    ncols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < ncols:
            r.append("")
    return rows, idx


def _is_heading_or_list(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if re.match(r"^\s*https?://", s) or "链接:" in s or "链接：" in s:
        return True
    if s.startswith("#") or re.match(r"^\s*[-*]\s+", s):
        return True
    tc = _parse_md_table_line(line)
    if tc is not None and len(tc) >= 2:
        return True
    return False


# 二级标题自动编号：（一）（二）…（二十），超出则退回阿拉伯
_CN_PAREN_HEAD: tuple[str, ...] = tuple(
    f"（{x}）"
    for x in (
        "一",
        "二",
        "三",
        "四",
        "五",
        "六",
        "七",
        "八",
        "九",
        "十",
        "十一",
        "十二",
        "十三",
        "十四",
        "十五",
        "十六",
        "十七",
        "十八",
        "十九",
        "二十",
    )
)


def _int_to_cn_parenthetical(n: int) -> str:
    if n < 1:
        return "（？）"
    if n <= len(_CN_PAREN_HEAD):
        return _CN_PAREN_HEAD[n - 1]
    return f"（{n}）"


def _strip_manual_h2_title_prefix(title: str) -> str:
    """去掉模型在 ## 标题里手写的（一）/1./一、等，避免与导出层编号重复。"""
    s = (title or "").strip()
    while s:
        nxt = re.sub(r"^\s*（[一二三四五六七八九十百千]+）\s*", "", s)
        nxt = re.sub(r"^\s*[(（]\d+[)）]\s*", "", nxt)
        nxt = re.sub(r"^\s*[一二三四五六七八九十百千0-9]+\s*[、.）)]\s*", "", nxt)
        if nxt == s:
            break
        s = nxt.strip()
    return s


def _strip_manual_h3_title_prefix(title: str) -> str:
    """去掉 ### 标题前手写的 1. / 1、/（1）等。"""
    s = (title or "").strip()
    while s:
        nxt = re.sub(r"^\s*[(（]?\d+[)）]?[.、．）)]\s*", "", s)
        if nxt == s:
            break
        s = nxt.strip()
    return s


def _parse_markdown_heading_line(line: str) -> Optional[Tuple[int, str]]:
    """解析行首 Markdown 标题：(#+) + 标题；剥离模型多打的「#」（如 #### 被误判为 ### 时残留）。
    返回 (级别, 纯标题)；非标题行返回 None。"""
    s = (line or "").strip()
    m = re.match(r"^([#＃]+)\s*(.*)$", s)
    if not m:
        return None
    raw = m.group(1).replace("＃", "#")
    level = len(raw)
    if level < 1 or level > 9:
        return None
    title = (m.group(2) or "").strip()
    while title:
        t2 = re.sub(r"^[#＃]+\s*", "", title).strip()
        if t2 == title:
            break
        title = t2
    if not title:
        return None
    return level, title


def _add_paragraph_runs_with_bold(para, text: str, font_name: str, font_pt: int, qn, table_cell: bool = False) -> None:
    from docx.shared import Pt

    if not table_cell:
        text = re.sub(r"\s*\|\s*", " ", text)
    parts = re.split(r"\*\*", text)
    for i, seg in enumerate(parts):
        seg = (seg.replace("**", "").strip() if table_cell else seg.replace("|", " ").replace("**", "").strip())
        if not seg:
            continue
        r = para.add_run(seg)
        r.font.name = font_name
        try:
            r._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
        except Exception:
            pass
        r.font.size = Pt(font_pt)
        r.bold = i % 2 == 1


def _add_markdown_table_to_docx(
    doc: "Document",
    rows: List[List[str]],
    font_name: str,
    body_pt: int,
    qn,
) -> None:
    from docx.shared import Pt

    if not rows or len(rows) < 2:
        return
    ncols = len(rows[0])
    nrows = len(rows)
    tbl = doc.add_table(rows=nrows, cols=ncols)
    try:
        tbl.style = "Table Grid"
    except Exception:
        pass
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            cell = tbl.rows[ri].cells[ci]
            txt = row[ci] if ci < len(row) else ""
            cp = cell.paragraphs[0]
            for r in list(cp.runs):
                try:
                    r._element.getparent().remove(r._element)
                except Exception:
                    pass
            _add_paragraph_runs_with_bold(cp, txt, font_name, body_pt, qn, table_cell=True)
            if ri == 0:
                for r in cp.runs:
                    r.bold = True
    doc.add_paragraph()


def _write_body_with_markdown_styles(
    doc: "Document",
    body: str,
    font_name: str = "微软雅黑",
    body_pt: int = 12,
    heading1_pt: int = 14,
    heading2_pt: int = 12,
    heading3_pt: int = 12,
    *,
    body_paragraph_justify: bool = False,
    body_first_line_indent_pt: Optional[float] = None,
    body_line_spacing_multiple: Optional[float] = None,
    heading_blank_before_h1: bool = False,
    render_list_with_bullet: bool = True,
    markdown_cn_auto_number: bool = False,
) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    def _apply_para_body_style(para, apply_first_line_indent: bool = True) -> None:
        if body_line_spacing_multiple is not None:
            try:
                para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
                para.paragraph_format.line_spacing = body_line_spacing_multiple
            except Exception:
                pass
        if body_paragraph_justify:
            try:
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            except Exception:
                pass
        if apply_first_line_indent and body_first_line_indent_pt is not None:
            try:
                para.paragraph_format.first_line_indent = Pt(int(body_first_line_indent_pt))
            except Exception:
                pass

    if not body or not body.strip():
        return
    lines = body.split("\n")
    i = 0
    h1_num = 0
    h2_num = 0
    _cn = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四", "十五"]

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        # 容错：去掉零宽字符 / 全角井号，避免标题前残留 “#”
        s = (
            s.replace("\u200b", "")
            .replace("\ufeff", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\u2060", "")
        )
        s = s.replace("＃", "#")
        if not render_list_with_bullet and re.match(r"^\s*[•●▪◦]\s+", s):
            s = re.sub(r"^\s*[•●▪◦]\s+", "", s, count=1).strip()
        if re.match(r"^\s*https?://", s) or "链接:" in s or "链接：" in s:
            i += 1
            continue
        if not s:
            i += 1
            continue
        tbl_rows, next_i = _try_extract_md_table(lines, i)
        if tbl_rows is not None:
            _add_markdown_table_to_docx(doc, tbl_rows, font_name, body_pt, qn)
            i = next_i
            continue
        hm = _parse_markdown_heading_line(s)
        if hm is not None:
            level, title = hm
            if markdown_cn_auto_number:
                if level == 2:
                    title = _strip_manual_h2_title_prefix(title)
                elif level >= 3:
                    title = _strip_manual_h3_title_prefix(title)
            if not title:
                i += 1
                continue

            def _style_heading_runs(p, pt: int) -> None:
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                if body_line_spacing_multiple is not None:
                    try:
                        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
                        p.paragraph_format.line_spacing = body_line_spacing_multiple
                    except Exception:
                        pass
                for r in p.runs:
                    r.font.name = font_name
                    try:
                        r._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
                    except Exception:
                        pass
                    r.font.size = Pt(pt)
                    r.bold = True

            if markdown_cn_auto_number:
                if level == 1:
                    if heading_blank_before_h1 and h1_num > 0:
                        doc.add_paragraph()
                    h2_num = 0
                    h1_num += 1
                    stripped_after_num = re.sub(
                        r"^[一二三四五六七八九十0-9]+\s*[)）.、]\s*",
                        "",
                        title,
                    ).strip()
                    is_meta_label = bool(
                        re.match(r"^(项目名称|活动名称)\s*[：:]", stripped_after_num)
                    )
                    is_number_heading = bool(
                        re.match(r"^[一二三四五六七八九十0-9]+\s*[)）.、]\s*", title)
                    )
                    disp_title = title
                    if not is_meta_label and not is_number_heading:
                        prefix = _cn[h1_num - 1] + "、" if 1 <= h1_num <= len(_cn) else f"{h1_num}、"
                        if not disp_title.startswith(
                            (
                                "一、",
                                "二、",
                                "三、",
                                "四、",
                                "五、",
                                "六、",
                                "七、",
                                "八、",
                                "九、",
                                "十、",
                                "十一、",
                                "十二、",
                            )
                        ):
                            disp_title = prefix + disp_title
                    p = doc.add_heading(disp_title, level=1)
                    _style_heading_runs(p, heading1_pt)
                elif level == 2:
                    h2_num += 1
                    disp = _int_to_cn_parenthetical(h2_num) + title
                    p = doc.add_heading(disp, level=2)
                    _style_heading_runs(p, heading2_pt)
                else:
                    # 三级及以下：不再加「1.2.3.」阿拉伯编号，仅保留洗净标题；避免 #### 残留「#」
                    wd_lv = min(level, 9)
                    p = doc.add_heading(title, level=wd_lv)
                    _style_heading_runs(p, heading3_pt)
            else:
                wd_lv = min(level, 4)
                p = doc.add_heading(title, level=wd_lv)
                pt = heading1_pt if level == 1 else (heading2_pt if level == 2 else heading3_pt)
                _style_heading_runs(p, pt)
            i += 1
            continue
        if re.match(r"^\s*[-*]\s+", s):
            text = re.sub(r"^\s*[-*]\s+", "", s, count=1).strip()
            if text:
                para = doc.add_paragraph()
                para.paragraph_format.first_line_indent = Cm(0.74 if not render_list_with_bullet else 0)
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(0)
                _apply_para_body_style(para, apply_first_line_indent=False)
                _add_paragraph_runs_with_bold(
                    para, ("• " + text) if render_list_with_bullet else text, font_name, body_pt, qn
                )
            i += 1
            continue
        merged = [s]
        j = i + 1
        while j < len(lines):
            next_s = lines[j].strip()
            if not render_list_with_bullet and re.match(r"^\s*[•●▪◦]\s+", next_s):
                next_s = re.sub(r"^\s*[•●▪◦]\s+", "", next_s, count=1).strip()
            if not next_s or _is_heading_or_list(lines[j]):
                break
            if merged and re.search(r"[。？！；?!;]\s*$", merged[-1]):
                break
            merged.append(next_s)
            j += 1
        i = j
        para_text = "".join(merged)
        para = doc.add_paragraph()
        if body_first_line_indent_pt is not None:
            para.paragraph_format.first_line_indent = Pt(int(body_first_line_indent_pt))
        else:
            para.paragraph_format.first_line_indent = Cm(0.74)
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        _apply_para_body_style(para)
        _add_paragraph_runs_with_bold(para, para_text, font_name, body_pt, qn)


def save_activity_plan_to_docx(
    out_path: str,
    project_title: str,
    service_college: str,
    activity_type: str,
    activity_time: str,
    thinking_text: str,
    body_markdown: str,
    *,
    cover_title_override: Optional[str] = None,
) -> None:
    """保存为 Word：仿宋封面大标题、副标题「活动方案」、信息行、Markdown 映射正文。
    cover_title_override：若填写则优先作为封面主标题（仍会自动补上「活动方案」规范后缀逻辑于 _normalize 内）。
    thinking_text：兼容旧接口，不写入文档。
    """
    if _Document is None:
        raise RuntimeError("当前环境缺少 python-docx，请使用包含完整依赖的发布包。")

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Pt

    service_college = (service_college or "").strip()
    activity_type = (activity_type or "").strip()
    activity_time = (activity_time or "").strip()
    _ = thinking_text
    body_markdown = _strip_activity_plan_editor_artifacts((body_markdown or "").strip())

    override = (cover_title_override or "").strip()
    if override:
        project_title = normalize_cover_activity_title(override)
    else:
        project_title = (project_title or "").strip()
        extracted_title = extract_project_title_from_body(body_markdown)
        if extracted_title:
            project_title = extracted_title
        elif not project_title:
            project_title = ""
        project_title = normalize_cover_activity_title(project_title)

    doc = Document()
    doc.styles["Normal"].font.name = "宋体"
    doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    doc.styles["Normal"].font.size = Pt(12)

    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    try:
        tp.paragraph_format.line_spacing = 1.5
    except Exception:
        pass
    r1 = tp.add_run(project_title)
    r1.font.name = "仿宋"
    r1._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
    r1.font.size = Pt(22)
    r1.bold = True

    if "活动方案" not in project_title:
        tp_sub = doc.add_paragraph()
        tp_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        try:
            tp_sub.paragraph_format.line_spacing = 1.5
        except Exception:
            pass
        r_sub = tp_sub.add_run("活动方案")
        r_sub.font.name = "仿宋"
        r_sub._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
        r_sub.font.size = Pt(22)
        r_sub.bold = True

    sp = doc.add_paragraph()
    sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    try:
        sp.paragraph_format.line_spacing = 1.5
    except Exception:
        pass
    meta = f"服务院校：{service_college}　活动类型：{activity_type}　活动时间：{activity_time}"
    r2 = sp.add_run(meta)
    r2.font.name = "宋体"
    r2._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    r2.font.size = Pt(12)

    doc.add_paragraph()

    if body_markdown:
        _write_body_with_markdown_styles(
            doc,
            body_markdown,
            font_name="宋体",
            body_pt=12,
            heading1_pt=14,
            heading2_pt=12,
            body_paragraph_justify=True,
            body_first_line_indent_pt=24,
            body_line_spacing_multiple=1.5,
            heading_blank_before_h1=True,
            render_list_with_bullet=False,
            markdown_cn_auto_number=True,
        )
    else:
        pe = doc.add_paragraph("（正文为空）")
        try:
            pe.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pe.paragraph_format.line_spacing = 1.5
            pe.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            pe.paragraph_format.first_line_indent = Pt(24)
        except Exception:
            pass
        for r in pe.runs:
            r.font.name = "宋体"
            try:
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            except Exception:
                pass
            r.font.size = Pt(12)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass
    doc.save(out_path)
