"""WSNE Hiring Hub: one place for intake, screening, assessment and role line-up."""
import csv
import io
import os
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import intake, scoring, services, transcribe
from .content import CHAT_SCENARIOS, TYPING_TEXT
from .db import Base, SessionLocal, engine, get_db
from .models import Candidate

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
STATUSES = ["screened", "invited", "assessed", "shortlisted", "hold", "rejected", "joined"]
MAX_UPLOAD = 25 * 1024 * 1024
AUDIO_EXT = {".webm", ".ogg", ".mp4", ".m4a", ".mp3", ".wav", ".aac", ".3gp", ".amr"}
TOOLS = [("OpenCATS (ATS)", "OPENCATS_URL"), ("Cal.com (interviews)", "CALCOM_URL"),
         ("Chatwoot (inbox)", "CHATWOOT_URL"), ("Metabase (reports)", "METABASE_URL")]

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    stop = threading.Event()
    if os.getenv("DISABLE_BACKGROUND") != "1":
        threading.Thread(target=intake.loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="WSNE Hiring Hub", lifespan=lifespan)


def admin(creds: HTTPBasicCredentials = Depends(security)) -> str:
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Set ADMIN_PASSWORD before using the hub.")
    ok = secrets.compare_digest(creds.username, ADMIN_USER) and secrets.compare_digest(creds.password, ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(401, "Wrong username or password", headers={"WWW-Authenticate": "Basic"})
    return creds.username


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    tools = [(label, os.getenv(env, "")) for label, env in TOOLS if os.getenv(env)]
    return templates.TemplateResponse(request, name, {"roles": services.ROLES, "tools": tools,
                                                      "statuses": STATUSES, **ctx})


def get_candidate(db: Session, cid: int) -> Candidate:
    c = db.get(Candidate, cid)
    if not c:
        raise HTTPException(404, "Candidate not found")
    return c


async def save_upload(up: UploadFile, dest: Path) -> None:
    data = await up.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB")
    dest.write_bytes(data)


@app.get("/health")
def health():
    problem = transcribe.problem()
    return {"ok": True, "roles": list(services.ROLES), "whisper": not problem, "whisper_problem": problem}


# ---- recruiter pages --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _: str = Depends(admin)):
    rows = db.execute(select(Candidate.matched_role, Candidate.applied_role, Candidate.status,
                             Candidate.recommendation, func.count()).group_by(
        Candidate.matched_role, Candidate.applied_role, Candidate.status, Candidate.recommendation)).all()
    board = {code: {"total": 0, "shortlist": 0, "pending": 0, "not_suitable": 0,
                    **{s: 0 for s in STATUSES}} for code in services.ROLES}
    for matched, applied, status, rec, n in rows:
        code = matched or applied
        if code not in board:
            continue
        board[code]["total"] += n
        board[code][status] = board[code].get(status, 0) + n
        board[code][rec] = board[code].get(rec, 0) + n
    waiting = [c for c in db.scalars(select(Candidate).where(
        Candidate.voice_human.is_(None), Candidate.voice_detail.is_not(None)).limit(200))
        if (c.voice_detail or {}).get("answer_file")][:25]
    return page(request, "dashboard.html", board=board, waiting=waiting, log=list(reversed(intake.log)),
                whisper=transcribe.available())


@app.get("/candidates", response_class=HTMLResponse)
def candidates(request: Request, role: str = "", status: str = "", rec: str = "", q: str = "",
               db: Session = Depends(get_db), _: str = Depends(admin)):
    stmt = select(Candidate)
    if role:
        stmt = stmt.where(or_(Candidate.matched_role == role,
                              (Candidate.matched_role == "") & (Candidate.applied_role == role)))
    if status:
        stmt = stmt.where(Candidate.status == status)
    if rec:
        stmt = stmt.where(Candidate.recommendation == rec)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Candidate.name.ilike(like), Candidate.email.ilike(like), Candidate.phone.ilike(like)))
    rows = db.scalars(stmt.order_by(Candidate.overall_score.desc().nulls_last(), Candidate.id.desc()).limit(500)).all()
    return page(request, "candidates.html", rows=rows, f={"role": role, "status": status, "rec": rec, "q": q})


@app.get("/candidates/{cid}", response_class=HTMLResponse)
def candidate(request: Request, cid: int, msg: str = "", db: Session = Depends(get_db), _: str = Depends(admin)):
    c = get_candidate(db, cid)
    invite, interview = services.invite_message(c), services.interview_message(c)
    return page(request, "candidate.html", c=c, msg=msg, invite=invite, interview=interview,
                link=services.assessment_link(c), wa_invite=services.whatsapp_link(c, invite),
                wa_interview=services.whatsapp_link(c, interview),
                resume_detail={code: scoring.resume_score(r, services.candidate_text(c))[1]
                               for code, r in services.ROLES.items()})


@app.post("/candidates/{cid}/rate")
def rate(cid: int, clarity: int = Form(...), tone: int = Form(...), neutrality: int = Form(...),
         db: Session = Depends(get_db), who: str = Depends(admin)):
    c = get_candidate(db, cid)
    for v in (clarity, tone, neutrality):
        if not 1 <= v <= 5:
            raise HTTPException(422, "Ratings are 1 to 5")
    c.voice_human = {"clarity": clarity, "tone": tone, "neutrality": neutrality, "by": who,
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    services.rescore(c)
    db.commit()
    return RedirectResponse(f"/candidates/{cid}?msg=Voice+rating+saved", 303)


@app.post("/candidates/{cid}/update")
def update(cid: int, status: str = Form(""), applied_role: str = Form(""), notes: str = Form(None),
           experience_years: str = Form(None), notice_days: str = Form(None), ctc_lpa: str = Form(None),
           location: str = Form(None), education: str = Form(None),
           db: Session = Depends(get_db), _: str = Depends(admin)):
    c = get_candidate(db, cid)
    if status in STATUSES:
        c.status = status
    if applied_role in services.ROLES:
        c.applied_role = applied_role
    if notes is not None:
        c.notes = notes
    for field, raw, cast in (("experience_years", experience_years, float), ("notice_days", notice_days, int),
                             ("ctc_lpa", ctc_lpa, float)):
        if raw is not None:
            try:
                setattr(c, field, cast(raw) if raw.strip() else None)
            except ValueError:
                raise HTTPException(422, f"{field} must be a number")
    if location is not None:
        c.location = location.strip()
    if education is not None:
        c.education = education.strip().lower()
    services.rescore(c)
    db.commit()
    return RedirectResponse(f"/candidates/{cid}?msg=Saved", 303)


@app.post("/candidates/{cid}/send")
def send(cid: int, kind: str = Form(...), db: Session = Depends(get_db), _: str = Depends(admin)):
    c = get_candidate(db, cid)
    if kind == "invite":
        err = services.send_email(c.email, f"{services.COMPANY}: online assessment", services.invite_message(c))
        if not err and c.status == "screened":
            c.status = "invited"
    elif kind == "interview":
        err = services.send_email(c.email, f"{services.COMPANY}: interview", services.interview_message(c))
    elif kind == "invited":
        err = ""
        c.status = "invited" if c.status == "screened" else c.status
    elif kind == "chatwoot":
        err = services.push_to_chatwoot(c)
    else:
        raise HTTPException(422, "Unknown action")
    db.commit()
    return RedirectResponse(f"/candidates/{cid}?msg={(err or 'Done').replace(' ', '+')}", 303)


@app.post("/candidates/{cid}/retranscribe")
def retranscribe(cid: int, bg: BackgroundTasks, db: Session = Depends(get_db), _: str = Depends(admin)):
    get_candidate(db, cid)
    for which in ("reading", "answer"):
        bg.add_task(_transcribe_job, cid, which)
    return RedirectResponse(f"/candidates/{cid}?msg=Transcription+started", 303)


@app.get("/candidates/{cid}/audio/{which}")
def audio(cid: int, which: str, db: Session = Depends(get_db), _: str = Depends(admin)):
    c = get_candidate(db, cid)
    path = (c.voice_detail or {}).get(f"{which}_file") if which in ("reading", "answer") else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "No recording")
    return FileResponse(path)


@app.get("/candidates/{cid}/resume")
def resume(cid: int, db: Session = Depends(get_db), _: str = Depends(admin)):
    c = get_candidate(db, cid)
    if not c.resume_path or not Path(c.resume_path).exists():
        raise HTTPException(404, "No resume file")
    return FileResponse(c.resume_path, filename=f"{c.name or 'resume'}{Path(c.resume_path).suffix}")


@app.get("/intake", response_class=HTMLResponse)
def intake_page(request: Request, msg: str = "", _: str = Depends(admin)):
    return page(request, "intake.html", msg=msg, inbox=str(intake.INBOX_DIR),
                imap=bool(os.getenv("IMAP_HOST")))


@app.post("/intake")
async def intake_upload(role: str = Form(...), files: list[UploadFile] = File(...),
                        db: Session = Depends(get_db), _: str = Depends(admin)):
    if role not in services.ROLES:
        raise HTTPException(422, "Unknown role")
    new = upd = 0
    warns = []
    with tempfile.TemporaryDirectory() as tmp:
        for up in files:
            if not up.filename:
                continue
            p = Path(tmp) / Path(up.filename).name
            await save_upload(up, p)
            n, u, w = intake.import_file(db, p, role, "upload")
            new, upd = new + n, upd + u
            if w:
                warns.append(w)
    msg = f"{new} new, {upd} updated." + (" Warnings: " + "; ".join(warns) if warns else "")
    intake.note(f"{role}: upload -> {msg}")
    return RedirectResponse(f"/intake?msg={msg.replace(' ', '+')}", 303)


@app.get("/roles", response_class=HTMLResponse)
def roles_page(request: Request, _: str = Depends(admin)):
    return page(request, "roles.html")


@app.post("/roles/reload")
def roles_reload(db: Session = Depends(get_db), _: str = Depends(admin)):
    services.reload_roles()
    for c in db.scalars(select(Candidate)):
        services.rescore(c)
    db.commit()
    return RedirectResponse("/roles", 303)


@app.get("/export.csv")
def export(db: Session = Depends(get_db), _: str = Depends(admin)):
    cols = ["id", "name", "email", "phone", "location", "education", "experience_years", "notice_days",
            "ctc_lpa", "source", "applied_role", "matched_role", "second_role", "recommendation",
            "overall_score", "chat_score", "typing_wpm", "voice_score", "voice_auto_score", "status", "notes"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for c in db.scalars(select(Candidate).order_by(Candidate.id)):
        w.writerow([getattr(c, k) if getattr(c, k) is not None else "" for k in cols])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=wsne-candidates.csv"})


# ---- candidate assessment (no login, secret link) ---------------------------------

def by_token(db: Session, token: str) -> Candidate:
    c = db.scalars(select(Candidate).where(Candidate.token == token)).first()
    if not c:
        raise HTTPException(404, "This link is not valid.")
    return c


def need_consent(c: Candidate) -> None:
    if not c.consent_at:
        raise HTTPException(403, "Consent is required first.")


@app.get("/a/{token}", response_class=HTMLResponse)
def assessment(request: Request, token: str, db: Session = Depends(get_db)):
    c = by_token(db, token)
    a = services.role_assessment(c.applied_role)
    vd = c.voice_detail or {}
    done = {"consent": bool(c.consent_at), "typing": c.typing_wpm is not None,
            "chat": bool((c.chat_detail or {}).get("replies")),
            "reading": bool(vd.get("reading_file")), "answer": bool(vd.get("answer_file"))}
    return templates.TemplateResponse(request, "assessment.html", {
        "c": c, "done": done, "company": services.COMPANY, "typing_text": TYPING_TEXT,
        "scenarios": CHAT_SCENARIOS, "passage": a.get("reading_passage", ""),
        "question": a.get("voice_question", ""),
        "role_title": services.ROLES.get(c.applied_role, {}).get("title", "")})


@app.post("/a/{token}/consent")
def consent(token: str, db: Session = Depends(get_db)):
    c = by_token(db, token)
    c.consent_at = c.consent_at or datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@app.post("/a/{token}/typing/start")
def typing_start(token: str, db: Session = Depends(get_db)):
    c = by_token(db, token)
    need_consent(c)
    if c.typing_wpm is not None:
        raise HTTPException(409, "Typing test already submitted.")
    c.typing_started_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@app.post("/a/{token}/typing")
def typing_submit(token: str, typed: str = Form(""), db: Session = Depends(get_db)):
    c = by_token(db, token)
    need_consent(c)
    if c.typing_wpm is not None:
        raise HTTPException(409, "Typing test already submitted.")
    if not c.typing_started_at:
        raise HTTPException(409, "Start the typing test first.")
    started = c.typing_started_at
    if started.tzinfo is None:  # SQLite drops the timezone
        started = started.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - started).total_seconds()
    c.typing_wpm, c.typing_accuracy = scoring.typing_result(TYPING_TEXT, typed[:2000], seconds)
    services.rescore(c)
    db.commit()
    return {"ok": True}


@app.post("/a/{token}/chat")
def chat_submit(token: str, answers: list[str] = Form(...), db: Session = Depends(get_db)):
    c = by_token(db, token)
    need_consent(c)
    if (c.chat_detail or {}).get("replies"):
        raise HTTPException(409, "Written test already submitted.")
    services.save_chat(c, [a[:3000] for a in answers])
    db.commit()
    return {"ok": True}


def _transcribe_job(cid: int, which: str) -> None:
    with SessionLocal() as db:
        services.transcribe_clip(db, cid, which)


@app.post("/a/{token}/voice/{which}")
async def voice_upload(token: str, which: str, bg: BackgroundTasks, file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    if which not in ("reading", "answer"):
        raise HTTPException(404)
    c = by_token(db, token)
    need_consent(c)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        ext = {"audio/webm": ".webm", "audio/mp4": ".mp4", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
               "audio/wav": ".wav", "audio/x-m4a": ".m4a"}.get((file.content_type or "").split(";")[0], "")
    if not ext:
        raise HTTPException(415, "Please upload an audio recording.")
    dest = services.AUDIO_DIR / f"{c.id}_{which}{ext}"
    await save_upload(file, dest)
    if dest.stat().st_size < 2000:
        dest.unlink()
        raise HTTPException(422, "The recording is empty. Please try again.")
    vd = {k: v for k, v in (c.voice_detail or {}).items() if k not in (which, f"{which}_error", "metrics")}
    vd[f"{which}_file"] = str(dest)
    c.voice_detail = vd
    services.rescore(c)
    db.commit()
    bg.add_task(_transcribe_job, c.id, which)
    return {"ok": True}
