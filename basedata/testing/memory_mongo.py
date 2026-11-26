"""A small in-memory stand-in for MongoDB and GridFS, for tests and the offline demo.

It implements only the part of the pymongo API this module uses (find/sort/limit, insert, update with
$set/$unset/$push/$inc/$setOnInsert, replace, delete, count, unique indexes) and GridFSBucket's
upload_from_stream / open_download_stream. Production code uses real pymongo and gridfs.
"""

from __future__ import annotations

import copy
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

_MISSING = object()


def _get(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _set(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _unset(doc: dict, path: str) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        cur = cur.get(part)
        if not isinstance(cur, dict):
            return
    cur.pop(parts[-1], None)


def _cmp_key(v):
    """Sort order close to BSON: missing/None < numbers < strings < dicts < lists < bools < dates."""
    if v is _MISSING or v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (5, v)
    if isinstance(v, (int, float)):
        return (1, v)
    if isinstance(v, str):
        return (2, v)
    if isinstance(v, datetime):
        return (6, v.timestamp())
    return (3, str(v))


def _match_cond(value, cond) -> bool:
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$eq" and not _match_cond(value, arg):
                return False
            if op == "$ne" and _match_cond(value, arg):
                return False
            if op == "$in" and not any(_match_cond(value, a) for a in arg):
                return False
            if op == "$nin" and any(_match_cond(value, a) for a in arg):
                return False
            if op == "$exists" and (value is not _MISSING) != bool(arg):
                return False
            if op in ("$gt", "$gte", "$lt", "$lte"):
                if value is _MISSING or value is None:
                    return False
                a, b = _cmp_key(value), _cmp_key(arg)
                ok = {"$gt": a > b, "$gte": a >= b, "$lt": a < b, "$lte": a <= b}[op]
                if not ok:
                    return False
            if op == "$regex":
                flags = re.I if "i" in cond.get("$options", "") else 0
                if not isinstance(value, str) or not re.search(arg, value, flags):
                    return False
        return True
    if isinstance(value, list) and not isinstance(cond, list):
        return any(v == cond for v in value)
    if value is _MISSING:
        return cond is None
    return value == cond


def matches(doc: dict, flt: dict | None) -> bool:
    """True when `doc` satisfies the MongoDB-style filter."""
    for key, cond in (flt or {}).items():
        if key == "$or":
            if not any(matches(doc, f) for f in cond):
                return False
        elif key == "$and":
            if not all(matches(doc, f) for f in cond):
                return False
        elif not _match_cond(_get(doc, key), cond):
            return False
    return True


@dataclass
class InsertOneResult:
    inserted_id: object


@dataclass
class UpdateResult:
    matched_count: int
    modified_count: int
    upserted_id: object = None


@dataclass
class DeleteResult:
    deleted_count: int


class DuplicateKeyError(Exception):
    """Raised when a unique index would be violated (mirrors pymongo.errors.DuplicateKeyError)."""


class Cursor:
    """Lazy result of find(): supports sort, limit, skip and iteration."""

    def __init__(self, docs: list[dict], projection: dict | None):
        self._docs, self._projection = docs, projection
        self._sort: list[tuple[str, int]] = []
        self._limit = 0
        self._skip = 0

    def sort(self, key, direction: int = 1) -> "Cursor":
        self._sort = list(key) if isinstance(key, list) else [(key, direction)]
        return self

    def limit(self, n: int) -> "Cursor":
        self._limit = n
        return self

    def skip(self, n: int) -> "Cursor":
        self._skip = n
        return self

    def _project(self, doc: dict) -> dict:
        if not self._projection:
            return copy.deepcopy(doc)
        include = {k for k, v in self._projection.items() if v}
        if include:
            out = {k: copy.deepcopy(doc[k]) for k in include if k in doc}
            if self._projection.get("_id", 1) and "_id" in doc:
                out["_id"] = doc["_id"]
            return out
        return {k: copy.deepcopy(v) for k, v in doc.items() if self._projection.get(k, 1)}

    def __iter__(self):
        docs = list(self._docs)
        for key, direction in reversed(self._sort):
            docs.sort(key=lambda d: _cmp_key(_get(d, key)), reverse=direction < 0)
        docs = docs[self._skip:]
        if self._limit:
            docs = docs[: self._limit]
        return iter([self._project(d) for d in docs])


class MemoryCollection:
    """One collection: a list of documents plus unique-index bookkeeping."""

    def __init__(self, name: str):
        self.name = name
        self._docs: list[dict] = []
        self._unique: list[str] = []

    def _check_unique(self, doc: dict, skip: dict | None = None) -> None:
        for field in self._unique:
            v = _get(doc, field)
            if v is _MISSING:
                continue
            for other in self._docs:
                if other is not skip and _get(other, field) == v:
                    raise DuplicateKeyError(f"duplicate key {field}={v!r} in {self.name}")

    def create_index(self, keys, unique: bool = False, **_kwargs) -> str:
        names = [keys] if isinstance(keys, str) else [k for k, _ in keys]
        if unique and len(names) == 1:
            self._unique.append(names[0])
        return "_".join(names)

    def insert_one(self, doc: dict) -> InsertOneResult:
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", uuid.uuid4().hex[:24])
        if any(d["_id"] == doc["_id"] for d in self._docs):
            raise DuplicateKeyError(f"duplicate _id {doc['_id']!r} in {self.name}")
        self._check_unique(doc)
        self._docs.append(doc)
        return InsertOneResult(doc["_id"])

    def insert_many(self, docs: list[dict]):
        return [self.insert_one(d).inserted_id for d in docs]

    def find(self, flt: dict | None = None, projection: dict | None = None, sort=None, limit: int = 0) -> Cursor:
        cur = Cursor([d for d in self._docs if matches(d, flt)], projection)
        if sort:
            cur.sort(sort)
        if limit:
            cur.limit(limit)
        return cur

    def find_one(self, flt: dict | None = None, projection: dict | None = None, sort=None) -> dict | None:
        for doc in self.find(flt, projection, sort=sort, limit=1):
            return doc
        return None

    def count_documents(self, flt: dict | None = None) -> int:
        return sum(1 for d in self._docs if matches(d, flt))

    def distinct(self, key: str, flt: dict | None = None) -> list:
        out = []
        for d in self._docs:
            if matches(d, flt):
                v = _get(d, key)
                for item in (v if isinstance(v, list) else [v]):
                    if item is not _MISSING and item not in out:
                        out.append(item)
        return out

    @staticmethod
    def _apply(doc: dict, update: dict, inserting: bool) -> None:
        for op, fields in update.items():
            for path, value in fields.items():
                if op == "$set" or (op == "$setOnInsert" and inserting):
                    _set(doc, path, copy.deepcopy(value))
                elif op == "$unset":
                    _unset(doc, path)
                elif op == "$inc":
                    cur = _get(doc, path)
                    _set(doc, path, (0 if cur is _MISSING else cur) + value)
                elif op in ("$push", "$addToSet"):
                    cur = _get(doc, path)
                    arr = [] if cur is _MISSING else cur
                    items = value["$each"] if isinstance(value, dict) and "$each" in value else [value]
                    for item in items:
                        if op == "$push" or item not in arr:
                            arr.append(copy.deepcopy(item))
                    _set(doc, path, arr)

    def update_one(self, flt: dict, update: dict, upsert: bool = False) -> UpdateResult:
        for doc in self._docs:
            if matches(doc, flt):
                before = copy.deepcopy(doc)
                trial = copy.deepcopy(doc)
                self._apply(trial, update, inserting=False)
                self._check_unique(trial, skip=doc)
                doc.clear()
                doc.update(trial)
                return UpdateResult(1, int(before != doc))
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            self._apply(new, update, inserting=True)
            return UpdateResult(0, 0, self.insert_one(new).inserted_id)
        return UpdateResult(0, 0)

    def update_many(self, flt: dict, update: dict) -> UpdateResult:
        n = 0
        for doc in self._docs:
            if matches(doc, flt):
                self._apply(doc, update, inserting=False)
                n += 1
        return UpdateResult(n, n)

    def replace_one(self, flt: dict, doc: dict, upsert: bool = False) -> UpdateResult:
        for i, existing in enumerate(self._docs):
            if matches(existing, flt):
                new = copy.deepcopy(doc)
                new["_id"] = existing["_id"]
                self._check_unique(new, skip=existing)
                self._docs[i] = new
                return UpdateResult(1, 1)
        if upsert:
            return UpdateResult(0, 0, self.insert_one(doc).inserted_id)
        return UpdateResult(0, 0)

    def delete_one(self, flt: dict) -> DeleteResult:
        for i, doc in enumerate(self._docs):
            if matches(doc, flt):
                del self._docs[i]
                return DeleteResult(1)
        return DeleteResult(0)

    def delete_many(self, flt: dict | None) -> DeleteResult:
        keep = [d for d in self._docs if not matches(d, flt)]
        n = len(self._docs) - len(keep)
        self._docs = keep
        return DeleteResult(n)


class MemoryDatabase:
    """A database: collections are created on first use, as in MongoDB."""

    is_memory = True

    def __init__(self, name: str = "memory"):
        self.name = name
        self._collections: dict[str, MemoryCollection] = {}
        self._blobs: dict[object, bytes] = {}

    def __getitem__(self, name: str) -> MemoryCollection:
        if name not in self._collections:
            self._collections[name] = MemoryCollection(name)
        return self._collections[name]

    def __getattr__(self, name: str) -> MemoryCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def list_collection_names(self) -> list[str]:
        return list(self._collections)


class GridOut(io.BytesIO):
    """A downloaded GridFS file: readable, with filename, length, upload date and metadata."""

    def __init__(self, data: bytes, info: dict):
        super().__init__(data)
        self._id = info["_id"]
        self.filename = info["filename"]
        self.length = info["length"]
        self.upload_date = info["uploadDate"]
        self.metadata = info.get("metadata")


class NoFile(Exception):
    """Raised when a GridFS file does not exist (mirrors gridfs.errors.NoFile)."""


class MemoryGridFSBucket:
    """GridFSBucket stand-in: file info in '<bucket>.files', bytes kept in memory."""

    def __init__(self, db: MemoryDatabase, bucket_name: str = "fs"):
        self._db, self._files = db, db[f"{bucket_name}.files"]

    def upload_from_stream(self, filename: str, source, metadata: dict | None = None) -> str:
        data = source if isinstance(source, (bytes, bytearray)) else source.read()
        file_id = uuid.uuid4().hex[:24]
        self._files.insert_one({"_id": file_id, "filename": filename, "length": len(data), "chunkSize": 261120,
                                "uploadDate": datetime.now(timezone.utc), "metadata": metadata or {}})
        self._db._blobs[file_id] = bytes(data)
        return file_id

    def open_download_stream(self, file_id) -> GridOut:
        info = self._files.find_one({"_id": file_id})
        if info is None:
            raise NoFile(f"no file {file_id!r}")
        return GridOut(self._db._blobs[file_id], info)

    def delete(self, file_id) -> None:
        self._files.delete_one({"_id": file_id})
        self._db._blobs.pop(file_id, None)
