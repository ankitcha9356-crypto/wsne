"""Turn resumes and Naukri exports into plain candidate fields."""
import csv
import re
from pathlib import Path

CITIES = [
    "hyderabad", "bengaluru", "bangalore", "chennai", "mumbai", "pune", "delhi", "new delhi",
    "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad", "jaipur", "chandigarh", "mohali",
    "indore", "coimbatore", "kochi", "lucknow", "nagpur", "vizag", "visakhapatnam", "bhubaneswar",
    "mysore", "mysuru", "thane", "navi mumbai", "vadodara", "surat", "bhopal", "patna",
]
EDUCATION = [
    ("postgraduate", r"\b(mba|pgdm|m\.?\s?tech|m\.?\s?sc|m\.?\s?com|m\.?\s?a\b|mca|post\s?graduat\w*|master'?s?)"),
    ("graduate", r"\b(b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|b\.?\s?com|b\.?\s?a\b|bba|bca|bbm|graduat\w*|bachelor'?s?|degree)"),
    ("diploma", r"\bdiploma\b"),
    ("12th", r"\b(12th|hsc|intermediate|higher secondary|xii|\+2)\b"),
    ("10th", r"\b(10th|ssc|sslc|matriculation)\b"),
]
EDU_RANK = {"": 0, "10th": 1, "12th": 2, "diploma": 3, "graduate": 4, "postgraduate": 5}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+?91[\s-]?|\b0)?([6-9]\d{4}[\s-]?\d{5})\b")


def extract_text(path: str | Path) -> str:
    """Read text out of a PDF, DOCX or TXT resume. Returns '' if unreadable."""
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        if ext == ".docx":
            import docx

            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)
        if ext in (".txt", ".md"):
            return path.read_text(errors="ignore")
    except Exception:
        return ""
    return ""


def clean_phone(raw: str) -> str:
    m = PHONE_RE.search(str(raw or ""))
    return re.sub(r"\D", "", m.group(1)) if m else ""


def parse_experience(raw) -> float | None:
    """'3 Year(s) 6 Month(s)', '3.5 yrs', '4+ years', 'Fresher' -> years."""
    if raw is None:
        return None
    s = str(raw).lower().strip()
    if not s:
        return None
    if "fresher" in s:
        return 0.0
    y = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:year|yr)", s)
    m = re.search(r"(\d+)\s*month", s)
    if y or m:
        years = float(y.group(1)) if y else 0.0
        if m and (not y or "." not in y.group(1)):
            years += int(m.group(1)) / 12
        return round(years, 1)
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    return None


def parse_notice(raw) -> int | None:
    """'15 Days or less', '1 Month', 'Immediate', 'Serving notice period' -> days."""
    if raw is None:
        return None
    s = str(raw).lower().strip()
    if not s:
        return None
    if "immediate" in s or "currently serving" in s or "serving notice" in s:
        return 0
    m = re.search(r"(\d+)\s*(day|week|month)", s)
    if m:
        n = int(m.group(1))
        return n * {"day": 1, "week": 7, "month": 30}[m.group(2)]
    if re.fullmatch(r"\d+", s):
        return int(s)
    return None


def parse_ctc(raw) -> float | None:
    """'INR 3,50,000', '3.5 Lacs', '3.5 LPA', 350000 -> lakhs per annum."""
    if raw is None:
        return None
    s = str(raw).lower().replace(",", "").strip()
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    n = float(m.group(1))
    if re.search(r"lac|lakh|lpa", s):
        return round(n, 2)
    if n >= 10000:
        return round(n / 100000, 2)
    return round(n, 2)


def detect_education(text: str) -> str:
    low = text.lower()
    for label, pat in EDUCATION:
        if re.search(pat, low):
            return label
    return ""


def detect_location(text: str) -> str:
    low = text.lower()
    for c in CITIES:
        if re.search(rf"\b{re.escape(c)}\b", low):
            return c.title()
    return ""


def guess_name(text: str) -> str:
    for line in text.splitlines()[:12]:
        line = line.strip()
        if not line or "@" in line or re.search(r"\d", line):
            continue
        if re.search(r"resume|curriculum|vitae|profile|objective|summary", line, re.I):
            continue
        words = line.split()
        if 1 < len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'-]+", w) for w in words):
            return line.title()
    return ""


def parse_resume(text: str) -> dict:
    """Best-effort field extraction from resume text. Missing fields stay empty/None."""
    out = {"name": guess_name(text), "email": "", "phone": "", "location": detect_location(text),
           "education": detect_education(text), "experience_years": None, "notice_days": None,
           "ctc_lpa": None, "skills": ""}
    m = EMAIL_RE.search(text)
    if m:
        out["email"] = m.group(0).lower()
    out["phone"] = clean_phone(text)
    low = text.lower()
    if re.search(r"\bfresher\b", low):
        out["experience_years"] = 0.0
    yrs = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", low)]
    yrs = [y for y in yrs if y <= 40]
    if yrs:
        out["experience_years"] = max(yrs)
    n = re.search(r"notice\s*period\s*[:\-]?\s*([^\n]{0,30})", low)
    if n:
        out["notice_days"] = parse_notice(n.group(1))
    elif "immediate joiner" in low:
        out["notice_days"] = 0
    s = re.search(r"(?:key\s+)?skills?\s*[:\-]\s*([^\n]{3,300})", text, re.I)
    if s:
        out["skills"] = s.group(1).strip()
    return out


# ---- Naukri / spreadsheet import -------------------------------------------------

HEADER_MAP = {
    "name": ["candidate name", "name", "applicant name", "full name"],
    "email": ["email id", "email", "e-mail", "email address"],
    "phone": ["phone number", "mobile", "mobile no", "contact no", "phone", "contact number"],
    "location": ["current location", "location", "city"],
    "experience_years": ["total experience", "experience", "work experience", "exp"],
    "ctc_lpa": ["annual salary", "current ctc", "ctc", "salary", "curr. annual salary"],
    "notice_days": ["notice period", "notice period/ availability to join", "availability to join"],
    "education": ["ug degree", "education", "highest qualification", "qualification", "degree"],
    "skills": ["key skills", "skills", "resume headline"],
}


def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().rstrip(".:"))


def map_headers(headers: list) -> dict:
    """column index -> field name, matching exact names first then partial ones."""
    normed = [_norm(h) for h in headers]
    mapping: dict[int, str] = {}
    for field, names in HEADER_MAP.items():
        idx = next((i for n in names for i, h in enumerate(normed) if h == n and i not in mapping), None)
        if idx is None:
            idx = next((i for n in names for i, h in enumerate(normed)
                        if h and n in h and i not in mapping), None)
        if idx is not None:
            mapping[idx] = field
    return mapping


def read_rows(path: str | Path) -> list[list]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
            return [r for r in csv.reader(f)]
    from openpyxl import load_workbook

    ws = load_workbook(str(path), read_only=True, data_only=True).active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def parse_sheet(path: str | Path) -> tuple[list[dict], list[str]]:
    """Read a Naukri-style export (.xlsx or .csv). Returns (candidates, unmatched_fields)."""
    rows = read_rows(path)
    header_i, mapping = 0, {}
    for i, row in enumerate(rows[:15]):  # exports sometimes start with title rows
        m = map_headers(row)
        if len(m) > len(mapping):
            header_i, mapping = i, m
    found = set(mapping.values())
    if not ({"name", "email", "phone"} & found):
        return [], sorted(HEADER_MAP)
    out = []
    for row in rows[header_i + 1:]:
        rec = {mapping[i]: row[i] for i in mapping if i < len(row) and row[i] not in (None, "")}
        if not rec:
            continue
        cand = {
            "name": str(rec.get("name", "")).strip().title(),
            "email": str(rec.get("email", "")).strip().lower(),
            "phone": clean_phone(rec.get("phone", "")),
            "location": str(rec.get("location", "")).strip().title(),
            "education": detect_education(str(rec.get("education", ""))) or str(rec.get("education", "")).strip()[:60],
            "skills": str(rec.get("skills", "")).strip(),
            "experience_years": parse_experience(rec.get("experience_years")),
            "notice_days": parse_notice(rec.get("notice_days")),
            "ctc_lpa": parse_ctc(rec.get("ctc_lpa")),
        }
        if cand["name"] or cand["email"] or cand["phone"]:
            out.append(cand)
    return out, sorted(set(HEADER_MAP) - found)
