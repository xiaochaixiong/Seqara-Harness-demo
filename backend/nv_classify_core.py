# -*- coding: utf-8 -*-
"""发票分类（分类测试 V0.59）。从「工具集V4.3 CTK替换新UI底层.py」抽出，供 PySide6 调用。"""
from __future__ import annotations

import json
import hashlib
import os
import random
import re
import threading
import time
from collections import defaultdict
from copy import copy as _cp
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from nv_data_safety import new_output_path, staged_outputs

config_base_path = os.path.abspath(os.path.dirname(__file__))


def set_classify_config_dir(path: str) -> None:
    global config_base_path
    config_base_path = os.path.abspath(path)


# ========================= 基本信息（可按需修改） =========================
COMPANY_NAME = "示例公司"
GROUP_COVER_PREFIX = "示例产教融合项目"  # 分组封面sheet前缀
# 机票类明细 sheet：机票报销明细_1、机票报销明细_2 …（与历史「机票报销」「机票报销_N」区分）
TICKET_DETAIL_SHEET_PREFIX = "机票报销明细"
# 机票类封面 sheet：机票报销封面_1、机票报销封面_2 …
TICKET_COVER_SHEET_PREFIX = "机票报销封面"
COVER_SERIES = 1                  # “2-?” 中的 “2”
START_INDEX_FOR_GROUP = 2         # 分组封面从 2-2 开始编号；2-1 预留给机票


# ========================= 标签、顺序、颜色 =========================
LABEL_ORDER = [
    "交通费",
    "邮寄费",
    "住宿费",
    "餐饮招待费",
    "茶歇费",
    "服务费",           # ← 合并：培训/考察费 + 咨询/服务费
    "办公用品",
    "通讯费",
    "电费",
    "保险费",
    "招待用品",
    "服装费",
    "物料费",
    "日用杂项",
    "未分类",
]

# 强优先（遇到就直接定类，覆盖星标/关键词）
STRONG_LABELS: Dict[str, List[str]] = {
    "住宿费": ["住宿", "房费"],
}

# —— 硬优先：整行匹配到就直接判为“交通费”（覆盖 *旅游服务*代订租车费）——
TRANSPORT_HARD_TRIGGERS = ["租车", "代订租车费"]

# 关键词库（常规匹配，顺序按 LABEL_ORDER）
KEYWORDS: Dict[str, List[str]] = {
    "住宿费": ["住宿","房费"],

    "交通费": [
        "过路费","运输","高铁","火车票","代订机票","汽油","停车","物流",
        "大巴","租车","车","柴油","客运","机票款","代订附加","航空运输",
        "通行","通行费","代订租车费","出行"
    ],

    "邮寄费": [
        "运输", "物流", "航空运输", "邮寄", "邮费", "顺丰"
    ],

    "餐饮招待费": ["餐饮","招待","餐费"],

    "茶歇费": [
        "食品","水果","饮料","肉","果","乳","奶","水产","调味品","农副",
        "肉制品","谷物","蔬菜","植物油","焙烤食品","蛋糕","面包","糕点","饼干","零食","牛肉肠","香肠"
    ],

    # 合并后的“服务费”关键词 = 原“咨询/服务费” + “培训/考察费”
    "服务费": [
        "设计服务","广告","技术服务","摄影摄像费","广播影视服务","咨询","生活服务","设计","会议","现代服务",
        "旅游","图书","教育服务","培训","门票","场地租赁费","设备租赁费","会务","接待","会展服务"
    ],

    # 去掉“纸制品/纸”，避免误将“纸面巾/餐巾纸”等判到办公
    "办公用品": [
        "机械","电子","文具","打印","通讯设备","通信设备","印刷",
        "计算机","体育用品","器材","仪器","仪","手机","交通运输设备",
        "显示器","键盘","鼠标","主机","显卡","板卡","办公用品"
    ],

    "通讯费": ["电信","话费","通讯"],

    "电费": ["电费","供电"],

    "保险费": ["保险服务","保险","航意险","运输保险","客运保险","车辆保险","意外险"],

    # 「包」类高价皮具见物料费规则（金额>2000+皮革毛皮+包）；珠宝/首饰品类见物料费关键词（避免 *珠宝首饰*首饰品 等判为招待）
    "招待用品": ["酒","烟","茶叶","箱","茶"],

    "服装费": ["服装","帽","鞋","衣服"],

    # 贵金属珠宝、首饰品等发票项目（与星标术语兜底 classify_keywords_first 一致）
    "物料费": ["珠宝首饰", "首饰品", "珠宝"],

    "日用杂项": [
        "日常","护肤","休闲","日用","杂品","玩具","工艺",
        "纺织","布","餐饮具","非金属矿物制品","家用器具","家具","药品","家用",
        "金属制品","药","塑料","产品","包装费","配送费"
    ],
}

# 排除词（例如“保险费”避免命中“保险柜/保险箱/保险杠/保险盒”）
NEGATIVE_TERMS: Dict[str, List[str]] = {
    "保险费": ["保险柜","保险箱","保险杠","保险盒"],
}

# ========================= 关键词持续学习（权重/阈值） =========================
# 目标：把人工在“明细中的分类标签”修正后的差异回流到关键词判定里，
#      让同一类“XXX费”的识别越来越稳（避免无限堆关键词）。
LEARNING_STATE_FILE = "invoice_keyword_learning_state.json"

DEFAULT_KW_WEIGHT = 1.0
DEFAULT_LABEL_THRESHOLD = 1.0

KW_WEIGHT_MIN = 0.05
KW_WEIGHT_MAX = 5.0
LABEL_THRESHOLD_MIN = 0.5
LABEL_THRESHOLD_MAX = 10.0

# 单样本更新幅度（小步学习，避免一次回流改坏）
LEARNING_LR_INC = 0.15   # 正样本：正确类关键词权重 +v
LEARNING_LR_DEC = 0.10   # 负样本：错误类关键词权重 -v
LEARNING_LR_TH_INC = 0.05  # 错误类阈值 +v
LEARNING_LR_TH_DEC = 0.05  # 正确类阈值 -v


def _learning_state_path() -> str:
    return os.path.join(config_base_path, LEARNING_STATE_FILE)


# 运行期可被 load_keyword_learning_state 覆盖
KEYWORD_WEIGHTS: Dict[str, Dict[str, float]] = {
    lab: {kw: DEFAULT_KW_WEIGHT for kw in kws}
    for lab, kws in KEYWORDS.items()
}
LABEL_THRESHOLDS: Dict[str, float] = {
    lab: DEFAULT_LABEL_THRESHOLD for lab in LABEL_ORDER if lab != "未分类"
}
LEARNED_FEEDBACK_IDS: set[str] = set()
MAX_LEARNED_FEEDBACK_IDS = 10000


def load_keyword_learning_state() -> None:
    """从本地 json 读取学习状态；缺失字段自动回填默认值。"""
    global KEYWORD_WEIGHTS, LABEL_THRESHOLDS, LEARNED_FEEDBACK_IDS
    p = _learning_state_path()
    if not os.path.isfile(p):
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            st = json.load(f)
        weights_in = st.get("keyword_weights") or {}
        thresholds_in = st.get("label_thresholds") or {}
        learned_in = st.get("processed_feedback_ids") or []
        if isinstance(learned_in, list):
            LEARNED_FEEDBACK_IDS = {
                str(value) for value in learned_in[-MAX_LEARNED_FEEDBACK_IDS:] if value
            }

        # weights：只更新 KEYWORDS 里存在的关键词
        for lab, kws in KEYWORDS.items():
            KEYWORD_WEIGHTS.setdefault(lab, {})
            for kw in kws:
                val = ((weights_in.get(lab) or {}).get(kw))
                if isinstance(val, (int, float)):
                    v = float(val)
                    v = min(max(v, KW_WEIGHT_MIN), KW_WEIGHT_MAX)
                    KEYWORD_WEIGHTS[lab][kw] = v
                else:
                    KEYWORD_WEIGHTS[lab][kw] = KEYWORD_WEIGHTS[lab].get(kw, DEFAULT_KW_WEIGHT)

        # thresholds：只更新 LABEL_ORDER 里存在的类
        for lab in LABEL_THRESHOLDS.keys():
            val = thresholds_in.get(lab, None)
            if isinstance(val, (int, float)):
                v = float(val)
                v = min(max(v, LABEL_THRESHOLD_MIN), LABEL_THRESHOLD_MAX)
                LABEL_THRESHOLDS[lab] = v
    except Exception:
        # 学习文件损坏时不影响主流程
        return


def save_keyword_learning_state() -> None:
    """保存学习状态到本地 json。"""
    try:
        p = _learning_state_path()
        st = {
            "version": 2,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword_weights": KEYWORD_WEIGHTS,
            "label_thresholds": LABEL_THRESHOLDS,
            "processed_feedback_ids": sorted(LEARNED_FEEDBACK_IDS)[-MAX_LEARNED_FEEDBACK_IDS:],
        }
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        return


def keyword_learning_summary() -> Dict[str, int]:
    """Return a compact, UI-safe summary of the persisted learning state."""
    load_keyword_learning_state()
    changed_weights = sum(
        1
        for weights in KEYWORD_WEIGHTS.values()
        for value in weights.values()
        if abs(float(value) - DEFAULT_KW_WEIGHT) > 1e-9
    )
    changed_thresholds = sum(
        1
        for value in LABEL_THRESHOLDS.values()
        if abs(float(value) - DEFAULT_LABEL_THRESHOLD) > 1e-9
    )
    return {
        "feedback_count": len(LEARNED_FEEDBACK_IDS),
        "changed_weights": changed_weights,
        "changed_thresholds": changed_thresholds,
    }


def reset_keyword_learning_state() -> None:
    """Restore in-memory learning values and remove the persisted feedback state."""
    global KEYWORD_WEIGHTS, LABEL_THRESHOLDS, LEARNED_FEEDBACK_IDS
    KEYWORD_WEIGHTS = {
        lab: {kw: DEFAULT_KW_WEIGHT for kw in kws}
        for lab, kws in KEYWORDS.items()
    }
    LABEL_THRESHOLDS = {
        lab: DEFAULT_LABEL_THRESHOLD for lab in LABEL_ORDER if lab != "未分类"
    }
    LEARNED_FEEDBACK_IDS = set()
    try:
        os.remove(_learning_state_path())
    except FileNotFoundError:
        pass


def _feedback_signature(key: str, predicted: str, corrected: str, evidence_json: str) -> str:
    raw = "\x1f".join((key, predicted, corrected, evidence_json))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def keyword_match_details(merged_text: str) -> Tuple[Dict[str, List[str]], Dict[str, float]]:
    """
    返回：
      matched_keywords_by_label: {label: [kw1, kw2, ...]}（已应用排除词逻辑；命中但被排除则该 label 置空）
      score_by_label: {label: score}
    """
    t_raw = merged_text
    t_norm = norm_text(merged_text)
    matched: Dict[str, List[str]] = {}
    scores: Dict[str, float] = {}

    for lab in LABEL_ORDER:
        if lab == "未分类":
            continue
        kws = KEYWORDS.get(lab, [])
        if not kws:
            continue
        negs = NEGATIVE_TERMS.get(lab, [])

        hits: List[str] = []
        for kw in kws:
            nkw = norm_text(kw)
            if nkw and nkw in t_norm:
                hits.append(kw)

        # label 命中但触发排除词 => 认为该 label 无效（得分置 0）
        if hits and negs and (not _text_contains_none(t_raw, negs)):
            hits = []

        if hits:
            matched[lab] = hits
        score = 0.0
        if hits:
            wmap = KEYWORD_WEIGHTS.get(lab) or {}
            score = sum(float(wmap.get(kw, DEFAULT_KW_WEIGHT)) for kw in hits)

        scores[lab] = score

    return matched, scores


def keyword_evidence_json(merged_text: str) -> str:
    matched, _ = keyword_match_details(merged_text)
    return json.dumps(matched, ensure_ascii=False)


def _normalize_date_for_key(v) -> str:
    try:
        from datetime import datetime, date
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, date):
            return v.strftime("%Y-%m-%d")
    except Exception:
        pass
    s = "" if v is None else str(v).strip()
    s = re.sub(r"\s+00:00:00(\.0+)?$", "", s)
    return s


def _find_amount_col(header_map: Dict[str, int]) -> Optional[int]:
    for k in AMOUNT_KEYS:
        col = header_map.get(k)
        if col:
            return col
    return None


INVOICE_ROW_ID = 'Seqara发票标识'


def make_invoice_key(ws: Worksheet, header_map: Dict[str,int], row: int, amount_col: int, *, legacy=False) -> str:
    """
    用于“证据(分类&分组)”与“人工修正(明细)”之间的行对齐。
    优先用（发票号码 + 开票日期 + 金额），缺失时回退到（序号 + 金额）。
    """
    identity_col = header_map.get(INVOICE_ROW_ID)
    if not legacy and identity_col and ws.cell(row, identity_col).value:
        return str(ws.cell(row, identity_col).value)
    inv_no_col = header_map.get("发票号码")
    date_col = header_map.get("开票日期")
    seq_col = header_map.get("序号")

    inv_no = ws.cell(row=row, column=inv_no_col).value if inv_no_col else None
    date_v = ws.cell(row=row, column=date_col).value if date_col else None
    seq_v = ws.cell(row=row, column=seq_col).value if seq_col else None
    amt_v = ws.cell(row=row, column=amount_col).value
    amt = parse_amount(amt_v)
    amt_s = str(round(float(amt), 2))
    inv_no_s = "" if inv_no is None else str(inv_no).strip()
    date_s = _normalize_date_for_key(date_v)
    if inv_no_s:
        return f"inv:{inv_no_s}|date:{date_s}|amt:{amt_s}"
    if seq_v is not None and str(seq_v).strip():
        return f"seq:{str(seq_v).strip()}|amt:{amt_s}"
    content = '|'.join(norm_text(ws.cell(row, header_map[k]).value) for k in PRIMARY_FIELDS if k in header_map)
    return f"content:{hashlib.sha1(content.encode('utf8')).hexdigest()}|date:{date_s}|amt:{amt_s}"


def try_update_keyword_learning_from_previous_outputs(wb_style: "openpyxl.Workbook") -> int:
    """
    从“已人工修正过”的结果 Excel 中读取差异，更新本地关键词权重/阈值。
    需要你使用同一份输出文件（或保留了“分类&分组/报销明细”这些sheet的文件）再次运行。
    """
    updated = 0

    if "分类&分组" not in wb_style.sheetnames:
        return 0

    ws_group = wb_style["分类&分组"]
    hr_group = detect_header_row(ws_group)
    if not hr_group:
        return 0
    header_group = build_header_map(ws_group, hr_group)

    evidence_col = header_group.get("关键词证据(JSON)")
    why_col = header_group.get("命中关键词/说明")
    amount_col = _find_amount_col(header_group)
    if not evidence_col or not why_col or not amount_col:
        return 0

    # key -> (is_keyword_stage, evidence_json)
    evidence_map: Dict[str, Tuple[bool, str]] = {}
    for r in range(hr_group + 1, ws_group.max_row + 1):
        ev = ws_group.cell(row=r, column=evidence_col).value
        if not ev:
            continue
        why = ws_group.cell(row=r, column=why_col).value
        is_kw_stage = "[关键词]" in str(why) if why is not None else False
        key = make_invoice_key(ws_group, header_group, r, amount_col)
        evidence_map[key] = (is_kw_stage, str(ev))

    # 扫描所有“明细”sheet：读取分类标签(人工)与预测分类标签(PY基线)差异
    for ws in wb_style.worksheets:
        hr = detect_header_row(ws)
        if not hr:
            continue
        header = build_header_map(ws, hr)
        class_col = header.get("分类标签")
        pred_col = header.get("预测分类标签")
        amt_col = _find_amount_col(header)
        if not class_col or not pred_col or not amt_col:
            continue

        for r in range(hr + 1, ws.max_row + 1):
            corr_lab = ws.cell(row=r, column=class_col).value
            pred_lab = ws.cell(row=r, column=pred_col).value
            if corr_lab is None or pred_lab is None:
                continue
            corr_lab_s = str(corr_lab).strip()
            pred_lab_s = str(pred_lab).strip()
            if not corr_lab_s or not pred_lab_s:
                continue
            if corr_lab_s == pred_lab_s:
                continue

            key = make_invoice_key(ws, header, r, amt_col)
            ev = evidence_map.get(key)
            if not ev:
                continue
            is_kw_stage, ev_json = ev
            if not is_kw_stage:
                continue

            try:
                matched_by_label = json.loads(ev_json) if ev_json else {}
            except Exception:
                continue
            feedback_id = _feedback_signature(key, pred_lab_s, corr_lab_s, ev_json)
            if feedback_id in LEARNED_FEEDBACK_IDS:
                continue

            # 权重更新：错误类关键词 -v；正确类关键词 +v
            if pred_lab_s in KEYWORD_WEIGHTS:
                for kw in matched_by_label.get(pred_lab_s, []) or []:
                    old = KEYWORD_WEIGHTS[pred_lab_s].get(kw, DEFAULT_KW_WEIGHT)
                    new_v = max(KW_WEIGHT_MIN, float(old) - LEARNING_LR_DEC)
                    KEYWORD_WEIGHTS[pred_lab_s][kw] = new_v

            if corr_lab_s in KEYWORD_WEIGHTS:
                for kw in matched_by_label.get(corr_lab_s, []) or []:
                    old = KEYWORD_WEIGHTS[corr_lab_s].get(kw, DEFAULT_KW_WEIGHT)
                    new_v = min(KW_WEIGHT_MAX, float(old) + LEARNING_LR_INC)
                    KEYWORD_WEIGHTS[corr_lab_s][kw] = new_v

            # 阈值微调（让“正确类更容易抢占”，“错误类更不容易抢占”）
            if pred_lab_s in LABEL_THRESHOLDS:
                LABEL_THRESHOLDS[pred_lab_s] = min(
                    LABEL_THRESHOLD_MAX,
                    float(LABEL_THRESHOLDS[pred_lab_s]) + LEARNING_LR_TH_INC
                )
            if corr_lab_s in LABEL_THRESHOLDS:
                LABEL_THRESHOLDS[corr_lab_s] = max(
                    LABEL_THRESHOLD_MIN,
                    float(LABEL_THRESHOLDS[corr_lab_s]) - LEARNING_LR_TH_DEC
                )

            LEARNED_FEEDBACK_IDS.add(feedback_id)
            if len(LEARNED_FEEDBACK_IDS) > MAX_LEARNED_FEEDBACK_IDS:
                LEARNED_FEEDBACK_IDS.pop()
            updated += 1

    if updated > 0:
        save_keyword_learning_state()
    return updated

# 标签配色（用于明细中“发票项目”列着色）——对比度明显
COLOR_BY_LABEL = {
    "交通费":         "FFDBEAFE",
    "邮寄费":         "91AADF",
    "住宿费":         "FFDCFCE7",
    "餐饮招待费":     "FFFFCDD2",  # 粉红
    "茶歇费":     "FFB2DFDB",  # 青绿
    "服务费":         "FFFDE68A",
    "办公用品":       "FFE2E8F0",
    "通讯费":         "FFEDE9FE",
    "电费":           "FFE9D5FF",
    "保险费":         "FFCCE5FF",
    "招待用品":         "FFD1FAE5",
    "服装费":         "A06CD0",
    "物料费":         "FFCFFAFE",  # 浅青，与办公/日用区分
    "日用杂项":       "FFF1F5F9",
    "未分类":         "FFFFFFFF",
}

# 主要/次要字段（组合文本做关键词匹配）
PRIMARY_FIELDS = [
    "发票项目","费用名称","发票内容",
    "货物或应税劳务、服务名称","货物或应税劳务服务名称",
    "商品名称","品名","用途","事由"
]
SECONDARY_FIELDS = ["摘要","备注","备注说明","说明","明细"]
AMOUNT_KEYS = ["金额（元）","金额"]


# ========================= 星标优先（发票项目列 *术语*） =========================
# 食饮类星标：命中 → 茶歇费
FOOD_STAR_TO_TEA: List[str] = [
    "焙烤食品","肉及肉制品","食品","饮料","乳制品","牛奶","酸奶","咖啡","茶饮料",
    "方便食品","休闲食品","零食","谷物","植物油","调味品","肉制品","水产","蔬菜","水果"
]
# 生活杂物星标：命中 → 日用杂项（除非触发纸制品办公细则）
LIFE_STAR_TO_MISC: List[str] = [
    "日用杂品","日用品","清洁用品","清洁用具","洗手液","塑料制品","非金属矿物制品",
    "家用器具","家居用品","餐饮具","工艺品","玩具"
]
# 纸制品命中“办公纸张”的提示词（命中这些就归办公）
OFFICE_PAPER_HINTS: List[str] = [
    "a4纸","复印纸","打印纸","档案","档案盒","档案袋","标签纸","收据","打印机纸","复印机纸"
]

# 其他星标直映射
STAR_PRIORITY_MAP = {
    # 设备直归 办公用品
    "移动通信设备": "办公用品",
    "通信设备": "办公用品",
    "通讯设备": "办公用品",
    "交通运输设备": "办公用品",

    # 交通
    "通行费": "交通费",
    "租车": "交通费",
    "运输服务": "交通费",
    "客运服务": "交通费",

    # 招待用品（注意：*酒* 的“长尾+非酒星标”规则会先行拦截）
    "酒": "招待用品",
    "酒水": "招待用品",
    "白酒": "招待用品",
    "葡萄酒": "招待用品",
    "啤酒": "招待用品",

    # 服务（合并到“服务费”）
    "现代服务": "服务费",
    "生活服务": "服务费",

    # 保险
    "保险服务": "保险费",
    "航意险": "保险费",
}
STAR_PATTERN = re.compile(r"\*([^*]+)\*")  # 抽取 *……* 内术语

# *酒* 长尾阈值（可调）
WINE_LONG_TAIL_THRESHOLD = 35
# 视为“酒类”的星标术语（用于排除）
WINE_STAR_TERMS = [
    "酒","酒水","白酒","红酒","黄酒","啤酒","米酒","葡萄酒","果酒",
    "洋酒","威士忌","白兰地","伏特加","清酒","烈酒"
]


# ========================= 基础工具（规范化/样式复制/日期处理） =========================
def to_half(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000: code = 0x20
        elif 0xFF01 <= code <= 0xFF5E: code -= 0xFEE0
        out.append(chr(code))
    return "".join(out)

def norm_text(x) -> str:
    s = "" if x is None else str(x)
    s = to_half(s).lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\u4e00-\u9fa5a-z0-9]+", "", s)
    return s

def build_header_map(ws: Worksheet, header_row: int) -> Dict[str,int]:
    m: Dict[str,int] = {}
    for c in ws[header_row]:
        if c.value is None: continue
        key = str(c.value).strip()
        if key:
            m[key] = getattr(c, "column", getattr(c, "col_idx", 0))
    return m

def detect_header_row(ws: Worksheet, search_rows: int = 12) -> Optional[int]:
    want = ["发票项目"] + AMOUNT_KEYS
    best_row, best_cnt = None, -1
    for r in range(1, min(search_rows, ws.max_row) + 1):
        vals = [("" if c.value is None else str(c.value)) for c in ws[r]]
        text = " ".join(vals)
        cnt = sum(1 for k in want if k in text)
        if cnt > best_cnt:
            best_cnt, best_row = cnt, r
    return best_row

def ensure_sheet(wb, name: str):
    raw_name = name
    name = re.sub(r'[\\/*?:\[\]]', '_', name).strip("'") or '工作表'
    if len(name) > 31:
        name = name[:22] + '_' + hashlib.sha1(raw_name.encode('utf-8')).hexdigest()[:8]
    reserved = getattr(wb, '_seqara_reserved', set())
    base, index = name, 2
    while name in reserved:
        suffix = f'_{index}'
        name = base[:31-len(suffix)] + suffix
        index += 1
    if name in wb.sheetnames:
        del wb[name]
    return wb.create_sheet(title=name)


def _invoice_metadata(wb):
    return next((ws for ws in wb if ws.title.startswith('_Seqara处理信息')
                 and ws['A1'].value in ('Seqara invoice sources v1', 'Seqara invoice sources v2')), None)


def _invoice_overrides(wb):
    overrides = {}
    meta = _invoice_metadata(wb)
    if meta is not None and meta['B3'].value:
        overrides = json.loads(meta['B3'].value)
        if not isinstance(overrides, dict) or any(v not in LABEL_ORDER for v in overrides.values()):
            raise ValueError('发票人工分类记录损坏，请从原始发票表重新处理。')
    for ws in wb.worksheets:
        hr = detect_header_row(ws)
        header = build_header_map(ws, hr)
        if '预测分类标签' not in header or '分类标签' not in header:
            continue
        amount = _find_amount_col(header)
        if not amount:
            continue
        for row in range(hr + 1, ws.max_row + 1):
            corrected = norm_text(ws.cell(row, header['分类标签']).value)
            predicted = norm_text(ws.cell(row, header['预测分类标签']).value)
            if corrected and predicted and corrected != predicted:
                if corrected not in LABEL_ORDER:
                    raise ValueError(f'{ws.title} 第 {row} 行分类标签无效：{corrected}')
                overrides[make_invoice_key(ws, header, row, amount)] = corrected
    return overrides


def _invoice_sources(wb_style, wb_vals):
    """Resolve source sheets explicitly, and retain values/styles in one canonical table."""
    meta_name = '_Seqara处理信息'
    old_generated = set()
    selected = None
    meta = _invoice_metadata(wb_style)
    if meta is not None:
        selected = json.loads(meta['B1'].value)
        old_generated = set(json.loads(meta['B2'].value or '[]'))
        if not isinstance(selected, list) or not selected or any(not isinstance(name,str) or name not in wb_style for name in selected):
            raise ValueError('原始发票数据页已被删除或记录损坏，请重新选择原始工作簿。')
        if meta['A1'].value == 'Seqara invoice sources v1':
            # Old manifests accidentally listed user notes as generated pages.
            # Retain unrecognised sheets when upgrading those workbooks.
            def generated_page(name):
                if name not in wb_style:return False
                ws = wb_style[name]
                header = build_header_map(ws, detect_header_row(ws))
                invoice_table = '发票项目' in header and _find_amount_col(header)
                return ((invoice_table and name.startswith(('Seqara发票汇总源数据',TICKET_DETAIL_SHEET_PREFIX)))
                        or {'分类标签','分组编号'}.issubset(header)
                        or {'组内笔数','组内金额合计'}.issubset(header)
                        or (invoice_table and name.startswith('未分类_待处理') and '参考文本' in header)
                        or '预测分类标签' in header
                        or ('报销明细-' in str(ws['B2'].value) and ws['B3'].value == '序号'))
            old_generated = {name for name in old_generated if generated_page(name)}
    legacy_output = any('预测分类标签' in build_header_map(ws, detect_header_row(ws)).keys()
                        for ws in wb_style.worksheets)
    sources = []
    for ws in list(wb_style.worksheets):
        if ws is meta or (selected is not None and ws.title not in selected and ws.title in old_generated):
            continue
        hr = detect_header_row(ws)
        headers = build_header_map(ws, hr)
        if selected is None and legacy_output and (
            ws.title.startswith((TICKET_DETAIL_SHEET_PREFIX, TICKET_COVER_SHEET_PREFIX))
            or ws.title in ('分类&分组', '分组汇总', '分组统计', '未分类_待处理')
            or '预测分类标签' in headers
        ):
            old_generated.add(ws.title)
            continue
        item = next((headers[k] for k in ['发票项目','费用名称','发票内容','项目','用途','事由'] if k in headers), None)
        amount = next((headers[k] for k in AMOUNT_KEYS if k in headers), None)
        if item and amount:
            sources.append((ws, wb_vals[ws.title], hr, item, amount))
    if not sources:
        raise ValueError('未找到同时包含发票项目和金额的数据工作表。')
    # Validate original coordinates before changing workbook structure.
    rows = []
    columns = []
    for ws, vals, hr, item, amount in sources:
        mapping = {}
        for name, col in build_header_map(ws, hr).items():
            normalized = '发票项目' if col == item else '金额（元）' if col == amount else name
            mapping[col] = normalized
            if normalized not in columns:
                columns.append(normalized)
        for r in range(hr + 1, ws.max_row + 1):
            if not any(ws.cell(r, c).value not in (None, '') for c in mapping):
                continue
            item_text = norm_text(vals.cell(r, item).value)
            totals = ('合计', '总计', '小计', '总金额', '金额合计')
            # A note saying “合计” is still an invoice; only structural labels count.
            if item_text in totals or (not item_text and any(
                norm_text(vals.cell(r, c).value) in totals for c in mapping if c < item)):
                continue
            cell = ws.cell(r, amount)
            value = vals.cell(r, amount).value
            if cell.data_type == 'f' and value is None:
                raise ValueError(f'{ws.title}!{cell.coordinate} 金额公式没有计算结果，请用 Excel/WPS 重算并保存后重试。')
            try:
                parsed = parse_amount(value)
            except ValueError as exc:
                raise ValueError(f'{ws.title}!{cell.coordinate}：{exc}') from exc
            rows.append((ws, vals, r, mapping, amount, parsed))
    if not rows:
        raise ValueError('发票数据页没有可处理的明细行。')
    source_names = [ws.title for ws, *_ in sources]
    for name in old_generated:
        if name in wb_style and name not in source_names:
            del wb_style[name]
    if meta is not None:
        del wb_style[meta.title]
    wb_style._seqara_reserved = set(wb_style.sheetnames)
    canonical = ensure_sheet(wb_style, 'Seqara发票汇总源数据')
    canonical_vals = wb_vals.create_sheet(canonical.title)
    if INVOICE_ROW_ID not in columns:
        columns.append(INVOICE_ROW_ID)
    canonical.append(columns)
    canonical_vals.append(columns)
    for ws, _, hr, item, amount in sources:
        for name, col in build_header_map(ws, hr).items():
            normalized = '发票项目' if col == item else '金额（元）' if col == amount else name
            dest_col = columns.index(normalized) + 1
            letter = get_column_letter(dest_col)
            src_width = ws.column_dimensions[get_column_letter(col)].width
            canonical.column_dimensions[letter].width = max(canonical.column_dimensions[letter].width or 13, src_width or 13)
            if not canonical.cell(1, dest_col).has_style:
                apply_style_from(ws.cell(hr, col), canonical.cell(1, dest_col))
        canonical.row_dimensions[1].height = max(canonical.row_dimensions[1].height or 15, ws.row_dimensions[hr].height or 15)
    occurrences = defaultdict(int)
    for out_r, (ws, vals, r, mapping, amount, parsed) in enumerate(rows, 2):
        for c, name in mapping.items():
            out_c = columns.index(name) + 1
            dst = canonical.cell(out_r, out_c)
            dst.value = parsed if c == amount else vals.cell(r, c).value
            apply_style_from(ws.cell(r, c), dst)
            canonical_vals.cell(out_r, out_c).value = dst.value
        source_header = build_header_map(ws, detect_header_row(ws))
        content = [norm_text(vals.cell(r, source_header[k]).value) for k in PRIMARY_FIELDS if k in source_header]
        identity = json.dumps([ws.title, make_invoice_key(vals, source_header, r, amount, legacy=True), content], ensure_ascii=False)
        occurrences[identity] += 1
        row_id = 'row:' + hashlib.sha1(f'{identity}|{occurrences[identity]}'.encode('utf8')).hexdigest()
        id_col = columns.index(INVOICE_ROW_ID) + 1
        canonical.cell(out_r,id_col).value = row_id
        canonical_vals.cell(out_r,id_col).value = row_id
        copy_row_height(ws, canonical, r, out_r)
    meta = ensure_sheet(wb_style, meta_name)
    meta['A1'] = 'Seqara invoice sources v2'
    meta['B1'] = json.dumps(source_names, ensure_ascii=False)
    meta.sheet_state = 'hidden'
    wb_style._seqara_source_names = source_names
    wb_style._seqara_metadata_name = meta.title
    return canonical, canonical_vals, 1

def copy_column_widths(src: Worksheet, dst: Worksheet):
    for k, dim in src.column_dimensions.items():
        dst.column_dimensions[k].width = dim.width

def copy_row_height(src: Worksheet, dst: Worksheet, src_r: int, dst_r: int):
    h = src.row_dimensions[src_r].height
    if h is not None:
        dst.row_dimensions[dst_r].height = h

def apply_style_from(src_cell, dst_cell):
    try:
        if src_cell.has_style:
            if src_cell.font:        dst_cell.font        = _cp(src_cell.font)
            if src_cell.border:      dst_cell.border      = _cp(src_cell.border)
            if src_cell.fill:        dst_cell.fill        = _cp(src_cell.fill)
            if src_cell.alignment:   dst_cell.alignment   = _cp(src_cell.alignment)
            if src_cell.protection:  dst_cell.protection  = _cp(src_cell.protection)
            if src_cell.number_format:
                dst_cell.number_format = src_cell.number_format
    except Exception:
        dst_cell.number_format = src_cell.number_format

def paste_value_and_style(src_style_cell, src_value_cell, dst_cell):
    val = src_value_cell.value
    if val is None:
        sval = src_style_cell.value
        if not (isinstance(sval, str) and str(sval).startswith("=")):
            val = sval
    dst_cell.value = val
    apply_style_from(src_style_cell, dst_cell)

# 日期列：原样复制 + 若为纯数字但无日期格式，则套默认格式
DATE_FORMAT_DEFAULT = "yyyy-mm-dd"

def _looks_like_date_format(fmt: str) -> bool:
    if not fmt:
        return False
    f = fmt.lower()
    f = re.sub(r"\[[^\]]*\]", "", f)
    f = re.sub(r'"[^"]*"', "", f)
    if ("y" in f and "m" in f and "d" in f): return True
    if ("年" in fmt and "月" in fmt and "日" in fmt): return True
    if any(k in f for k in ("h", "s")) and ("y" in f or "m" in f or "d" in f): return True
    return False

DATE_HEADER_HINTS = ("日期", "时间")

def find_date_cols(header_map: Dict[str, int]) -> set:
    cols = set()
    for name, col in header_map.items():
        if any(h in str(name) for h in DATE_HEADER_HINTS):
            cols.add(col)
    return cols

def copy_row_dual(src_ws_style: Worksheet, src_ws_vals: Worksheet,
                  dst_ws: Worksheet, src_r: int, dst_r: int, max_col: int,
                  date_cols: Optional[set] = None):
    """值：来自 data_only 的 wb；样式：来自原样式 wb；日期列保持原式样，必要时套 yyyy-mm-dd"""
    copy_row_height(src_ws_style, dst_ws, src_r, dst_r)
    if date_cols is None:
        date_cols = set()

    for c in range(1, max_col + 1):
        s_style = src_ws_style.cell(row=src_r, column=c)
        s_vals  = src_ws_vals.cell(row=src_r, column=c)
        d_cell  = dst_ws.cell(row=dst_r, column=c)

        if c in date_cols:
            if isinstance(s_style.value, str) and s_style.value.startswith("="):
                d_cell.value = s_vals.value
                apply_style_from(s_style, d_cell)
            else:
                d_cell.value = s_style.value
                apply_style_from(s_style, d_cell)
            if isinstance(d_cell.value, (int, float)):
                fmt_src = s_style.number_format or ""
                if not _looks_like_date_format(fmt_src):
                    d_cell.number_format = DATE_FORMAT_DEFAULT
        else:
            paste_value_and_style(s_style, s_vals, d_cell)

def copy_row_dual_mapped(
    src_ws_style: Worksheet,
    src_ws_vals: Worksheet,
    dst_ws: Worksheet,
    src_r: int,
    dst_r: int,
    max_col: int,
    date_cols: Optional[set] = None,
    col_mapping: Optional[Dict[int, int]] = None,
):
    """
    在 copy_row_dual 的基础上，允许指定列映射：
    col_mapping: {原列 -> 目标列}，未指定的列默认保持不变。
    """
    copy_row_height(src_ws_style, dst_ws, src_r, dst_r)
    if date_cols is None:
        date_cols = set()
    if col_mapping is None:
        col_mapping = {}

    for c in range(1, max_col + 1):
        tgt_c = col_mapping.get(c, c)
        s_style = src_ws_style.cell(row=src_r, column=c)
        s_vals  = src_ws_vals.cell(row=src_r, column=c)
        d_cell  = dst_ws.cell(row=dst_r, column=tgt_c)

        if c in date_cols:
            if isinstance(s_style.value, str) and s_style.value.startswith("="):
                d_cell.value = s_vals.value
                apply_style_from(s_style, d_cell)
            else:
                d_cell.value = s_style.value
                apply_style_from(s_style, d_cell)
            if isinstance(d_cell.value, (int, float)):
                fmt_src = s_style.number_format or ""
                if not _looks_like_date_format(fmt_src):
                    d_cell.number_format = DATE_FORMAT_DEFAULT
        else:
            paste_value_and_style(s_style, s_vals, d_cell)

def color_cell(cell, argb: str):
    cell.fill = PatternFill(start_color=argb, end_color=argb, fill_type="solid")

def parse_amount(val) -> float:
    import math
    if val is None or isinstance(val, bool):
        raise ValueError("金额缺失或格式不正确，请核对金额单元格。")
    s = str(val).strip()
    s = re.sub(r'^(?:人民币|RMB|CNY|[￥¥])\s*', '', s, flags=re.I)
    s = re.sub(r'\s*元$', '', s)
    m = re.match(r"^\((.*)\)$", s)
    if m: s = "-" + m.group(1)
    if re.search(r'\s', s) or ((',' in s or '，' in s) and not re.fullmatch(r'[+-]?\d{1,3}(?:[,，]\d{3})+(?:\.\d+)?', s)):
        raise ValueError(f'金额分隔符格式不正确：{val}；例如 1,200.50。')
    s = re.sub(r'[,，]', '', s)
    try:
        amount = float(s)
    except (ValueError, TypeError):
        raise ValueError(f"无法识别金额：{val}；请填写有效数值。") from None
    if not math.isfinite(amount):
        raise ValueError("金额必须是有限数值。")
    return amount


# ========================= 分类：强优先 → 硬优先 → 星标(食饮>酒长尾+非酒星标>纸细则>生活杂物>映射) → 销售方 → 关键词 → 金额兜底 =========================
def extract_star_terms(raw) -> List[str]:
    if not raw:
        return []
    return STAR_PATTERN.findall(str(raw))

def _extract_star_terms_with_spans(text: str):
    """返回 [(术语, start, end), ...]，用于判断 *酒* 之后是否还有“非酒类星标”"""
    return [(m.group(1), m.start(), m.end()) for m in STAR_PATTERN.finditer(text or "")]

def collect_texts(ws: Worksheet, header_map: Dict[str,int], row: int) -> Tuple[str, Dict[str,str]]:
    field_texts: Dict[str,str] = {}
    for name in PRIMARY_FIELDS + SECONDARY_FIELDS:
        col = header_map.get(name)
        if not col: continue
        val = ws.cell(row=row, column=col).value
        field_texts[name] = "" if val is None else str(val)
    merged = " ".join([v for v in field_texts.values() if v])
    return merged, field_texts

def _text_contains_any(raw, terms) -> bool:
    t = norm_text("" if raw is None else str(raw))
    return any(norm_text(k) in t for k in terms)

def _text_contains_none(raw, terms) -> bool:
    if not terms:
        return True
    t = norm_text("" if raw is None else str(raw))
    return all(norm_text(k) not in t for k in terms)

def classify_keywords_first(merged_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    关键词阶段：把“命中即返回”升级为“按权重得分选择”。
    保留原有 LABEL_ORDER 的优先级：相当于阈值默认为 >=1 才会抢占更靠前的类别。
    """
    matched, scores = keyword_match_details(merged_text)

    for lab in LABEL_ORDER:
        if lab == "未分类":
            continue
        score = float(scores.get(lab, 0.0) or 0.0)
        th = float(LABEL_THRESHOLDS.get(lab, DEFAULT_LABEL_THRESHOLD))
        if score >= th:
            hits = matched.get(lab, []) or []
            # 只用于说明文本，不影响学习逻辑
            preview = "、".join(hits[:4]) if hits else ""
            if not preview:
                preview = "（命中关键词）"
            return lab, preview
    return None, None

# 销售方公司辅助定位（航空相关 → 交通费）
SELLER_FIELDS = ["销售方公司名称", "销售方名称", "销方名称", "销售方", "供应商", "供货方", "供方名称"]
AIR_TRAVEL_SELLER_HINTS = ["航空服务有限公司","航空公司","航空服务","航空","航旅","航服","航空客运"]
AIR_TRAVEL_TRIGGER_TERMS = ["退票","改签","经纪代理服务","代订机票","机票款","航空运输","客运","机票","代订附加"]

def _first_existing_col(header_map: Dict[str,int], candidates: List[str]) -> Optional[int]:
    for name in candidates:
        col = header_map.get(name)
        if col: return col
    return None

def _check_wine_long_tail_misc(raw_text: str) -> bool:
    """
    联动规则：
    - 行内出现 '*酒*'
    - 从该处到“整行末尾”的有效字符（去空白/标点/星号）长度 > 阈值
    - 且在该 '*酒*' 之后还存在“非酒类”的星标术语（如 *洗涤剂*、*日用杂品* 等）
    满足以上三者，才判定为『日用杂项』
    """
    if not raw_text:
        return False

    s = str(raw_text)

    # 清理函数：去空白、星号和常见分隔符/标点
    def _clean(x: str) -> str:
        return re.sub(r"[\s\*\-—_/\\|、，,；;.:：!！?？\[\]\(\)（）]+", "", x)

    star_terms = _extract_star_terms_with_spans(s)  # [(term, st, ed), ...]
    wine_norms = {norm_text(t) for t in WINE_STAR_TERMS}

    for m in re.finditer(r"\*酒\*", s):
        tail = s[m.end():]                  # 从 '*酒*' 之后直到行尾
        tail_clean_len = len(_clean(tail))
        if tail_clean_len <= WINE_LONG_TAIL_THRESHOLD:
            continue

        # 必须在 *酒* 之后出现“非酒类星标”
        has_non_wine_after = False
        for term, st, ed in star_terms:
            if st >= m.end() and norm_text(term) not in wine_norms:
                has_non_wine_after = True
                break

        if has_non_wine_after:
            return True

    return False

# 物料费：金额须 **>** 2000，且皮革毛皮/箱包语义与「包」同现（支持 *皮革毛皮制品* *包* 等星标）
MATERIAL_FEE_AMOUNT_MIN = 2000.0
_MATERIAL_LEATHER_MARKERS = (
    "皮革毛皮制品",
    "皮革毛皮",
    "毛皮制品",
    "箱包皮具",
)
_MATERIAL_BAG_PHRASES = (
    "皮包",
    "箱包",
    "女包",
    "男包",
    "手提包",
    "背包",
    "公文包",
    "钱包",
    "坤包",
    "双肩包",
    "皮夹",
)
_MATERIAL_PACKAGING_HINTS = ("包装费", "包装盒", "包装袋", "打包费", "包装服务")


def classify_material_fee_row(
    merged_all: str, raw_item, amount_value: float
) -> Tuple[Optional[str], Optional[str]]:
    """皮革毛皮箱包类 + 金额>2000 → 物料费（在关键词阶段之前判定，避免与其它含「包」类别冲突）。"""
    if amount_value <= MATERIAL_FEE_AMOUNT_MIN:
        return None, None
    raw_s = "" if raw_item is None else str(raw_item)
    t = norm_text(merged_all + " " + raw_s)
    star_terms = extract_star_terms(raw_item)
    star_joined = norm_text(" ".join(star_terms)) if star_terms else ""
    tall = (t + " " + star_joined).strip()

    has_leather = any(norm_text(m) in tall for m in _MATERIAL_LEATHER_MARKERS) or (
        "皮革" in tall and "毛皮" in tall
    )
    if not has_leather:
        return None, None

    if any(norm_text(b) in tall for b in _MATERIAL_BAG_PHRASES):
        return "物料费", "物料费 ← [规则] 金额>2000 且皮革毛皮相关+箱包类词"

    if "包" in tall:
        if any(norm_text(x) in tall for x in _MATERIAL_PACKAGING_HINTS):
            return None, None
        if "包邮" in tall:
            return None, None
        return "物料费", "物料费 ← [规则] 金额>2000 且皮革毛皮相关+包"

    if star_terms and any("包" in norm_text(s) for s in star_terms):
        return "物料费", "物料费 ← [规则] 金额>2000 且星标术语中含包类"

    return None, None


def classify_from_star_terms(item_text: str, full_row_text: str = "") -> Tuple[Optional[str], Optional[str]]:
    terms = extract_star_terms(item_text)
    if not terms:
        return None, None
    nfull = norm_text(full_row_text)

    # 1) 食饮星标优先 → 茶歇费
    for term in terms:
        if any(norm_text(k) in norm_text(term) for k in FOOD_STAR_TO_TEA):
            return "茶歇费", f"茶歇费 ← [星标食饮]*{term}*"

    # 2) *酒* 的“长尾+非酒星标”规则（在映射到招待用品之前先行拦截）
    if _check_wine_long_tail_misc(item_text):
        return "日用杂项", "日用杂项 ← [规则] *酒* 长尾>阈值 且后续存在非酒星标"

    # 3) 纸制品细则：遇到办公纸类提示词就办公，否则日用杂项
    for term in terms:
        if norm_text("纸制品") in norm_text(term):
            hints = [norm_text(x) for x in OFFICE_PAPER_HINTS]
            if any(h in nfull for h in hints):
                return "办公用品", f"办公用品 ← [星标纸制品+办公纸提示] *{term}*"
            return "日用杂项", f"日用杂项 ← [星标纸制品] *{term}*"

    # 4) 生活杂物星标 → 日用杂项
    for term in terms:
        if any(norm_text(k) in norm_text(term) for k in LIFE_STAR_TO_MISC):
            return "日用杂项", f"日用杂项 ← [星标生活杂物]*{term}*"

    # 5) 其余仍用 STAR_PRIORITY_MAP（包括“酒/酒水/白酒/葡萄酒/啤酒”→招待用品）
    for term in terms:
        t_norm = norm_text(term)
        for k, lab in STAR_PRIORITY_MAP.items():
            if norm_text(k) in t_norm:
                return lab, f"{lab} ← [星标]*{term}* 命中“{k}”"

    # 6) 兜底：术语自身再跑关键词
    for term in terms:
        lab2, kw2 = classify_keywords_first(term)
        if lab2:
            return lab2, f"{lab2} ← [星标关键词]*{term}* 含“{kw2}”"
    return None, None

def classify_row(ws_style: Worksheet, header_map: Dict[str,int], row: int,
                 amount_value: float, use_amount_fallback: bool,
                 item_col: Optional[int] = None) -> Tuple[str, str]:
    """
    优先级：
    ① 强优先（住宿费：整条文本含“住宿/房费”）
    ② 硬优先（整行含“租车/代订租车费”→交通费）
    ③ 星标优先（传入整行文本，以便 食饮优先 / 酒长尾规则 / 纸制品细则 / 生活杂物）
    ③b 物料费（金额>2000 且 皮革毛皮/箱包 +「包」同现）
    ④ 销售方公司辅助（航空相关 + 退改签/机票等触发词）→ 交通费
    ⑤ 关键词（全字段，带排除词）
    ⑥ 金额兜底（≥10000 → 招待用品；≤5000 → 日用杂项）
    ⑦ 未分类
    """
    if item_col is None:
        for k in ["发票项目","费用名称","发票内容","项目","用途","事由"]:
            if header_map.get(k):
                item_col = header_map[k]; break

    raw_item = ws_style.cell(row=row, column=item_col).value if item_col else None
    merged_all, _ = collect_texts(ws_style, header_map, row)

    # ① 强优先（住宿）
    if _text_contains_any(merged_all, STRONG_LABELS.get("住宿费", [])):
        return "住宿费", "住宿费 ← [强优先] 文本含“住宿/房费”"

    # ② 硬优先（租车/代订租车费）
    if _text_contains_any(merged_all, TRANSPORT_HARD_TRIGGERS) or _text_contains_any(raw_item, TRANSPORT_HARD_TRIGGERS):
        return "交通费", "交通费 ← [硬优先] 含“租车/代订租车费”"

    # ③ 星标优先（传入整行文本）
    lab, why = classify_from_star_terms(raw_item, full_row_text=merged_all)
    if lab:
        return lab, why

    lab_m, why_m = classify_material_fee_row(merged_all, raw_item, amount_value)
    if lab_m:
        return lab_m, why_m

    # ④ 销售方航空辅助
    seller_col = _first_existing_col(header_map, SELLER_FIELDS)
    if seller_col:
        seller_val = ws_style.cell(row=row, column=seller_col).value
        if _text_contains_any(seller_val, AIR_TRAVEL_SELLER_HINTS):
            if _text_contains_any(merged_all, AIR_TRAVEL_TRIGGER_TERMS) or _text_contains_any(raw_item, AIR_TRAVEL_TRIGGER_TERMS):
                return "交通费", "交通费 ← [销售方航空+机票/退改签触发]"

    # ⑤ 关键词
    lab, kw = classify_keywords_first(merged_all)
    if lab:
        return lab, f"{lab} ← [关键词] “{kw}”"

    # ⑥ 金额兜底
    if use_amount_fallback:
        if amount_value >= 10000:
            return "招待用品", "招待用品 ← [兜底] 金额≥10000"
        if amount_value <= 5000:
            return "日用杂项", "日用杂项 ← [兜底] 金额≤5000"

    return "未分类", ""

def category_rank(label: str) -> int:
    return LABEL_ORDER.index(label) if label in LABEL_ORDER else len(LABEL_ORDER)-1

def order_labels_for_summary(sums: Dict[str, float]) -> List[str]:
    present = [lab for lab, amt in sums.items() if amt and amt != 0]
    present.sort(key=category_rank)
    seen, ordered = set(), []
    for lab in present:
        if lab not in seen:
            seen.add(lab); ordered.append(lab)
    return ordered


# ========================= 封面写入（贴合模板：左侧大合并） =========================
def _set_range_border(ws, r1, r2, c1, c2, side=None):
    if side is None:
        side = Side(style="thin", color="FF999999")
    bd = Border(left=side, right=side, top=side, bottom=side)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            ws.cell(row=r, column=c).border = bd

def write_template_like_cover(ws: Worksheet, title_text: str,
                              rows: List[Tuple[str, float]], grand_total: float,
                              min_lines: int = 7) -> int:
    # 列宽/行高略贴近模板
    widths = {"B": 7, "C": 14, "D": 18, "E": 22, "F": 14, "G": 20, "H": 16}
    for k, w in widths.items():
        ws.column_dimensions[k].width = w
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 22

    # 标题：B2:H2
    ws.merge_cells("B2:H2")
    ws["B2"] = title_text
    ws["B2"].font = Font(size=14, bold=True)
    ws["B2"].alignment = Alignment(horizontal="center", vertical="center")

    # 表头：第3行
    headers = ["序号", "项目类别", "服务院校", "项目明细", "时间", "支出明细", "报销金额（元）"]
    for i, h in enumerate(headers, start=2):
        cell = ws.cell(row=3, column=i, value=h)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    _set_range_border(ws, 3, 3, 2, 8)

    # 左侧大合并：B..F 自第4行起纵向合并
    n = max(len(rows), min_lines)
    start = 4
    end = start + n - 1

    for col in range(2, 7):
        ws.merge_cells(start_row=start, start_column=col, end_row=end, end_column=col)
    ws.cell(row=start, column=2, value=1).alignment = Alignment(horizontal="center", vertical="center")
    _set_range_border(ws, start, end, 2, 6)

    # 右侧 G/H 明细
    for r in range(start, end + 1):
        ws.row_dimensions[r].height = 26
        _set_range_border(ws, r, r, 7, 8)

    for i, (cat, amt) in enumerate(rows):
        r = start + i
        ws.cell(row=r, column=7, value=cat).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=r, column=8, value=round(float(amt), 2)).alignment = Alignment(horizontal="center", vertical="center")

    # 总计行
    total_row = end + 1
    ws.row_dimensions[total_row].height = 26
    ws.merge_cells(start_row=total_row, start_column=2, end_row=total_row, end_column=7)
    tcell = ws.cell(row=total_row, column=2, value="总计")
    tcell.alignment = Alignment(horizontal="center", vertical="center")
    tcell.font = Font(bold=True)
    ws.cell(row=total_row, column=8, value=round(float(grand_total), 2)).font = Font(bold=True)
    _set_range_border(ws, total_row, total_row, 2, 8)

    return total_row


# ========================= 主处理流程 =========================
def process(
    wb_path: Path,
    base: float = 130000,
    jitter: float = 20000,
    seed: int = 42,
    insert_blank_between_groups: bool = True,
    enable_amount_fallback: bool = True,
    color_category_cell: bool = True,
    hide_pred_label: bool = True,  # 输出时隐藏“预测分类标签”列（仅影响 Excel 显示）
    ticket_split_threshold: float = 700000,   # 机票总额超过此值才拆分
    ticket_group_size: int = 240,            # 每组机票张数
    output_dir: Optional[Path] = None,       # 指定则保存到此目录，否则保存到与输入同目录
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    company_name: Optional[str] = None,
    group_cover_prefix: Optional[str] = None,
    cover_series: Optional[int] = None,
    start_index_for_group: Optional[int] = None,
) -> Path:
    if Path(wb_path).suffix.lower() == '.xls':
        import tempfile
        options = dict(locals())
        options.pop('wb_path')
        options.pop('tempfile', None)
        options['output_dir'] = Path(output_dir) if output_dir is not None else Path(wb_path).parent
        with tempfile.TemporaryDirectory(prefix='seqara-xls-') as staging:
            converted = Path(staging) / (Path(wb_path).stem + '.xlsx')
            try:
                with pd.ExcelWriter(converted, engine='openpyxl') as writer:
                    sheets = pd.read_excel(wb_path, sheet_name=None, header=None, dtype=str, engine='xlrd')
                    for title, frame in sheets.items():
                        frame.to_excel(writer, sheet_name=str(title)[:31], index=False, header=False)
            except Exception as exc:
                raise ValueError(f'.xls 转换失败，请确认文件完整：{exc}') from exc
            return process(converted, **options)

    global COMPANY_NAME, GROUP_COVER_PREFIX, COVER_SERIES, START_INDEX_FOR_GROUP
    if company_name is not None and str(company_name).strip():
        COMPANY_NAME = str(company_name).strip()
    if group_cover_prefix is not None and str(group_cover_prefix).strip():
        GROUP_COVER_PREFIX = str(group_cover_prefix).strip()
    if cover_series is not None:
        try:
            COVER_SERIES = int(cover_series)
        except (TypeError, ValueError):
            pass
    if start_index_for_group is not None:
        try:
            START_INDEX_FOR_GROUP = int(start_index_for_group)
        except (TypeError, ValueError):
            pass

    wb_path = Path(wb_path)

    # 双开：一个保公式样式，一个取值
    wb_style = load_workbook(wb_path, data_only=False)
    wb_vals  = load_workbook(wb_path, data_only=True)

    # Learn from corrected output before regenerating it, then select every source sheet.
    load_keyword_learning_state()
    updated_cnt = try_update_keyword_learning_from_previous_outputs(wb_style)
    manual_overrides = _invoice_overrides(wb_style)
    data_ws_style, data_ws_vals, header_row = _invoice_sources(wb_style, wb_vals)
    header_map = build_header_map(data_ws_style, header_row)
    date_cols = find_date_cols(header_map)
    if progress_cb:
        progress_cb(0, 1, f"读取 {len(wb_style._seqara_source_names)} 个发票数据页；回流更新 {updated_cnt} 条")

    # 关键列
    item_col = None
    for k in ["发票项目","费用名称","发票内容","项目","用途","事由"]:
        if header_map.get(k): item_col = header_map[k]; break
    amount_col = None
    for k in AMOUNT_KEYS:
        if header_map.get(k): amount_col = header_map[k]; break
    if not item_col or not amount_col:
        raise RuntimeError("未能定位到“发票项目（或费用名称/发票内容等）”或“金额（元）/金额”列。")

    # Upgrade old corrections only when the old key identifies a single invoice.
    legacy_rows = defaultdict(list)
    for row in range(header_row + 1, data_ws_style.max_row + 1):
        legacy_rows[make_invoice_key(data_ws_style, header_map, row, amount_col, legacy=True)].append(row)
    for key, rows in legacy_rows.items():
        if key not in manual_overrides:continue
        if len(rows) != 1:
            raise ValueError('旧结果中多张发票使用相同标识，无法确定人工分类属于哪张发票；请从原表重新处理后逐张核对分类。')
        manual_overrides[make_invoice_key(data_ws_style, header_map, rows[0], amount_col)] = manual_overrides.pop(key)

    def label_for_row(row, amount):
        key = make_invoice_key(data_ws_style, header_map, row, amount_col)
        if key in manual_overrides:
            return manual_overrides[key], '沿用该发票的人工分类'
        return classify_row(data_ws_style, header_map, row, amount, enable_amount_fallback, item_col=item_col)

    # “序号”列（用于 明细标题（X~Y））
    seq_col = header_map.get("序号", 1)

    max_col   = data_ws_style.max_column
    body_rows = [r for r in range(header_row + 1, data_ws_style.max_row + 1)
                 if any(data_ws_style.cell(r, c).value not in (None, '') for c in range(1, max_col + 1))]
    # Validate all amounts before writing any financial output.
    try:
        for r in body_rows:
            cell = data_ws_style.cell(r, amount_col)
            value = data_ws_vals.cell(r, amount_col).value
            if cell.data_type == 'f' and value is None:
                raise ValueError(f'{data_ws_style.title}!{cell.coordinate} 金额公式没有计算结果，请用 Excel/WPS 重算并保存后重试。')
            try:
                parsed = parse_amount(value)
            except ValueError as exc:
                raise ValueError(f'{data_ws_style.title}!{cell.coordinate}：{exc}') from exc
            data_ws_vals.cell(r, amount_col).value = parsed
    except Exception:
        wb_style.close()
        wb_vals.close()
        raise

    # === 第 1 步：将“发票项目=机票”的行抽到独立 sheet【机票报销明细_1】 ===
    ticket_rows: List[int] = []
    for r in body_rows:
        v = data_ws_style.cell(row=r, column=item_col).value
        if norm_text(v) == "机票":  # 严格等于“机票”
            ticket_rows.append(r)
    rest_rows = [r for r in body_rows if r not in ticket_rows]

    # 【机票报销明细_1】基准明细表头（拆分模式下复用为第 1 组明细）
    ws_ticket_detail = ensure_sheet(wb_style, f"{TICKET_DETAIL_SHEET_PREFIX}_1")
    copy_column_widths(data_ws_style, ws_ticket_detail)
    copy_row_dual(
        data_ws_style, data_ws_vals,
        ws_ticket_detail, header_row, 1, max_col, date_cols=date_cols
    )

    # 机票拆分控制：
    # ticket_split = True 表示触发“按张数拆分并生成多组封面+明细”
    ticket_split = False
    # 机票拆分：按组记录 (封面, 明细)，保存后一次性重排 tab，保证每组均为「封面→明细」且整体置顶
    ticket_sheet_pairs_order: List[Tuple[Worksheet, Worksheet]] = []
    ws_ticket_cover: Worksheet | None = None

    if ticket_rows:
        total_ticket = sum(
            parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
            for r in ticket_rows
        )

        # 判断是否需要拆分：
        # 仅当设置了正数阈值，且机票总额 > 阈值 时触发
        if (
            ticket_split_threshold is not None
            and ticket_split_threshold > 0
            and total_ticket > ticket_split_threshold
        ):
            # 触发机票拆分逻辑
            ticket_split = True

            # 每组张数保护：异常/非正数则回退到 240
            try:
                group_size = int(ticket_group_size)
            except Exception:
                group_size = 240
            if group_size <= 0:
                group_size = 240

            # ① 初次按张数切组
            raw_groups: List[List[int]] = []
            for start_idx in range(0, len(ticket_rows), group_size):
                raw_groups.append(ticket_rows[start_idx:start_idx + group_size])

            # ② 尾组规则：最后一组不足 group_size 时，根据金额决定是否合并
            if len(raw_groups) >= 2:
                last_group = raw_groups[-1]
                if len(last_group) < group_size:
                    last_amount = sum(
                        parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
                        for r in last_group
                    )
                    # >150000：保留为独立组；≤150000：并入前一组
                    if last_amount <= 150000:
                        raw_groups[-2].extend(last_group)
                        raw_groups.pop()

            # ③ 按调整后的分组生成明细 & 封面
            for gi, group_rows in enumerate(raw_groups, start=1):
                # 明细 sheet
                if gi == 1:
                    ws_detail = ws_ticket_detail
                else:
                    detail_name = f"{TICKET_DETAIL_SHEET_PREFIX}_{gi}"
                    ws_detail = ensure_sheet(wb_style, detail_name)
                    copy_column_widths(data_ws_style, ws_detail)
                    copy_row_dual(
                        data_ws_style, data_ws_vals,
                        ws_detail, header_row, 1, max_col, date_cols=date_cols
                    )

                rr = 2
                for i, r in enumerate(group_rows, start=1):
                    copy_row_dual(
                        data_ws_style, data_ws_vals,
                        ws_detail, r, rr, max_col, date_cols=date_cols
                    )
                    rr += 1
                    if progress_cb:
                        progress_cb(
                            i,
                            max(1, len(group_rows)),
                            f"复制机票报销明细(组{gi}) {i}/{len(group_rows)}"
                        )

                # 本组金额
                group_amount = sum(
                    parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
                    for r in group_rows
                )

                # 封面 sheet
                cover_name = f"{TICKET_COVER_SHEET_PREFIX}_{gi}"
                ws_cover = ensure_sheet(wb_style, cover_name)

                title = f"{COMPANY_NAME}报销明细-{COVER_SERIES}-1"
                if gi > 1:
                    title = f"{COMPANY_NAME}报销明细-{COVER_SERIES}-1-{gi}"

                write_template_like_cover(
                    ws_cover,
                    title_text=title,
                    rows=[("机票", group_amount)],
                    grand_total=group_amount
                )

                ticket_sheet_pairs_order.append((ws_cover, ws_detail))

        else:
            # —— 不触发拆分：所有机票集中到【机票报销明细_1】 ——
            rr = 2
            for i, r in enumerate(ticket_rows, start=1):
                copy_row_dual(
                    data_ws_style, data_ws_vals,
                    ws_ticket_detail, r, rr, max_col, date_cols=date_cols
                )
                rr += 1
                if progress_cb:
                    progress_cb(
                        i,
                        max(1, len(ticket_rows)),
                        f"复制机票报销明细 {i}/{len(ticket_rows)}"
                    )

    # ======================== 对“非机票”的剩余行继续分类/分组 ========================
    # 分组（保持顺序；130000±20000）
    amounts = [parse_amount(data_ws_vals.cell(row=r, column=amount_col).value) for r in rest_rows]
    rng = random.Random(seed); gid = 1; running = 0.0
    target = base + rng.uniform(-jitter, jitter)
    group_ids: List[int] = []
    for val in amounts:
        group_ids.append(gid)
        running += float(val)
        if running >= target:
            gid += 1; running = 0.0
            target = base + rng.uniform(-jitter, jitter)

    group_to_rows: Dict[int, List[int]] = defaultdict(list)
    for idx, r in enumerate(rest_rows):
        group_to_rows[group_ids[idx]].append(r)
    groups_sorted = sorted(group_to_rows.keys())

    # 进度估算
    steps_copy_ticket   = len(ticket_rows)
    steps_copy_rest     = len(rest_rows)
    steps_write_labels  = len(rest_rows)
    steps_write_detail  = len(rest_rows)
    steps_write_summary = len(groups_sorted)
    extra_steps_cover   = len(groups_sorted) + 1
    steps_save          = 1
    total_steps = (steps_copy_ticket + steps_copy_rest + steps_write_labels +
                   steps_write_detail + steps_write_summary + extra_steps_cover + steps_save)
    done_steps = 0
    def step(inc: int, msg: str = ""):
        nonlocal done_steps, total_steps
        done_steps += inc
        if progress_cb: progress_cb(done_steps, max(1, total_steps), msg)
        if cancel_flag and cancel_flag.is_set():
            raise RuntimeError("用户已取消")

    # ========== 分类&分组（含“分类标签/分组编号/命中说明”三列） ==========
    ws_rest = ensure_sheet(wb_style, "分类&分组")
    copy_column_widths(data_ws_style, ws_rest)
    copy_row_dual(data_ws_style, data_ws_vals, ws_rest, header_row, 1, max_col, date_cols=date_cols)

    hdr_ref = data_ws_style.cell(row=header_row, column=max_col)
    c1 = ws_rest.cell(row=1, column=max_col + 1, value="分类标签"); apply_style_from(hdr_ref, c1)
    c2 = ws_rest.cell(row=1, column=max_col + 2, value="分组编号"); apply_style_from(hdr_ref, c2)
    c3 = ws_rest.cell(row=1, column=max_col + 3, value="命中关键词/说明"); apply_style_from(hdr_ref, c3)
    c4 = ws_rest.cell(row=1, column=max_col + 4, value="关键词证据(JSON)"); apply_style_from(hdr_ref, c4)
    ws_rest.column_dimensions[get_column_letter(max_col + 1)].width = 12
    ws_rest.column_dimensions[get_column_letter(max_col + 2)].width = 10
    ws_rest.column_dimensions[get_column_letter(max_col + 3)].width = 36
    ws_rest.column_dimensions[get_column_letter(max_col + 4)].width = 80

    dst_r = 2
    unclassified_rows: List[int] = []
    unclassified_refs: List[str] = []

    for i, r in enumerate(rest_rows, start=1):
        copy_row_dual(data_ws_style, data_ws_vals, ws_rest, r, dst_r, max_col, date_cols=date_cols)
        dst_r += 1
        step(1, f"复制非机票行 {i}/{steps_copy_rest}")

        amt = parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
        lab, why = label_for_row(r, amt)
        ws_rest.cell(row=1 + i, column=max_col + 1, value=lab)
        color_cell(ws_rest.cell(row=1 + i, column=max_col + 1), COLOR_BY_LABEL.get(lab, COLOR_BY_LABEL["未分类"]))
        ws_rest.cell(row=1 + i, column=max_col + 2, value=group_ids[i - 1])
        ws_rest.cell(row=1 + i, column=max_col + 3, value=why or "（未命中关键词）")
        # 关键词阶段学习需要：保存该行命中的“关键词集合”（已应用排除词逻辑）
        merged_all, _ = collect_texts(data_ws_style, header_map, r)
        ws_rest.cell(row=1 + i, column=max_col + 4, value=keyword_evidence_json(merged_all))

        if lab == "未分类":
            merged, field_texts = collect_texts(data_ws_style, header_map, r)
            ref = []
            for nm in PRIMARY_FIELDS + SECONDARY_FIELDS:
                if nm in field_texts and field_texts[nm]:
                    ref.append(f"{nm}:{field_texts[nm]}")
            unclassified_rows.append(r)
            unclassified_refs.append(" | ".join(ref)[:500])
        step(1, f"写入分类/分组 {i}/{steps_write_labels}")

    ws_rest.row_dimensions[1].height = data_ws_style.row_dimensions[header_row].height
    for i, r in enumerate(rest_rows, start=2):
        h = data_ws_style.row_dimensions[r].height
        if h is not None:
            ws_rest.row_dimensions[i].height = h

    # ========== 分组汇总（展开原顺序） ==========
    ws_detail = ensure_sheet(wb_style, "分组汇总")
    copy_column_widths(data_ws_style, ws_detail)
    copy_row_dual(data_ws_style, data_ws_vals, ws_detail, header_row, 1, max_col, date_cols=date_cols)
    d1 = ws_detail.cell(row=1, column=max_col + 1, value="分类标签"); apply_style_from(hdr_ref, d1)
    d2 = ws_detail.cell(row=1, column=max_col + 2, value="分组编号"); apply_style_from(hdr_ref, d2)
    ws_detail.column_dimensions[get_column_letter(max_col + 1)].width = 12
    ws_detail.column_dimensions[get_column_letter(max_col + 2)].width = 10

    write_r = 2
    for gi, g in enumerate(groups_sorted, start=1):
        rows = group_to_rows[g]
        for r in rows:
            copy_row_dual(data_ws_style, data_ws_vals, ws_detail, r, write_r, max_col, date_cols=date_cols)
            amt = parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
            lab, _ = label_for_row(r, amt)
            ws_detail.cell(row=write_r, column=max_col + 1, value=lab)
            ws_detail.cell(row=write_r, column=max_col + 2, value=g)
            write_r += 1
            step(1, f"展开分组明细 {gi}/{len(groups_sorted)}")
        if insert_blank_between_groups:
            write_r += 1

    # ========== 分组统计 ==========
    ws_sum = ensure_sheet(wb_style, "分组统计")
    ws_sum["A1"].value = "分组编号"
    ws_sum["B1"].value = "组内笔数"
    ws_sum["C1"].value = "组内金额合计"
    ws_sum["D1"].value = "目标下限"
    ws_sum["E1"].value = "目标上限"
    cnt: Dict[int,int] = defaultdict(int)
    total: Dict[int,float] = defaultdict(float)
    for g, val in zip(group_ids, amounts):
        cnt[g] += 1; total[g] += float(val)
    row = 2
    for g in groups_sorted:
        ws_sum.cell(row=row, column=1, value=g)
        ws_sum.cell(row=row, column=2, value=cnt[g])
        ws_sum.cell(row=row, column=3, value=round(total[g], 2))
        ws_sum.cell(row=row, column=4, value=base - jitter)
        ws_sum.cell(row=row, column=5, value=base + jitter)
        row += 1
        step(1, f"写入分组统计 {g}/{groups_sorted[-1]}")

    # ========== 每组生成“封面+明细”；明细标题含（起始序号~结束序号），并在明细中插入“分类标签”列（发票号码前） ==========
    curr_idx = START_INDEX_FOR_GROUP
    for gi, g in enumerate(groups_sorted, start=1):
        rows = group_to_rows[g]

        # 计算标签金额、记录每行标签与“序号”
        sums: Dict[str,float] = defaultdict(float)
        row_lab_map_group: Dict[int,str] = {}
        seq_values: List = []
        for r in rows:
            amt = parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
            lab, _ = label_for_row(r, amt)
            sums[lab] += float(amt)
            row_lab_map_group[r] = lab
            seq_values.append(data_ws_vals.cell(row=r, column=seq_col).value)

        # 不排序，保持原顺序
        rows_sorted = rows

        # 目录页类别顺序：与明细一致
        ordered_labels = order_labels_for_summary(sums)
        items = [(lab, sums[lab]) for lab in ordered_labels]
        gtotal = sum(sums.values())

        # 封面
        cover_name = f"{GROUP_COVER_PREFIX}{COVER_SERIES}-{curr_idx}"
        ws_cover = ensure_sheet(wb_style, cover_name)
        write_template_like_cover(
            ws_cover,
            title_text=f"{COMPANY_NAME}报销明细-{COVER_SERIES}-{curr_idx}",
            rows=items,
            grand_total=gtotal
        )

        # 明细
        detail_name = f"{GROUP_COVER_PREFIX}{COVER_SERIES}-{curr_idx}明细"
        ws_gdetail = ensure_sheet(wb_style, detail_name)
        copy_column_widths(data_ws_style, ws_gdetail)

        # 找“发票号码”列（用于在其前插入“分类标签”）
        invoice_col = header_map.get("发票号码")
        if not invoice_col:
            # 兜底：模糊找含“发票”和“号”的表头
            for name, c in header_map.items():
                if "发票" in str(name) and "号" in str(name):
                    invoice_col = c
                    break

        # 构造列映射：若有发票号码列，则在其前插入一列
        col_mapping: Dict[int, int] = {}
        if invoice_col:
            for c in range(1, max_col + 1):
                col_mapping[c] = c if c < invoice_col else c + 1
            class_col = invoice_col
            dst_max_col = max_col + 1
        else:
            for c in range(1, max_col + 1):
                col_mapping[c] = c
            class_col = max_col + 1
            dst_max_col = max_col + 1
        pred_label_col = dst_max_col + 1  # 额外追加列：用于学习时区分“预测 vs 人工”
        # ⭐ 在这里设置“发票号码”列宽
        if invoice_col is not None:
            invoice_col_dst = col_mapping.get(invoice_col, invoice_col)
            ws_gdetail.column_dimensions[get_column_letter(invoice_col_dst)].width = 25  # 比如 20
        # 标题“报销明细表（X~Y）”：取“序号”最小~最大（保留原序号，不重编）
        def _to_int(v):
            try:
                return int(str(v).strip())
            except Exception:
                return None
        nums = [n for n in (_to_int(v) for v in seq_values) if n is not None]
        if nums:
            seq_min, seq_max = min(nums), max(nums)
        else:
            seq_min = seq_values[0] if seq_values else ""
            seq_max = seq_values[-1] if seq_values else ""
        start_col, end_col = 2, min(8, max_col)  # B..H（不受插入新列影响）
        ws_gdetail.merge_cells(start_row=1, start_column=start_col, end_row=1, end_column=end_col)
        title_cell = ws_gdetail.cell(row=1, column=start_col, value=f"报销明细表（{seq_min}~{seq_max}）")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        title_cell.font = Font(size=13, bold=True)
        ws_gdetail.row_dimensions[1].height = 24

        # 表头复制到第2行（带列映射）
        copy_row_dual_mapped(
            data_ws_style,
            data_ws_vals,
            ws_gdetail,
            header_row,
            2,
            max_col,
            date_cols=date_cols,
            col_mapping=col_mapping,
        )
        ws_gdetail.row_dimensions[2].height = data_ws_style.row_dimensions[header_row].height

        # 设置“分类标签”表头样式与列宽
        ref_col_for_header = class_col + 1 if class_col + 1 <= dst_max_col else dst_max_col
        ref_cell = ws_gdetail.cell(row=2, column=ref_col_for_header)
        class_header_cell = ws_gdetail.cell(row=2, column=class_col)
        class_header_cell.value = "分类标签"
        apply_style_from(ref_cell, class_header_cell)
        class_header_cell.border = _cp(ref_cell.border)
        try:
            ref_letter = get_column_letter(ref_col_for_header)
            cls_letter = get_column_letter(class_col)
            ref_width = ws_gdetail.column_dimensions[ref_letter].width
            ws_gdetail.column_dimensions[cls_letter].width = 12 # 固定宽度 16
        except Exception:
            ws_gdetail.column_dimensions[get_column_letter(class_col)].width = 12

        # 追加“预测分类标签”表头（不参与着色，仅用于回流学习）
        pred_header_cell = ws_gdetail.cell(row=2, column=pred_label_col, value="预测分类标签")
        apply_style_from(class_header_cell, pred_header_cell)
        pred_header_cell.border = _cp(class_header_cell.border)
        ws_gdetail.column_dimensions[get_column_letter(pred_label_col)].width = 12
        ws_gdetail.column_dimensions[get_column_letter(pred_label_col)].hidden = hide_pred_label

        # 计算“发票项目”在新明细表中的列号（考虑插入列后的位移）
        item_col_dst = item_col
        if invoice_col and item_col >= invoice_col:
            item_col_dst = item_col + 1
            ws_gdetail.column_dimensions[get_column_letter(item_col_dst)].width = 45
        # 数据从第3行，并按标签给“发票项目”和“分类标签”列上色
        rr2 = 3
        for r in rows_sorted:
            copy_row_dual_mapped(
                data_ws_style,
                data_ws_vals,
                ws_gdetail,
                r,
                rr2,
                max_col,
                date_cols=date_cols,
                col_mapping=col_mapping,
            )
            lab = row_lab_map_group.get(r, "未分类")
            fill = COLOR_BY_LABEL.get(lab, COLOR_BY_LABEL["未分类"])
            if color_category_cell:
                # 发票项目着色
                color_cell(ws_gdetail.cell(row=rr2, column=item_col_dst), fill)
                # 分类标签文字 + 着色
                cls_cell = ws_gdetail.cell(row=rr2, column=class_col, value=lab)
                color_cell(cls_cell, fill)
            else:
                ws_gdetail.cell(row=rr2, column=class_col, value=lab)

            # 预测基线（学习用）：不着色，避免干扰人工判断
            ws_gdetail.cell(row=rr2, column=pred_label_col, value=lab)
            rr2 += 1

        curr_idx += 1
        step(1, f"生成封面与明细：{cover_name}")

    # ========== 机票“封面”生成 & Sheet 顺序前置 ==========

    # 未拆分时，生成单一【机票报销封面_1】
    if ticket_rows and not ticket_split:
        total_ticket = sum(
            parse_amount(data_ws_vals.cell(row=r, column=amount_col).value)
            for r in ticket_rows
        )
        ws_ticket_cover = ensure_sheet(wb_style, f"{TICKET_COVER_SHEET_PREFIX}_1")
        write_template_like_cover(
            ws_ticket_cover,
            title_text=f"{COMPANY_NAME}报销明细-{COVER_SERIES}-1",
            rows=[("机票", total_ticket)],
            grand_total=total_ticket
        )
        step(1, "机票报销封面_1 完成")

    # 机票相关 sheet 顺序：显式重排 _sheets，避免反复 insert(0) 在首组上与预期不一致
    ticket_chain: List[Worksheet] = []
    if ticket_split and ticket_sheet_pairs_order:
        for cover_ws, detail_ws in ticket_sheet_pairs_order:
            ticket_chain.extend([cover_ws, detail_ws])
    elif ws_ticket_cover is not None:
        ticket_chain = [ws_ticket_cover, ws_ticket_detail]

    if ticket_chain:
        sheets_list = wb_style._sheets
        ticket_set = set(ticket_chain)
        wb_style._sheets = ticket_chain + [ws for ws in sheets_list if ws not in ticket_set]
    else:
        if ws_ticket_detail in wb_style._sheets:
            sheets = wb_style._sheets
            sheets.insert(0, sheets.pop(sheets.index(ws_ticket_detail)))

    # ========== 未分类_待处理（附参考文本） ==========
    ws_unc = ensure_sheet(wb_style, "未分类_待处理")
    copy_column_widths(data_ws_style, ws_unc)
    copy_row_dual(data_ws_style, data_ws_vals, ws_unc, header_row, 1, max_col, date_cols=date_cols)
    ws_unc.column_dimensions[get_column_letter(max_col + 1)].width = 80
    ws_unc.cell(row=1, column=max_col + 1, value="参考文本")
    wr = 2
    for r, ref in zip(unclassified_rows, unclassified_refs):
        copy_row_dual(data_ws_style, data_ws_vals, ws_unc, r, wr, max_col, date_cols=date_cols)
        ws_unc.cell(row=wr, column=max_col + 1, value=ref)
        wr += 1

    # 隐藏所有包含“预测分类标签”的列（仅影响 Excel 显示，不改变单元格内容）
    try:
        for ws in wb_style.worksheets:
            hr = detect_header_row(ws)
            if not hr:
                continue
            header = build_header_map(ws, hr)
            pred_col = header.get("预测分类标签")
            if pred_col:
                ws.column_dimensions[get_column_letter(pred_col)].hidden = hide_pred_label
            if INVOICE_ROW_ID in header:
                ws.column_dimensions[get_column_letter(header[INVOICE_ROW_ID])].hidden = True
    except Exception:
        pass

    # Track generated pages so reruns never consume summaries or stale groups.
    meta = wb_style[wb_style._seqara_metadata_name]
    meta['B3'] = json.dumps(manual_overrides, ensure_ascii=False)
    meta['B2'] = json.dumps([ws.title for ws in wb_style.worksheets
                            if ws.title not in wb_style._seqara_reserved
                            and ws.title != meta.title], ensure_ascii=False)
    folder = Path(output_dir) if output_dir is not None else wb_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    out_path = new_output_path(folder, wb_path.stem + "_处理结果.xlsx", (wb_path,))
    step(0, "保存中…")
    with staged_outputs(out_path) as (staged,):
        wb_style.save(staged)
    wb_style.close()
    wb_vals.close()
    step(1, "保存完成")
    return out_path
