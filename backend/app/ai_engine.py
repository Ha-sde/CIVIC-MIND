"""
Civic Mind AI engine
====================
Two cooperating layers:

1. LOCAL engine (always on, offline, deterministic, explainable)
   - weighted keyword / phrase classifier over a fixed civic taxonomy (English, Hinglish, Devanagari)
   - rule based severity model (life-safety terms, scale terms, per-sub-category floors)
   - vulnerability detector (school / hospital / transit proximity words)

2. CLAUDE layer (optional, enabled when ANTHROPIC_API_KEY is set)
   - reads complaint text AND up to 2 photos, returns category, severity, title, confidence, reason
   - its output is validated against the taxonomy and blended with the local engine

If Claude is unavailable, slow, or returns garbage, the local result is used. The pipeline never fails
because an external dependency failed.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .config import settings

log = logging.getLogger("civicmind.ai")

# ----------------------------------------------------------------------------- taxonomy
# subs: {name: {"kw": [...], "floor": minimum severity}}
TAXONOMY = {
    "Roads & Transport": {
        "department": "Roads & Public Works", "weight": 0.80, "base": 2,
        "subs": {
            "Pothole": {"floor": 2, "kw": ["pothole", "pot hole", "khadda", "khadde", "gadda", "gaddha", "crater", "hole in road", "hole on road", "road has hole", "खड्डा", "खड्डे", "गड्ढा", "गड्ढे"]},
            "Road Damage": {"floor": 2, "kw": ["road damage", "damaged road", "broken road", "cracked road", "road cracked", "road caved", "road cave", "road sinking", "sinkhole", "uneven road", "bad road", "road repair", "road not repaired", "asphalt", "tar road", "waterbound"]},
            "Broken Divider / Signage": {"floor": 2, "kw": ["divider", "road divider", "median", "signboard", "sign board", "road sign", "zebra crossing", "speed breaker", "barricade", "guard rail", "guardrail", "reflector"]},
            "Traffic Signal Fault": {"floor": 3, "kw": ["traffic signal", "traffic light", "signal not working", "signal is off", "signal off", "signal broken", "signal malfunction"]},
        }},
    "Water Supply": {
        "department": "Water Supply Department", "weight": 0.85, "base": 2,
        "subs": {
            "Water Leakage": {"floor": 2, "kw": ["water leak", "water leakage", "pipe leak", "leaking pipe", "pipeline burst", "burst pipe", "pipe burst", "pipeline leak", "leakage", "water wasting", "water wastage", "paani leak", "गळती", "पाईप फुटला", "पाइप फूटा"]},
            "No Water Supply": {"floor": 3, "kw": ["no water", "water supply", "not getting water", "no water supply", "water not coming", "tap dry", "dry tap", "low pressure", "water shortage", "paani nahi", "पाणी नाही", "पानी नहीं", "पाणीपुरवठा"]},
            "Contaminated Water": {"floor": 4, "kw": ["dirty water", "contaminated water", "muddy water", "smelly water", "water smells", "yellow water", "foul water", "polluted water", "water quality", "दूषित पाणी", "गंदा पानी"]},
        }},
    "Sanitation & Waste": {
        "department": "Sanitation & Solid Waste", "weight": 0.70, "base": 2,
        "subs": {
            "Garbage Not Collected": {"floor": 2, "kw": ["garbage", "trash", "waste", "kachra", "kachara", "not collected", "garbage truck", "dumping", "dumped", "litter", "ghanta gadi", "कचरा", "कचरा गाडी"]},
            "Overflowing Bin": {"floor": 2, "kw": ["overflowing bin", "dustbin", "dust bin", "bin overflow", "overflowing dustbin", "garbage bin", "community bin", "bin is full"]},
            "Dead Animal": {"floor": 3, "kw": ["dead animal", "dead dog", "dead cow", "dead cat", "carcass"]},
            "Public Toilet": {"floor": 2, "kw": ["public toilet", "toilet", "washroom", "urinal", "community toilet", "शौचालय"]},
        }},
    "Drainage & Sewage": {
        "department": "Drainage & Sewerage", "weight": 0.85, "base": 3,
        "subs": {
            "Sewage Overflow": {"floor": 3, "kw": ["sewage", "sewer", "sewage overflow", "overflowing sewer", "sewer overflow", "gutter overflow", "gutter", "drain overflow", "foul smell", "bad smell", "stink", "नाली", "गटार", "गटर"]},
            "Blocked Drain": {"floor": 2, "kw": ["blocked drain", "drain blocked", "clogged drain", "choked drain", "drain choked", "clogged", "choked", "nala", "nullah"]},
            "Waterlogging": {"floor": 3, "kw": ["waterlogging", "water logging", "waterlogged", "flooded road", "flooded street", "water stagnation", "stagnant water", "water accumulation", "rainwater", "पाणी साचले", "जलभराव"]},
            "Open Manhole": {"floor": 4, "kw": ["manhole", "open manhole", "missing manhole cover", "manhole cover", "uncovered manhole", "drain cover", "open drain"]},
        }},
    "Electricity & Lighting": {
        "department": "Electricity & Street Lighting", "weight": 0.90, "base": 3,
        "subs": {
            "Streetlight Not Working": {"floor": 2, "kw": ["streetlight", "street light", "lamp post", "light not working", "lights not working", "light is off", "dark road", "no light", "street lamp", "lamp not working", "बत्ती", "लाइट बंद", "दिवा बंद", "पथदिवे"]},
            "Exposed / Live Wire": {"floor": 4, "kw": ["live wire", "exposed wire", "hanging wire", "loose wire", "wire hanging", "sparking", "sparks", "short circuit", "electric shock", "electrocution", "transformer", "उघडी तार", "तार"]},
            "Power Outage": {"floor": 3, "kw": ["power cut", "power outage", "no electricity", "no power", "blackout", "load shedding", "voltage", "बिजली नहीं", "वीज नाही", "वीज गेली"]},
            "Damaged Pole": {"floor": 3, "kw": ["electric pole", "damaged pole", "leaning pole", "pole fallen", "fallen pole", "broken pole", "tilted pole", "utility pole"]},
        }},
    "Public Safety": {
        "department": "Public Safety & Disaster Management", "weight": 1.00, "base": 3,
        "subs": {
            "Fallen Tree": {"floor": 3, "kw": ["fallen tree", "tree fell", "tree fallen", "tree down", "uprooted", "tree branch", "branch fallen", "dangerous tree", "झाड पडले"]},
            "Unsafe Structure": {"floor": 4, "kw": ["unsafe building", "building collapse", "wall collapse", "collapsed wall", "cracked building", "dangerous building", "dilapidated", "unsafe structure", "leaning building", "balcony collapse", "building tilted"]},
            "Stray Animals": {"floor": 2, "kw": ["stray dog", "stray cattle", "stray cow", "stray animals", "dog bite", "monkey", "bull on road", "cattle on road", "aawara", "आवारा"]},
            "Fire Hazard": {"floor": 4, "kw": ["fire", "fire hazard", "burning", "smoke", "gas leak", "cylinder"]},
        }},
    "Encroachment & Construction": {
        "department": "Town Planning & Encroachment Control", "weight": 0.50, "base": 1,
        "subs": {
            "Illegal Construction": {"floor": 1, "kw": ["illegal construction", "unauthorized construction", "unauthorised construction", "illegal building", "construction without permission", "illegal floor", "unauthorized building", "illegal structure", "अवैध बांधकाम"]},
            "Footpath Encroachment": {"floor": 1, "kw": ["encroachment", "footpath blocked", "footpath encroached", "hawkers", "vendors on footpath", "illegal parking", "blocked footpath", "pavement blocked", "shop on footpath", "अतिक्रमण"]},
            "Illegal Hoarding": {"floor": 1, "kw": ["hoarding", "banner", "illegal banner", "illegal hoarding", "flex board", "flex", "poster", "billboard"]},
        }},
    "Parks & Environment": {
        "department": "Parks, Gardens & Environment", "weight": 0.40, "base": 1,
        "subs": {
            "Damaged Park": {"floor": 1, "kw": ["park", "garden", "playground", "broken bench", "swing broken", "park not maintained", "park maintenance", "jogging track", "fountain"]},
            "Tree Cutting": {"floor": 2, "kw": ["tree cutting", "tree felling", "illegal tree cutting", "trees cut", "cutting trees"]},
            "Pollution": {"floor": 2, "kw": ["air pollution", "noise pollution", "smoke pollution", "burning garbage", "burning waste", "loud speaker", "loudspeaker", "dust pollution", "industrial smoke", "construction dust"]},
        }},
    "Other": {
        "department": "General Administration", "weight": 0.30, "base": 1,
        "subs": {"General Issue": {"floor": 1, "kw": []}}},
}

DEPARTMENTS = sorted({v["department"] for v in TAXONOMY.values()})
CATEGORY_WEIGHT = {k: v["weight"] for k, v in TAXONOMY.items()}

LIFE_SAFETY = ["accident", "injured", "injury", "death", "died", "fatal", "child", "children", "kid", "school", "hospital", "clinic",
               "elderly", "live wire", "exposed wire", "sparking", "electrocut", "shock", "fire", "gas leak", "collapse", "collapsed",
               "flood", "flooded", "sinkhole", "open manhole", "drowning", "drowned", "emergency", "dangerous", "danger", "unsafe", "bleeding"]
SCALE_TERMS = ["weeks", "months", "since", "whole", "entire", "many", "colony", "society", "main road", "highway", "market",
               "residents", "everyone", "daily", "every day", "several", "days"]
VULNERABLE_PLACES = ["school", "hospital", "clinic", "college", "nursery", "daycare", "anganwadi", "bus stand", "bus stop",
                     "railway station", "metro station"]


# ----------------------------------------------------------------------------- compiled patterns
def _compile(kw: str):
    kw = kw.lower().strip()
    if kw.isascii():
        body = r"\s+".join(re.escape(part) for part in kw.split())
        return re.compile(r"(?<![a-z0-9])" + body + r"(?:s|es)?(?![a-z0-9])"), (1.8 if " " in kw else 1.0)
    return re.compile(re.escape(kw)), 1.5


_PATTERNS = {
    (cat, sub): [(*_compile(k), k) for k in spec["kw"]]
    for cat, cdef in TAXONOMY.items() for sub, spec in cdef["subs"].items()
}
_TERM_RX = {t: re.compile(r"(?<![a-z0-9])" + re.escape(t)) for t in set(LIFE_SAFETY + SCALE_TERMS + VULNERABLE_PLACES)}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _terms(text: str, terms) -> list[str]:
    return [t for t in terms if _TERM_RX[t].search(text)]


# ----------------------------------------------------------------------------- result
@dataclass
class AIResult:
    category: str = "Other"
    sub_category: str = "General Issue"
    department: str = "General Administration"
    severity: int = 1
    confidence: float = 0.25
    reason: str = ""
    title: str = ""
    engine: str = "local"
    vulnerability: bool = False
    keywords: list = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.confidence < 0.5

    def as_dict(self) -> dict:
        d = asdict(self)
        d["needs_review"] = self.needs_review
        return d


# ----------------------------------------------------------------------------- local engine
def classify_local(text: str):
    t = _norm(text)
    sub_scores: dict[tuple, tuple[float, list]] = {}
    for key, patterns in _PATTERNS.items():
        score, hits = 0.0, []
        for rx, weight, kw in patterns:
            n = len(rx.findall(t))
            if n:
                score += weight * (1 + 0.25 * (min(n, 4) - 1))
                hits.append(kw)
        if score:
            sub_scores[key] = (score, hits)
    if not sub_scores:
        return "Other", "General Issue", 0.25, []

    cat_scores: dict[str, float] = {}
    best_sub: dict[str, tuple] = {}
    for (cat, sub), (score, hits) in sub_scores.items():
        if cat not in best_sub or score > best_sub[cat][1]:
            best_sub[cat] = (sub, score, hits)
    for cat in best_sub:
        top = best_sub[cat][1]
        rest = sum(s for (c, _), (s, _) in sub_scores.items() if c == cat) - top
        cat_scores[cat] = top + 0.35 * rest

    ranked = sorted(cat_scores.items(), key=lambda kv: kv[1], reverse=True)
    best_cat, s1 = ranked[0]
    s2 = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = max(0.25, min(0.97, s1 / (s1 + s2 + 0.6)))
    sub, _, hits = best_sub[best_cat]
    return best_cat, sub, round(confidence, 2), hits


def severity_local(text: str, category: str, sub: str):
    t = _norm(text)
    base = TAXONOMY[category]["base"]
    floor = TAXONOMY[category]["subs"][sub]["floor"]
    life = _terms(t, LIFE_SAFETY)
    scale = _terms(t, SCALE_TERMS)
    sev = base + min(2, len(life)) + (1 if len(scale) >= 2 else 0)
    sev = max(sev, floor)
    sev = max(1, min(5, sev))
    drivers = []
    if life:
        drivers.append("life-safety terms: " + ", ".join(life[:4]))
    if len(scale) >= 2:
        drivers.append("long-running / wide impact: " + ", ".join(scale[:3]))
    if floor > base:
        drivers.append(f"{sub} has minimum severity {floor}")
    return sev, drivers


def vulnerability_local(text: str) -> list[str]:
    return _terms(_norm(text), VULNERABLE_PLACES)


def _make_title(sub: str, address: str, text: str) -> str:
    where = f" near {address.strip()}" if address and address.strip() else ""
    return f"{sub}{where}"[:90]


def analyze_local(text: str, address: str = "") -> AIResult:
    cat, sub, conf, hits = classify_local(text)
    sev, drivers = severity_local(text, cat, sub)
    vuln = bool(vulnerability_local(text))
    reason_bits = []
    if hits:
        reason_bits.append("matched: " + ", ".join(hits[:5]))
    reason_bits.extend(drivers)
    if vuln:
        reason_bits.append("mentions a school / hospital / transit location")
    if not text.strip():
        reason_bits.append("no description provided - needs officer review")
    return AIResult(
        category=cat, sub_category=sub, department=TAXONOMY[cat]["department"], severity=sev, confidence=conf,
        reason="; ".join(reason_bits) or "no strong signals - needs officer review",
        title=_make_title(sub, address, text), engine="local", vulnerability=vuln, keywords=hits[:8])


# ----------------------------------------------------------------------------- Claude layer
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def load_images(paths: list[Path], limit: int = 2) -> list[tuple[str, str]]:
    out = []
    for p in paths:
        mime = _MIME.get(Path(p).suffix.lower())
        if not mime:
            continue
        try:
            data = Path(p).read_bytes()
        except OSError:
            continue
        if len(data) > 4_500_000:
            continue
        out.append((mime, base64.b64encode(data).decode()))
        if len(out) >= limit:
            break
    return out


def _claude(text: str, address: str, images: list[tuple[str, str]]) -> Optional[dict]:
    if not settings.ANTHROPIC_API_KEY:
        return None
    taxonomy = {c: list(v["subs"].keys()) for c, v in TAXONOMY.items()}
    system = (
        "You triage civic complaints for a city administration. Classify the complaint using ONLY this taxonomy "
        f"(category -> sub_category list): {json.dumps(taxonomy)}. "
        "Severity scale: 1 cosmetic, 2 inconvenience, 3 significant disruption, 4 serious hazard, 5 immediate danger to life. "
        "Judge the photo(s) when present. Respond with ONE JSON object and nothing else: "
        '{"category": str, "sub_category": str, "severity": int 1-5, "confidence": float 0-1, '
        '"title": str (max 80 chars, neutral), "reason": str (max 160 chars, why this category and severity), '
        '"near_vulnerable_place": bool}'
    )
    content = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": b}} for m, b in images]
    content.append({"type": "text", "text": f"Complaint text: {text or '(none)'}\nAddress: {address or '(unknown)'}\nReturn JSON only."})
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": settings.CLAUDE_MODEL, "max_tokens": 450, "system": system, "messages": [{"role": "user", "content": content}]},
            timeout=settings.AI_TIMEOUT)
        r.raise_for_status()
        raw = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        return data if isinstance(data, dict) else None
    except Exception as exc:  # network, quota, parse - never fatal
        log.warning("Claude analysis unavailable, using local engine: %s", exc)
        return None


def analyze(text: str, address: str = "", image_paths: Optional[list[Path]] = None) -> AIResult:
    """Full pipeline: local engine first, then blend with Claude when available."""
    local = analyze_local(text, address)
    images = load_images(image_paths or [])
    if not (text.strip() or images):
        return local
    data = _claude(text, address, images)
    if not data:
        return local

    cat, sub = data.get("category"), data.get("sub_category")
    if cat not in TAXONOMY:
        return local
    if sub not in TAXONOMY[cat]["subs"]:
        sub = next(iter(TAXONOMY[cat]["subs"]))
    try:
        c_sev = max(1, min(5, int(data.get("severity", local.severity))))
        c_conf = max(0.0, min(1.0, float(data.get("confidence", 0.6))))
    except (TypeError, ValueError):
        return local

    agree = (cat == local.category)
    if agree:
        confidence = min(0.99, max(c_conf, local.confidence) + 0.05)
    elif c_conf >= 0.6:
        confidence = c_conf
    else:  # Claude unsure and disagrees: trust the local deterministic result
        return local

    floor = TAXONOMY[cat]["subs"][sub]["floor"]
    severity = max(round(0.6 * c_sev + 0.4 * local.severity), floor)
    severity = max(1, min(5, severity))
    vuln = bool(data.get("near_vulnerable_place")) or local.vulnerability
    reason = str(data.get("reason") or local.reason)[:200]
    reason += " | " + ("local engine agrees" if agree else "local engine suggested " + local.category)
    title = str(data.get("title") or "").strip()[:90] or _make_title(sub, address, text)
    return AIResult(
        category=cat, sub_category=sub, department=TAXONOMY[cat]["department"], severity=severity,
        confidence=round(confidence, 2), reason=reason, title=title,
        engine="claude+local" + ("+vision" if images else ""), vulnerability=vuln, keywords=local.keywords)
