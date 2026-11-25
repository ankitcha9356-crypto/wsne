from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import intake, parsing, scoring, services, transcribe
from app.content import CHAT_SCENARIOS, TYPING_TEXT
from app.db import SessionLocal
from app.main import app
from app.models import Candidate

AUTH = ("admin", "test-pass")
PASSAGE = services.ROLES["INTL-VOICE"]["assessment"]["reading_passage"]

RESUME = """Priya Sharma
priya.sharma@example.com | +91 98765 43210 | Hyderabad
Customer support executive with 3 years of experience in an international voice process (US shift)
at a BPO. Handled inbound calls, billing queries and CRM (Zendesk). Excellent English.
Education: B.Com graduate
Notice period: 15 days
Skills: customer service, inbound calls, Zendesk, night shift
"""
GOOD_REPLY = ("Hello, thank you for contacting us. I am really sorry for the inconvenience and I understand how "
              "frustrating this is. Please share your order number so I can check the delivery status right away. "
              "If the parcel cannot be traced, I will arrange a full refund within 48 hours. Is there anything "
              "else I can help you with? Regards, Priya")
BAD_REPLY = "ok wat is ur order no i will chk dont worry u will get it"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_field_parsers():
    assert parsing.parse_experience("3 Year(s) 6 Month(s)") == 3.5
    assert parsing.parse_experience("Fresher") == 0.0
    assert parsing.parse_notice("15 Days or less") == 15
    assert parsing.parse_notice("2 Months") == 60
    assert parsing.parse_notice("Serving Notice Period") == 0
    assert parsing.parse_ctc("INR 3,50,000") == 3.5
    assert parsing.parse_ctc("4.2 Lacs") == 4.2
    assert parsing.clean_phone("+91-98765 43210") == "9876543210"


def test_resume_parse():
    p = parsing.parse_resume(RESUME)
    assert p["name"] == "Priya Sharma"
    assert p["email"] == "priya.sharma@example.com"
    assert p["phone"] == "9876543210"
    assert p["location"] == "Hyderabad"
    assert p["education"] == "graduate"
    assert p["experience_years"] == 3.0
    assert p["notice_days"] == 15


def test_resume_scores_separate_roles():
    roles = services.ROLES
    voice, d = scoring.resume_score(roles["INTL-VOICE"], RESUME)
    chat, _ = scoring.resume_score(roles["CHAT-EMAIL"], RESUME)
    unrelated, _ = scoring.resume_score(roles["INTL-VOICE"], "Civil engineer with AutoCAD and site supervision.")
    assert voice > 75 and voice > chat > unrelated
    assert not d["must_missing"]


def test_knockouts_never_reject_on_missing_data():
    role = services.ROLES["INTL-VOICE"]
    blank = Candidate(name="x")
    failed, unknown = scoring.knockouts(role, blank)
    assert failed == [] and "notice period" in unknown
    late = Candidate(name="x", notice_days=90, ctc_lpa=9, education="10th")
    failed, _ = scoring.knockouts(role, late)
    assert len(failed) == 3


def test_typing_and_chat_scoring():
    wpm, acc = scoring.typing_result(TYPING_TEXT, TYPING_TEXT, 60)
    assert acc == 1.0 and wpm == round(len(TYPING_TEXT) / 5, 1)
    _, sloppy = scoring.typing_result(TYPING_TEXT, TYPING_TEXT.replace("e", "x"), 60)
    assert sloppy < 0.95
    good = scoring.chat_reply_score(CHAT_SCENARIOS[0], GOOD_REPLY)
    bad = scoring.chat_reply_score(CHAT_SCENARIOS[0], BAD_REPLY)
    assert good["score"] > 80 > 45 > bad["score"]
    assert scoring.chat_reply_score(CHAT_SCENARIOS[0], "ok")["score"] == 0


def fake_transcript(text, wpm=140, gap=0.2):
    words, t, segs = text.split(), 0.0, []
    for i in range(0, len(words), 8):
        chunk = words[i:i + 8]
        dur = len(chunk) / wpm * 60
        segs.append({"start": round(t, 2), "end": round(t + dur, 2), "text": " ".join(chunk)})
        t += dur + gap
    return {"text": text, "segments": segs}


def test_voice_scoring():
    answer = ("A customer was upset because his refund was delayed. I listened carefully, apologised and "
              "explained the process. Then I raised the request again and called him back the next day to "
              "confirm that the money had reached his account. He thanked me and stayed with the company. "
              "I learned that staying calm and giving a clear timeline makes a real difference to people.")
    good, m = scoring.voice_auto(PASSAGE, fake_transcript(PASSAGE), fake_transcript(answer))
    poor, _ = scoring.voice_auto(PASSAGE, fake_transcript("thank you for calling um support uh i understand", 70, 2.5),
                                 fake_transcript("um i dont know uh basically i mean customer was angry um", 70, 2.5))
    assert good > 85 and m["reading_accuracy"] == 100
    assert poor < 45
    assert scoring.voice_total(good, None) is None  # no final score until a recruiter rates
    assert scoring.voice_total(80, {"clarity": 5, "tone": 4, "neutrality": 3}) == 80.0


def test_naukri_sheet_import(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Naukri export - Voice process"])
    ws.append(["Candidate Name", "Email ID", "Phone Number", "Current Location", "Total Experience",
               "Annual Salary", "Notice period/ Availability to join", "UG degree", "Key Skills"])
    ws.append(["rahul verma", "Rahul@Example.com", "9812345678", "Pune", "2 Year(s) 6 Month(s)",
               "INR 3,20,000", "15 Days or less", "B.Com", "customer service, inbound calls, english, bpo"])
    ws.append(["Anita Rao", "anita@example.com", "+91 9900112233", "Chennai", "Fresher", "", "Immediate", "B.A", "english, chat"])
    f = tmp_path / "naukri.xlsx"
    wb.save(f)
    rows, missing = parsing.parse_sheet(f)
    assert missing == [] and len(rows) == 2
    assert rows[0] == {"name": "Rahul Verma", "email": "rahul@example.com", "phone": "9812345678",
                       "location": "Pune", "education": "graduate",
                       "skills": "customer service, inbound calls, english, bpo",
                       "experience_years": 2.5, "notice_days": 15, "ctc_lpa": 3.2}
    assert rows[1]["experience_years"] == 0.0 and rows[1]["notice_days"] == 0


def test_folder_pickup_and_dedupe(tmp_path, client):
    folder = intake.INBOX_DIR / "INTL-VOICE"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "priya.txt"
    f.write_text(RESUME)
    import os, time
    os.utime(f, (time.time() - 10, time.time() - 10))
    assert intake.scan_folder() == 1
    assert not f.exists() and list((intake.INBOX_DIR / "_processed" / "INTL-VOICE").iterdir())
    f.write_text(RESUME)
    os.utime(f, (time.time() - 10, time.time() - 10))
    intake.scan_folder()
    with SessionLocal() as db:
        assert db.query(Candidate).filter_by(email="priya.sharma@example.com").count() == 1


def test_role_from_subject():
    assert intake.role_from_subject("Fwd: application chat-email Hyderabad") == "CHAT-EMAIL"


def test_full_flow(client, monkeypatch, tmp_path):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "wrong")).status_code == 401

    resume = tmp_path / "Asha Nair.txt"
    resume.write_text(RESUME.replace("Priya Sharma", "Asha Nair").replace("priya.sharma", "asha.nair")
                      .replace("98765 43210", "91234 56789"))
    r = client.post("/intake", auth=AUTH, data={"role": "INTL-VOICE"},
                    files={"files": (resume.name, resume.read_bytes(), "text/plain")}, follow_redirects=False)
    assert r.status_code == 303 and "1+new" in r.headers["location"]
    with SessionLocal() as db:
        c = db.query(Candidate).filter_by(email="asha.nair@example.com").one()
        cid, token = c.id, c.token
        assert c.recommendation == "pending" and c.matched_role == "INTL-VOICE" and c.status == "screened"

    # candidate side
    assert client.get("/a/nope").status_code == 404
    assert client.get(f"/a/{token}").status_code == 200
    assert client.post(f"/a/{token}/typing/start").status_code == 403  # consent first
    assert client.post(f"/a/{token}/consent").status_code == 200
    assert client.post(f"/a/{token}/typing/start").status_code == 200
    with SessionLocal() as db:  # pretend the candidate typed for 75 seconds
        from datetime import datetime, timedelta, timezone
        c = db.get(Candidate, cid)
        c.typing_started_at = datetime.now(timezone.utc) - timedelta(seconds=75)
        db.commit()
    assert client.post(f"/a/{token}/typing", data={"typed": TYPING_TEXT}).status_code == 200
    assert client.post(f"/a/{token}/typing", data={"typed": "again"}).status_code == 409
    assert client.post(f"/a/{token}/chat", data={"answers": [GOOD_REPLY, GOOD_REPLY.replace("order number", "transaction details and account")]}).status_code == 200

    answer = ("A customer was upset because his refund was delayed. I listened carefully, apologised and "
              "explained the process, then raised the request again and called him back the next day to confirm "
              "the money had reached his account. He thanked me and stayed with the company. I learned that "
              "staying calm and giving a clear timeline makes a real difference to people who are worried.")
    monkeypatch.setattr(transcribe, "transcribe",
                        lambda path: fake_transcript(PASSAGE if "reading" in path else answer))
    assert client.post(f"/a/{token}/voice/reading", files={"file": ("a.txt", b"x" * 5000, "text/plain")}).status_code == 415
    assert client.post(f"/a/{token}/voice/reading", files={"file": ("clip.webm", b"x" * 100, "audio/webm")}).status_code == 422
    for which in ("reading", "answer"):
        r = client.post(f"/a/{token}/voice/{which}", files={"file": ("clip.webm", b"x" * 5000, "audio/webm")})
        assert r.status_code == 200

    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert c.status == "assessed" and c.typing_wpm > 40 and c.chat_score > 75
        assert c.voice_auto_score > 85 and c.voice_score is None
        assert c.recommendation == "shortlist" and c.matched_role == "CHAT-EMAIL"  # voice still unrated
        assert c.lineup["INTL-VOICE"]["waiting_for"] == ["voice"]

    # recruiter rates the clip -> voice role opens up and wins
    r = client.post(f"/candidates/{cid}/rate", auth=AUTH, data={"clarity": 5, "tone": 4, "neutrality": 4},
                    follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert c.voice_score > 85 and c.recommendation == "shortlist"
        assert c.matched_role == "INTL-VOICE" and c.second_role == "CHAT-EMAIL"
        assert c.status == "assessed"  # the hub never shortlists by itself

    # a knockout entered by the recruiter flips the recommendation
    client.post(f"/candidates/{cid}/update", auth=AUTH, data={"notice_days": "90", "status": "hold"})
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert c.recommendation == "not_suitable" and c.status == "hold" and c.matched_role == ""

    for url in ("/", "/candidates", f"/candidates/{cid}", "/intake", "/roles", "/export.csv",
                f"/candidates/{cid}/audio/reading", f"/candidates?role=INTL-VOICE&rec=not_suitable&q=asha"):
        assert client.get(url, auth=AUTH).status_code == 200, url
    assert "Asha Nair" in client.get("/export.csv", auth=AUTH).text
    assert "wa.me/919123456789" in client.get(f"/candidates/{cid}", auth=AUTH).text
