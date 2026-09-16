# -*- coding: utf-8 -*-
"""院校名称的单一规范化入口。"""
from __future__ import annotations

import re


OFFICE_SEGMENT = "驻校办公室"
INVALID_SCHOOL_LABELS = {"", "/", "-", "--", "无", "未知", "总部", "所有高校"}
_TRAILING_SCOPE_RE = re.compile(r"\s*[（(][^（）()]*[）)]\s*$")


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "null", "<na>"} else text


def _strip_scope_suffix(value: str) -> str:
    result = value.strip()
    while result and _TRAILING_SCOPE_RE.search(result):
        result = _TRAILING_SCOPE_RE.sub("", result).strip()
    return result


def school_from_department(value: object) -> str:
    """只取 ``驻校办公室/院校名称`` 的院校层级。

    ``驻校办公室/示例院校03（美设学院）`` 和
    ``驻校办公室/示例院校03/二级学院`` 均返回 ``示例院校03``。
    不含驻校办公室层级的总部记录返回空字符串。
    """

    text = _text(value).replace("／", "/").replace("\\", "/")
    parts = [part.strip() for part in text.split("/")]
    try:
        marker_index = parts.index(OFFICE_SEGMENT)
    except ValueError:
        return ""
    if marker_index + 1 >= len(parts):
        return ""
    school = _strip_scope_suffix(parts[marker_index + 1])
    return "" if school in INVALID_SCHOOL_LABELS else school


def normalize_cleaned_school(value: object) -> str:
    """规范旧版清洗结果中的学校名称，并排除非驻校标签。"""

    text = _text(value).replace("／", "/").replace("\\", "/")
    if OFFICE_SEGMENT in text:
        return school_from_department(text)
    school = _strip_scope_suffix(text.split("/", 1)[0].strip())
    return "" if school in INVALID_SCHOOL_LABELS else school


__all__ = ["normalize_cleaned_school", "school_from_department"]
