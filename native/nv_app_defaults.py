# -*- coding: utf-8 -*-
"""发票分类页默认「公司名称」「分组前缀」（invoice_classify_defaults.json）。

各公司下属院校不在此文件，而在 ticket_company_schools.json（机票）与
project_company_schools.json（产教封面），见工具集「设置」对应标签页。
"""
from __future__ import annotations

import json
from pathlib import Path

_bundle_dir: Path = Path(__file__).resolve().parent

DEFAULT_COMPANY_NAME = "示例公司"
DEFAULT_GROUP_PREFIX = "示例产教融合项目"


def set_bundle_dir(path: str) -> None:
    global _bundle_dir
    _bundle_dir = Path(path).resolve()


def _defaults_path() -> Path:
    return _bundle_dir / "invoice_classify_defaults.json"


def load_classify_form_defaults() -> dict[str, str]:
    p = _defaults_path()
    if not p.is_file():
        return {
            "company_name": DEFAULT_COMPANY_NAME,
            "group_prefix": DEFAULT_GROUP_PREFIX,
        }
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "company_name": str(d.get("company_name") or DEFAULT_COMPANY_NAME).strip()
            or DEFAULT_COMPANY_NAME,
            "group_prefix": str(d.get("group_prefix") or DEFAULT_GROUP_PREFIX).strip()
            or DEFAULT_GROUP_PREFIX,
        }
    except Exception:
        return {
            "company_name": DEFAULT_COMPANY_NAME,
            "group_prefix": DEFAULT_GROUP_PREFIX,
        }


def save_classify_form_defaults(company_name: str, group_prefix: str) -> None:
    _bundle_dir.mkdir(parents=True, exist_ok=True)
    path = _defaults_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(
                {
                    "company_name": (company_name or "").strip(),
                    "group_prefix": (group_prefix or "").strip(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
