import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from FZBypass.core.exceptions import DDLException

CACHE_PATH = os.getenv("DESTINATION_CACHE_DB", "destinations.sqlite3")
DEFAULT_TTL = max(300, int(os.getenv("DESTINATION_CACHE_TTL_SECONDS", "86400")))
INVALID_HOST_MARKERS = (
    "skrresults.com",
    "google.com/httpservice",
)


def _connect():
    path = Path(CACHE_PATH)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""
        CREATE TABLE IF NOT EXISTS verified_destinations (
            source_url TEXT PRIMARY KEY,
            destination_url TEXT NOT NULL,
            method TEXT NOT NULL,
            verified_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    db.commit()
    return db


def _valid_destination(source: str, destination: str) -> bool:
    if not destination or destination.rstrip("/") == source.rstrip("/"):
        return False
    parsed = urlparse(destination)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    return not any(marker in host for marker in INVALID_HOST_MARKERS)


def get_cached(source: str, ttl: int = DEFAULT_TTL) -> str | None:
    now = int(time.time())
    with _connect() as db:
        row = db.execute(
            "SELECT destination_url, expires_at FROM verified_destinations WHERE source_url = ?",
            (source.rstrip("/"),),
        ).fetchone()
        if not row:
            return None
        destination, expires_at = row
        if expires_at <= now or not _valid_destination(source, destination):
            db.execute("DELETE FROM verified_destinations WHERE source_url = ?", (source.rstrip("/"),))
            db.commit()
            return None
        return destination


def save_verified(source: str, destination: str, method: str) -> None:
    if not _valid_destination(source, destination):
        raise DDLException("Refusing to cache an invalid or intermediary destination")
    now = int(time.time())
    with _connect() as db:
        db.execute(
            """
            INSERT INTO verified_destinations
              (source_url, destination_url, method, verified_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
              destination_url = excluded.destination_url,
              method = excluded.method,
              verified_at = excluded.verified_at,
              expires_at = excluded.expires_at
            """,
            (source.rstrip("/"), destination, method, now, now + DEFAULT_TTL),
        )
        db.commit()
