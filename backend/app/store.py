"""SQLite store. Raw source rows are kept verbatim so every fact can cite the exact row it came from."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(os.environ.get("MANAS_DB", Path(__file__).resolve().parent.parent / "manas.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    source   TEXT NOT NULL,          -- logical table: customers, loans, payments, promises, communications
    row_id   TEXT NOT NULL,          -- stable id of the row inside its source
    customer_id TEXT NOT NULL,
    data     TEXT NOT NULL,          -- JSON of the original row
    PRIMARY KEY (source, row_id)
);
CREATE INDEX IF NOT EXISTS idx_records_customer ON records(customer_id);

CREATE TABLE IF NOT EXISTS brains (
    customer_id TEXT PRIMARY KEY,
    pack     TEXT NOT NULL,
    built_at TEXT NOT NULL,
    data     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    arm      TEXT NOT NULL,          -- treatment | holdout
    data     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_customer ON decisions(customer_id);

CREATE TABLE IF NOT EXISTS outcomes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    decision_id INTEGER,
    arm      TEXT NOT NULL,
    converted INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def reset() -> None:
    with db() as conn:
        for table in ("records", "brains", "decisions", "outcomes"):
            conn.execute(f"DELETE FROM {table}")


def put_records(source: str, rows: list[dict[str, Any]], id_field: str, customer_field: str) -> int:
    with db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO records(source,row_id,customer_id,data) VALUES (?,?,?,?)",
            [(source, str(r[id_field]), str(r[customer_field]), json.dumps(r, ensure_ascii=False)) for r in rows],
        )
    return len(rows)


def records_for(customer_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    with db() as conn:
        for row in conn.execute("SELECT source,row_id,data FROM records WHERE customer_id=?", (customer_id,)):
            item = json.loads(row["data"])
            item["_row_id"] = row["row_id"]
            out.setdefault(row["source"], []).append(item)
    return out


def customer_ids() -> list[str]:
    with db() as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT customer_id FROM records WHERE source='customers' ORDER BY customer_id")]


def source_counts() -> dict[str, int]:
    with db() as conn:
        return {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM records GROUP BY source")}


def save_brain(customer_id: str, pack: str, built_at: str, brain: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO brains(customer_id,pack,built_at,data) VALUES (?,?,?,?)",
            (customer_id, pack, built_at, json.dumps(brain, ensure_ascii=False)),
        )


def get_brain(customer_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT data FROM brains WHERE customer_id=?", (customer_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def all_brains() -> list[dict[str, Any]]:
    with db() as conn:
        return [json.loads(r["data"]) for r in conn.execute("SELECT data FROM brains ORDER BY customer_id")]


def save_decision(customer_id: str, created_at: str, arm: str, decision: dict[str, Any]) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO decisions(customer_id,created_at,arm,data) VALUES (?,?,?,?)",
            (customer_id, created_at, arm, json.dumps(decision, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def latest_decision(customer_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id,arm,data FROM decisions WHERE customer_id=? ORDER BY id DESC LIMIT 1", (customer_id,)
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    data["decision_id"] = row["id"]
    data["arm"] = row["arm"]
    return data


def latest_decisions() -> dict[str, dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT d.id, d.customer_id, d.arm, d.data FROM decisions d "
            "JOIN (SELECT customer_id, MAX(id) mid FROM decisions GROUP BY customer_id) m ON d.id = m.mid"
        ).fetchall()
    out = {}
    for r in rows:
        data = json.loads(r["data"])
        data["decision_id"] = r["id"]
        data["arm"] = r["arm"]
        out[r["customer_id"]] = data
    return out


def record_outcome(customer_id: str, decision_id: int | None, arm: str, converted: bool, at: str, simulated: bool) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO outcomes(customer_id,decision_id,arm,converted,recorded_at,simulated) VALUES (?,?,?,?,?,?)",
            (customer_id, decision_id, arm, int(converted), at, int(simulated)),
        )


def outcome_summary() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            "SELECT arm, COUNT(*) n, SUM(converted) c, MAX(simulated) s FROM outcomes GROUP BY arm"
        ).fetchall()
    return {r["arm"]: {"n": r["n"], "converted": r["c"] or 0, "simulated": bool(r["s"])} for r in rows}


def get_setting(key: str, default: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, value))
