#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从「明细」sheet 汇总开票日期等，填写「封面」C4~F4。
封面：名称含 cover_title_contains 且不以明细后缀结尾。
明细：名称以「明细」或「-明细」结尾；配对优先「封面名+后缀」，否则按顺序。

供工具集「发票分类整理」在生成 _处理结果.xlsx 后可选调用（原地保存见 run 的 output_xlsx）。

依赖：openpyxl；可选 python-docx（--docx-placeholder）。

修改规则：SETTINGS / PROJECT_CATEGORIES 在本文件；
公司→院校：ticket_company_schools.json、project_company_schools.json（推荐 `{ "公司": ["院校", ...] }`，兼容旧版二维数组，城市关键词已忽略）。
内置默认中「用户 JSON 尚未列出的院校」会追加到同名公司下。
服务院校不按开票城市或地区表推断：机票封面为该公司全部院校；产教封面从公司名单随机 2～4 所；无法识别购买方公司时 D4 留空。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# 公司全称 → 服务院校名称列表（无城市关键词）
CompanySchoolsMap = dict[str, list[str]]

from openpyxl import load_workbook
from openpyxl.styles import Alignment
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

# ---------------------------------------------------------------------------
# 运行参数（原 settings.json）
# ---------------------------------------------------------------------------
SETTINGS: dict[str, Any] = {
    "category_mode": "random",
    "random_seed": 42,
    "category_count_min": 3,
    "category_count_max": 4,
    "detail_tag_column": "分类标签",
    "fallback_detail_tag_column": "预测分类标签",
    "cover_title_contains": "产教融合项目",
    "detail_name_suffixes": ["明细", "-明细"],
    "major_for_docx_placeholder": "艺术设计",
    "schools_joiner": "、",
}

# ---------------------------------------------------------------------------
# 机票 / 产教封面「服务院校」：购买方公司 → 院校全称列表
# （与发票分类界面「公司名称」、明细「购买方公司名称」一致；示例企业A/示例企业B互不串校）
# ---------------------------------------------------------------------------
TICKET_COMPANY_SCHOOLS: CompanySchoolsMap = {}

# 产教融合封面 D4「服务院校」：默认同机票名单（可在 project_company_schools.json 单独维护）
PROJECT_COMPANY_SCHOOLS: CompanySchoolsMap = copy.deepcopy(TICKET_COMPANY_SCHOOLS)

# 机票封面 C4「项目类别」固定四项（与产教分组随机类别不同）
TICKET_COVER_CATEGORY_LABELS: tuple[str, ...] = (
    "专业调研",
    "人才培养",
    "研学",
    "企业考察",
)

# 与 api_config 同目录：ticket_company_schools.json（可由工具集「设置」写入）
_cover_fill_config_dir: Path = Path(__file__).resolve().parent


def set_cover_fill_config_dir(path: str) -> None:
    global _cover_fill_config_dir
    _cover_fill_config_dir = Path(path).resolve()


def _ticket_company_schools_builtin() -> CompanySchoolsMap:
    return copy.deepcopy(TICKET_COMPANY_SCHOOLS)


def ticket_company_schools_to_jsonable(d: CompanySchoolsMap) -> dict[str, Any]:
    """序列化为 JSON：{ 公司: [ 院校, ... ] }。"""
    return {k: list(schools) for k, schools in d.items()}


def parse_ticket_company_schools_obj(obj: Any) -> CompanySchoolsMap:
    """解析 JSON：推荐 { 公司全称: [ \"院校\", ... ] }；兼容旧版 [[院校, [城市关键词…]], …]（城市字段忽略）。"""
    if not isinstance(obj, dict):
        raise ValueError("根节点须为 JSON 对象（{}）")
    out: CompanySchoolsMap = {}
    for k, v in obj.items():
        ck = str(k).strip()
        if not ck or not isinstance(v, list):
            continue
        schools: list[str] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    schools.append(s)
            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                sch = str(item[0]).strip()
                if sch:
                    schools.append(sch)
            elif isinstance(item, dict):
                sch = str(item.get("school") or "").strip()
                if sch:
                    schools.append(sch)
        if schools:
            out[ck] = schools
    if not out:
        raise ValueError("未解析到任何有效的「公司→院校」规则")
    return out


def ticket_company_schools_json_path() -> Path:
    return _cover_fill_config_dir / "ticket_company_schools.json"


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def read_ticket_company_schools_file_raw() -> str:
    p = ticket_company_schools_json_path()
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return default_ticket_company_schools_json_text()


def default_ticket_company_schools_json_text() -> str:
    return json.dumps(
        ticket_company_schools_to_jsonable(_ticket_company_schools_builtin()),
        ensure_ascii=False,
        indent=2,
    )


def _merge_company_schools_supplement(
    builtin: CompanySchoolsMap,
    user: CompanySchoolsMap,
) -> CompanySchoolsMap:
    """以用户 JSON 为主；同一公司键下，把内置里「尚未出现在用户列表中的院校」追加在后。"""
    out = copy.deepcopy(user)
    for company, base_schools in builtin.items():
        if company not in out:
            out[company] = list(base_schools)
            continue
        have = set(out[company])
        for sch in base_schools:
            if sch not in have:
                out[company].append(sch)
                have.add(sch)
    return out


def load_ticket_company_schools_runtime() -> CompanySchoolsMap:
    p = ticket_company_schools_json_path()
    built = _ticket_company_schools_builtin()
    if not p.is_file():
        return built
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        loaded = parse_ticket_company_schools_obj(obj)
        return _merge_company_schools_supplement(built, loaded)
    except Exception:
        return built


def save_ticket_company_schools_file(data: CompanySchoolsMap) -> None:
    p = ticket_company_schools_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        p,
        json.dumps(ticket_company_schools_to_jsonable(data), ensure_ascii=False, indent=2),
    )


def _project_company_schools_builtin() -> CompanySchoolsMap:
    return copy.deepcopy(PROJECT_COMPANY_SCHOOLS)


def project_company_schools_json_path() -> Path:
    return _cover_fill_config_dir / "project_company_schools.json"


def read_project_company_schools_file_raw() -> str:
    p = project_company_schools_json_path()
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return default_project_company_schools_json_text()


def default_project_company_schools_json_text() -> str:
    return json.dumps(
        ticket_company_schools_to_jsonable(_project_company_schools_builtin()),
        ensure_ascii=False,
        indent=2,
    )


def load_project_company_schools_runtime() -> CompanySchoolsMap:
    p = project_company_schools_json_path()
    built = _project_company_schools_builtin()
    if not p.is_file():
        return built
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        loaded = parse_ticket_company_schools_obj(obj)
        return _merge_company_schools_supplement(built, loaded)
    except Exception:
        return built


def save_project_company_schools_file(data: CompanySchoolsMap) -> None:
    p = project_company_schools_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        p,
        json.dumps(ticket_company_schools_to_jsonable(data), ensure_ascii=False, indent=2),
    )


def _project_cover_company_conflict(err: str | None) -> bool:
    """购买方与界面公司冲突时，不填写服务院校并标为错误。"""
    if not err:
        return False
    return "不一致" in err or "无法对应" in err


# ---------------------------------------------------------------------------
# 项目类别（原 project_categories.json）
# ---------------------------------------------------------------------------
PROJECT_CATEGORIES: dict[str, Any] = {
    "all": [
        "专业考察调研",
        "专家讲座",
        "专业论坛",
        "人培研讨",
        "研学",
        "师资培训",
        "实训营",
        "专业竞赛",
    ],
    "tag_rules": {
        "交通费": ["专业考察调研", "研学"],
        "住宿费": ["研学", "专业考察调研"],
        "餐饮费": ["研学", "人培研讨"],
        "办公用品": ["实训营", "专业竞赛"],
        "物料费": ["专业考察调研", "实训营"],
        "招待用品": ["人培研讨", "专业论坛"],
        "咨询费": ["专家讲座", "专业论坛", "人培研讨"],
        "培训费": ["师资培训", "实训营"],
        "会议费": ["专业论坛", "人培研讨"],
        "差旅费": ["专业考察调研", "研学"],
        "默认": ["专家讲座", "专业论坛", "实训营"],
    },
}


def is_detail_sheet(name: str, suffixes: list[str]) -> bool:
    for suf in suffixes:
        if name.endswith(suf):
            return True
    return False


def detail_for_cover(cover_name: str, suffixes: list[str], available: set[str]) -> str | None:
    for suf in sorted(suffixes, key=len, reverse=True):
        cand = f"{cover_name}{suf}"
        if cand in available:
            return cand
    return None


def find_header_row(ws: Worksheet, labels: Iterable[str], max_scan: int = 30) -> dict[str, int] | None:
    want = set(labels)
    for r in range(1, max_scan + 1):
        found: dict[str, int] = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if v is None:
                continue
            s = str(v).strip()
            if s in want:
                found[s] = c
        if "开票日期" in found:
            found["_row"] = r
            return found
    return None


def parse_invoice_date(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    s_full = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s_full[:19], fmt)
        except ValueError:
            continue
    s_date = s_full.split()[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s_date[:10], fmt)
        except ValueError:
            pass
    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$", s_full)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s_date)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s_date)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def format_month_range(dates: list[datetime]) -> str:
    months = sorted({(d.year, d.month) for d in dates})
    if not months:
        return ""
    if len(months) == 1:
        y, m = months[0]
        return f"{y}年{m}月"
    y1, m1 = months[0]
    y2, m2 = months[-1]
    return f"{y1}年{m1}月~{y2}年{m2}月"


def unique_preserve(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def pick_categories_random(
    all_cats: list[str],
    rng: random.Random,
    cmin: int,
    cmax: int,
) -> list[str]:
    k = rng.randint(cmin, cmax)
    k = min(k, len(all_cats))
    return sorted(rng.sample(list(all_cats), k=k))


def pick_categories_rules(
    tags: list[str],
    tag_rules: dict[str, list[str]],
    all_cats: list[str],
    rng: random.Random,
    cmin: int,
    cmax: int,
) -> list[str]:
    scores: dict[str, int] = defaultdict(int)
    default = tag_rules.get("默认") or ["专家讲座", "专业论坛"]
    for t in tags:
        key = (t or "").strip()
        cats = tag_rules.get(key) or default
        for c in cats:
            if c in all_cats:
                scores[c] += 1
    if not scores:
        return pick_categories_random(all_cats, rng, cmin, cmax)
    ordered = sorted(scores.keys(), key=lambda x: (-scores[x], x))
    k = rng.randint(cmin, cmax)
    k = min(k, len(all_cats))
    picked = list(ordered[:k])
    if len(picked) < cmin:
        rest = [c for c in all_cats if c not in picked]
        rng.shuffle(rest)
        for c in rest:
            if len(picked) >= cmin:
                break
            picked.append(c)
    if len(picked) > cmax:
        picked = picked[:cmax]
    return sorted(picked)


def merged_top_left_cell(ws: Worksheet, cell_ref: str):
    """返回 cell_ref 所在合并区域的左上角单元格（无合并时等价于 ws[cell_ref]）。"""
    ref = (cell_ref or "").replace("$", "").split("!")[-1].strip()
    if not ref:
        raise ValueError("cell_ref 为空")
    col_letter, row = coordinate_from_string(ref)
    col = column_index_from_string(col_letter)
    for rng in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = range_boundaries(str(rng))
        if min_row <= row <= max_row and min_col <= col <= max_col:
            return ws.cell(row=min_row, column=min_col)
    return ws[ref]


def write_merged_top_left(ws: Worksheet, cell_ref: str, value: str) -> None:
    merged_top_left_cell(ws, cell_ref).value = value


def set_cover_block_style(ws: Worksheet) -> None:
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col in ("C", "D", "E", "F"):
        cell = merged_top_left_cell(ws, f"{col}4")
        cell.alignment = align


def pair_covers_details(
    sheet_names: list[str],
    cover_token: str,
    detail_suffixes: list[str],
) -> list[tuple[str, str]]:
    details_set = set(sheet_names)
    covers_in_order: list[str] = []
    for n in sheet_names:
        if cover_token not in n:
            continue
        if is_detail_sheet(n, detail_suffixes):
            continue
        covers_in_order.append(n)

    details_in_order = [n for n in sheet_names if is_detail_sheet(n, detail_suffixes)]

    pairs: list[tuple[str, str]] = []
    used_detail: set[str] = set()
    detail_queue = list(details_in_order)

    for cov in covers_in_order:
        dname = detail_for_cover(cov, detail_suffixes, details_set)
        if dname and dname not in used_detail:
            pairs.append((cov, dname))
            used_detail.add(dname)
            if dname in detail_queue:
                detail_queue.remove(dname)
            continue
        if detail_queue:
            d = detail_queue.pop(0)
            pairs.append((cov, d))
            used_detail.add(d)
        else:
            pairs.append((cov, ""))

    return pairs


def find_ticket_detail_header_row(ws: Worksheet, max_scan: int = 30) -> dict[str, Any] | None:
    """机票明细：需具备 开票日期、购买方公司名称（或购买方名称）；「开票城市」列可有可无。"""
    for r in range(1, max_scan + 1):
        found: dict[str, int] = {}
        buyer_this: int | None = None
        buyer_generic: int | None = None
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if v is None:
                continue
            s = str(v).strip()
            if s == "开票日期":
                found["开票日期"] = c
            if s == "开票城市":
                found["开票城市"] = c
            if s == "购买方公司名称":
                buyer_this = c
            elif s == "购买方名称":
                buyer_generic = c
        if "开票日期" not in found:
            continue
        bc = buyer_this or buyer_generic
        if bc is None:
            continue
        out: dict[str, Any] = dict(found)
        out["_row"] = r
        out["_buyer_col"] = bc
        return out
    return None


def _canonical_ticket_company(
    buyer_samples: list[str],
    ui_company: str | None,
    schools_map: CompanySchoolsMap,
) -> tuple[str | None, str | None]:
    """根据明细购买方与界面公司名称，解析为 schools_map 中的公司键；失败时返回 (None, 错误说明)。"""
    keys = list(schools_map.keys())

    def match_key(text: str) -> str | None:
        t = (text or "").strip()
        if not t:
            return None
        for k in keys:
            if k in t or t in k:
                return k
        return None

    row_keys = [match_key(b) for b in buyer_samples]
    row_keys = [x for x in row_keys if x]
    row_unique = list(dict.fromkeys(row_keys))
    ui_key = match_key(ui_company or "")

    if len(row_unique) > 1:
        return None, f"明细购买方不一致：{' / '.join(row_unique)}"
    if row_unique:
        if ui_key and ui_key != row_unique[0]:
            return (
                None,
                f"界面公司名称与明细购买方不一致（界面→{ui_key}，明细→{row_unique[0]}）",
            )
        return row_unique[0], None
    if ui_key:
        return ui_key, None
    if (ui_company or "").strip():
        return None, f"购买方无法对应到「设置」中的公司全称：界面「{ui_company}」"
    return None, "未识别购买方：请填写界面「公司名称」或保证明细含「购买方公司名称」"


def _school_names_in_pool_order(pool: list[str]) -> list[str]:
    """院校白名单中去重（保持列表中首次出现顺序）。"""
    return unique_preserve(pool)


def _schools_for_project_cover_random_buyer_pool(
    pool: list[str],
    rng: random.Random,
    *,
    min_count: int = 2,
    max_count: int = 4,
) -> list[str]:
    """产教封面：从购买方对应白名单院校中随机抽取 min_count～max_count 所（不超过池大小）。"""
    names = _school_names_in_pool_order(pool)
    if not names:
        return []
    hi = min(max_count, len(names))
    lo = min(min_count, hi)
    k = rng.randint(lo, hi)
    picked = set(rng.sample(names, k))
    return [n for n in names if n in picked]


def _ticket_cover_index_map(sheet_names: list[str]) -> dict[int, str]:
    """识别机票类「封面」sheet。

    1) 标准名：机票报销封面、机票报销封面_n
    2) 常见改名：工作表名与 B2 大标题一致，如「某某公司报销明细-1-1」（与 nv_classify 中 title 形态一致）
    """
    suffixes = list(SETTINGS.get("detail_name_suffixes", ["明细", "-明细"]))
    covers: dict[int, str] = {}
    for raw in sheet_names:
        n = (raw or "").strip()
        if is_detail_sheet(n, suffixes):
            continue
        # 排除机票明细表（名称以「机票报销明细」结尾等，避免误当封面）
        if re.search(r"机票报销明细_\d+\s*$", n) or n == "机票报销":
            continue
        m = re.fullmatch(r"机票报销封面_(\d+)", n)
        if m:
            covers[int(m.group(1))] = n
            continue
        m2 = re.search(r"机票报销封面_(\d+)\s*$", n)
        if m2:
            i = int(m2.group(1))
            if i not in covers:
                covers[i] = n
            continue
        if n == "机票报销封面":
            covers.setdefault(1, n)
            continue
        # 标题式命名：…报销明细-<系列>-<组号>（组号与 机票报销明细_n 的 n 对应）
        m3 = re.search(r"报销明细[-－](\d+)[-－](\d+)\s*$", n)
        if m3:
            i = int(m3.group(2))
            if i not in covers:
                covers[i] = n
    return covers


def _ticket_detail_index_map(sheet_names: list[str]) -> dict[int, str]:
    """识别「机票报销明细」sheet（含历史名「机票报销」）。"""
    details: dict[int, str] = {}
    for raw in sheet_names:
        n = (raw or "").strip()
        m = re.fullmatch(r"机票报销明细_(\d+)", n)
        if m:
            details[int(m.group(1))] = n
            continue
        m2 = re.search(r"机票报销明细_(\d+)\s*$", n)
        if m2:
            i = int(m2.group(1))
            if i not in details:
                details[i] = n
            continue
        if n == "机票报销":
            details.setdefault(1, n)
    return details


def iter_ticket_cover_detail_pairs(sheet_names: list[str]) -> list[tuple[str, str, int]]:
    """配对 机票报销封面[_n] 与 机票报销明细[_n]（兼容历史 sheet 名与尾部匹配）。"""
    covers = _ticket_cover_index_map(sheet_names)
    details = _ticket_detail_index_map(sheet_names)
    common = sorted(set(covers) & set(details))
    return [(covers[i], details[i], i) for i in common]


def list_ticket_cover_sheet_names_ordered(sheet_names: list[str]) -> list[str]:
    """工作簿内全部机票封面 sheet，按封面序号升序。用于汇总方案写回 E4（多封面同一方案名）。"""
    cov = _ticket_cover_index_map(sheet_names)
    return [cov[i] for i in sorted(cov)]


def run_ticket_cover_fill(
    input_xlsx: Path,
    log_path: Path,
    *,
    ui_company_name: str | None = None,
    output_xlsx: Path | None = None,
    joiner: str | None = None,
) -> Path:
    """填写机票类封面 C4～F4：项目类别固定为 TICKET_COVER_CATEGORY_LABELS 四项；
    服务院校为购买方公司在设置名单中的**全部**院校；时间由开票日期汇总。"""
    input_xlsx = Path(input_xlsx)
    log_path = Path(log_path)
    save_path = Path(output_xlsx) if output_xlsx is not None else input_xlsx
    j = joiner or str(SETTINGS.get("schools_joiner") or "、")

    if output_xlsx is not None:
        shutil.copy2(input_xlsx, save_path)
    wb = load_workbook(save_path)
    pairs = iter_ticket_cover_detail_pairs(list(wb.sheetnames))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    theme_placeholder = "（待大模型生成：活动主题 / 项目明细表述）"
    schools_map = load_ticket_company_schools_runtime()

    with open(log_path, "w", encoding="utf-8") as logf:
        if not pairs:
            logf.write(
                json.dumps(
                    {"status": "skip", "messages": ["工作簿中无成对的机票封面与机票明细 sheet"]},
                    ensure_ascii=False,
                )
                + "\n"
            )
            wb.save(save_path)
            return save_path

        for cover_name, detail_name, idx in pairs:
            rec: dict[str, Any] = {
                "kind": "ticket_cover",
                "group_index": idx,
                "cover_sheet": cover_name,
                "detail_sheet": detail_name,
                "status": "ok",
                "messages": [],
            }
            dws = wb[detail_name]
            cws = wb[cover_name]
            header = find_ticket_detail_header_row(dws)
            if not header:
                rec["status"] = "error"
                rec["messages"].append("机票明细未找到表头（需含开票日期、购买方公司名称或购买方名称）")
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            hr = int(header["_row"])
            date_c = header["开票日期"]
            buyer_c = int(header["_buyer_col"])

            buyers: list[str] = []
            dates: list[datetime] = []
            for r in range(hr + 1, dws.max_row + 1):
                bv = dws.cell(row=r, column=buyer_c).value
                if bv is not None and str(bv).strip():
                    buyers.append(str(bv).strip())
                pd = parse_invoice_date(dws.cell(row=r, column=date_c).value)
                if pd:
                    dates.append(pd)

            canon, err = _canonical_ticket_company(buyers, ui_company_name, schools_map)
            if err or not canon:
                rec["status"] = "error"
                rec["messages"].append(err or "无法确定购买方公司")
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            pool = schools_map.get(canon) or []
            schools_unique = _school_names_in_pool_order(pool)
            if not schools_unique:
                rec["messages"].append(
                    "当前公司在 ticket_company_schools.json（或内置默认）中无院校条目，D4 为空"
                )
            else:
                rec["messages"].append(
                    f"服务院校：已写入该公司全部 {len(schools_unique)} 所"
                )

            time_str = format_month_range(dates)
            if not dates:
                rec["messages"].append("未解析到任何开票日期，时间为空")

            schools_str = j.join(schools_unique)
            cats_str = j.join(TICKET_COVER_CATEGORY_LABELS)

            set_cover_block_style(cws)
            write_merged_top_left(cws, "C4", cats_str)
            write_merged_top_left(cws, "D4", schools_str)
            write_merged_top_left(cws, "E4", theme_placeholder)
            write_merged_top_left(cws, "F4", time_str)

            rec["filled"] = {
                "购买方公司": canon,
                "项目类别": cats_str,
                "服务院校": schools_str,
                "项目明细": theme_placeholder,
                "时间": time_str,
            }
            logf.write(json.dumps(rec, ensure_ascii=False) + "\n")

    wb.save(save_path)
    return save_path


def try_build_docx_placeholder(
    out_docx: Path,
    *,
    theme: str,
    schools: str,
    categories: str,
    time_span: str,
    major: str,
) -> None:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return
    doc = Document()
    t = doc.add_heading(theme or "（活动主题待生成）", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"专业方向：{major}")
    doc.add_paragraph(f"服务院校：{schools}")
    doc.add_paragraph(f"项目类别：{categories}")
    doc.add_paragraph(f"活动周期：{time_span}")
    doc.add_paragraph("")
    doc.add_paragraph(
        "【说明】尚未接入大模型 API。接入后请用正式模板替换本占位文档，"
        "并删除文中可能出现的 AI 声明字样。"
    )
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_docx)


def run(
    input_xlsx: Path,
    log_path: Path,
    *,
    output_xlsx: Path | None = None,
    write_placeholder_docx: bool = False,
    settings_overrides: dict[str, Any] | None = None,
    ui_company_name: str | None = None,
) -> Path:
    """填写产教融合封面 C4~F4。

    服务院校：能解析到 project_company_schools.json 中的公司键时，从该公司院校名单**随机**抽取 2～4 所；
    否则 D4 留空（不再按开票城市或内置地区表推断）。购买方与界面公司名称「不一致」时该封面记为错误并跳过。

    若 ``output_xlsx`` 为 ``None``，则直接打开并保存 ``input_xlsx``（与发票分类输出同一路径）。
    否则先 ``copy2`` 到输出路径再处理（CLI 用）。
    返回最终写入的 xlsx 路径。
    """
    input_xlsx = Path(input_xlsx)
    log_path = Path(log_path)
    save_path = Path(output_xlsx) if output_xlsx is not None else input_xlsx

    settings = copy.deepcopy(SETTINGS)
    if settings_overrides:
        settings.update(settings_overrides)
    cat_cfg = copy.deepcopy(PROJECT_CATEGORIES)

    all_cats = list(cat_cfg["all"])
    tag_rules = {
        k: v
        for k, v in (cat_cfg.get("tag_rules") or {}).items()
        if not str(k).startswith("_")
    }

    mode = settings.get("category_mode", "random")
    seed = settings.get("random_seed")
    rng = random.Random(seed) if seed is not None else random.Random()

    cmin = int(settings.get("category_count_min", 3))
    cmax = int(settings.get("category_count_max", 4))
    cover_token = settings.get("cover_title_contains", "产教融合项目")
    detail_suffixes = list(settings.get("detail_name_suffixes", ["明细", "-明细"]))
    tag_col = settings.get("detail_tag_column", "分类标签")
    fallback_tag = settings.get("fallback_detail_tag_column", "预测分类标签")
    joiner = settings.get("schools_joiner", "、")
    major = settings.get("major_for_docx_placeholder", "艺术设计")

    if output_xlsx is not None:
        shutil.copy2(input_xlsx, save_path)
    wb = load_workbook(save_path)
    proj_schools_map = load_project_company_schools_runtime()

    pairs = pair_covers_details(wb.sheetnames, cover_token, detail_suffixes)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as logf:
        for cover_name, detail_name in pairs:
            rec: dict[str, Any] = {
                "cover_sheet": cover_name,
                "detail_sheet": detail_name,
                "status": "ok",
                "messages": [],
            }
            if not detail_name:
                rec["status"] = "error"
                rec["messages"].append("未找到可配对的明细 sheet")
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            if detail_name not in wb.sheetnames or cover_name not in wb.sheetnames:
                rec["status"] = "error"
                rec["messages"].append("sheet 名称在工作簿中不存在")
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            dws = wb[detail_name]
            cws = wb[cover_name]
            header = find_header_row(
                dws,
                ("开票日期", "开票城市", tag_col, fallback_tag, "购买方公司名称", "购买方名称"),
            )
            if not header:
                rec["status"] = "error"
                rec["messages"].append("明细表未找到「开票日期」表头行（及分类/购买方等列）")
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            hr = int(header["_row"])
            date_c = header["开票日期"]
            tag_c = header.get(tag_col) or header.get(fallback_tag)
            buyer_c = header.get("购买方公司名称") or header.get("购买方名称")

            dates: list[datetime] = []
            tags: list[str] = []
            buyers: list[str] = []
            for r in range(hr + 1, dws.max_row + 1):
                pd = parse_invoice_date(dws.cell(r, date_c).value)
                if pd:
                    dates.append(pd)
                if buyer_c:
                    bv = dws.cell(r, int(buyer_c)).value
                    if bv is not None and str(bv).strip():
                        buyers.append(str(bv).strip())
                if tag_c:
                    tv = dws.cell(r, tag_c).value
                    if tv is not None and str(tv).strip():
                        tags.append(str(tv).strip())

            time_str = format_month_range(dates)
            if not dates:
                rec["messages"].append("未解析到任何开票日期，时间为空")

            canon, proj_err = _canonical_ticket_company(
                buyers, ui_company_name, proj_schools_map
            )
            schools_unique: list[str] = []

            if canon:
                pool = proj_schools_map.get(canon) or []
                schools_unique = _schools_for_project_cover_random_buyer_pool(
                    pool, rng, min_count=2, max_count=4
                )
                if not schools_unique:
                    rec["messages"].append(
                        "购买方公司已识别，但院校名单为空，D4 未写入服务院校"
                    )
                else:
                    rec["messages"].append(
                        f"服务院校：从「{canon}」名单随机抽取 {len(schools_unique)} 所（2～4）"
                    )
            else:
                if _project_cover_company_conflict(proj_err):
                    rec["status"] = "error"
                    rec["messages"].append(proj_err or "无法确定购买方公司")
                    logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    continue
                schools_unique = []
                rec["messages"].append(
                    proj_err
                    or "未识别购买方公司对应名单，服务院校 D4 留空（已取消按开票城市/地区表推断）。"
                )

            schools_str = joiner.join(schools_unique)

            if mode == "rules":
                cats = pick_categories_rules(tags, tag_rules, all_cats, rng, cmin, cmax)
            else:
                cats = pick_categories_random(all_cats, rng, cmin, cmax)
            cats_str = joiner.join(cats)

            theme_placeholder = "（待大模型生成：活动主题 / 项目明细表述）"

            set_cover_block_style(cws)
            write_merged_top_left(cws, "C4", cats_str)
            write_merged_top_left(cws, "D4", schools_str)
            write_merged_top_left(cws, "E4", theme_placeholder)
            write_merged_top_left(cws, "F4", time_str)

            filled_rec: dict[str, Any] = {
                "项目类别": cats_str,
                "服务院校": schools_str,
                "项目明细": theme_placeholder,
                "时间": time_str,
            }
            if canon:
                filled_rec["购买方公司(白名单)"] = canon
            rec["filled"] = filled_rec

            if write_placeholder_docx:
                safe = re.sub(r'[\\/:*?"<>|]', "_", cover_name)[:80]
                docx_path = save_path.parent / f"{safe}_方案占位.docx"
                try_build_docx_placeholder(
                    docx_path,
                    theme=theme_placeholder,
                    schools=schools_str,
                    categories=cats_str,
                    time_span=time_str,
                    major=major,
                )
                if docx_path.exists():
                    rec["docx_placeholder"] = str(docx_path)

            logf.write(json.dumps(rec, ensure_ascii=False) + "\n")

    wb.save(save_path)
    return save_path


def main() -> None:
    ap = argparse.ArgumentParser(description="按明细自动填写封面 C4~F4（单文件，无外部配置）")
    ap.add_argument("input", type=Path, help="输入 xlsx（完成前）")
    ap.add_argument("-o", "--output", type=Path, required=True, help="输出 xlsx 路径")
    ap.add_argument("--log", type=Path, required=True, help="批量日志（JSON Lines）")
    ap.add_argument(
        "--docx-placeholder",
        action="store_true",
        help="为每个封面生成简易占位 .docx（需安装 python-docx）",
    )
    ap.add_argument(
        "--category-mode",
        choices=("random", "rules"),
        default=None,
        help="覆盖本文件 SETTINGS 中的 category_mode",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="覆盖 SETTINGS['random_seed']；不设则使用文件内配置",
    )
    ap.add_argument(
        "--no-seed",
        action="store_true",
        help="每次随机（将 random_seed 置为 None）",
    )
    args = ap.parse_args()

    overrides: dict[str, Any] = {}
    if args.category_mode is not None:
        overrides["category_mode"] = args.category_mode
    if args.no_seed:
        overrides["random_seed"] = None
    elif args.seed is not None:
        overrides["random_seed"] = args.seed

    run(
        args.input,
        args.log,
        output_xlsx=args.output,
        write_placeholder_docx=args.docx_placeholder,
        settings_overrides=overrides or None,
    )


if __name__ == "__main__":
    main()
