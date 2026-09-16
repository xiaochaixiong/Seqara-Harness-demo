"""
工作日历台 — PySide6 数据层：日/周/月视图、四象限、番茄会话（供工具集 QWidget 界面使用）。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    QSortFilterProxyModel,
    Qt,
    QDate,
    QTimer,
    Signal,
    Slot,
)

if TYPE_CHECKING:
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _local_now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


def _local_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def _parse_local_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _parse_date_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def db_path_for_bundle(bundle_dir: Path) -> Path:
    """数据目录与工具集同 bundle，便于便携部署。"""
    root = bundle_dir / "work_calendar_data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "app.db"


def init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                quadrant INTEGER NOT NULL DEFAULT 0,
                due_date TEXT,
                start_datetime TEXT,
                end_datetime TEXT,
                all_day INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                planned_duration_sec INTEGER NOT NULL,
                actual_duration_sec INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class TaskModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    QuadrantRole = Qt.ItemDataRole.UserRole + 3
    CompletedRole = Qt.ItemDataRole.UserRole + 4
    StartRole = Qt.ItemDataRole.UserRole + 5
    EndRole = Qt.ItemDataRole.UserRole + 6
    DueRole = Qt.ItemDataRole.UserRole + 7
    AllDayRole = Qt.ItemDataRole.UserRole + 8

    def __init__(self, db_file: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._rows: list[dict] = []
        self.load()

    def roleNames(self):
        return {
            self.IdRole: QByteArray(b"id"),
            self.TitleRole: QByteArray(b"title"),
            self.QuadrantRole: QByteArray(b"quadrant"),
            self.CompletedRole: QByteArray(b"completed"),
            self.StartRole: QByteArray(b"startDatetime"),
            self.EndRole: QByteArray(b"endDatetime"),
            self.DueRole: QByteArray(b"dueDate"),
            self.AllDayRole: QByteArray(b"allDay"),
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.IdRole:
            return row["id"]
        if role == self.TitleRole:
            return row["title"]
        if role == self.QuadrantRole:
            return row["quadrant"]
        if role == self.CompletedRole:
            return bool(row["completed"])
        if role == self.StartRole:
            return row["start_datetime"] or ""
        if role == self.EndRole:
            return row["end_datetime"] or ""
        if role == self.DueRole:
            return row["due_date"] or ""
        if role == self.AllDayRole:
            return bool(row["all_day"])
        if role == Qt.ItemDataRole.DisplayRole:
            return row["title"]
        return None

    def _row_from_db(self, r: tuple) -> dict:
        return {
            "id": r[0],
            "title": r[1],
            "quadrant": int(r[2]),
            "due_date": r[3],
            "start_datetime": r[4],
            "end_datetime": r[5],
            "all_day": bool(r[6]),
            "completed": bool(r[7]),
        }

    def load(self) -> None:
        self.beginResetModel()
        conn = sqlite3.connect(self._db)
        try:
            cur = conn.execute(
                """
                SELECT id, title, quadrant, due_date, start_datetime, end_datetime,
                       all_day, completed
                FROM tasks ORDER BY id ASC
                """
            )
            self._rows = [self._row_from_db(r) for r in cur.fetchall()]
        finally:
            conn.close()
        self.endResetModel()

    def add_task(self, title: str, quadrant: int) -> None:
        title = (title or "").strip()
        if not title:
            return
        quadrant = max(0, min(3, int(quadrant)))
        now = _utc_now_iso()
        conn = sqlite3.connect(self._db)
        try:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, quadrant, completed, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                """,
                (title, quadrant, now, now),
            )
            conn.commit()
            new_id = int(cur.lastrowid)
        finally:
            conn.close()
        row = {
            "id": new_id,
            "title": title,
            "quadrant": quadrant,
            "due_date": None,
            "start_datetime": None,
            "end_datetime": None,
            "all_day": False,
            "completed": False,
        }
        i = len(self._rows)
        self.beginInsertRows(QModelIndex(), i, i)
        self._rows.append(row)
        self.endInsertRows()

    def add_scheduled_task(
        self,
        title: str,
        quadrant: int,
        start_local: datetime,
        end_local: datetime,
    ) -> None:
        title = (title or "").strip()
        if not title or end_local <= start_local:
            return
        quadrant = max(0, min(3, int(quadrant)))
        now = _utc_now_iso()
        start_s = _local_iso(start_local)
        end_s = _local_iso(end_local)
        conn = sqlite3.connect(self._db)
        try:
            cur = conn.execute(
                """
                INSERT INTO tasks (
                    title, quadrant, start_datetime, end_datetime, all_day,
                    completed, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (title, quadrant, start_s, end_s, now, now),
            )
            conn.commit()
            new_id = int(cur.lastrowid)
        finally:
            conn.close()
        row = {
            "id": new_id,
            "title": title,
            "quadrant": quadrant,
            "due_date": None,
            "start_datetime": start_s,
            "end_datetime": end_s,
            "all_day": False,
            "completed": False,
        }
        i = len(self._rows)
        self.beginInsertRows(QModelIndex(), i, i)
        self._rows.append(row)
        self.endInsertRows()

    def remove_task(self, task_id: int) -> None:
        conn = sqlite3.connect(self._db)
        try:
            conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._rows[i]
                self.endRemoveRows()
                break

    def set_quadrant(self, task_id: int, quadrant: int) -> None:
        quadrant = max(0, min(3, int(quadrant)))
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                "UPDATE tasks SET quadrant = ?, updated_at = ? WHERE id = ?",
                (quadrant, _utc_now_iso(), int(task_id)),
            )
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                row["quadrant"] = quadrant
                ix = self.index(i, 0)
                self.dataChanged.emit(ix, ix, [self.QuadrantRole])
                break

    def set_completed(self, task_id: int, completed: bool) -> None:
        done = 1 if bool(completed) else 0
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                "UPDATE tasks SET completed = ?, updated_at = ? WHERE id = ?",
                (done, _utc_now_iso(), int(task_id)),
            )
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                row["completed"] = bool(completed)
                ix = self.index(i, 0)
                self.dataChanged.emit(ix, ix, [self.CompletedRole])
                break

    def clear_schedule(self, task_id: int) -> None:
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                """
                UPDATE tasks SET start_datetime = NULL, end_datetime = NULL,
                    all_day = 0, updated_at = ? WHERE id = ?
                """,
                (_utc_now_iso(), int(task_id)),
            )
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                row["start_datetime"] = None
                row["end_datetime"] = None
                row["all_day"] = False
                ix = self.index(i, 0)
                # 通知全部角色，确保代理模型与 QML 委托刷新日程相关绑定
                self.dataChanged.emit(ix, ix, list(self.roleNames().keys()))
                break

    def update_task_basic(self, task_id: int, title: str, quadrant: int) -> None:
        title = (title or "").strip()
        if not title:
            return
        quadrant = max(0, min(3, int(quadrant)))
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                """
                UPDATE tasks
                SET title = ?, quadrant = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, quadrant, _utc_now_iso(), int(task_id)),
            )
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                row["title"] = title
                row["quadrant"] = quadrant
                ix = self.index(i, 0)
                self.dataChanged.emit(ix, ix, [self.TitleRole, self.QuadrantRole])
                break

    def update_task_schedule(
        self,
        task_id: int,
        start_local: datetime,
        end_local: datetime,
        all_day: bool = False,
    ) -> None:
        if end_local <= start_local:
            return
        start_s = _local_iso(start_local)
        end_s = _local_iso(end_local)
        all_day_i = 1 if bool(all_day) else 0
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                """
                UPDATE tasks
                SET start_datetime = ?, end_datetime = ?, all_day = ?, updated_at = ?
                WHERE id = ?
                """,
                (start_s, end_s, all_day_i, _utc_now_iso(), int(task_id)),
            )
            conn.commit()
        finally:
            conn.close()
        for i, row in enumerate(self._rows):
            if row["id"] == int(task_id):
                row["start_datetime"] = start_s
                row["end_datetime"] = end_s
                row["all_day"] = bool(all_day)
                ix = self.index(i, 0)
                self.dataChanged.emit(ix, ix, [self.StartRole, self.EndRole, self.AllDayRole])
                break

    def task_snapshot(self, task_id: int) -> dict | None:
        for row in self._rows:
            if row["id"] == int(task_id):
                return dict(row)
        return None

    def detect_conflicts(
        self,
        start_local: datetime,
        end_local: datetime,
        exclude_task_id: int = -1,
    ) -> list[dict]:
        if end_local <= start_local:
            return []
        start_s = _local_iso(start_local)
        end_s = _local_iso(end_local)
        out: list[dict] = []
        conn = sqlite3.connect(self._db)
        try:
            cur = conn.execute(
                """
                SELECT id, title, start_datetime, end_datetime
                FROM tasks
                WHERE completed = 0
                  AND start_datetime IS NOT NULL
                  AND end_datetime IS NOT NULL
                  AND id != ?
                  AND start_datetime < ?
                  AND end_datetime > ?
                ORDER BY start_datetime ASC
                """,
                (int(exclude_task_id), end_s, start_s),
            )
            for r in cur.fetchall():
                out.append(
                    {
                        "id": int(r[0]),
                        "title": str(r[1] or ""),
                        "start_datetime": str(r[2] or ""),
                        "end_datetime": str(r[3] or ""),
                    }
                )
        finally:
            conn.close()
        return out

    def has_task(self, task_id: int) -> bool:
        return any(row["id"] == int(task_id) for row in self._rows)

    def schedule_focus_date_iso(self, task_id: int) -> str:
        """用于日历定位：优先排程开始日，否则截止日期。"""
        for row in self._rows:
            if row["id"] != int(task_id):
                continue
            st = row.get("start_datetime") or ""
            if isinstance(st, str) and len(st) >= 10:
                return st[:10]
            du = row.get("due_date") or ""
            if isinstance(du, str) and len(du) >= 10:
                return du[:10]
            if isinstance(du, str) and du:
                return du.split("T")[0][:10]
            return ""
        return ""


def _split_task_into_week_segments(
    t0: datetime,
    t1: datetime,
    week_start: date,
) -> list[tuple[int, int, int]]:
    """Return list of (day_index 0-6, start_minute, duration_minutes)."""
    out: list[tuple[int, int, int]] = []
    ws = datetime.combine(week_start, time.min)
    we = ws + timedelta(days=7)
    seg0 = max(t0, ws)
    seg1 = min(t1, we)
    if seg0 >= seg1:
        return out
    cur = seg0
    while cur < seg1:
        day_start = datetime.combine(cur.date(), time.min)
        next_day = day_start + timedelta(days=1)
        chunk_end = min(seg1, next_day)
        day_index = (cur.date() - week_start).days
        if 0 <= day_index < 7:
            start_min = cur.hour * 60 + cur.minute + cur.second // 60
            dur = int((chunk_end - cur).total_seconds() // 60)
            if dur > 0:
                out.append((day_index, start_min, dur))
        cur = chunk_end
    return out


# 跨整日片段（按日）与「几乎整天」展示在周视图顶部全日带
_FULL_DAY_MINUTES = 24 * 60 - 1


def _build_week_timed_and_allday_rows(
    db_file: Path,
    week_start: date,
) -> tuple[list[dict], list[dict], int]:
    timed: list[dict] = []
    allday_buckets: list[list[dict]] = [[] for _ in range(7)]
    conn = sqlite3.connect(db_file)
    try:
        cur = conn.execute(
            """
            SELECT id, title, quadrant, start_datetime, end_datetime
            FROM tasks
            WHERE completed = 0
              AND start_datetime IS NOT NULL
              AND end_datetime IS NOT NULL
            """
        )
        for r in cur.fetchall():
            tid, title, quad, s_s, e_s = r[0], r[1], int(r[2]), r[3], r[4]
            t0 = _parse_local_iso(s_s)
            t1 = _parse_local_iso(e_s)
            if not t0 or not t1 or t1 <= t0:
                continue
            for day_idx, sm, dm in _split_task_into_week_segments(t0, t1, week_start):
                base = {
                    "task_id": tid,
                    "title": title,
                    "quadrant": quad,
                    "day_index": day_idx,
                }
                if sm == 0 and dm >= _FULL_DAY_MINUTES:
                    allday_buckets[day_idx].append(dict(base))
                else:
                    row = dict(base)
                    row["start_minute"] = sm
                    row["duration_minutes"] = max(1, dm)
                    timed.append(row)
    finally:
        conn.close()
    allday_flat: list[dict] = []
    for d in range(7):
        for si, row in enumerate(allday_buckets[d]):
            r2 = dict(row)
            r2["stack_slot"] = si
            allday_flat.append(r2)
    mx = max((len(allday_buckets[i]) for i in range(7)), default=0)
    strip_h = max(28, min(mx * 26 + 12, 220))
    return timed, allday_flat, strip_h


class WeekScheduleModel(QAbstractListModel):
    TaskIdRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    QuadrantRole = Qt.ItemDataRole.UserRole + 3
    DayIndexRole = Qt.ItemDataRole.UserRole + 4
    StartMinuteRole = Qt.ItemDataRole.UserRole + 5
    DurationMinuteRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, db_file: Path, calendar: "CalendarController", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._calendar = calendar
        self._rows: list[dict] = []

    def apply_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def roleNames(self):
        return {
            self.TaskIdRole: QByteArray(b"taskId"),
            self.TitleRole: QByteArray(b"title"),
            self.QuadrantRole: QByteArray(b"quadrant"),
            self.DayIndexRole: QByteArray(b"dayIndex"),
            self.StartMinuteRole: QByteArray(b"startMinute"),
            self.DurationMinuteRole: QByteArray(b"durationMinutes"),
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.TaskIdRole:
            return row["task_id"]
        if role == self.TitleRole:
            return row["title"]
        if role == self.QuadrantRole:
            return row["quadrant"]
        if role == self.DayIndexRole:
            return row["day_index"]
        if role == self.StartMinuteRole:
            return row["start_minute"]
        if role == self.DurationMinuteRole:
            return row["duration_minutes"]
        return None


class WeekAllDayModel(QAbstractListModel):
    TaskIdRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    QuadrantRole = Qt.ItemDataRole.UserRole + 3
    DayIndexRole = Qt.ItemDataRole.UserRole + 4
    StackSlotRole = Qt.ItemDataRole.UserRole + 5

    def __init__(self, db_file: Path, calendar: "CalendarController", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._calendar = calendar
        self._rows: list[dict] = []

    def apply_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def roleNames(self):
        return {
            self.TaskIdRole: QByteArray(b"taskId"),
            self.TitleRole: QByteArray(b"title"),
            self.QuadrantRole: QByteArray(b"quadrant"),
            self.DayIndexRole: QByteArray(b"dayIndex"),
            self.StackSlotRole: QByteArray(b"stackSlot"),
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.TaskIdRole:
            return row["task_id"]
        if role == self.TitleRole:
            return row["title"]
        if role == self.QuadrantRole:
            return row["quadrant"]
        if role == self.DayIndexRole:
            return row["day_index"]
        if role == self.StackSlotRole:
            return row["stack_slot"]
        return None


class DayAgendaModel(QAbstractListModel):
    TaskIdRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    QuadrantRole = Qt.ItemDataRole.UserRole + 3
    StartMinuteRole = Qt.ItemDataRole.UserRole + 4
    DurationMinuteRole = Qt.ItemDataRole.UserRole + 5
    IsDueOnlyRole = Qt.ItemDataRole.UserRole + 6
    FullDayRole = Qt.ItemDataRole.UserRole + 7

    def __init__(self, db_file: Path, calendar: "CalendarController", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._calendar = calendar
        self._rows: list[dict] = []
        self.reload()

    def roleNames(self):
        return {
            self.TaskIdRole: QByteArray(b"taskId"),
            self.TitleRole: QByteArray(b"title"),
            self.QuadrantRole: QByteArray(b"quadrant"),
            self.StartMinuteRole: QByteArray(b"startMinute"),
            self.DurationMinuteRole: QByteArray(b"durationMinutes"),
            self.IsDueOnlyRole: QByteArray(b"isDueOnly"),
            self.FullDayRole: QByteArray(b"fullDay"),
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.TaskIdRole:
            return row["task_id"]
        if role == self.TitleRole:
            return row["title"]
        if role == self.QuadrantRole:
            return row["quadrant"]
        if role == self.StartMinuteRole:
            return row["start_minute"]
        if role == self.DurationMinuteRole:
            return row["duration_minutes"]
        if role == self.IsDueOnlyRole:
            return row["is_due_only"]
        if role == self.FullDayRole:
            return bool(row.get("full_day", False))
        if role == Qt.ItemDataRole.DisplayRole:
            if row.get("is_due_only"):
                return row["title"]
            if row.get("full_day"):
                return f"全天 · {row['title']}"
            sm = int(row["start_minute"])
            h, m = divmod(sm, 60)
            return f"{h:02d}:{m:02d}  {row['title']}"
        return None

    @Slot()
    def reload(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        sd = self._calendar.selected_date()
        d = date(sd.year(), sd.month(), sd.day())
        day_start = datetime.combine(d, time.min)
        day_end = day_start + timedelta(days=1)
        conn = sqlite3.connect(self._db)
        try:
            cur = conn.execute(
                """
                SELECT id, title, quadrant, start_datetime, end_datetime, due_date
                FROM tasks
                WHERE completed = 0
                """
            )
            for r in cur.fetchall():
                tid, title, quad = r[0], r[1], int(r[2])
                s_s, e_s, due = r[3], r[4], r[5]
                t0 = _parse_local_iso(s_s)
                t1 = _parse_local_iso(e_s)
                if t0 and t1 and t1 > t0:
                    seg0 = max(t0, day_start)
                    seg1 = min(t1, day_end)
                    if seg0 < seg1:
                        sm = seg0.hour * 60 + seg0.minute
                        dur = int((seg1 - seg0).total_seconds() // 60)
                        fd = sm == 0 and dur >= _FULL_DAY_MINUTES
                        self._rows.append(
                            {
                                "task_id": tid,
                                "title": title,
                                "quadrant": quad,
                                "start_minute": sm,
                                "duration_minutes": max(1, dur),
                                "is_due_only": False,
                                "full_day": fd,
                            }
                        )
                due_d = _parse_date_iso(due)
                if due_d == d and not (t0 and t1):
                    self._rows.append(
                        {
                            "task_id": tid,
                            "title": title + " · " + "截止",
                            "quadrant": quad,
                            "start_minute": 0,
                            "duration_minutes": 30,
                            "is_due_only": True,
                            "full_day": False,
                        }
                    )
        finally:
            conn.close()
        self._rows.sort(key=lambda x: (x["is_due_only"], x["start_minute"]))
        self.endResetModel()


def _count_tasks_on_day(conn: sqlite3.Connection, day_str: str) -> int:
    cur = conn.execute(
        """
        SELECT COUNT(*) FROM tasks WHERE completed = 0 AND (
            (
                start_datetime IS NOT NULL AND end_datetime IS NOT NULL
                AND date(start_datetime) <= date(?)
                AND date(end_datetime) >= date(?)
            )
            OR (due_date IS NOT NULL AND date(due_date) = date(?))
        )
        """,
        (day_str, day_str, day_str),
    )
    return int(cur.fetchone()[0])


class MonthGridModel(QAbstractListModel):
    CellDateRole = Qt.ItemDataRole.UserRole + 1
    InMonthRole = Qt.ItemDataRole.UserRole + 2
    TaskCountRole = Qt.ItemDataRole.UserRole + 3
    IsTodayRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self, db_file: Path, calendar: "CalendarController", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._calendar = calendar
        self._rows: list[dict] = []
        self.reload()

    def roleNames(self):
        return {
            self.CellDateRole: QByteArray(b"cellDate"),
            self.InMonthRole: QByteArray(b"inMonth"),
            self.TaskCountRole: QByteArray(b"taskCount"),
            self.IsTodayRole: QByteArray(b"isToday"),
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.CellDateRole:
            return row["cell_date"]
        if role == self.InMonthRole:
            return row["in_month"]
        if role == self.TaskCountRole:
            return row["task_count"]
        if role == self.IsTodayRole:
            return row["is_today"]
        if role == Qt.ItemDataRole.DisplayRole:
            qd = QDate.fromString(row["cell_date"], Qt.DateFormat.ISODate)
            if qd.isValid():
                return str(qd.day())
            return ""
        return None

    @Slot()
    def reload(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        ma = self._calendar.month_anchor_date()
        first = QDate(ma.year(), ma.month(), 1)
        grid_start = first.addDays(-(first.dayOfWeek() - 1))
        today = QDate.currentDate()
        month = ma.month()
        conn = sqlite3.connect(self._db)
        try:
            for i in range(42):
                qd = grid_start.addDays(i)
                ds = qd.toString(Qt.DateFormat.ISODate)
                cnt = _count_tasks_on_day(conn, ds)
                self._rows.append(
                    {
                        "cell_date": ds,
                        "in_month": qd.month() == month,
                        "task_count": cnt,
                        "is_today": qd == today,
                    }
                )
        finally:
            conn.close()
        self.endResetModel()


class CalendarController(QObject):
    weekStartChanged = Signal()
    selectedDateChanged = Signal()
    monthAnchorChanged = Signal()
    layoutChanged = Signal()

    def __init__(self, db_file: Path, task_model: TaskModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._task_model = task_model
        today = QDate.currentDate()
        self._week_start = today.addDays(-(today.dayOfWeek() - 1))
        self._selected = today
        self._month_anchor = QDate(today.year(), today.month(), 1)

        self._week_model = WeekScheduleModel(db_file, self, self)
        self._week_allday_model = WeekAllDayModel(db_file, self, self)
        self._week_allday_strip_height = 28
        self._day_model = DayAgendaModel(db_file, self, self)
        self._month_model = MonthGridModel(db_file, self, self)
        self._reload_week_submodels()

    def week_start_date(self) -> QDate:
        return self._week_start

    def selected_date(self) -> QDate:
        return self._selected

    def month_anchor_date(self) -> QDate:
        return self._month_anchor

    def _reload_week_submodels(self) -> None:
        ws = self._week_start
        week_start = date(ws.year(), ws.month(), ws.day())
        timed, allday, strip_h = _build_week_timed_and_allday_rows(self._db, week_start)
        self._week_allday_strip_height = strip_h
        self._week_model.apply_rows(timed)
        self._week_allday_model.apply_rows(allday)
        self.layoutChanged.emit()

    @Property(str, notify=weekStartChanged)
    def weekStartIso(self) -> str:
        return self._week_start.toString(Qt.DateFormat.ISODate)

    @weekStartIso.setter
    def weekStartIso(self, s: str) -> None:
        d = QDate.fromString(s, Qt.DateFormat.ISODate)
        if d.isValid() and d != self._week_start:
            self._week_start = d
            self.weekStartChanged.emit()
            self._reload_week_submodels()

    @Property(str, notify=selectedDateChanged)
    def selectedDateIso(self) -> str:
        return self._selected.toString(Qt.DateFormat.ISODate)

    @selectedDateIso.setter
    def selectedDateIso(self, s: str) -> None:
        d = QDate.fromString(s, Qt.DateFormat.ISODate)
        if d.isValid() and d != self._selected:
            self._selected = d
            self.selectedDateChanged.emit()
            self._day_model.reload()

    @Property(str, notify=monthAnchorChanged)
    def monthAnchorIso(self) -> str:
        return self._month_anchor.toString(Qt.DateFormat.ISODate)

    @monthAnchorIso.setter
    def monthAnchorIso(self, s: str) -> None:
        d = QDate.fromString(s, Qt.DateFormat.ISODate)
        if d.isValid():
            anchor = QDate(d.year(), d.month(), 1)
            if anchor != self._month_anchor:
                self._month_anchor = anchor
                self.monthAnchorChanged.emit()
                self._month_model.reload()

    @Property(QObject, constant=True)
    def weekModel(self) -> WeekScheduleModel:
        return self._week_model

    @Property(QObject, constant=True)
    def weekAllDayModel(self) -> WeekAllDayModel:
        return self._week_allday_model

    @Property(int, notify=layoutChanged)
    def weekAllDayStripHeight(self) -> int:
        return self._week_allday_strip_height

    @Property(QObject, constant=True)
    def dayModel(self) -> DayAgendaModel:
        return self._day_model

    @Property(QObject, constant=True)
    def monthModel(self) -> MonthGridModel:
        return self._month_model

    @Property(str, notify=weekStartChanged)
    def weekRangeLabel(self) -> str:
        a = self._week_start
        b = a.addDays(6)
        return f"{a.year()}-{a.month():02d}-{a.day():02d} — {b.year()}-{b.month():02d}-{b.day():02d}"

    @Property(str, notify=monthAnchorChanged)
    def monthTitleLabel(self) -> str:
        m = self._month_anchor
        return f"{m.year()} 年 {m.month()} 月"

    @Slot()
    def prevWeek(self) -> None:
        self.weekStartIso = self._week_start.addDays(-7).toString(Qt.DateFormat.ISODate)

    @Slot()
    def nextWeek(self) -> None:
        self.weekStartIso = self._week_start.addDays(7).toString(Qt.DateFormat.ISODate)

    @Slot()
    def goThisWeek(self) -> None:
        t = QDate.currentDate()
        self.weekStartIso = t.addDays(-(t.dayOfWeek() - 1)).toString(Qt.DateFormat.ISODate)
        self.selectedDateIso = t.toString(Qt.DateFormat.ISODate)

    @Slot()
    def goToday(self) -> None:
        t = QDate.currentDate()
        self.weekStartIso = t.addDays(-(t.dayOfWeek() - 1)).toString(Qt.DateFormat.ISODate)
        self.selectedDateIso = t.toString(Qt.DateFormat.ISODate)
        self.monthAnchorIso = QDate(t.year(), t.month(), 1).toString(Qt.DateFormat.ISODate)

    @Slot()
    def prevDay(self) -> None:
        self.selectedDateIso = self._selected.addDays(-1).toString(Qt.DateFormat.ISODate)

    @Slot()
    def nextDay(self) -> None:
        self.selectedDateIso = self._selected.addDays(1).toString(Qt.DateFormat.ISODate)

    @Slot()
    def prevMonth(self) -> None:
        m = self._month_anchor.addMonths(-1)
        self.monthAnchorIso = QDate(m.year(), m.month(), 1).toString(Qt.DateFormat.ISODate)

    @Slot()
    def nextMonth(self) -> None:
        m = self._month_anchor.addMonths(1)
        self.monthAnchorIso = QDate(m.year(), m.month(), 1).toString(Qt.DateFormat.ISODate)

    @Slot()
    def goTodayMonth(self) -> None:
        t = QDate.currentDate()
        self.monthAnchorIso = QDate(t.year(), t.month(), 1).toString(Qt.DateFormat.ISODate)
        self.selectedDateIso = t.toString(Qt.DateFormat.ISODate)

    @Slot(str)
    def pickMonthCell(self, cell_iso: str) -> None:
        d = QDate.fromString(cell_iso, Qt.DateFormat.ISODate)
        if d.isValid():
            self.selectedDateIso = cell_iso
            self.weekStartIso = d.addDays(-(d.dayOfWeek() - 1)).toString(Qt.DateFormat.ISODate)

    @Slot()
    def refresh(self) -> None:
        self._reload_week_submodels()
        self._day_model.reload()
        self._month_model.reload()


def _quadrant_proxy(source: TaskModel, quadrant: int) -> QSortFilterProxyModel:
    p = QSortFilterProxyModel()
    p.setSourceModel(source)
    p.setFilterRole(TaskModel.QuadrantRole)
    p.setFilterFixedString(str(quadrant))
    return p


class AppBridge(QObject):
    def __init__(
        self,
        task_model: TaskModel,
        calendar: CalendarController,
        pomodoro: "PomodoroService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._task_model = task_model
        self._calendar = calendar
        self._pomodoro = pomodoro

    @Slot(int)
    def jumpToTaskInCalendar(self, task_id: int) -> None:
        if not self._task_model.has_task(int(task_id)):
            return
        iso = self._task_model.schedule_focus_date_iso(task_id)
        if iso:
            d = QDate.fromString(iso, Qt.DateFormat.ISODate)
            if d.isValid():
                self._calendar.selectedDateIso = iso
                self._calendar.weekStartIso = d.addDays(-(d.dayOfWeek() - 1)).toString(Qt.DateFormat.ISODate)
                self._calendar.monthAnchorIso = QDate(d.year(), d.month(), 1).toString(Qt.DateFormat.ISODate)
                return
        self._calendar.goToday()

    @Slot(str, int)
    def addTask(self, title: str, quadrant: int) -> None:
        self._task_model.add_task(title, quadrant)
        self._calendar.refresh()

    @Slot(int)
    def removeTask(self, task_id: int) -> None:
        if self._pomodoro is not None:
            self._pomodoro.abortIfTaskRemoved(int(task_id))
        self._task_model.remove_task(task_id)
        self._calendar.refresh()

    @Slot(int, int)
    def setQuadrant(self, task_id: int, quadrant: int) -> None:
        self._task_model.set_quadrant(task_id, quadrant)
        self._calendar.refresh()

    @Slot(int, bool)
    def completeTask(self, task_id: int, completed: bool = True) -> None:
        self._task_model.set_completed(task_id, completed)
        self._calendar.refresh()

    @Slot(int)
    def clearSchedule(self, task_id: int) -> None:
        self._task_model.clear_schedule(task_id)
        self._calendar.refresh()

    @Slot(int, str, int)
    def updateTaskBasic(self, task_id: int, title: str, quadrant: int) -> None:
        self._task_model.update_task_basic(task_id, title, quadrant)
        self._calendar.refresh()

    @Slot(int, str, str, bool)
    def updateTaskSchedule(self, task_id: int, start_iso: str, end_iso: str, all_day: bool = False) -> None:
        t0 = _parse_local_iso(start_iso)
        t1 = _parse_local_iso(end_iso)
        if not t0 or not t1:
            return
        self._task_model.update_task_schedule(task_id, t0, t1, all_day)
        self._calendar.refresh()

    @Slot(str, str, int, result="QVariantList")
    def detectConflicts(self, start_iso: str, end_iso: str, exclude_task_id: int = -1):
        t0 = _parse_local_iso(start_iso)
        t1 = _parse_local_iso(end_iso)
        if not t0 or not t1:
            return []
        return self._task_model.detect_conflicts(t0, t1, int(exclude_task_id))

    def _insert_interval(
        self,
        title: str,
        quadrant: int,
        start: datetime,
        end: datetime,
    ) -> None:
        if end <= start:
            return
        self._task_model.add_scheduled_task(title, quadrant, start, end)
        self._calendar.refresh()

    @Slot(str, int, str, int, int)
    def addDayHourPeriodTask(
        self,
        title: str,
        quadrant: int,
        date_iso: str,
        start_hour: int,
        end_hour: int,
    ) -> None:
        """同一天内 [start_hour:00, end_hour:00)，精确到整点，如 8~12 即 8:00–12:00。"""
        title = (title or "").strip()
        if not title:
            return
        qd = QDate.fromString(date_iso, Qt.DateFormat.ISODate)
        if not qd.isValid():
            return
        sh = max(0, min(23, int(start_hour)))
        eh = max(0, min(24, int(end_hour)))
        if eh <= sh:
            return
        d = date(qd.year(), qd.month(), qd.day())
        start = datetime.combine(d, time(hour=sh, minute=0))
        if eh == 24:
            end = datetime.combine(d + timedelta(days=1), time.min)
        else:
            end = datetime.combine(d, time(hour=eh, minute=0))
        self._insert_interval(title, quadrant, start, end)

    @Slot(str, int, str, str)
    def addDateRangeTask(
        self,
        title: str,
        quadrant: int,
        start_date_iso: str,
        end_date_iso: str,
    ) -> None:
        """按日历日闭区间 [start, end]，每日视为全天；存库为 start 日 0:00 至 end 日次日 0:00。"""
        title = (title or "").strip()
        if not title:
            return
        d0 = QDate.fromString(start_date_iso.strip(), Qt.DateFormat.ISODate)
        d1 = QDate.fromString(end_date_iso.strip(), Qt.DateFormat.ISODate)
        if not d0.isValid() or not d1.isValid():
            return
        a = date(d0.year(), d0.month(), d0.day())
        b = date(d1.year(), d1.month(), d1.day())
        if b < a:
            a, b = b, a
        start = datetime.combine(a, time.min)
        end = datetime.combine(b + timedelta(days=1), time.min)
        self._insert_interval(title, quadrant, start, end)


class PomodoroService(QObject):
    remainingChanged = Signal()
    runningChanged = Signal()
    taskBindingChanged = Signal()

    def __init__(self, db_file: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db_file
        self._focus_sec = 25 * 60
        self._remaining = self._focus_sec
        self._running = False
        self._task_id = -1
        self._task_title = ""
        self._session_start: datetime | None = None
        self._planned_sec = self._focus_sec
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    @Property(int, notify=remainingChanged)
    def remainingSeconds(self) -> int:
        return self._remaining

    @Property(bool, notify=runningChanged)
    def running(self) -> bool:
        return self._running

    @Property(int, constant=True)
    def focusDurationSeconds(self) -> int:
        return self._focus_sec

    @Property(int, notify=taskBindingChanged)
    def currentTaskId(self) -> int:
        return self._task_id

    @Property(str, notify=taskBindingChanged)
    def currentTaskTitle(self) -> str:
        return self._task_title

    def _set_remaining(self, v: int) -> None:
        self._remaining = max(0, v)
        self.remainingChanged.emit()

    def _set_running(self, v: bool) -> None:
        if self._running == v:
            return
        self._running = v
        self.runningChanged.emit()

    def _persist_session(self, completed: bool) -> None:
        if self._session_start is None:
            return
        end = _local_now()
        actual = max(0, int((end - self._session_start).total_seconds()))
        started_s = _local_iso(self._session_start)
        ended_s = _local_iso(end)
        tid = self._task_id if self._task_id >= 0 else None
        conn = sqlite3.connect(self._db)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO pomodoro_sessions (
                    task_id, started_at, ended_at,
                    planned_duration_sec, actual_duration_sec, completed
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    started_s,
                    ended_s,
                    self._planned_sec,
                    actual,
                    1 if completed else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._session_start = None

    def _on_tick(self) -> None:
        self._set_remaining(self._remaining - 1)
        if self._remaining <= 0:
            self._timer.stop()
            self._set_running(False)
            self._persist_session(completed=True)

    @Slot(int, str)
    def setCurrentTask(self, task_id: int, title: str) -> None:
        tid = int(task_id)
        if tid == self._task_id and title == self._task_title:
            return
        self._task_id = tid
        self._task_title = title or ""
        self.taskBindingChanged.emit()

    @Slot()
    def clearCurrentTask(self) -> None:
        self.setCurrentTask(-1, "")

    def abortIfTaskRemoved(self, task_id: int) -> None:
        """任务从列表删除时：停止计时且不写入未完成会话，并解除绑定。"""
        if self._task_id != int(task_id):
            return
        self._timer.stop()
        self._set_running(False)
        self._session_start = None
        self._set_remaining(self._focus_sec)
        self.setCurrentTask(-1, "")

    @Slot()
    def startFocus(self) -> None:
        if self._running:
            return
        self._planned_sec = self._focus_sec
        self._set_remaining(self._focus_sec)
        self._session_start = _local_now()
        self._set_running(True)
        self._timer.start(1000)

    @Slot()
    def stop(self) -> None:
        if self._running:
            self._timer.stop()
            self._set_running(False)
            self._persist_session(completed=False)
        self._set_remaining(self._focus_sec)

    @Slot()
    def reset(self) -> None:
        if self._running:
            self._timer.stop()
            self._set_running(False)
            self._persist_session(completed=False)
        self._set_remaining(self._focus_sec)


def build_calendar_context(bundle_dir: Path) -> tuple[
    Path,
    TaskModel,
    CalendarController,
    QSortFilterProxyModel,
    QSortFilterProxyModel,
    QSortFilterProxyModel,
    QSortFilterProxyModel,
    PomodoroService,
    AppBridge,
]:
    """初始化数据库与 QML 所需上下文对象（由工具集页面在 setSource 前注入 engine）。"""
    path = db_path_for_bundle(bundle_dir)
    init_db(path)
    task_model = TaskModel(path)
    calendar = CalendarController(path, task_model)
    q0 = _quadrant_proxy(task_model, 0)
    q1 = _quadrant_proxy(task_model, 1)
    q2 = _quadrant_proxy(task_model, 2)
    q3 = _quadrant_proxy(task_model, 3)
    pomodoro = PomodoroService(path)
    bridge = AppBridge(task_model, calendar, pomodoro)
    return path, task_model, calendar, q0, q1, q2, q3, pomodoro, bridge
