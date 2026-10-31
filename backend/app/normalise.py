"""Suggest merges for typos and variants in category-like fields. Nothing is applied without approval."""

import re
from collections import Counter
from dataclasses import dataclass
from difflib import get_close_matches

FUZZY_CUTOFF = 0.85

CITY_ALIASES = {
    "bangalore": "Bengaluru", "banglore": "Bengaluru", "bangaluru": "Bengaluru", "bengaluru": "Bengaluru",
    "bengalore": "Bengaluru", "blr": "Bengaluru", "bombay": "Mumbai", "madras": "Chennai", "calcutta": "Kolkata",
    "gurgaon": "Gurugram", "poona": "Pune", "trivandrum": "Thiruvananthapuram", "cochin": "Kochi",
    "pan india": "PAN India", "anywhere in india": "PAN India", "remote": "Remote", "wfh": "Remote",
    "work from home": "Remote", "usa": "US", "united states": "US", "u.s.": "US", "uk": "UK",
}

KNOWN_CITIES = [
    "Bengaluru", "Chennai", "Hyderabad", "Mumbai", "Pune", "Delhi", "New Delhi", "Gurugram", "Noida", "Kolkata",
    "Coimbatore", "Kochi", "Ahmedabad", "Jaipur", "Chandigarh", "Thiruvananthapuram", "Mysuru", "Indore",
    "PAN India", "Remote", "US", "UK", "Singapore", "Dubai", "London", "Berlin", "Amsterdam", "Toronto",
]

SOURCE_ALIASES = {
    "company website": "Company Site", "company site": "Company Site", "career site": "Company Site",
    "careers site": "Company Site", "careers page": "Company Site", "career page": "Company Site",
    "linkedin": "LinkedIn", "linked in": "LinkedIn", "linkedin easy apply": "LinkedIn",
    "naukri.com": "Naukri", "naukri": "Naukri", "referral": "Referral", "referred": "Referral",
    "employee referral": "Referral", "email": "Email", "e-mail": "Email", "mail": "Email",
    "recruiter": "Recruiter Call", "recruiter call": "Recruiter Call",
}

WORK_MODE_ALIASES = {
    "onsite": "Onsite", "on-site": "Onsite", "on site": "Onsite", "office": "Onsite", "in office": "Onsite",
    "wfo": "Onsite", "hybrid": "Hybrid", "remote": "Remote", "wfh": "Remote", "work from home": "Remote",
    "fully remote": "Remote",
}

STATUS_ALIASES = {
    "interviewing": "Screening", "interview": "Screening", "phone screen": "Screening", "hr round": "Screening",
    "hr screening": "Screening", "technical round": "First Round", "round 1": "First Round",
    "round 2": "Second Round", "final": "Final Round", "offered": "Offer", "offer received": "Offer",
    "offer accepted": "Accepted", "joined": "Accepted", "declined": "Withdrawn", "withdrew": "Withdrawn",
    "no response": "Ghosted", "not selected": "Rejected", "position filled": "Rejected", "rejection": "Rejected",
    "to apply": "Wishlist", "target": "Wishlist", "wishlist": "Wishlist", "submitted": "Applied",
}

# Fields that get merge suggestions, and the canonical vocabulary each starts from.
NORMALISED_FIELDS = ("source", "location", "work_mode", "company")


@dataclass
class Suggestion:
    field: str
    source: str  # value as found
    target: str  # suggested value
    count: int
    reason: str  # "alias" | "case" | "typo"

    @property
    def key(self) -> str:
        return f"{self.field}|{self.source}"


def _k(s: str) -> str:
    return " ".join(s.lower().split())


def _match(value: str, aliases: dict[str, str], canonical: list[str], fuzzy: bool = True) -> tuple[str, str] | None:
    """Return (target, reason) for a value, or None when it is already canonical / unknown."""
    key = _k(value)
    if key in aliases:
        target = aliases[key]
        if target != value:
            return target, "case" if _k(target) == key else "alias"
        return None
    by_key = {_k(c): c for c in canonical}
    if key in by_key:
        return (by_key[key], "case") if by_key[key] != value else None
    if fuzzy:
        close = get_close_matches(key, list(by_key), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return by_key[close[0]], "typo"
    return None


def _split_places(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,/;|]", value) if p.strip()]


def suggest(values: dict[str, Counter], vocab: dict[str, list[str]]) -> list[Suggestion]:
    """values: field -> Counter of values seen in the import.
    vocab: field -> extra canonical values (settings lists, values already in the database)."""
    out: list[Suggestion] = []
    for field in NORMALISED_FIELDS:
        counts = values.get(field, Counter())
        if field == "company":
            out += _suggest_company(counts, vocab.get("company", []))
            continue
        aliases = {"source": SOURCE_ALIASES, "work_mode": WORK_MODE_ALIASES, "location": CITY_ALIASES}[field]
        base = list(vocab.get(field, []))
        if field == "location":
            base += KNOWN_CITIES
        for value, count in counts.items():
            if field == "location":
                # Normalise each place in multi-city values ("Banglore, Chennai").
                parts = _split_places(value)
                fixed, reasons = [], set()
                for p in parts:
                    m = _match(p, aliases, base)
                    fixed.append(m[0] if m else p)
                    if m:
                        reasons.add(m[1])
                target = ", ".join(dict.fromkeys(fixed))
                if target != value and (reasons or ", ".join(parts) != value):
                    out.append(Suggestion(field, value, target, count, _strongest(reasons or {"case"})))
                continue
            # Other values that appear more often are candidates too, so rare typos merge into the common spelling.
            peers = [v for v, c in counts.items() if v != value and (c, v) > (count, value)]
            m = _match(value, aliases, base + peers)
            if m:
                out.append(Suggestion(field, value, m[0], count, m[1]))
    return out


def clean_vocab(field: str, values: list[str], base: list[str]) -> list[str]:
    """Existing database values that are themselves variants/typos of a canonical value must not
    become canonical (e.g. an old 'Copmay Site' record would otherwise hide the suggestion)."""
    aliases = {"source": SOURCE_ALIASES, "work_mode": WORK_MODE_ALIASES, "location": CITY_ALIASES}.get(field, {})
    if field == "location":
        base = base + KNOWN_CITIES
    return [v for v in dict.fromkeys(values) if not _match(v, aliases, base)]


def _suggest_company(counts: Counter, existing: list[str]) -> list[Suggestion]:
    """Company names only merge on case/spacing differences: fuzzy matching would merge distinct companies."""
    groups: dict[str, list[tuple[int, str]]] = {}
    for v, c in counts.items():
        groups.setdefault(_k(v), []).append((c, v))
    by_key = {_k(e): e for e in existing}
    out = []
    for key, members in groups.items():
        canonical = by_key.get(key) or max(members)[1]
        out += [Suggestion("company", v, canonical, c, "case") for c, v in members if v != canonical]
    return out


def _strongest(reasons: set[str]) -> str:
    for r in ("typo", "alias", "case"):
        if r in reasons:
            return r
    return "case"


def match_status(value: str, statuses: list[str]) -> tuple[str | None, str | None]:
    """Map a raw status to a configured one. Returns (status, reason); reason is None for exact/case matches."""
    key = _k(value)
    by_key = {_k(s): s for s in statuses}
    if key in by_key:
        return by_key[key], None
    if key in STATUS_ALIASES and STATUS_ALIASES[key] in statuses:
        return STATUS_ALIASES[key], "alias"
    close = get_close_matches(key, list(by_key), n=1, cutoff=0.8)
    if close:
        return by_key[close[0]], "typo"
    return None, None


def match_work_mode(value: str) -> str | None:
    return WORK_MODE_ALIASES.get(_k(value))
