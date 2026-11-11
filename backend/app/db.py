"""SQLite persistence: audit_log, dismissals, score_history, advisor_reports,
advisor_actions (append-only ledger)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    node_id INTEGER,
    params_before TEXT,
    params_after TEXT,
    result TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    problem_key TEXT NOT NULL UNIQUE,
    node_id INTEGER,
    reason TEXT,
    until REAL
);
CREATE TABLE IF NOT EXISTS score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    node_id INTEGER,
    total REAL,
    grade TEXT,
    network_total REAL,
    network_grade TEXT
);
CREATE TABLE IF NOT EXISTS advisor_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    report TEXT NOT NULL,
    tokens_in INTEGER,
    tokens_out INTEGER
);
CREATE TABLE IF NOT EXISTS advisor_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    report_id INTEGER,
    action TEXT NOT NULL,
    node_id INTEGER,
    params TEXT,
    problem_refs TEXT,
    explanation TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    verified_ts REAL,
    verification_detail TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.tx() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    # --- audit ---
    def add_audit(self, actor: str, action: str, node_id: int | None,
                  params_before: Any = None, params_after: Any = None,
                  result: Any = None, source: str = "api") -> int:
        return self.execute(
            "INSERT INTO audit_log (ts, actor, action, node_id, params_before, params_after, result, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), actor, action, node_id,
             json.dumps(params_before) if params_before is not None else None,
             json.dumps(params_after) if params_after is not None else None,
             json.dumps(result) if result is not None else None, source))

    def get_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            for k in ("params_before", "params_after", "result"):
                if r.get(k):
                    try:
                        r[k] = json.loads(r[k])
                    except (TypeError, ValueError):
                        pass
        return rows

    # --- dismissals ---
    def dismiss(self, problem_key: str, node_id: int | None, reason: str | None,
                until: float | None = None) -> None:
        self.execute(
            "INSERT INTO dismissals (ts, problem_key, node_id, reason, until) VALUES (?,?,?,?,?) "
            "ON CONFLICT(problem_key) DO UPDATE SET ts=excluded.ts, reason=excluded.reason, until=excluded.until",
            (time.time(), problem_key, node_id, reason, until))

    def active_dismissals(self) -> set[str]:
        now = time.time()
        rows = self.query("SELECT problem_key FROM dismissals WHERE until IS NULL OR until > ?", (now,))
        return {r["problem_key"] for r in rows}

    # --- score history ---
    def add_score(self, node_id: int | None, total: float | None, grade: str | None,
                  network_total: float | None = None, network_grade: str | None = None) -> None:
        self.execute(
            "INSERT INTO score_history (ts, node_id, total, grade, network_total, network_grade) "
            "VALUES (?,?,?,?,?,?)",
            (time.time(), node_id, total, grade, network_total, network_grade))

    # --- advisor reports ---
    def add_report(self, mode: str, report: dict[str, Any],
                   tokens_in: int = 0, tokens_out: int = 0) -> int:
        return self.execute(
            "INSERT INTO advisor_reports (ts, mode, report, tokens_in, tokens_out) VALUES (?,?,?,?,?)",
            (time.time(), mode, json.dumps(report), tokens_in, tokens_out))

    def latest_report(self, mode: str | None = None) -> dict[str, Any] | None:
        if mode:
            rows = self.query("SELECT * FROM advisor_reports WHERE mode=? ORDER BY ts DESC LIMIT 1", (mode,))
        else:
            rows = self.query("SELECT * FROM advisor_reports ORDER BY ts DESC LIMIT 1")
        if not rows:
            return None
        r = rows[0]
        r["report"] = json.loads(r["report"])
        return r

    def report_history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM advisor_reports ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            r["report"] = json.loads(r["report"])
        return rows

    # --- advisor actions ledger: APPEND ONLY (no update/delete of rows) ---
    def append_ledger_action(self, report_id: int | None, action: str, node_id: int | None,
                             params: dict[str, Any] | None, problem_refs: list[str],
                             explanation: str | None,
                             verification_status: str = "pending") -> int:
        return self.execute(
            "INSERT INTO advisor_actions (ts, report_id, action, node_id, params, problem_refs, "
            "explanation, verification_status) VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), report_id, action, node_id,
             json.dumps(params) if params else None,
             json.dumps(problem_refs), explanation, verification_status))

    def update_ledger_verification(self, action_id: int, status: str,
                                   detail: str | None = None) -> None:
        """Only the verification_status / verified_ts / verification_detail columns
        may be updated; rows are never deleted or rewritten."""
        allowed = {"pending", "confirmed_improvement", "no_change", "inconclusive"}
        if status not in allowed:
            raise ValueError(f"invalid verification status: {status}")
        self.execute(
            "UPDATE advisor_actions SET verification_status=?, verified_ts=?, verification_detail=? WHERE id=?",
            (status, time.time(), detail, action_id))

    def get_ledger(self, days: int = 7, limit: int = 500) -> list[dict[str, Any]]:
        cutoff = time.time() - days * 86400
        rows = self.query(
            "SELECT * FROM advisor_actions WHERE ts >= ? ORDER BY ts DESC LIMIT ?", (cutoff, limit))
        for r in rows:
            for k in ("params", "problem_refs"):
                if r.get(k):
                    try:
                        r[k] = json.loads(r[k])
                    except (TypeError, ValueError):
                        pass
        return rows

    def open_pending_actions(self) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM advisor_actions WHERE verification_status='pending' "
            "ORDER BY ts DESC LIMIT 500")
        for r in rows:
            for k in ("params", "problem_refs"):
                if r.get(k):
                    try:
                        r[k] = json.loads(r[k])
                    except (TypeError, ValueError):
                        pass
        return rows

    def confirmed_actions(self, days: int = 14) -> list[dict[str, Any]]:
        cutoff = time.time() - days * 86400
        rows = self.query(
            "SELECT * FROM advisor_actions WHERE verification_status='confirmed_improvement' AND ts >= ?",
            (cutoff,))
        for r in rows:
            for k in ("params", "problem_refs"):
                if r.get(k):
                    try:
                        r[k] = json.loads(r[k])
                    except (TypeError, ValueError):
                        pass
        return rows
