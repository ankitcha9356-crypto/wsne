"""Automatic intake: a watched folder and (optionally) a mailbox."""
import email
import imaplib
import os
import re
import shutil
import tempfile
import threading
import time
from email.header import decode_header, make_header
from pathlib import Path

from . import services
from .db import SessionLocal
from .parsing import parse_sheet

INBOX_DIR = Path(os.getenv("INBOX_DIR", "./inbox"))
RESUME_EXT = {".pdf", ".docx", ".txt"}
SHEET_EXT = {".xlsx", ".csv"}
log: list[str] = []  # last few intake events, shown on the dashboard


def note(msg: str) -> None:
    log.append(f"{time.strftime('%d %b %H:%M')}  {msg}")
    del log[:-30]


def import_file(db, path: Path, role_code: str, source: str) -> tuple[int, int, str]:
    """Returns (new, updated, warning)."""
    ext = path.suffix.lower()
    if ext in SHEET_EXT:
        rows, missing = parse_sheet(path)
        if not rows:
            return 0, 0, f"{path.name}: could not find name/email/phone columns"
        new = sum(services.ingest(db, r, role_code, source)[1] for r in rows)
        warn = f"columns not found: {', '.join(missing)}" if missing else ""
        return new, len(rows) - new, warn
    if ext in RESUME_EXT:
        _, created = services.ingest(db, {}, role_code, source, resume_file=path)
        return int(created), int(not created), ""
    return 0, 0, f"{path.name}: unsupported file type (use PDF, DOCX, TXT, XLSX or CSV)"


def scan_folder() -> int:
    """inbox/<ROLE-CODE>/file -> candidate. Processed files move to inbox/_processed/."""
    handled = 0
    for code in services.ROLES:
        folder = INBOX_DIR / code
        folder.mkdir(parents=True, exist_ok=True)
        for f in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            if time.time() - f.stat().st_mtime < 3:  # still being copied
                continue
            with SessionLocal() as db:
                try:
                    new, upd, warn = import_file(db, f, code, "folder")
                    note(f"{code}: {f.name} -> {new} new, {upd} updated{' (' + warn + ')' if warn else ''}")
                except Exception as e:
                    db.rollback()
                    note(f"{code}: {f.name} failed: {e}")
            done = INBOX_DIR / "_processed" / code
            done.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(done / f"{int(time.time())}_{f.name}"))
            handled += 1
    return handled


def role_from_subject(subject: str) -> str:
    """Use a role code written in the subject, e.g. 'Application for INTL-VOICE'."""
    up = subject.upper()
    for code in services.ROLES:
        if code.upper() in up:
            return code
    return os.getenv("DEFAULT_ROLE", "") or next(iter(services.ROLES))


def attachments(msg) -> list[tuple[str, bytes]]:
    out = []
    for part in msg.walk():
        name = part.get_filename()
        if not name:
            continue
        name = str(make_header(decode_header(name)))
        if Path(name).suffix.lower() in RESUME_EXT | SHEET_EXT:
            out.append((re.sub(r"[^\w.\- ]", "_", name), part.get_payload(decode=True) or b""))
    return out


def scan_mailbox() -> int:
    host = os.getenv("IMAP_HOST", "")
    if not host:
        return 0
    handled = 0
    box = imaplib.IMAP4_SSL(host, int(os.getenv("IMAP_PORT", "993")))
    try:
        box.login(os.getenv("IMAP_USER", ""), os.getenv("IMAP_PASSWORD", ""))
        box.select(os.getenv("IMAP_FOLDER", "INBOX"))
        _, data = box.search(None, "UNSEEN")
        for num in data[0].split():
            _, raw = box.fetch(num, "(RFC822)")  # fetching marks the mail as read
            msg = email.message_from_bytes(raw[0][1])
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            code = role_from_subject(subject)
            for name, blob in attachments(msg):
                with tempfile.TemporaryDirectory() as tmp, SessionLocal() as db:
                    p = Path(tmp) / name
                    p.write_bytes(blob)
                    new, upd, warn = import_file(db, p, code, "email")
                    note(f"{code}: email '{subject[:40]}' {name} -> {new} new, {upd} updated")
                    handled += 1
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return handled


def loop(stop: threading.Event) -> None:
    every = int(os.getenv("INTAKE_INTERVAL_SECONDS", "30"))
    while not stop.is_set():
        for job in (scan_folder, scan_mailbox):
            try:
                job()
            except Exception as e:
                note(f"{job.__name__} error: {e}")
        stop.wait(every)
