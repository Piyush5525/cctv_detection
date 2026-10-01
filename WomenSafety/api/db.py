"""SQLite persistence for CCTV incidents (CHANGELOG.md "CCTV Incident
Capture Pipeline" phase). Replaces the old in-memory-only IncidentService
store for the live product -- incidents must survive a backend restart.

Uses the stdlib sqlite3 module synchronously. This project has no other
database and a single-process API server, so a lightweight synchronous
store (each call wrapped in its own short-lived connection) is enough;
adding an async driver dependency for this scale wasn't justified.

Table schema: one row per incident, storing the full incident as a JSON
blob (`data`) plus a handful of real columns pulled out for indexed
filtering (camera_id, category, status, source, event_start). The JSON
blob is the single source of truth for every other field, so a schema
change to Incident (adding a field) never requires a migration here --
only a new filterable column would.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from api.core.config import settings

DB_PATH: Path = settings.INCIDENTS_DB_PATH

# Phase 1c hardening item 5: WAL mode lets readers (API requests) proceed
# concurrently with a writer (a detection thread creating an incident)
# without blocking each other -- the classic "database is locked" error
# under the default rollback journal happens when a writer and a reader
# (or two writers) collide; WAL's separate write-ahead log avoids that for
# reader/writer overlap. A single process-wide lock additionally
# serializes WRITES from this process (multiple detection threads across
# cameras could otherwise still collide with each other), and
# busy_timeout covers the remaining edge case (e.g. an external sqlite3
# CLI inspecting the file) by waiting instead of failing immediately.
_write_lock = threading.Lock()
_BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    event_start TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_camera_id ON incidents(camera_id);
CREATE INDEX IF NOT EXISTS idx_incidents_category ON incidents(category);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_event_start ON incidents(event_start);

CREATE TABLE IF NOT EXISTS quarantine (
    quarantine_id TEXT PRIMARY KEY,
    camera_id TEXT,
    quarantined_at TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _write() -> Iterator[sqlite3.Connection]:
    """Every write goes through this single process-wide lock (in
    addition to WAL mode) -- see the module-level note on _write_lock."""
    with _write_lock:
        with _connect() as conn:
            yield conn


def init_db() -> None:
    with _write() as conn:
        conn.executescript(_SCHEMA)


def insert_incident(incident_id: str, camera_id: str, category: str, status: str,
                     source: str, event_start: str, data: dict) -> None:
    with _write() as conn:
        conn.execute(
            "INSERT INTO incidents (incident_id, camera_id, category, status, source, event_start, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (incident_id, camera_id, category, status, source, event_start, json.dumps(data)),
        )


def update_incident_data(incident_id: str, status: str, data: dict) -> bool:
    with _write() as conn:
        cur = conn.execute(
            "UPDATE incidents SET status = ?, data = ? WHERE incident_id = ?",
            (status, json.dumps(data), incident_id),
        )
        return cur.rowcount > 0


def get_incident(incident_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT data FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return json.loads(row["data"]) if row else None


def list_incidents(
    camera_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    clauses = []
    params: list = []
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if start_date:
        clauses.append("event_start >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("event_start <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT data FROM incidents {where} ORDER BY event_start DESC", params
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]


def count_incidents() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM incidents").fetchone()["c"]


def insert_quarantine(quarantine_id: str, camera_id: Optional[str], quarantined_at: str, data: dict) -> None:
    with _write() as conn:
        conn.execute(
            "INSERT INTO quarantine (quarantine_id, camera_id, quarantined_at, data) VALUES (?, ?, ?, ?)",
            (quarantine_id, camera_id, quarantined_at, json.dumps(data)),
        )


def list_quarantine() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT data FROM quarantine ORDER BY quarantined_at DESC").fetchall()
        return [json.loads(r["data"]) for r in rows]
