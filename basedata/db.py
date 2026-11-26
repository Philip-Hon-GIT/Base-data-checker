"""Databasetilgang: samlingsnavn, lokal database, lagring av binærdata, indekser og id-er."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .settings import Settings

FILES = "basedata_files"
CHECKS = "basedata_checks"
QUESTIONS = "basedata_questions"
PROJECTS = "basedata_projects"
RULESETS = "basedata_rulesets"
RUNS = "basedata_runs"
ENTRIES = "basedata_entries"
NOTIFICATIONS = "basedata_notifications"


def now() -> datetime:
    """Current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """A readable unique id such as 'bdf-3f9a1c2e7b4d' (letters, digits and hyphens only)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def connect(settings: Settings):
    """Åpne den lokale databasen (SQLite-fila i settings.store_path)."""
    from .localstore import open_store

    return open_store(settings.resolved_store_path())


def gridfs_bucket(db, bucket_name: str):
    """Lagring av binærdata (høyderutenett) i den lokale databasen eller i minnet."""
    from .testing.memory_mongo import MemoryGridFSBucket

    return MemoryGridFSBucket(db, bucket_name)


def ensure_indexes(db) -> None:
    """Create the indexes the register pages and the worker rely on. Safe to run repeatedly."""
    db[FILES].create_index("source_key", unique=True)
    db[FILES].create_index("entry_id")
    db[ENTRIES].create_index("group_key", unique=True)
    db[ENTRIES].create_index([("project_id", 1), ("received_at", 1)])
    db[ENTRIES].create_index([("project_id", 1), ("ready", 1), ("lifecycle", 1)])
    db[FILES].create_index([("project_id", 1), ("status", 1)])
    db[FILES].create_index([("project_id", 1), ("check_result", 1)])
    db[CHECKS].create_index([("file_id", 1), ("run_id", 1)])
    db[QUESTIONS].create_index([("entry_id", 1), ("status", 1)])
    db[QUESTIONS].create_index([("uploader_email", 1), ("status", 1)])
    db[RUNS].create_index([("started_at", -1)])
    db[RULESETS].create_index([("project_id", 1), ("version", 1)])
    db[NOTIFICATIONS].create_index([("to", 1), ("created_at", -1)])
