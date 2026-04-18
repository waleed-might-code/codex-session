"""
Thread-safe, atomic CSV storage backed by pandas DataFrames.
Each table is a separate CSV file. Writes use temp-file atomic replacement.
"""
import os
import uuid
import threading
import tempfile
import shutil
import contextlib
from datetime import datetime
from typing import Any
import pandas as pd
import fcntl

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), os.getenv("STORAGE_DIR", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# Per-file write locks
_locks: dict[str, threading.Lock] = {}
_lock_meta = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _lock_meta:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def _csv_path(table: str) -> str:
    return os.path.join(DATA_DIR, f"{table}.csv")


def _lock_path(table: str) -> str:
    return os.path.join(DATA_DIR, f".{table}.lock")


@contextlib.contextmanager
def _write_lock(table: str):
    path = _csv_path(table)
    thread_lock = _get_lock(path)
    thread_lock.acquire()
    lock_fd = open(_lock_path(table), "a+")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        thread_lock.release()


def load(table: str, schema: dict[str, Any]) -> pd.DataFrame:
    """Load CSV into DataFrame, creating with schema if missing."""
    path = _csv_path(table)
    if not os.path.exists(path):
        df = pd.DataFrame(columns=list(schema.keys()))
        for col, dtype in schema.items():
            df[col] = df[col].astype(dtype)
        return df
    df = pd.read_csv(path, dtype=str).fillna("")
    # Ensure all schema columns exist
    for col in schema:
        if col not in df.columns:
            df[col] = ""
    return df[list(schema.keys())]


def save(table: str, df: pd.DataFrame):
    """Atomically write DataFrame to CSV."""
    with _write_lock(table):
        path = _csv_path(table)
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        try:
            os.close(fd)
            df.to_csv(tmp, index=False)
            shutil.move(tmp, path)
        except Exception:
            os.unlink(tmp)
            raise


def new_id() -> str:
    return str(uuid.uuid4())[:8]


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert(table: str, schema: dict, match_col: str, match_val: str, record: dict) -> pd.DataFrame:
    """Insert or update a record matched by match_col=match_val."""
    with _write_lock(table):
        df = load(table, schema)
        record.setdefault("updated_at", now())
        mask = df[match_col] == match_val
        if mask.any():
            for k, v in record.items():
                if k in df.columns:
                    df.loc[mask, k] = v
        else:
            record.setdefault("id", new_id())
            record.setdefault("created_at", now())
            new_row = {col: record.get(col, "") for col in schema}
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        path = _csv_path(table)
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        try:
            os.close(fd)
            df.to_csv(tmp, index=False)
            shutil.move(tmp, path)
        except Exception:
            os.unlink(tmp)
            raise
        return df


def delete_where(table: str, schema: dict, col: str, val: str):
    with _write_lock(table):
        df = load(table, schema)
        df = df[df[col] != val]
        path = _csv_path(table)
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        try:
            os.close(fd)
            df.to_csv(tmp, index=False)
            shutil.move(tmp, path)
        except Exception:
            os.unlink(tmp)
            raise


def find_one(table: str, schema: dict, col: str, val: str) -> dict | None:
    df = load(table, schema)
    rows = df[df[col] == val]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def find_all(table: str, schema: dict, col: str = None, val: str = None) -> list[dict]:
    df = load(table, schema)
    if col and val is not None:
        df = df[df[col] == val]
    return df.to_dict("records")
