"""Grammar checking: LanguageTool if it is running, simple rules otherwise."""
import os
import re

import httpx

LT_URL = os.getenv("LANGUAGETOOL_URL", "").rstrip("/")
SMS_WORDS = r"\b(u|ur|pls|plz|thx|tnx|gud|bcoz|bcz|coz|wat|dat|dis|msg|abt|tmrw|k|ok+k|r|y|n|wud|cud|shud|im|dont|cant|wont|didnt|isnt)\b"
IGNORED_RULES = {"WHITESPACE_RULE", "UPPERCASE_SENTENCE_START_AFTER_NEWLINE"}


def _fallback(text: str) -> tuple[int, list[str]]:
    issues = []
    for m in re.finditer(SMS_WORDS, text):
        issues.append(f"informal '{m.group(0)}'")
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if s and s[0].isalpha() and s[0].islower():
            issues.append(f"no capital: '{s[:20]}'")
    issues += ["lowercase 'i'"] * len(re.findall(r"(?<![A-Za-z])i(?![A-Za-z])", text))
    issues += ["repeated punctuation"] * len(re.findall(r"[!?]{2,}|\.{4,}", text))
    issues += ["missing space after punctuation"] * len(re.findall(r"[,.!?][A-Za-z]{2,}", text))
    return len(issues), issues[:8]


def check(text: str) -> dict:
    """Return {'errors': n, 'examples': [...], 'engine': 'languagetool'|'basic'}."""
    text = (text or "").strip()
    if not text:
        return {"errors": 0, "examples": [], "engine": "none"}
    if LT_URL:
        try:
            r = httpx.post(f"{LT_URL}/v2/check", data={"language": "en-US", "text": text}, timeout=20)
            r.raise_for_status()
            matches = [m for m in r.json().get("matches", []) if m["rule"]["id"] not in IGNORED_RULES]
            ex = [f"{m['rule'].get('issueType', 'issue')}: {m['message'][:70]}" for m in matches[:8]]
            return {"errors": len(matches), "examples": ex, "engine": "languagetool"}
        except Exception:
            pass
    n, ex = _fallback(text)
    return {"errors": n, "examples": ex, "engine": "basic"}


def score(text: str, zero_at: float = 12.0) -> tuple[float, dict]:
    """0-100 score from errors per 100 words (0 errors = 100, `zero_at` errors = 0)."""
    words = max(1, len(re.findall(r"[A-Za-z']+", text or "")))
    res = check(text)
    per100 = res["errors"] * 100 / words
    res["per_100_words"] = round(per100, 1)
    return round(max(0.0, 100 - per100 * 100 / zero_at), 1), res
