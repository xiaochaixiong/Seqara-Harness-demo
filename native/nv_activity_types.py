"""活动类型的统一统计口径，保留未指定的历史类型。"""
import re

ACTIVITY_TYPE_MAP = {
    "学科竞赛": "赛事", "产业赛事": "赛事",
    "双师赋能": "师资培训", "设计工坊": "实训营",
    **dict.fromkeys(("协同育人", "成果转化", "校企共建", "企业研学", "其他", "展览", "论坛"), "品牌活动"),
}


def normalize_activity_types(value):
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return ""
    parts = re.split(r"[，,、/|;；]+", str(value))
    return "、".join(dict.fromkeys(
        ACTIVITY_TYPE_MAP.get(part.strip(), part.strip()) for part in parts if part.strip()
    ))
