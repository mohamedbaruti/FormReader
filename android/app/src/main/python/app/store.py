"""Saved enrolments in an SQLite database: formreader/data/enrolments.db.

Every saved enrolment is one row (its full JSON record), written in one transaction, so a record
is either saved completely or not at all, also if the computer loses power. A JSON copy of each
record is still written to data/output/<id>.json as before (a second, plain-file copy that any
program can read).

When the reader starts, records found in data/output that are not yet in the database (saved by
an earlier version) are added to it, so nothing saved before is lost.

The database is a single file: back it up by copying data/enrolments.db (and data/output) while
the reader is stopped, or with any SQLite tool while it runs.
"""
import json
import os
import sqlite3
import threading

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.environ.get("FORMREADER_DB") or os.path.join(
    os.environ.get("FORMREADER_DATA_DIR") or os.path.join(BASE, "data"), "enrolments.db")

_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")       # safe against power loss, readers never wait
        c.execute("PRAGMA synchronous=FULL")
        c.execute("""CREATE TABLE IF NOT EXISTS enrolments (
                       id         TEXT PRIMARY KEY,
                       saved_at   TEXT,
                       form       TEXT,
                       first_name TEXT,
                       last_name  TEXT,
                       record     TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS enrolments_saved_at ON enrolments(saved_at)")
        c.commit()
        _conn = c
    return _conn


def save(record):
    """Insert or replace one record (a dict with at least "id")."""
    d = record.get("data") or {}
    with _lock:
        c = _db()
        c.execute("INSERT OR REPLACE INTO enrolments (id, saved_at, form, first_name, last_name, record) "
                  "VALUES (?, ?, ?, ?, ?, ?)",
                  (record["id"], record.get("saved_at"), record.get("form"), d.get("first_name"),
                   d.get("last_name"), json.dumps(record, ensure_ascii=False)))
        c.commit()


def get(rid):
    with _lock:
        row = _db().execute("SELECT record FROM enrolments WHERE id = ?", (rid,)).fetchone()
    return json.loads(row[0]) if row else None


def all_records():
    """Every record, newest first."""
    with _lock:
        rows = _db().execute("SELECT record FROM enrolments ORDER BY saved_at DESC").fetchall()
    out = []
    for (txt,) in rows:
        try:
            out.append(json.loads(txt))
        except ValueError:
            pass
    return out


def count():
    with _lock:
        return _db().execute("SELECT COUNT(*) FROM enrolments").fetchone()[0]


def import_folder(folder, normalise):
    """Add records from JSON files in `folder` that are not in the database yet.
    normalise(filename, dict) -> record dict (older files kept only the data)."""
    if not os.path.isdir(folder):
        return 0
    with _lock:
        have = {r[0] for r in _db().execute("SELECT id FROM enrolments")}
    added = 0
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".json") or fn[:-5] in have:
            continue
        try:
            with open(os.path.join(folder, fn), encoding="utf-8") as fh:
                rec = normalise(fn, json.load(fh))
        except (OSError, ValueError):
            continue
        save(rec)
        added += 1
    return added
