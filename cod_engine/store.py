"""SQLite repository. JSON snapshots preserve policy decisions and pure workflow state."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from .schema import ROOT


def connect():
    path = Path(os.getenv("COD_DB", str(ROOT / "data/operations.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, day TEXT NOT NULL, snapshot TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, snapshot TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS settings_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL)")
    db.commit()
    return db


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save(db, record):
    db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET day=excluded.day,snapshot=excluded.snapshot",
               (record["id"], record["day"], json.dumps(record)))


def get(db, identifier):
    row = db.execute("SELECT snapshot FROM records WHERE id=?", (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def all_records(db):
    return [json.loads(row[0]) for row in db.execute("SELECT snapshot FROM records ORDER BY day DESC,id")]
