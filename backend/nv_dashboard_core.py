# -*- coding: utf-8 -*-
"""企业微信活动数据看板的数据层。

只读取看板白名单字段，不修改源工作簿，也不会把报销表中的身份、银行或联系方式
带入内存模型。所有聚合均可追溯到 12 位审批编号。
"""
from __future__ import annotations

import hashlib
import math
import json
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd

from nv_school_utils import normalize_cleaned_school, school_from_department
from nv_activity_types import normalize_activity_types


APPROVAL_ID_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
DATE_RE = re.compile(r"(\d{4})(?:[./-]|年)(\d{1,2})(?:[./-]|月)(\d{1,2})(?:日)?")
COMPACT_DATE_RE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")
TYPE_SPLIT_RE = re.compile(r"[，,、/|;；]+")
EXPERT_SPLIT_RE = re.compile(r"[、,，;/；]+")

APP_COLUMNS = (
    "审批编号",
    "审批详情",
    "提交时间",
    "完成时间",
    "申请人部门",
    "活动名称",
    "学校名称",
    "活动类型",
    "服务教师（人数）",
    "服务学生（人数）",
    "开始时间",
    "结束时间",
    "当前审批状态",
    "专家费-专家姓名",
    "专家费-专家简介",
    "专家费-专家费（元）",
)
APP_REQUIRED = {
    "审批编号",
    "申请人部门",
    "活动名称",
    "活动类型",
    "服务教师（人数）",
    "服务学生（人数）",
    "开始时间",
    "结束时间",
    "当前审批状态",
}
CLEANED_COLUMNS = (
    "审批编号",
    "活动名称",
    "学校名称",
    "活动类型",
    "活动时间",
    "新闻链接",
    "服务教师（人数）",
    "服务学生（人数）",
)
CLEANED_REQUIRED = {
    "活动名称",
    "学校名称",
    "活动类型",
    "活动时间",
    "服务教师（人数）",
    "服务学生（人数）",
}
REIM_COLUMNS = (
    "审批编号",
    "审批详情",
    "提交时间",
    "完成时间",
    "关联申请单",
    "当前审批状态",
)
REIM_REQUIRED = {"审批编号", "关联申请单", "当前审批状态"}

EMPTY_TEXT = {"", "nan", "none", "null", "无", "0"}
APPROVED_STATUS = {"已通过", "已同意", "通过", "同意"}
REJECTED_STATUS = {"已驳回", "已拒绝", "已撤销", "已作废", "已退回"}


@dataclass(frozen=True)
class ActivityRecord:
    approval_id: str
    detail_url: str
    school: str
    activity_name: str
    activity_types: tuple[str, ...]
    start_date: Optional[date]
    end_date: Optional[date]
    month: str
    teacher_count: float
    student_count: float
    status: str
    teacher_excluded: bool = False
    student_excluded: bool = False
    is_supplementary: bool = False


@dataclass(frozen=True)
class UnreimbursedRecord:
    approval_id: str
    detail_url: str
    school: str
    activity_name: str
    activity_types: tuple[str, ...]
    start_date: Optional[date]
    end_date: Optional[date]
    days_since_end: Optional[int]
    business_state: str


@dataclass(frozen=True)
class ExpertInvitation:
    approval_id: str
    detail_url: str
    expert_name: str
    normalized_name: str
    intro: str
    school: str
    activity_name: str
    activity_types: tuple[str, ...]
    event_date: Optional[date]
    fee_amount: Optional[float]
    fee_shared: bool
    needs_review: bool


@dataclass(frozen=True)
class ExpertProfile:
    expert_name: str
    normalized_name: str
    intros: tuple[str, ...]
    schools: tuple[str, ...]
    activity_types: tuple[str, ...]
    invitation_count: int
    latest_event_date: Optional[date]
    has_intro_conflict: bool
    needs_review: bool
    invitations: tuple[ExpertInvitation, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class QualityIssue:
    issue_type: str
    label: str
    severity: str
    approval_id: str
    school: str
    activity_name: str
    message: str
    impact: str
    resolution: str
    detail_url: str = ""


@dataclass(frozen=True)
class DashboardQuality:
    raw_application_rows: int
    logical_application_records: int
    non_approved_application_records: int
    missing_school_records: int
    missing_start_date_records: int
    invalid_teacher_values: int
    invalid_student_values: int
    raw_reimbursement_rows: int
    logical_reimbursement_records: int
    reimbursement_records_without_links: int
    reimbursement_records_with_multiple_links: int
    linked_application_ids_not_in_file: int
    expert_rows: int
    expert_names_needing_review: int
    expert_profiles_with_conflicts: int
    total_issues: int


@dataclass(frozen=True)
class ArchiveBatch:
    batch_id: int
    source_name: str
    source_hash: str
    archived_at: str
    invitation_count: int


@dataclass(frozen=True)
class ArchiveResult:
    batch_id: int
    imported_invitations: int
    duplicate_batch: bool


@dataclass(frozen=True)
class DashboardSnapshot:
    source_application_path: str
    source_reimbursement_path: str
    source_kind: str
    supports_reimbursement: bool
    supports_experts: bool
    as_of_date: date
    activities: tuple[ActivityRecord, ...]
    months: tuple[str, ...]
    school_counts: dict[str, int]
    school_month_counts: dict[str, dict[str, int]]
    school_type_counts: dict[str, dict[str, int]]
    school_month_type_counts: dict[str, dict[str, dict[str, int]]]
    teacher_by_school: dict[str, float]
    student_by_school: dict[str, float]
    teacher_by_school_month: dict[str, dict[str, float]]
    student_by_school_month: dict[str, dict[str, float]]
    teacher_total: float
    student_total: float
    excluded_teacher_records: int
    excluded_student_records: int
    unreimbursed: tuple[UnreimbursedRecord, ...]
    experts: tuple[ExpertProfile, ...]
    quality: DashboardQuality
    quality_issues: tuple[QualityIssue, ...]
    expert_sync: Optional[ArchiveResult] = None
    source_supplementary_path: str = ""

    @property
    def activity_count(self) -> int:
        return len(self.activities)

    @property
    def school_count(self) -> int:
        return len(self.school_counts)


@dataclass(frozen=True)
class DashboardFilter:
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    school: str = ""
    activity_type: str = ""


@dataclass(frozen=True)
class DashboardView:
    filters: DashboardFilter
    activities: tuple[ActivityRecord, ...]
    months: tuple[str, ...]
    school_counts: dict[str, int]
    school_month_counts: dict[str, dict[str, int]]
    school_type_counts: dict[str, dict[str, int]]
    school_month_type_counts: dict[str, dict[str, dict[str, int]]]
    teacher_by_school: dict[str, float]
    student_by_school: dict[str, float]
    teacher_by_school_month: dict[str, dict[str, float]]
    student_by_school_month: dict[str, dict[str, float]]
    teacher_total: float
    student_total: float
    excluded_teacher_records: int
    excluded_student_records: int
    unreimbursed: tuple[UnreimbursedRecord, ...]
    experts: tuple[ExpertProfile, ...]
    closure_counts: dict[str, int]

    @property
    def activity_count(self) -> int:
        return len(self.activities)

    @property
    def school_count(self) -> int:
        return len(self.school_counts)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in EMPTY_TEXT else text


def _approval_ids(value: object) -> list[str]:
    return APPROVAL_ID_RE.findall(_clean_text(value))


def _primary_approval_id(value: object) -> str:
    values = _approval_ids(value)
    return values[0] if values else ""


def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    compact = _clean_text(value)
    if re.fullmatch(r'\d{8}', compact):
        try:
            return datetime.strptime(compact, '%Y%m%d').date()
        except ValueError:
            return None
    # “清洗与整理”输出可能把 Excel 日期存成序号。Excel 的 1900 日期
    # 系统以 1899-12-30 为换算原点；先处理数值，避免把 46042 误判为文本。
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = pd.to_datetime(value, unit="D", origin="1899-12-30", errors="coerce")
        if not pd.isna(parsed):
            return parsed.date()
    match = DATE_RE.search(_clean_text(value))
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _parse_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _parse_number(value: object) -> tuple[float, bool]:
    from nv_data_safety import parse_headcount
    if value is None or _clean_text(value) == '':
        return 0.0, False
    try:
        return float(parse_headcount(value)), False
    except (ValueError, OverflowError):
        return 0.0, True


def _parse_optional_number(value: object) -> Optional[float]:
    if value is None or _clean_text(value) == "":
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _split_types(value: object) -> tuple[str, ...]:
    raw = normalize_activity_types(_clean_text(value))
    if not raw:
        return ("未分类",)
    parts = tuple(dict.fromkeys(part.strip() for part in TYPE_SPLIT_RE.split(raw) if part.strip()))
    return parts or ("未分类",)


def _split_expert_names(value: object) -> tuple[str, ...]:
    raw = _clean_text(value)
    if not raw:
        return ()
    return tuple(dict.fromkeys(part.strip() for part in EXPERT_SPLIT_RE.split(raw) if part.strip()))


def _normalize_expert_name(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().casefold()


def _normalize_profile(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().casefold()


def _is_approved(status: object) -> bool:
    text = _clean_text(status)
    return text in APPROVED_STATUS or text.startswith("已通过")


def _is_rejected(status: object) -> bool:
    text = _clean_text(status)
    return text in REJECTED_STATUS or any(word in text for word in ("驳回", "拒绝", "撤销", "作废"))


def _extract_school(department: object) -> str:
    """从申请人部门提取驻校办公室后的第二级院校名称。"""

    return school_from_department(department) or "未识别院校"


def _read_header(path: str | Path, label: str) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"{label}不存在：{source}")
    try:
        if source.suffix.casefold() == ".csv":
            return pd.read_csv(source, nrows=0, encoding="utf-8-sig")
        return pd.read_excel(source, nrows=0)
    except Exception as exc:
        raise ValueError(f"无法读取{label}：{exc}") from exc


def detect_activity_source_kind(path: str | Path) -> str:
    """识别原始活动申请或“清洗与整理”输出，不读取正文数据。"""

    header = _read_header(path, "活动数据")
    available = {str(column).strip() for column in header.columns}
    if APP_REQUIRED <= available or {"审批编号", "当前审批状态"} <= available:
        return "raw"
    if CLEANED_REQUIRED <= available:
        return "cleaned"
    raw_missing = "、".join(sorted(APP_REQUIRED - available))
    cleaned_missing = "、".join(sorted(CLEANED_REQUIRED - available))
    raise ValueError(
        "活动数据格式无法识别。请选择企业微信原始活动申请，或“清洗与整理”输出表。"
        f"\n原始申请缺少：{raw_missing or '无'}"
        f"\n清洗结果缺少：{cleaned_missing or '无'}"
    )


def _read_whitelisted_excel(
    path: str | Path,
    allowed_columns: Sequence[str],
    required_columns: set[str],
    label: str,
) -> pd.DataFrame:
    source = Path(path)
    header = _read_header(source, label)
    available = {str(col).strip() for col in header.columns}
    missing = sorted(required_columns - available)
    if missing:
        raise ValueError(f"{label}缺少字段：{'、'.join(missing)}")
    selected = [col for col in allowed_columns if col in available]
    try:
        if source.suffix.casefold() == ".csv":
            return pd.read_csv(source, usecols=selected, dtype=object, encoding="utf-8-sig")
        return pd.read_excel(source, usecols=selected, dtype=object)
    except Exception as exc:
        raise ValueError(f"读取{label}数据失败：{exc}") from exc


def _file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SNAPSHOT_TYPES = {cls.__name__: cls for cls in (
    DashboardSnapshot, ActivityRecord, UnreimbursedRecord, ExpertInvitation,
    ExpertProfile, QualityIssue, DashboardQuality, ArchiveResult,
)}


def _encode_snapshot(value):
    if type(value).__name__ in _SNAPSHOT_TYPES:
        return {"type": type(value).__name__, "fields": {
            f.name: _encode_snapshot(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [_encode_snapshot(item) for item in value]}
    if isinstance(value, dict):
        return {"type": "dict", "items": {k: _encode_snapshot(v) for k, v in value.items()}}
    return value


def _decode_snapshot(value):
    if not isinstance(value, dict):
        return value
    kind = value["type"]
    if kind == "date":
        return date.fromisoformat(value["value"])
    if kind == "tuple":
        return tuple(_decode_snapshot(item) for item in value["items"])
    if kind == "dict":
        return {k: _decode_snapshot(v) for k, v in value["items"].items()}
    # Only explicitly listed data classes may be restored; never execute cached code.
    return _SNAPSHOT_TYPES[kind](**{k: _decode_snapshot(v) for k, v in value["fields"].items()})


class DashboardStateStore:
    """本地状态：最近成功的看板、人工覆盖排除与专家历史。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS dashboard_snapshot (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coverage_exclusions (
                    approval_id TEXT NOT NULL,
                    metric TEXT NOT NULL CHECK(metric IN ('teacher', 'student')),
                    marked_at TEXT NOT NULL,
                    PRIMARY KEY (approval_id, metric)
                );
                CREATE TABLE IF NOT EXISTS archive_batches (
                    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    source_hash TEXT NOT NULL UNIQUE,
                    archived_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experts (
                    expert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expert_profiles (
                    expert_id INTEGER NOT NULL REFERENCES experts(expert_id) ON DELETE CASCADE,
                    normalized_intro TEXT NOT NULL,
                    intro TEXT NOT NULL,
                    PRIMARY KEY (expert_id, normalized_intro)
                );
                CREATE TABLE IF NOT EXISTS expert_invitations (
                    invitation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expert_id INTEGER NOT NULL REFERENCES experts(expert_id) ON DELETE CASCADE,
                    approval_id TEXT NOT NULL,
                    detail_url TEXT NOT NULL DEFAULT '',
                    school TEXT NOT NULL,
                    activity_name TEXT NOT NULL,
                    activity_types_json TEXT NOT NULL,
                    event_date TEXT,
                    fee_amount REAL,
                    fee_shared INTEGER NOT NULL DEFAULT 0,
                    needs_review INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE (expert_id, approval_id)
                );
                CREATE TABLE IF NOT EXISTS batch_invitations (
                    batch_id INTEGER NOT NULL REFERENCES archive_batches(batch_id) ON DELETE CASCADE,
                    invitation_id INTEGER NOT NULL REFERENCES expert_invitations(invitation_id) ON DELETE CASCADE,
                    PRIMARY KEY (batch_id, invitation_id)
                );
                """
            )

    def save_snapshot(self, snapshot: DashboardSnapshot) -> None:
        payload = json.dumps(_encode_snapshot(snapshot), ensure_ascii=False, allow_nan=False)
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO dashboard_snapshot(id, version, payload) VALUES (1, 1, ?)",
                       (payload,))

    def load_snapshot(self) -> Optional[DashboardSnapshot]:
        with self._db() as db:
            row = db.execute("SELECT version, payload FROM dashboard_snapshot WHERE id = 1").fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            raise ValueError("已保存看板的版本不兼容，请重新生成看板。")
        snapshot = _decode_snapshot(json.loads(row["payload"]))
        if not isinstance(snapshot, DashboardSnapshot):
            raise ValueError("已保存的看板格式无效。")
        return snapshot

    def coverage_exclusions(self) -> set[tuple[str, str]]:
        with self._db() as db:
            rows = db.execute("SELECT approval_id, metric FROM coverage_exclusions").fetchall()
        return {(str(row["approval_id"]), str(row["metric"])) for row in rows}

    def set_coverage_excluded(self, approval_id: str, metric: str, excluded: bool) -> None:
        if metric not in {"teacher", "student"}:
            raise ValueError("metric 必须是 teacher 或 student")
        with self._db() as db:
            if excluded:
                db.execute(
                    "INSERT OR REPLACE INTO coverage_exclusions(approval_id, metric, marked_at) VALUES (?, ?, ?)",
                    (approval_id, metric, datetime.now().isoformat(timespec="seconds")),
                )
            else:
                db.execute(
                    "DELETE FROM coverage_exclusions WHERE approval_id = ? AND metric = ?",
                    (approval_id, metric),
                )

    def archive_experts(self, profiles: Sequence[ExpertProfile], source_path: str | Path) -> ArchiveResult:
        source = Path(source_path)
        source_hash = _file_hash(source)
        now = datetime.now().isoformat(timespec="seconds")
        with self._db() as db:
            duplicate = db.execute(
                "SELECT batch_id FROM archive_batches WHERE source_hash = ?", (source_hash,)
            ).fetchone()
            if duplicate:
                return ArchiveResult(int(duplicate["batch_id"]), 0, True)
            cursor = db.execute(
                "INSERT INTO archive_batches(source_name, source_hash, archived_at) VALUES (?, ?, ?)",
                (source.name, source_hash, now),
            )
            batch_id = int(cursor.lastrowid)
            imported = 0
            for profile in profiles:
                row = db.execute(
                    "SELECT expert_id FROM experts WHERE normalized_name = ?", (profile.normalized_name,)
                ).fetchone()
                if row:
                    expert_id = int(row["expert_id"])
                    db.execute(
                        "UPDATE experts SET display_name = ?, updated_at = ? WHERE expert_id = ?",
                        (profile.expert_name, now, expert_id),
                    )
                else:
                    cur = db.execute(
                        "INSERT INTO experts(normalized_name, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (profile.normalized_name, profile.expert_name, now, now),
                    )
                    expert_id = int(cur.lastrowid)
                for intro in profile.intros:
                    normalized_intro = _normalize_profile(intro)
                    if normalized_intro:
                        db.execute(
                            "INSERT OR IGNORE INTO expert_profiles(expert_id, normalized_intro, intro) VALUES (?, ?, ?)",
                            (expert_id, normalized_intro, intro),
                        )
                for invitation in profile.invitations:
                    existing = db.execute(
                        "SELECT invitation_id FROM expert_invitations WHERE expert_id = ? AND approval_id = ?",
                        (expert_id, invitation.approval_id),
                    ).fetchone()
                    values = (
                        invitation.detail_url,
                        invitation.school,
                        invitation.activity_name,
                        json.dumps(invitation.activity_types, ensure_ascii=False),
                        invitation.event_date.isoformat() if invitation.event_date else None,
                        invitation.fee_amount,
                        int(invitation.fee_shared),
                        int(invitation.needs_review),
                        now,
                    )
                    if existing:
                        invitation_id = int(existing["invitation_id"])
                        db.execute(
                            """
                            UPDATE expert_invitations
                            SET detail_url=?, school=?, activity_name=?, activity_types_json=?, event_date=?,
                                fee_amount=?, fee_shared=?, needs_review=?, updated_at=?
                            WHERE invitation_id=?
                            """,
                            (*values, invitation_id),
                        )
                    else:
                        cur = db.execute(
                            """
                            INSERT INTO expert_invitations(
                                expert_id, approval_id, detail_url, school, activity_name,
                                activity_types_json, event_date, fee_amount, fee_shared,
                                needs_review, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (expert_id, invitation.approval_id, *values),
                        )
                        invitation_id = int(cur.lastrowid)
                        imported += 1
                    db.execute(
                        "INSERT OR IGNORE INTO batch_invitations(batch_id, invitation_id) VALUES (?, ?)",
                        (batch_id, invitation_id),
                    )
            return ArchiveResult(batch_id, imported, False)

    def archive_batches(self) -> tuple[ArchiveBatch, ...]:
        with self._db() as db:
            rows = db.execute(
                """
                SELECT b.batch_id, b.source_name, b.source_hash, b.archived_at,
                       COUNT(bi.invitation_id) AS invitation_count
                FROM archive_batches b
                LEFT JOIN batch_invitations bi ON bi.batch_id = b.batch_id
                GROUP BY b.batch_id
                ORDER BY b.archived_at DESC, b.batch_id DESC
                """
            ).fetchall()
        return tuple(
            ArchiveBatch(
                int(row["batch_id"]),
                str(row["source_name"]),
                str(row["source_hash"]),
                str(row["archived_at"]),
                int(row["invitation_count"]),
            )
            for row in rows
        )

    def delete_archive_batch(self, batch_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM archive_batches WHERE batch_id = ?", (int(batch_id),))
            db.execute(
                "DELETE FROM expert_invitations WHERE invitation_id NOT IN (SELECT invitation_id FROM batch_invitations)"
            )
            db.execute("DELETE FROM experts WHERE expert_id NOT IN (SELECT expert_id FROM expert_invitations)")

    def load_archived_experts(self) -> tuple[ExpertProfile, ...]:
        with self._db() as db:
            experts = db.execute(
                "SELECT expert_id, normalized_name, display_name FROM experts ORDER BY display_name"
            ).fetchall()
            profile_rows = db.execute(
                "SELECT expert_id, intro FROM expert_profiles ORDER BY expert_id, intro"
            ).fetchall()
            invitation_rows = db.execute(
                """
                SELECT expert_id, approval_id, detail_url, school, activity_name,
                       activity_types_json, event_date, fee_amount, fee_shared, needs_review
                FROM expert_invitations
                ORDER BY event_date DESC, approval_id DESC
                """
            ).fetchall()
        intros_by_id: dict[int, list[str]] = defaultdict(list)
        for row in profile_rows:
            intros_by_id[int(row["expert_id"])].append(str(row["intro"]))
        invites_by_id: dict[int, list[ExpertInvitation]] = defaultdict(list)
        names = {int(row["expert_id"]): str(row["display_name"]) for row in experts}
        norms = {int(row["expert_id"]): str(row["normalized_name"]) for row in experts}
        for row in invitation_rows:
            expert_id = int(row["expert_id"])
            event_date = date.fromisoformat(row["event_date"]) if row["event_date"] else None
            try:
                activity_types = tuple(json.loads(row["activity_types_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                activity_types = ("未分类",)
            invites_by_id[expert_id].append(
                ExpertInvitation(
                    approval_id=str(row["approval_id"]),
                    detail_url=str(row["detail_url"] or ""),
                    expert_name=names[expert_id],
                    normalized_name=norms[expert_id],
                    intro="",
                    school=str(row["school"]),
                    activity_name=str(row["activity_name"]),
                    activity_types=activity_types,
                    event_date=event_date,
                    fee_amount=float(row["fee_amount"]) if row["fee_amount"] is not None else None,
                    fee_shared=bool(row["fee_shared"]),
                    needs_review=bool(row["needs_review"]),
                )
            )
        return _profiles_from_grouped(experts, intros_by_id, invites_by_id)


def _profiles_from_grouped(
    expert_rows: Iterable[sqlite3.Row],
    intros_by_id: dict[int, list[str]],
    invites_by_id: dict[int, list[ExpertInvitation]],
) -> tuple[ExpertProfile, ...]:
    profiles: list[ExpertProfile] = []
    for row in expert_rows:
        expert_id = int(row["expert_id"])
        invitations = tuple(invites_by_id.get(expert_id, ()))
        intros = tuple(dict.fromkeys(value for value in intros_by_id.get(expert_id, ()) if value))
        schools = tuple(sorted({inv.school for inv in invitations if inv.school}))
        types = tuple(sorted({value for inv in invitations for value in inv.activity_types}))
        dates = [inv.event_date for inv in invitations if inv.event_date]
        profiles.append(
            ExpertProfile(
                expert_name=str(row["display_name"]),
                normalized_name=str(row["normalized_name"]),
                intros=intros,
                schools=schools,
                activity_types=types,
                invitation_count=len(invitations),
                latest_event_date=max(dates) if dates else None,
                has_intro_conflict=len(intros) > 1,
                needs_review=any(inv.needs_review for inv in invitations),
                invitations=invitations,
            )
        )
    return tuple(sorted(profiles, key=lambda p: (-p.invitation_count, p.expert_name)))


def _build_current_experts(app_rows: pd.DataFrame, activity_by_id: dict[str, ActivityRecord]) -> tuple[ExpertProfile, ...]:
    grouped: dict[str, dict[str, object]] = {}
    dedupe: dict[tuple[str, str], ExpertInvitation] = {}
    for _, row in app_rows.iterrows():
        approval_id = _clean_text(row.get("_group_id"))
        activity = activity_by_id.get(approval_id)
        if not activity:
            continue
        names = _split_expert_names(row.get("专家费-专家姓名"))
        if not names:
            continue
        raw_name = _clean_text(row.get("专家费-专家姓名"))
        intro = _clean_text(row.get("专家费-专家简介"))
        fee = _parse_optional_number(row.get("专家费-专家费（元）"))
        shared = len(names) > 1
        for name in names:
            normalized = _normalize_expert_name(name)
            if not normalized:
                continue
            bucket = grouped.setdefault(
                normalized,
                {"display_name": name, "intros": [], "invitations": []},
            )
            if intro and intro not in bucket["intros"]:
                bucket["intros"].append(intro)
            invitation = ExpertInvitation(
                approval_id=approval_id,
                detail_url=activity.detail_url,
                expert_name=name,
                normalized_name=normalized,
                intro=intro,
                school=activity.school,
                activity_name=activity.activity_name,
                activity_types=activity.activity_types,
                event_date=activity.start_date,
                fee_amount=fee,
                fee_shared=shared,
                needs_review=shared or raw_name != name,
            )
            key = (normalized, approval_id)
            previous = dedupe.get(key)
            if previous is None or (
                (not previous.intro and invitation.intro)
                or (previous.fee_amount is None and invitation.fee_amount is not None)
            ):
                dedupe[key] = invitation
    for (normalized, _approval_id), invitation in dedupe.items():
        grouped[normalized]["invitations"].append(invitation)
    profiles: list[ExpertProfile] = []
    for normalized, bucket in grouped.items():
        invitations = tuple(
            sorted(
                bucket["invitations"],
                key=lambda inv: (inv.event_date or date.min, inv.approval_id),
                reverse=True,
            )
        )
        intros = tuple(bucket["intros"])
        dates = [inv.event_date for inv in invitations if inv.event_date]
        profiles.append(
            ExpertProfile(
                expert_name=str(bucket["display_name"]),
                normalized_name=normalized,
                intros=intros,
                schools=tuple(sorted({inv.school for inv in invitations})),
                activity_types=tuple(sorted({t for inv in invitations for t in inv.activity_types})),
                invitation_count=len(invitations),
                latest_event_date=max(dates) if dates else None,
                has_intro_conflict=len(intros) > 1,
                needs_review=any(inv.needs_review for inv in invitations),
                invitations=invitations,
            )
        )
    return tuple(sorted(profiles, key=lambda p: (-p.invitation_count, p.expert_name)))


def _resolve_as_of_date(
    application_path: str | Path,
    reimbursement_path: str | Path | None,
    app_rows: pd.DataFrame,
    reim_rows: pd.DataFrame,
) -> date:
    candidates: list[date] = []
    for path in (application_path, reimbursement_path):
        if not path:
            continue
        for match in DATE_RE.finditer(Path(path).stem):
            try:
                candidates.append(date(*(int(part) for part in match.groups())))
            except ValueError:
                continue
        for match in COMPACT_DATE_RE.finditer(Path(path).stem):
            value = match.group(1)
            try:
                candidates.append(date(int(value[:4]), int(value[4:6]), int(value[6:])))
            except ValueError:
                continue
    if candidates:
        return max(candidates)
    data_dates: list[date] = []
    for frame in (app_rows, reim_rows):
        for column in ("提交时间", "完成时间", "开始时间", "结束时间", "活动时间"):
            if column in frame:
                data_dates.extend(parsed for parsed in (_parse_date(v) for v in frame[column]) if parsed is not None)
    return max(data_dates) if data_dates else date.today()


def _aggregate_activities(activities: Sequence[ActivityRecord]) -> dict[str, object]:
    """构建全部院校维度聚合；未识别总部记录只进入质量提示。"""

    months = tuple(
        sorted({activity.month for activity in activities if activity.month != "日期缺失"})
        + (["日期缺失"] if any(activity.month == "日期缺失" for activity in activities) else [])
    )
    school_counts: dict[str, int] = defaultdict(int)
    school_month_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    school_type_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    school_month_type_counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    teacher_by_school: dict[str, float] = defaultdict(float)
    student_by_school: dict[str, float] = defaultdict(float)
    teacher_by_school_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    student_by_school_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for activity in activities:
        if activity.school == "未识别院校":
            continue
        school_counts[activity.school] += 1
        school_month_counts[activity.school][activity.month] += 1
        for activity_type in activity.activity_types:
            school_type_counts[activity.school][activity_type] += 1
            school_month_type_counts[activity.school][activity.month][activity_type] += 1
        if activity.is_supplementary:
            continue
        if not activity.teacher_excluded:
            teacher_by_school[activity.school] += activity.teacher_count
            teacher_by_school_month[activity.school][activity.month] += activity.teacher_count
        if not activity.student_excluded:
            student_by_school[activity.school] += activity.student_count
            student_by_school_month[activity.school][activity.month] += activity.student_count

    def plain_nested(mapping):
        return {key: dict(value) for key, value in mapping.items()}

    return {
        "months": months,
        "school_counts": dict(school_counts),
        "school_month_counts": plain_nested(school_month_counts),
        "school_type_counts": plain_nested(school_type_counts),
        "school_month_type_counts": {
            school: {month: dict(values) for month, values in months_map.items()}
            for school, months_map in school_month_type_counts.items()
        },
        "teacher_by_school": dict(teacher_by_school),
        "student_by_school": dict(student_by_school),
        "teacher_by_school_month": plain_nested(teacher_by_school_month),
        "student_by_school_month": plain_nested(student_by_school_month),
        "teacher_total": sum(teacher_by_school.values()),
        "student_total": sum(student_by_school.values()),
        "excluded_teacher_records": sum(activity.teacher_excluded for activity in activities),
        "excluded_student_records": sum(activity.student_excluded for activity in activities),
    }


def filter_dashboard_snapshot(
    snapshot: DashboardSnapshot,
    filters: DashboardFilter | None = None,
) -> DashboardView:
    """按统一口径筛选看板，并重建全部可视化聚合。"""

    active = filters or DashboardFilter()

    def matches(activity: ActivityRecord) -> bool:
        if active.start_date is not None:
            if activity.start_date is None or activity.start_date < active.start_date:
                return False
        if active.end_date is not None:
            if activity.start_date is None or activity.start_date > active.end_date:
                return False
        if active.school and activity.school != active.school:
            return False
        if active.activity_type and active.activity_type not in activity.activity_types:
            return False
        return True

    activities = tuple(activity for activity in snapshot.activities if matches(activity))
    activity_ids = {activity.approval_id for activity in activities}
    aggregates = _aggregate_activities(activities)
    unreimbursed = tuple(record for record in snapshot.unreimbursed if record.approval_id in activity_ids)

    experts: list[ExpertProfile] = []
    if snapshot.source_kind == "cleaned":
        # 清洗结果没有专家审批编号，无法把本地专家邀请与活动月份可靠关联。
        # 专家库因此作为独立的本地资料库保留，不随活动月份筛选而丢失。
        experts.extend(snapshot.experts)
    else:
        for profile in snapshot.experts:
            invitations = tuple(
                invitation for invitation in profile.invitations if invitation.approval_id in activity_ids
            )
            if not invitations:
                continue
            dates = [invitation.event_date for invitation in invitations if invitation.event_date]
            experts.append(
                ExpertProfile(
                    expert_name=profile.expert_name,
                    normalized_name=profile.normalized_name,
                    intros=profile.intros,
                    schools=tuple(sorted({invitation.school for invitation in invitations})),
                    activity_types=tuple(
                        sorted(
                            {
                                activity_type
                                for invitation in invitations
                                for activity_type in invitation.activity_types
                            }
                        )
                    ),
                    invitation_count=len(invitations),
                    latest_event_date=max(dates) if dates else None,
                    has_intro_conflict=profile.has_intro_conflict,
                    needs_review=any(invitation.needs_review for invitation in invitations),
                    invitations=invitations,
                )
            )
    experts.sort(key=lambda profile: (-profile.invitation_count, profile.expert_name))

    closure_counts: dict[str, int] = {}
    if snapshot.supports_reimbursement:
        closure_counts = {
            "已报销": max(0, len(activities) - len({record.approval_id for record in unreimbursed})),
            "报销审批中": 0,
            "已结束未报销": 0,
            "进行中": 0,
            "未开始": 0,
        }
        for record in unreimbursed:
            closure_counts[record.business_state] = closure_counts.get(record.business_state, 0) + 1

    return DashboardView(
        filters=active,
        activities=activities,
        unreimbursed=unreimbursed,
        experts=tuple(experts),
        closure_counts=closure_counts,
        **aggregates,
    )


def _build_cleaned_snapshot(
    application_path: str | Path,
    store: DashboardStateStore,
) -> DashboardSnapshot:
    rows = _read_whitelisted_excel(application_path, CLEANED_COLUMNS, CLEANED_REQUIRED, "清洗结果")
    exclusions = store.coverage_exclusions()
    activities: list[ActivityRecord] = []
    missing_school = 0
    missing_start = 0
    invalid_teacher = 0
    invalid_student = 0
    quality_issues: list[QualityIssue] = []
    identity_counts = defaultdict(int)
    legacy_group_counts = defaultdict(int)
    stable_group_counts = defaultdict(int)
    def identities(row):
        school = normalize_cleaned_school(row.get("学校名称")) or "未识别院校"
        raw = "\x1f".join((school, _clean_text(row.get("活动名称")),
                            _clean_text(row.get("活动类型")), _clean_text(row.get("活动时间"))))
        dt = _parse_date(row.get("活动时间"))
        explicit = _clean_text(row.get("审批编号"))
        base = ('approval:' + explicit) if explicit else "\x1f".join((school,
            _clean_text(row.get("活动名称")), _clean_text(row.get("活动类型")),
            dt.isoformat() if dt else _clean_text(row.get("活动时间")),
            _clean_text(row.get("新闻链接"))))
        return raw, base
    for _, row in rows.iterrows():
        raw, base = identities(row)
        legacy_group_counts[raw] += 1
        stable_group_counts[base] += 1
    stable_occurrences = defaultdict(int)
    for row_index, (_, row) in enumerate(rows.iterrows(), start=1):
        school = normalize_cleaned_school(row.get("学校名称")) or "未识别院校"
        missing_school += int(school == "未识别院校")
        event_date = _parse_date(row.get("活动时间"))
        missing_start += int(event_date is None)
        teacher_count, teacher_bad = _parse_number(row.get("服务教师（人数）"))
        student_count, student_bad = _parse_number(row.get("服务学生（人数）"))
        invalid_teacher += int(teacher_bad)
        invalid_student += int(student_bad)
        identity = "\x1f".join(
            (
                school,
                _clean_text(row.get("活动名称")),
                _clean_text(row.get("活动类型")),
                _clean_text(row.get("活动时间")),
            )
        )
        _, stable = identities(row)
        # Approval IDs and links identify duplicate-looking activities after sorting.
        # Without either, use the record's counts; never transfer an ambiguous legacy flag.
        if stable_group_counts[stable] > 1:
            stable += f'\x1f{teacher_count}\x1f{student_count}'
        stable_occurrences[stable] += 1
        stable += '\x1f' + str(stable_occurrences[stable])
        approval_id = 'CLN3-' + hashlib.sha1(stable.encode('utf-8')).hexdigest()[:12].upper()
        legacy_identity = identity + '\x1f' + str(row_index)
        legacy_id = 'CLN-' + hashlib.sha1(legacy_identity.encode('utf-8')).hexdigest()[:12].upper()
        identity_counts[identity] += 1
        old_stable = identity + '\x1f' + str(identity_counts[identity])
        old_id = 'CLN2-' + hashlib.sha1(old_stable.encode('utf-8')).hexdigest()[:12].upper()
        for metric in ('teacher', 'student'):
            for previous_id in (legacy_id, old_id):
                if (previous_id, metric) in exclusions and legacy_group_counts[identity] == 1:
                    store.set_coverage_excluded(approval_id, metric, True)
                    store.set_coverage_excluded(previous_id, metric, False)
                    exclusions.add((approval_id, metric))
                elif (previous_id, metric) in exclusions:
                    quality_issues.append(QualityIssue('legacy_exclusion', '旧版排除设置需复核',
                        'warning', approval_id, school, _clean_text(row.get("活动名称")),
                        '多条同名活动的旧版排除设置无法确定归属，未自动沿用。',
                        '本行暂按原人数统计。', '请在覆盖明细中重新选择要排除的活动。',
                        _clean_text(row.get("新闻链接"))))
        activity_name = _clean_text(row.get("活动名称")) or "未命名活动"
        detail_url = _clean_text(row.get("新闻链接"))
        if school == "未识别院校":
            quality_issues.append(
                QualityIssue(
                    "missing_school",
                    "未归属驻校",
                    "warning",
                    approval_id,
                    school,
                    activity_name,
                    "学校名称无法归并到有效驻校院校。",
                    "不进入院校、活动类型和覆盖人次聚合。",
                    "核对清洗结果中的学校名称或重新执行清洗。",
                    detail_url,
                )
            )
        if event_date is None:
            quality_issues.append(
                QualityIssue(
                    "missing_date",
                    "活动日期缺失",
                    "warning",
                    approval_id,
                    school,
                    activity_name,
                    "活动时间无法解析。",
                    "不进入启用日期条件后的筛选和月度趋势。",
                    "核对清洗结果中的活动时间。",
                    detail_url,
                )
            )
        for issue_type, label, is_bad, impact in (
            ("invalid_teacher", "教师人数格式异常", teacher_bad, "教师覆盖人次按 0 计算。"),
            ("invalid_student", "学生人数格式异常", student_bad, "学生覆盖人次按 0 计算。"),
        ):
            if is_bad:
                quality_issues.append(
                    QualityIssue(
                        issue_type,
                        label,
                        "warning",
                        approval_id,
                        school,
                        activity_name,
                        "人数单元格不是可识别数字。",
                        impact,
                        "核对清洗结果中的计划人数。",
                        detail_url,
                    )
                )
        activities.append(
            ActivityRecord(
                approval_id=approval_id,
                detail_url=detail_url,
                school=school,
                activity_name=activity_name,
                activity_types=_split_types(row.get("活动类型")),
                start_date=event_date,
                end_date=event_date,
                month=event_date.strftime("%Y-%m") if event_date else "日期缺失",
                teacher_count=teacher_count,
                student_count=student_count,
                status="已清洗",
                teacher_excluded=(approval_id, "teacher") in exclusions,
                student_excluded=(approval_id, "student") in exclusions,
            )
        )
    activities.sort(key=lambda item: (item.start_date or date.max, item.school, item.activity_name))
    aggregates = _aggregate_activities(activities)
    as_of = _resolve_as_of_date(application_path, None, rows, pd.DataFrame())
    quality = DashboardQuality(
        raw_application_rows=len(rows),
        logical_application_records=len(rows),
        non_approved_application_records=0,
        missing_school_records=missing_school,
        missing_start_date_records=missing_start,
        invalid_teacher_values=invalid_teacher,
        invalid_student_values=invalid_student,
        raw_reimbursement_rows=0,
        logical_reimbursement_records=0,
        reimbursement_records_without_links=0,
        reimbursement_records_with_multiple_links=0,
        linked_application_ids_not_in_file=0,
        expert_rows=0,
        expert_names_needing_review=0,
        expert_profiles_with_conflicts=0,
        total_issues=len(quality_issues),
    )
    archived_experts = store.load_archived_experts()
    return DashboardSnapshot(
        source_application_path=str(Path(application_path)),
        source_reimbursement_path="",
        source_kind="cleaned",
        supports_reimbursement=False,
        supports_experts=True,
        as_of_date=as_of,
        activities=tuple(activities),
        unreimbursed=(),
        experts=archived_experts,
        quality=quality,
        quality_issues=tuple(quality_issues),
        **aggregates,
    )


def _build_base_dashboard_snapshot(
    application_path: str | Path,
    reimbursement_path: str | Path | None,
    state_store: DashboardStateStore | str | Path,
) -> DashboardSnapshot:
    """读取原始审批组合或清洗结果，并构建不可变看板快照。"""

    store = state_store if isinstance(state_store, DashboardStateStore) else DashboardStateStore(state_store)
    source_kind = detect_activity_source_kind(application_path)
    if source_kind == "cleaned":
        return _build_cleaned_snapshot(application_path, store)
    if not reimbursement_path:
        raise ValueError("企业微信原始活动申请需要同时选择活动报销文件。")
    app_rows = _read_whitelisted_excel(application_path, APP_COLUMNS, APP_REQUIRED, "活动申请")
    reim_rows = _read_whitelisted_excel(reimbursement_path, REIM_COLUMNS, REIM_REQUIRED, "活动报销")

    app_rows["_primary_id"] = app_rows["审批编号"].map(_primary_approval_id)
    app_rows["_group_id"] = app_rows["_primary_id"].replace("", pd.NA).ffill()
    primary_apps = app_rows[app_rows["_primary_id"] != ""].drop_duplicates("_primary_id", keep="first")
    exclusions = store.coverage_exclusions()

    activities: list[ActivityRecord] = []
    invalid_teacher = 0
    invalid_student = 0
    missing_school = 0
    missing_start = 0
    non_approved = 0
    quality_issues: list[QualityIssue] = []
    for _, row in primary_apps.iterrows():
        approval_id = _clean_text(row.get("_primary_id"))
        activity_name = _clean_text(row.get("活动名称")) or "未命名活动"
        detail_url = _clean_text(row.get("审批详情"))
        status = _clean_text(row.get("当前审批状态"))
        if not _is_approved(status):
            non_approved += 1
            quality_issues.append(
                QualityIssue(
                    "non_approved",
                    "非已通过申请",
                    "info",
                    approval_id,
                    _extract_school(row.get("申请人部门")),
                    activity_name,
                    f"当前审批状态为“{status or '未知'}”。",
                    "不进入看板活动、覆盖和报销闭环统计。",
                    "在企业微信中核对审批状态。",
                    detail_url,
                )
            )
            continue
        school = _extract_school(row.get("申请人部门"))
        if school == "未识别院校":
            missing_school += 1
        start_date = _parse_date(row.get("开始时间"))
        end_date = _parse_date(row.get("结束时间"))
        if start_date is None:
            missing_start += 1
        teacher_count, teacher_bad = _parse_number(row.get("服务教师（人数）"))
        student_count, student_bad = _parse_number(row.get("服务学生（人数）"))
        invalid_teacher += int(teacher_bad)
        invalid_student += int(student_bad)
        if school == "未识别院校":
            quality_issues.append(
                QualityIssue(
                    "missing_school",
                    "未归属驻校",
                    "warning",
                    approval_id,
                    school,
                    activity_name,
                    "申请人部门中没有可识别的“驻校办公室/院校”层级。",
                    "保留在活动总数，但不进入院校、类型和覆盖人次聚合。",
                    "核对企业微信申请人部门设置。",
                    detail_url,
                )
            )
        if start_date is None:
            quality_issues.append(
                QualityIssue(
                    "missing_date",
                    "活动日期缺失",
                    "warning",
                    approval_id,
                    school,
                    activity_name,
                    "开始时间无法解析。",
                    "不进入启用日期条件后的筛选和月度趋势。",
                    "打开审批详情核对开始时间。",
                    detail_url,
                )
            )
        for issue_type, label, is_bad, impact in (
            ("invalid_teacher", "教师人数格式异常", teacher_bad, "教师覆盖人次按 0 计算。"),
            ("invalid_student", "学生人数格式异常", student_bad, "学生覆盖人次按 0 计算。"),
        ):
            if is_bad:
                quality_issues.append(
                    QualityIssue(
                        issue_type,
                        label,
                        "warning",
                        approval_id,
                        school,
                        activity_name,
                        "计划人数单元格不是可识别数字。",
                        impact,
                        "打开审批详情核对计划人数。",
                        detail_url,
                    )
                )
        activities.append(
            ActivityRecord(
                approval_id=approval_id,
                detail_url=detail_url,
                school=school,
                activity_name=activity_name,
                activity_types=_split_types(row.get("活动类型")),
                start_date=start_date,
                end_date=end_date,
                month=start_date.strftime("%Y-%m") if start_date else "日期缺失",
                teacher_count=teacher_count,
                student_count=student_count,
                status=status,
                teacher_excluded=(approval_id, "teacher") in exclusions,
                student_excluded=(approval_id, "student") in exclusions,
            )
        )

    activities.sort(key=lambda item: (item.start_date or date.max, item.school, item.activity_name))
    activity_by_id = {activity.approval_id: activity for activity in activities}

    reim_rows["_primary_id"] = reim_rows["审批编号"].map(_primary_approval_id)
    primary_reim = reim_rows[reim_rows["_primary_id"] != ""].drop_duplicates("_primary_id", keep="first")
    approved_links: set[str] = set()
    pending_links: set[str] = set()
    linked_all: set[str] = set()
    reim_without_links = 0
    reim_multi_links = 0
    external_issue_ids: set[str] = set()
    for _, row in primary_reim.iterrows():
        reimbursement_id = _clean_text(row.get("_primary_id"))
        reimbursement_url = _clean_text(row.get("审批详情"))
        links = _approval_ids(row.get("关联申请单"))
        linked_all.update(links)
        if not links:
            reim_without_links += 1
            quality_issues.append(
                QualityIssue(
                    "reimbursement_without_link",
                    "报销无关联申请",
                    "warning",
                    reimbursement_id,
                    "",
                    f"活动报销 {reimbursement_id}",
                    "关联申请单中没有可识别的 12 位审批编号。",
                    "无法证明任何活动已进入报销闭环。",
                    "打开报销审批并补充或核对关联申请单。",
                    reimbursement_url,
                )
            )
        if len(links) > 1:
            reim_multi_links += 1
        for linked_id in links:
            if linked_id not in activity_by_id and linked_id not in external_issue_ids:
                external_issue_ids.add(linked_id)
                quality_issues.append(
                    QualityIssue(
                        "external_application_link",
                        "关联申请不在当前活动中",
                        "info",
                        linked_id,
                        "",
                        f"外部申请 {linked_id}",
                        f"报销单 {reimbursement_id} 关联的申请不在当前已通过活动集合中。",
                        "不影响当前文件内其他活动的闭环判断。",
                        "确认是否跨批次导出或关联了未通过申请。",
                        reimbursement_url,
                    )
                )
        if _is_approved(row.get("当前审批状态")):
            approved_links.update(links)
        elif not _is_rejected(row.get("当前审批状态")):
            pending_links.update(links)

    as_of = _resolve_as_of_date(application_path, reimbursement_path, primary_apps, primary_reim)
    unreimbursed: list[UnreimbursedRecord] = []
    for activity in activities:
        if activity.approval_id in approved_links:
            continue
        if activity.approval_id in pending_links:
            business_state = "报销审批中"
        elif activity.start_date and activity.start_date > as_of:
            business_state = "未开始"
        elif activity.end_date and activity.start_date and activity.start_date <= as_of <= activity.end_date:
            business_state = "进行中"
        else:
            business_state = "已结束未报销"
        days_since_end = None
        if activity.end_date and activity.end_date < as_of:
            days_since_end = (as_of - activity.end_date).days
        unreimbursed.append(
            UnreimbursedRecord(
                approval_id=activity.approval_id,
                detail_url=activity.detail_url,
                school=activity.school,
                activity_name=activity.activity_name,
                activity_types=activity.activity_types,
                start_date=activity.start_date,
                end_date=activity.end_date,
                days_since_end=days_since_end,
                business_state=business_state,
            )
        )
    unreimbursed.sort(
        key=lambda item: (
            item.business_state != "已结束未报销",
            -(item.days_since_end or -1),
            item.school,
        )
    )

    aggregates = _aggregate_activities(activities)

    experts = _build_current_experts(app_rows, activity_by_id)
    for profile in experts:
        first_invitation = profile.invitations[0] if profile.invitations else None
        if profile.needs_review:
            quality_issues.append(
                QualityIssue(
                    "expert_name_review",
                    "专家姓名待核对",
                    "info",
                    first_invitation.approval_id if first_invitation else "",
                    first_invitation.school if first_invitation else "",
                    profile.expert_name,
                    "专家姓名来自多人共用或带分隔符的原始单元格。",
                    "专家邀请已拆分，但姓名仍建议人工确认。",
                    "在专家库中查看邀请历史并核对原审批。",
                    first_invitation.detail_url if first_invitation else "",
                )
            )
        if profile.has_intro_conflict:
            quality_issues.append(
                QualityIssue(
                    "expert_intro_conflict",
                    "专家简介存在多个版本",
                    "info",
                    first_invitation.approval_id if first_invitation else "",
                    first_invitation.school if first_invitation else "",
                    profile.expert_name,
                    f"当前文件中存在 {len(profile.intros)} 个不同简介版本。",
                    "不会自动覆盖简介，专家档案保留全部版本。",
                    "在专家库中比较版本并人工判断。",
                    first_invitation.detail_url if first_invitation else "",
                )
            )
    expert_sync = store.archive_experts(experts, application_path) if experts else None
    quality = DashboardQuality(
        raw_application_rows=len(app_rows),
        logical_application_records=len(primary_apps),
        non_approved_application_records=non_approved,
        missing_school_records=missing_school,
        missing_start_date_records=missing_start,
        invalid_teacher_values=invalid_teacher,
        invalid_student_values=invalid_student,
        raw_reimbursement_rows=len(reim_rows),
        logical_reimbursement_records=len(primary_reim),
        reimbursement_records_without_links=reim_without_links,
        reimbursement_records_with_multiple_links=reim_multi_links,
        linked_application_ids_not_in_file=len(linked_all - set(activity_by_id)),
        expert_rows=sum(1 for value in app_rows.get("专家费-专家姓名", pd.Series(dtype=object)) if _split_expert_names(value)),
        expert_names_needing_review=sum(1 for profile in experts if profile.needs_review),
        expert_profiles_with_conflicts=sum(1 for profile in experts if profile.has_intro_conflict),
        total_issues=len(quality_issues),
    )

    return DashboardSnapshot(
        source_application_path=str(Path(application_path)),
        source_reimbursement_path=str(Path(reimbursement_path)),
        source_kind="raw",
        supports_reimbursement=True,
        supports_experts=True,
        as_of_date=as_of,
        activities=tuple(activities),
        unreimbursed=tuple(unreimbursed),
        experts=experts,
        quality=quality,
        quality_issues=tuple(quality_issues),
        expert_sync=expert_sync,
        **aggregates,
    )


def build_dashboard_snapshot(
    application_path: str | Path,
    reimbursement_path: str | Path | None,
    state_store: DashboardStateStore | str | Path,
    supplementary_path: str | Path | None = None,
) -> DashboardSnapshot:
    """补充活动仅参与活动计数，视为已报销，不进入覆盖与专家统计。"""
    additions = []
    issues = []
    if supplementary_path:
        required = {"活动名称", "学校名称", "活动类型", "活动时间"}
        rows = _read_whitelisted_excel(
            supplementary_path, ("活动名称", "学校名称", "活动类型", "活动时间", "新闻链接"),
            required, "补充表格",
        )
        for row_index, (_, row) in enumerate(rows.iterrows(), start=2):
            if not any(_clean_text(row.get(column)) for column in required):
                continue
            name = _clean_text(row.get("活动名称"))
            if not name:
                raise ValueError(f"补充表格第 {row_index} 行缺少活动名称，请核对后重试。")
            school = normalize_cleaned_school(row.get("学校名称")) or "未识别院校"
            event_date = _parse_date(row.get("活动时间"))
            identity = "\x1f".join((school, name, str(row.get("活动时间")), str(row_index)))
            record_id = "SUP-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12].upper()
            detail_url = _clean_text(row.get("新闻链接"))
            additions.append(ActivityRecord(
                approval_id=record_id, detail_url=detail_url, school=school, activity_name=name,
                activity_types=_split_types(row.get("活动类型")), start_date=event_date,
                end_date=event_date, month=event_date.strftime("%Y-%m") if event_date else "日期缺失",
                teacher_count=0, student_count=0, status="已报销", is_supplementary=True,
            ))
            for condition, kind, label, impact in (
                (school == "未识别院校", "missing_school", "未归属驻校", "不进入院校和活动类型聚合。"),
                (event_date is None, "missing_date", "活动日期缺失", "不进入日期筛选和月度趋势。"),
            ):
                if condition:
                    issues.append(QualityIssue(kind, label, "warning", record_id, school, name,
                        f"补充表格第 {row_index} 行：{label}。", impact, "核对补充表格对应字段。", detail_url))
    snapshot = _build_base_dashboard_snapshot(application_path, reimbursement_path, state_store)
    if not supplementary_path:
        return snapshot
    activities = tuple(sorted((*snapshot.activities, *additions),
        key=lambda item: (item.start_date or date.max, item.school, item.activity_name)))
    quality = replace(snapshot.quality,
        missing_school_records=snapshot.quality.missing_school_records + sum(i.issue_type == "missing_school" for i in issues),
        missing_start_date_records=snapshot.quality.missing_start_date_records + sum(i.issue_type == "missing_date" for i in issues),
        total_issues=snapshot.quality.total_issues + len(issues))
    return replace(snapshot, activities=activities, quality=quality,
        quality_issues=(*snapshot.quality_issues, *issues),
        source_supplementary_path=str(Path(supplementary_path)), **_aggregate_activities(activities))


__all__ = [
    "ActivityRecord",
    "ArchiveBatch",
    "ArchiveResult",
    "DashboardFilter",
    "DashboardQuality",
    "DashboardSnapshot",
    "DashboardStateStore",
    "DashboardView",
    "ExpertInvitation",
    "ExpertProfile",
    "QualityIssue",
    "UnreimbursedRecord",
    "build_dashboard_snapshot",
    "detect_activity_source_kind",
    "filter_dashboard_snapshot",
]
