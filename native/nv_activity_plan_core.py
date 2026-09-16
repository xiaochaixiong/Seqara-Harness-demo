# -*- coding: utf-8 -*-
"""活动方案正文生成（从 CTK 合并版抽出，依赖 nv_deepseek_core）。"""
from __future__ import annotations

import hashlib
import re
from typing import Callable, List, Optional, Sequence

import nv_deepseek_core as nv_ds

from nv_activity_plan_prompts import (
    ACTIVITY_PLAN_LENGTH_MIN,
    ACTIVITY_PLAN_LENGTH_MAX,
    ACTIVITY_PLAN_GEN_TEMPERATURE,
    ACTIVITY_PLAN_USER_RED_LINES,
    ACTIVITY_PLAN_TITLE_DEDUP_RETRY_SUFFIX,
    ACTIVITY_PLAN_DIVERSITY_ANGLES,
    _activity_plan_diversity_index,
    _activity_plan_diversity_user_block,
    ACTIVITY_PLAN_BODY_SYSTEM,
    ACTIVITY_PLAN_BODY_SYSTEM_STRICT,
    ACTIVITY_PLAN_BODY_SYSTEM_STANDARD,
)


def _sanitize_activity_plan_text(text: str) -> str:
    if not text:
        return text
    money_patterns = [
        r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:元|RMB|人民币|万元|千元|亿元)\b",
        r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*（?:元|RMB|人民币|万元|千元|亿元）\b",
        r"\b\d+(?:\.\d+)?\s*(?:元|RMB|人民币)\b",
    ]
    for pat in money_patterns:
        text = re.sub(pat, "（金额另行核定）", text, flags=re.IGNORECASE)
    text = re.sub(
        r"[\u4e00-\u9fffA-Za-z0-9_]{1,28}(?:有限公司|集团|公司|企业)",
        "相关协办单位",
        text,
    )
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_activity_plan_editor_artifacts(text: str) -> str:
    if not text:
        return text
    t = text
    t = re.sub(r"[\n\r]+\s*\(?\s*全文字符数\s*[:：]\s*\d+\s*\)?\s*", "\n", t)
    t = re.sub(r"\s*\(?\s*全文字符数\s*[:：]\s*\d+\s*\)?\s*$", "", t)
    t = re.sub(r"全文字符数\s*[:：]\s*\d+", "", t)
    return t.strip()


def generate_activity_plan_body(
    activity_type: str,
    major_name: str,
    activity_time: str,
    service_college: str,
    style_mode: str = "豆包风",
    log_cb: Optional[Callable[[str], None]] = None,
    model: Optional[str] = None,
    variation_key: str = "",
    *,
    batch_slot: Optional[int] = None,
    batch_total: Optional[int] = None,
    avoid_titles: Optional[Sequence[str]] = None,
    extra_user_suffix: str = "",
) -> str:
    activity_type = (activity_type or "").strip()
    major_name = (major_name or "").strip()
    activity_time = (activity_time or "").strip()
    service_college = (service_college or "").strip()
    style_mode = (style_mode or "").strip() or "豆包风"
    variation_key = (variation_key or "").strip()
    if not activity_type or not major_name or not activity_time or not service_college:
        raise ValueError("请完整填写「活动类型 / 专业名称 / 活动时间 / 服务院校」。")

    diversity_parts = (activity_type, major_name, activity_time, service_college, variation_key)

    if style_mode == "标准":
        user = (
            f"请为「{service_college}」的「{major_name}」专业撰写活动方案：项目类型须覆盖「{activity_type}」；活动周期「{activity_time}」。\n"
            "要求：内容专业、务实、可执行；用「# / ##」为主分层，细目可用「###」等（见系统提示）；标题勿手写「一、」「（一）」「1.」；活动名称新颖，少用「训练营」式套名；不出现具体公司/企业名称与具体金额。\n"
            f"输出方式：请一次性输出完整终稿（不要分多次说明或追问）。全文汉字规模控制在约 "
            f"{ACTIVITY_PLAN_LENGTH_MIN}～{ACTIVITY_PLAN_LENGTH_MAX} 字之间（不少于{ACTIVITY_PLAN_LENGTH_MIN}、不超过{ACTIVITY_PLAN_LENGTH_MAX}），"
            "勿在文末标注字数或字符数统计。"
        )
        use_system_prompt = ACTIVITY_PLAN_BODY_SYSTEM_STANDARD
    else:
        user = (
            f"请为「{service_college}」「{major_name}」专业撰写一份产教融合方向的综合性活动策划方案。\n"
            f"须体现活动类型：{activity_type}；面向对象：该专业本科生与任课教师；活动周期：{activity_time}。\n"
            "写作体例：参考高校项目申报与实施方案，先阐明背景与必要性，再写活动概况、实施步骤与保障；段落饱满，避免空洞口号。\n"
            "章节排版：以「# 」「## 」为主组织层级（见系统提示）；各 # 大章下应有若干 ## 小节；更细可用 ### 等，勿重复井号。\n"
            "命名与形态：题目须新颖，少用「××周」套题与雷同的「训练营」式套名；可结合专业场景选用联展、课题、驻场、答辩、工作坊、沙盘等形态展开。\n"
            f"输出方式：请一次性输出完整终稿（不要分节追问、不要分卷）。全文汉字规模约 "
            f"{ACTIVITY_PLAN_LENGTH_MIN}～{ACTIVITY_PLAN_LENGTH_MAX} 字（不少于{ACTIVITY_PLAN_LENGTH_MIN}、不超过{ACTIVITY_PLAN_LENGTH_MAX}）；"
            "不得出现具体公司/企业/品牌名称与具体金额；勿在文末输出字数统计。\n"
            "「活动概况」中须明确写出：项目名称（或活动名称）、活动周期、活动地点、活动对象、活动形式。"
        )
        use_system_prompt = ACTIVITY_PLAN_BODY_SYSTEM_STRICT

    user = user + "\n\n" + _activity_plan_diversity_user_block(
        *diversity_parts,
        batch_slot=batch_slot,
        batch_total=batch_total,
        avoid_titles=avoid_titles,
    )
    _suf = (extra_user_suffix or "").strip()
    if _suf:
        user = user + "\n\n" + _suf

    if log_cb:
        log_cb(">>> 正在调用DeepSeek生成方案正文（单次输出，无自动扩写）…")
    # 单次 max_tokens 8192：留足输出空间；篇幅由提示词约束在约 3500～4000 汉字
    ok, resp = nv_ds.call_deepseek_api(
        user,
        system_prompt=use_system_prompt,
        model=model,
        max_tokens=8192,
        temperature=ACTIVITY_PLAN_GEN_TEMPERATURE,
    )
    if not ok:
        raise RuntimeError(resp)

    resp = _sanitize_activity_plan_text(resp.strip())
    resp = _strip_activity_plan_editor_artifacts(resp)
    for _bad in ("活动策划方案正文", "活动方案正文", "## 活动策划方案正文", "# 活动策划方案正文"):
        resp = resp.replace(_bad, "").strip()
    _n = len(resp)
    if log_cb and (_n < ACTIVITY_PLAN_LENGTH_MIN or _n > ACTIVITY_PLAN_LENGTH_MAX):
        log_cb(
            f">>> 提示：本次正文约 {_n} 个字符（含标点、Markdown），目标约 "
            f"{ACTIVITY_PLAN_LENGTH_MIN}～{ACTIVITY_PLAN_LENGTH_MAX}；可更换更强模型或重新生成。"
        )
    return resp
