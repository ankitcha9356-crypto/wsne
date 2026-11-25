"""All scoring rules: resume fit, knockouts, chat, voice and the role line-up."""
import math
import os
import re
from collections import Counter
from pathlib import Path

import yaml

from . import grammar
from .parsing import EDU_RANK

ROLES_DIR = Path(os.getenv("ROLES_DIR", Path(__file__).resolve().parent.parent / "roles"))
STOP = set("a an and are as at be by for from has have in is it of on or that the to was were will with "
           "you your we our i my this their they he she them his her not but can should must".split())
FILLERS = r"\b(um+|uh+|er+|erm+|hmm+|you know|i mean|basically|actually|like i said)\b"
EMPATHY = r"\b(sorry|apologi[sz]e|apolog(?:y|ies)|understand|inconvenience|appreciate|thank|frustrat\w*|regret)\b"
GREETING = r"\b(hi|hello|dear|good (?:morning|afternoon|evening)|greetings)\b"
CLOSING = r"(regards|thank you|thanks|anything else|have a (?:great|nice|good)|happy to help|feel free)"
TYPING_TARGET_WPM = 35


def load_roles() -> dict[str, dict]:
    roles = {}
    for f in sorted(ROLES_DIR.glob("*.yaml")):
        r = yaml.safe_load(f.read_text())
        roles[r["code"]] = r
    return roles


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z+#.]*", (text or "").lower()) if t not in STOP and len(t) > 1]


def cosine(a: str, b: str) -> float:
    ca, cb = Counter(tokens(a)), Counter(tokens(b))
    dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
    na, nb = math.sqrt(sum(v * v for v in ca.values())), math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    """Each keyword may hold alternatives split by '|', e.g. 'bpo|call center'."""
    low = (text or "").lower()
    return [k for k in keywords if any(re.search(rf"(?<![a-z]){re.escape(alt.strip())}(?![a-z])", low)
                                       for alt in k.split("|"))]


# ---- resume ----------------------------------------------------------------------

def resume_score(role: dict, text: str) -> tuple[float, dict]:
    cfg = role.get("resume", {})
    must, good = cfg.get("must_have_keywords", []), cfg.get("good_to_have_keywords", [])
    mh, gh = keyword_hits(text, must), keyword_hits(text, good)
    must_pct = len(mh) / len(must) if must else 1.0
    good_pct = len(gh) / len(good) if good else 1.0
    sim = min(1.0, cosine(text, role.get("job_description", "")) / 0.35)
    score = 100 * (0.5 * must_pct + 0.2 * good_pct + 0.3 * sim)
    return round(score, 1), {"must_hit": mh, "must_missing": [k for k in must if k not in mh],
                             "good_hit": gh, "jd_similarity": round(sim, 2)}


def knockouts(role: dict, c) -> tuple[list[str], list[str]]:
    """Returns (failed rules, facts we could not check). Unknown data never rejects anyone."""
    k = role.get("knockouts", {})
    failed, unknown = [], []

    def need(value, label):
        if value in (None, ""):
            unknown.append(label)
            return False
        return True

    if "min_experience_years" in k and need(c.experience_years, "experience"):
        if c.experience_years < k["min_experience_years"]:
            failed.append(f"experience {c.experience_years}y < {k['min_experience_years']}y")
    if "max_experience_years" in k and c.experience_years is not None:
        if c.experience_years > k["max_experience_years"]:
            failed.append(f"experience {c.experience_years}y > {k['max_experience_years']}y")
    if "max_notice_days" in k and need(c.notice_days, "notice period"):
        if c.notice_days > k["max_notice_days"]:
            failed.append(f"notice {c.notice_days}d > {k['max_notice_days']}d")
    if "max_ctc_lpa" in k and need(c.ctc_lpa, "current salary"):
        if c.ctc_lpa > k["max_ctc_lpa"]:
            failed.append(f"salary {c.ctc_lpa} LPA > {k['max_ctc_lpa']} LPA")
    if k.get("locations") and need(c.location, "location"):
        if not any(loc.lower() in c.location.lower() for loc in k["locations"]):
            failed.append(f"location {c.location} not in {', '.join(k['locations'])}")
    if k.get("min_education") and need(c.education, "education"):
        have = EDU_RANK.get(c.education, None)
        if have is None:
            unknown.append("education")
        elif have < EDU_RANK[k["min_education"]]:
            failed.append(f"education {c.education} below {k['min_education']}")
    return failed, unknown


# ---- chat ------------------------------------------------------------------------

def levenshtein(a, b) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def typing_result(target: str, typed: str, seconds: float) -> tuple[float, float]:
    """(words per minute, accuracy 0-1). A 'word' is 5 characters, the usual convention."""
    typed = (typed or "").strip()
    if not typed or seconds <= 0:
        return 0.0, 0.0
    ref = target.strip()[: len(typed)]
    acc = max(0.0, 1 - levenshtein(typed, ref) / max(len(typed), len(ref), 1))
    wpm = (len(typed) / 5) / (seconds / 60)
    return round(wpm, 1), round(acc, 3)


def chat_reply_score(scenario: dict, reply: str) -> dict:
    reply = (reply or "").strip()
    words = len(re.findall(r"[A-Za-z']+", reply))
    if words < 5:
        return {"score": 0.0, "words": words, "note": "no meaningful reply"}
    g, gd = grammar.score(reply)
    empathy = min(1.0, len(set(m.lower() for m in re.findall(EMPATHY, reply, re.I))) / 2) * 100
    expects = scenario.get("expects", [])
    hit = keyword_hits(reply, expects)
    resolution = 100 * len(hit) / len(expects) if expects else 100.0
    structure = 100 * (bool(re.search(GREETING, reply, re.I)) + bool(re.search(CLOSING, reply, re.I))
                       + (words >= 40)) / 3
    total = 0.40 * g + 0.20 * empathy + 0.25 * resolution + 0.15 * structure
    return {"score": round(total, 1), "words": words, "grammar": g, "grammar_engine": gd["engine"],
            "grammar_examples": gd["examples"], "empathy": round(empathy), "resolution": round(resolution),
            "resolution_missing": [e for e in expects if e not in hit], "structure": round(structure)}


def chat_total(typing_wpm: float | None, typing_acc: float | None, replies: list[dict]) -> float | None:
    if not replies:
        return None
    written = sum(r["score"] for r in replies) / len(replies)
    if typing_wpm is None:
        return round(written, 1)
    typing = min(100.0, typing_wpm / TYPING_TARGET_WPM * 100) * (typing_acc or 0)
    return round(0.7 * written + 0.3 * typing, 1)


# ---- voice -----------------------------------------------------------------------

def word_error_rate(reference: str, said: str) -> float:
    ref = re.findall(r"[a-z']+", reference.lower())
    hyp = re.findall(r"[a-z']+", said.lower())
    if not ref:
        return 0.0
    return min(1.0, levenshtein(ref, hyp) / len(ref))


def _ramp(x, zero_lo, full_lo, full_hi, zero_hi) -> float:
    """100 inside [full_lo, full_hi], falling in a straight line to 0 at the outer limits."""
    if full_lo <= x <= full_hi:
        return 100.0
    if x < full_lo:
        return max(0.0, 100 * (x - zero_lo) / (full_lo - zero_lo))
    return max(0.0, 100 * (zero_hi - x) / (zero_hi - full_hi))


def clip_metrics(transcript: dict) -> dict:
    """transcript = {'text': str, 'segments': [{'start','end','text'}]}"""
    segs = transcript.get("segments") or []
    text = transcript.get("text", "")
    words = len(re.findall(r"[A-Za-z']+", text))
    if not segs or not words:
        return {"words": words, "wpm": 0.0, "pause_ratio": 0.0, "fillers": 0, "duration": 0.0}
    dur = max(0.1, segs[-1]["end"] - segs[0]["start"])
    gaps = sum(max(0.0, b["start"] - a["end"]) for a, b in zip(segs, segs[1:])
               if b["start"] - a["end"] > 1.0)
    return {"words": words, "wpm": round(words / dur * 60, 1), "pause_ratio": round(gaps / dur, 3),
            "fillers": len(re.findall(FILLERS, text.lower())), "duration": round(dur, 1)}


def voice_auto(passage: str, reading: dict | None, answer: dict | None) -> tuple[float | None, dict]:
    """Automatic part of the voice score. Returns (None, ...) until both clips are transcribed."""
    if not reading or not answer:
        return None, {}
    rm, am = clip_metrics(reading), clip_metrics(answer)
    accuracy = 100 * (1 - word_error_rate(passage, reading.get("text", "")))
    pace = (_ramp(rm["wpm"], 60, 110, 170, 230) + _ramp(am["wpm"], 60, 100, 170, 230)) / 2
    words = max(1, rm["words"] + am["words"])
    fillers = max(0.0, 100 - (rm["fillers"] + am["fillers"]) * 100 / words * 12.5)  # 8 per 100 words = 0
    # long silences: 5% of the clip or less = 100, 35% or more = 0
    pauses = max(0.0, min(100.0, 100 * (0.35 - (rm["pause_ratio"] + am["pause_ratio"]) / 2) / 0.30))
    g, gd = grammar.score(answer.get("text", ""), zero_at=15)
    length = min(100.0, am["words"] / 60 * 100)
    total = 0.30 * accuracy + 0.20 * pace + 0.10 * fillers + 0.10 * pauses + 0.20 * g + 0.10 * length
    return round(total, 1), {"reading_accuracy": round(accuracy), "pace": round(pace), "fillers": round(fillers),
                             "pauses": round(pauses), "grammar": g, "grammar_engine": gd["engine"],
                             "answer_length": round(length), "reading": rm, "answer": am}


def voice_total(auto: float | None, human: dict | None) -> float | None:
    """Final voice score is half machine, half recruiter (clarity, tone, accent neutrality, 1-5 each)."""
    if auto is None:
        return None
    if not human:
        return None
    h = (human["clarity"] + human["tone"] + human["neutrality"]) / 3 * 20
    return round(0.5 * auto + 0.5 * h, 1)


# ---- line-up ---------------------------------------------------------------------

def lineup(roles: dict, c, resume_scores: dict[str, float]) -> dict:
    """Score the candidate against every open role and pick the best fit."""
    parts_all = {"voice": c.voice_score, "chat": c.chat_score}
    result = {}
    for code, role in roles.items():
        failed, unknown = knockouts(role, c)
        parts = dict(parts_all, resume=resume_scores.get(code))
        weights = {k: v for k, v in role.get("weights", {}).items() if v}
        missing = [k for k in weights if parts.get(k) is None]
        have = {k: w for k, w in weights.items() if parts.get(k) is not None}
        overall = (sum(parts[k] * w for k, w in have.items()) / sum(have.values())) if have else None
        reasons = list(failed)
        mins = role.get("minimums", {})
        for k in ("voice", "chat", "resume"):
            if k in mins and parts.get(k) is not None and parts[k] < mins[k]:
                reasons.append(f"{k} {parts[k]:.0f} < {mins[k]}")
        if "typing_wpm" in mins and c.typing_wpm is not None and c.typing_wpm < mins["typing_wpm"]:
            reasons.append(f"typing {c.typing_wpm:.0f} wpm < {mins['typing_wpm']}")
        if "typing_wpm" in mins and c.typing_wpm is None and "chat" not in missing:
            missing.append("typing")
        if not missing and overall is not None and "overall" in mins and overall < mins["overall"]:
            reasons.append(f"overall {overall:.0f} < {mins['overall']}")
        state = "not_suitable" if reasons else ("pending" if missing else "shortlist")
        result[code] = {"overall": None if overall is None else round(overall, 1), "state": state,
                        "reasons": reasons, "waiting_for": missing, "unknown": unknown,
                        "resume": resume_scores.get(code)}
    return result


def pick(lineup_result: dict, applied_role: str = "") -> tuple[str, str, str, float | None]:
    """(matched role, second choice, recommendation, overall).

    The role the candidate applied for wins whenever they qualify for it; otherwise the
    highest-scoring role they do qualify for. The same order is used for 'pending'.
    """
    def ranked(state):
        rows = [(code == applied_role, v["overall"] or 0, code) for code, v in lineup_result.items()
                if v["state"] == state]
        return [code for _, _, code in sorted(rows, reverse=True)]

    ready, waiting = ranked("shortlist"), ranked("pending")
    order = ready + waiting
    if order:
        first = order[0]
        second = order[1] if len(order) > 1 else ""
        return first, second, lineup_result[first]["state"], lineup_result[first]["overall"]
    best = max(lineup_result.items(), key=lambda kv: kv[1]["overall"] or 0, default=("", {"overall": None}))
    return "", "", "not_suitable", best[1]["overall"]
