"""Notifications to uploaders and reviewers.

StoreNotifier only stores messages in basedata_notifications (shown on the app's Varsler page). In the
real app, pass a notifier that calls the app's own e-mail or Teams service — anything with a
send(to, subject, body, link, kind) method works.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from basedata.core import db as dblib
from basedata.core.settings import Settings


class Notifier(Protocol):
    """Anything that can deliver a message to a person."""

    def send(self, to: dict, subject: str, body: str, link: str, kind: str) -> None: ...


class StoreNotifier:
    """Keeps messages in MongoDB; the default until the app's mail service is wired in."""

    def __init__(self, db):
        self.db = db

    def send(self, to: dict, subject: str, body: str, link: str, kind: str) -> None:
        self.db[dblib.NOTIFICATIONS].insert_one({"_id": dblib.new_id("bdn"), "to": to.get("email", ""),
                                                 "to_name": to.get("name", ""), "subject": subject, "body": body,
                                                 "link": link, "kind": kind, "created_at": dblib.now(), "read": False})


def questions_message(settings: Settings, uploader: dict, questions: list[dict], reminder: bool = False) -> tuple[str, str, str]:
    """Subject, body and link for one message listing an uploader's questions."""
    optional = [q for q in questions if q.get("optional")]
    questions = [q for q in questions if not q.get("optional")]
    entries = sorted({(q.get("entry_seq") or 0, q["entry_name"], q["entry_id"]) for q in questions})
    n = len(questions)
    subject = (f"Påminnelse: {n} ubesvarte spørsmål om grunnlagsdata" if reminder
               else f"{n} spørsmål om grunnlagsdata du har levert")
    what = f"#{entries[0][0]} {entries[0][1]}" if len(entries) == 1 else f"{len(entries)} registreringer"
    lines = [f"Hei {uploader.get('name', '').split(' ')[0] or 'der'},", "",
             f"Grunnlagsdatakontrollen trenger litt mer informasjon om {what}:", ""]
    for seq, name, eid in entries:
        lines.append(f"• #{seq} {name}")
        for q in questions:
            if q["entry_id"] == eid:
                lines.append(f"   – {q['question']}")
    if optional:
        lines += ["", "Det er også et valgfritt kommentarfelt for hver registrering."]
    lines += ["", "Klikk på registreringen i registeret for å svare. Hvert svar kontrollerer dataene på nytt med en gang."]
    link = f"{settings.app_base_url}/#entry-{entries[0][2]}" if len(entries) == 1 else f"{settings.app_base_url}/#register"
    return subject, "\n".join(lines), link


def send_reminders(db, settings: Settings, notifier: Notifier, now) -> int:
    """Remind uploaders about questions left open longer than the project's reminder interval."""
    by_person: dict[str, list[dict]] = {}
    projects = {p["_id"]: p for p in db[dblib.PROJECTS].find({})}
    for q in db[dblib.QUESTIONS].find({"status": "open"}):
        days = int((projects.get(q["project_id"]) or {}).get("question_reminder_days") or 0)
        if not days or q.get("optional"):
            continue
        last = q.get("reminder_sent_at") or q["asked_at"]
        if now - last >= timedelta(days=days):
            by_person.setdefault(q["uploader_email"], []).append(q)
    for email, qs in by_person.items():
        subject, body, link = questions_message(settings, {"name": qs[0]["uploader_name"], "email": email}, qs, True)
        notifier.send({"name": qs[0]["uploader_name"], "email": email}, subject, body, link, "reminder")
        for q in qs:
            db[dblib.QUESTIONS].update_one({"_id": q["_id"]}, {"$set": {"reminder_sent_at": now}})
    return len(by_person)
