"""Candidate pipeline: ingest, score, re-score, messages and optional integrations."""
import os
import re
import shutil
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import scoring, transcribe
from .content import CHAT_SCENARIOS
from .db import DATA_DIR
from .models import Candidate
from .parsing import extract_text, parse_resume

PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
COMPANY = os.getenv("COMPANY_NAME", "WSNE Consulting")
RESUME_DIR = DATA_DIR / "resumes"
AUDIO_DIR = DATA_DIR / "audio"
for d in (RESUME_DIR, AUDIO_DIR):
    d.mkdir(parents=True, exist_ok=True)

ROLES = scoring.load_roles()


def reload_roles():
    global ROLES
    ROLES = scoring.load_roles()
    return ROLES


def role_assessment(code: str) -> dict:
    role = ROLES.get(code) or next(iter(ROLES.values()))
    return role.get("assessment", {})


def candidate_text(c: Candidate) -> str:
    """Everything we know in words, used for keyword matching when there is no resume file."""
    return "\n".join(x for x in [c.resume_text, c.skills, c.education, c.location] if x)


def rescore(c: Candidate) -> None:
    """Recalculate every composite score and the role line-up from what is stored."""
    text = candidate_text(c)
    resume_scores = {code: scoring.resume_score(role, text)[0] for code, role in ROLES.items()}
    replies = (c.chat_detail or {}).get("replies") or []
    c.chat_score = scoring.chat_total(c.typing_wpm, c.typing_accuracy, replies)
    vd = c.voice_detail or {}
    passage = role_assessment(c.applied_role).get("reading_passage", "")
    auto, metrics = scoring.voice_auto(passage, vd.get("reading"), vd.get("answer"))
    c.voice_auto_score = auto
    if metrics:
        c.voice_detail = {**vd, "metrics": metrics}
    c.voice_score = scoring.voice_total(auto, c.voice_human)
    c.lineup = scoring.lineup(ROLES, c, resume_scores)
    c.matched_role, c.second_role, c.recommendation, c.overall_score = scoring.pick(c.lineup, c.applied_role)
    if c.status in ("screened", "invited") and assessment_done(c):
        c.status = "assessed"


def assessment_done(c: Candidate) -> bool:
    vd = c.voice_detail or {}
    return bool(c.typing_wpm is not None and (c.chat_detail or {}).get("replies")
                and vd.get("reading_file") and vd.get("answer_file"))


def ingest(db: Session, fields: dict, role_code: str, source: str,
           resume_file: Path | None = None) -> tuple[Candidate, bool]:
    """Create or update a candidate. Same email or phone for the same role = same person."""
    text = ""
    if resume_file:
        text = extract_text(resume_file)
        parsed = parse_resume(text)
        fields = {**parsed, **{k: v for k, v in fields.items() if v not in (None, "")}}
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    conds = [x for x in [Candidate.email == fields["email"] if fields.get("email") else None,
                         Candidate.phone == fields["phone"] if fields.get("phone") else None] if x is not None]
    existing = None
    if conds:
        existing = db.scalars(select(Candidate).where(Candidate.applied_role == role_code, or_(*conds))).first()
    c = existing or Candidate(applied_role=role_code, source=source)
    for k, v in fields.items():
        if hasattr(c, k):
            setattr(c, k, v)
    if not c.name:
        c.name = (resume_file.stem if resume_file else c.email or c.phone or "Unknown").replace("_", " ").title()
    if text:
        c.resume_text = text
    if not existing:
        db.add(c)
        db.flush()
    if resume_file:
        dest = RESUME_DIR / f"{c.id}{resume_file.suffix.lower()}"
        shutil.copyfile(resume_file, dest)
        c.resume_path = str(dest)
    rescore(c)
    db.commit()
    return c, existing is None


# ---- assessment steps ------------------------------------------------------------

def save_chat(c: Candidate, answers: list[str]) -> None:
    replies = []
    for sc, ans in zip(CHAT_SCENARIOS, answers):
        replies.append({"id": sc["id"], "customer": sc["customer"], "reply": ans,
                        **scoring.chat_reply_score(sc, ans)})
    c.chat_detail = {"replies": replies}
    rescore(c)


def transcribe_clip(db: Session, cand_id: int, which: str) -> None:
    """Runs after an upload. If Whisper is missing the clip simply waits for a recruiter."""
    c = db.get(Candidate, cand_id)
    if not c:
        return
    vd = dict(c.voice_detail or {})
    path = vd.get(f"{which}_file")
    if not path:
        return
    try:
        vd[which] = transcribe.transcribe(path)
        vd.pop(f"{which}_error", None)
    except Exception as e:  # keep the recording; a recruiter can still listen and rate it
        vd[f"{which}_error"] = f"{type(e).__name__}: {e}"[:200]
    c.voice_detail = vd
    rescore(c)
    db.commit()


# ---- messages --------------------------------------------------------------------

def assessment_link(c: Candidate) -> str:
    return f"{PUBLIC_URL}/a/{c.token}"


def invite_message(c: Candidate) -> str:
    role = ROLES.get(c.applied_role, {}).get("title", "the open role")
    return (f"Hi {c.name.split()[0] if c.name else 'there'}, thank you for applying to {COMPANY} for "
            f"{role}. Please complete this 10-minute online assessment (typing, two written replies "
            f"and two short voice recordings): {assessment_link(c)}")


def interview_message(c: Candidate) -> str:
    role = ROLES.get(c.matched_role or c.applied_role, {})
    link = role.get("interview_link") or os.getenv("INTERVIEW_LINK", "")
    tail = f" Please pick an interview slot here: {link}" if link else " Our recruiter will call you to fix an interview time."
    return (f"Hi {c.name.split()[0] if c.name else 'there'}, congratulations! You have been shortlisted "
            f"by {COMPANY} for {role.get('title', 'the role')}.{tail}")


def whatsapp_link(c: Candidate, text: str) -> str:
    """Free click-to-chat link: opens WhatsApp on the recruiter's device with the message filled in."""
    digits = re.sub(r"\D", "", c.phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else ""


def send_email(to: str, subject: str, body: str) -> str:
    """Returns '' on success or the reason it was not sent. Needs SMTP_* settings."""
    host = os.getenv("SMTP_HOST", "")
    if not host:
        return "Email is not set up (SMTP_HOST is empty)."
    if not to:
        return "Candidate has no email address."
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return ""
    except Exception as e:
        return f"Email failed: {e}"


def push_to_chatwoot(c: Candidate) -> str:
    """Create the candidate as a Chatwoot contact. Returns '' on success or the reason."""
    url, token = os.getenv("CHATWOOT_URL", "").rstrip("/"), os.getenv("CHATWOOT_API_TOKEN", "")
    account = os.getenv("CHATWOOT_ACCOUNT_ID", "1")
    if not (url and token):
        return "Chatwoot is not connected (set CHATWOOT_URL and CHATWOOT_API_TOKEN)."
    digits = re.sub(r"\D", "", c.phone or "")
    payload = {"name": c.name, "custom_attributes": {"role": c.matched_role or c.applied_role,
                                                      "hub_status": c.status, "overall_score": c.overall_score}}
    if c.email:
        payload["email"] = c.email
    if digits:
        payload["phone_number"] = "+" + (digits if len(digits) > 10 else "91" + digits)
    try:
        r = httpx.post(f"{url}/api/v1/accounts/{account}/contacts", json=payload,
                       headers={"api_access_token": token}, timeout=20)
        return "" if r.status_code < 300 else f"Chatwoot said {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return f"Chatwoot not reachable: {e}"
