"""Lokal lagring: registeret, kontroller, spørsmål, kommentarer, regelsett osv. i én SQLite-fil.

Ingen databaseserver trengs. SQLite følger med Python. Dokumentene ligger i minnet mens appen kjører
(samme spørringer som før, se testing/memory_mongo.py), og hver endring skrives straks til fila, så
ingenting går tapt hvis appen stoppes.

Fila heter som standard `<kildemappe>/_basedata/register.db`. Høyderutenett for sammenligning
lagres i samme fil (tabellen `blobs`).
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from basedata.core.memory_mongo import (DeleteResult, InsertOneResult, MemoryCollection, MemoryDatabase,
                                   MemoryGridFSBucket, UpdateResult, matches)

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (coll TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (coll, id));
CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
FORMAT_VERSION = "1"


def _encode(obj):
    """JSON-hjelper: datoer og bytes lagres med en markør, så de kommer tilbake som samme type."""
    if isinstance(obj, datetime):
        return {"$date": obj.isoformat()}
    if isinstance(obj, date):
        return {"$day": obj.isoformat()}
    if isinstance(obj, (bytes, bytearray)):
        return {"$bytes": base64.b64encode(bytes(obj)).decode("ascii")}
    if isinstance(obj, tuple):
        return list(obj)
    if hasattr(obj, "item"):  # numpy-tall
        return obj.item()
    raise TypeError(f"Kan ikke lagre {type(obj).__name__}")


def _decode(d: dict):
    if len(d) == 1:
        if "$date" in d:
            return datetime.fromisoformat(d["$date"])
        if "$day" in d:
            return date.fromisoformat(d["$day"])
        if "$bytes" in d:
            return base64.b64decode(d["$bytes"])
    return d


def dumps(doc: dict) -> str:
    return json.dumps(doc, default=_encode, ensure_ascii=False, separators=(",", ":"))


def loads(text: str) -> dict:
    return json.loads(text, object_hook=_decode)


def _key(doc_id) -> str:
    return json.dumps(doc_id, default=_encode)


class LocalCollection(MemoryCollection):
    """En samling som skriver hver endring til SQLite-fila."""

    def __init__(self, name: str, store: "LocalDatabase"):
        super().__init__(name)
        self._store = store

    def _ids(self, flt, first_only: bool = False) -> list:
        out = []
        for d in self._docs:
            if matches(d, flt):
                out.append(d["_id"])
                if first_only:
                    break
        return out

    def _persist(self, ids) -> None:
        by_id = {_key(d["_id"]): d for d in self._docs}
        rows_put, rows_del = [], []
        for i in ids:
            k = _key(i)
            if k in by_id:
                rows_put.append((self.name, k, dumps(by_id[k])))
            else:
                rows_del.append((self.name, k))
        self._store._write(rows_put, rows_del)

    def insert_one(self, doc: dict) -> InsertOneResult:
        with self._store.lock:
            res = super().insert_one(doc)
            self._persist([res.inserted_id])
            return res

    def update_one(self, flt: dict, update: dict, upsert: bool = False) -> UpdateResult:
        with self._store.lock:
            ids = self._ids(flt, first_only=True)
            res = super().update_one(flt, update, upsert)
            self._persist(ids + ([res.upserted_id] if res.upserted_id is not None else []))
            return res

    def update_many(self, flt: dict, update: dict) -> UpdateResult:
        with self._store.lock:
            ids = self._ids(flt)
            res = super().update_many(flt, update)
            self._persist(ids)
            return res

    def replace_one(self, flt: dict, doc: dict, upsert: bool = False) -> UpdateResult:
        with self._store.lock:
            ids = self._ids(flt, first_only=True)
            res = super().replace_one(flt, doc, upsert)
            self._persist(ids + ([res.upserted_id] if res.upserted_id is not None else []))
            return res

    def delete_one(self, flt: dict) -> DeleteResult:
        with self._store.lock:
            ids = self._ids(flt, first_only=True)
            res = super().delete_one(flt)
            self._persist(ids)
            return res

    def delete_many(self, flt: dict | None) -> DeleteResult:
        with self._store.lock:
            ids = self._ids(flt)
            res = super().delete_many(flt)
            self._persist(ids)
            return res


class LocalBlobs(dict):
    """Binærdata (høyderutenett) som leses fra og skrives til SQLite ved behov."""

    def __init__(self, store: "LocalDatabase"):
        super().__init__()
        self._store = store

    def __setitem__(self, key, value) -> None:
        with self._store.lock:
            self._store._conn.execute("INSERT OR REPLACE INTO blobs (id, data) VALUES (?, ?)", (str(key), bytes(value)))
            self._store._conn.commit()

    def __getitem__(self, key) -> bytes:
        with self._store.lock:
            row = self._store._conn.execute("SELECT data FROM blobs WHERE id = ?", (str(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        return bytes(row[0])

    def __contains__(self, key) -> bool:
        with self._store.lock:
            return self._store._conn.execute("SELECT 1 FROM blobs WHERE id = ?", (str(key),)).fetchone() is not None

    def pop(self, key, default=None):
        with self._store.lock:
            self._store._conn.execute("DELETE FROM blobs WHERE id = ?", (str(key),))
            self._store._conn.commit()
        return default


class LocalDatabase(MemoryDatabase):
    """Databasen i én SQLite-fil. Brukes på samme måte som før (db[samling].find(...))."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(self.path.stem)
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('format', ?)", (FORMAT_VERSION,))
        self._conn.commit()
        self._blobs = LocalBlobs(self)
        for coll, body in self._conn.execute("SELECT coll, body FROM docs ORDER BY rowid"):
            self[coll]._docs.append(loads(body))

    def __getitem__(self, name: str) -> LocalCollection:
        if name not in self._collections:
            self._collections[name] = LocalCollection(name, self)
        return self._collections[name]

    def _write(self, put: list[tuple], delete: list[tuple]) -> None:
        if not put and not delete:
            return
        with self.lock:
            if put:
                self._conn.executemany("INSERT OR REPLACE INTO docs (coll, id, body) VALUES (?, ?, ?)", put)
            if delete:
                self._conn.executemany("DELETE FROM docs WHERE coll = ? AND id = ?", delete)
            self._conn.commit()

    def close(self) -> None:
        with self.lock:
            self._conn.close()

    def __deepcopy__(self, memo):
        """En kopi i minnet (brukes når demosiden regner ut forhåndsvisninger). Endringer i kopien lagres ikke."""
        import copy

        mem = MemoryDatabase(self.name)
        for name, coll in self._collections.items():
            c = mem[name]
            c._docs = copy.deepcopy(coll._docs, memo)
            c._unique = list(coll._unique)
        with self.lock:
            mem._blobs = {k: bytes(v) for k, v in self._conn.execute("SELECT id, data FROM blobs")}
        return mem


def open_store(path: Path | str) -> LocalDatabase:
    """Åpne (eller opprett) den lokale databasen og sørg for indeksene."""
    from basedata.core import db as dblib

    db = LocalDatabase(path)
    dblib.ensure_indexes(db)
    return db


__all__ = ["LocalDatabase", "open_store", "MemoryGridFSBucket"]
