"""
recognition.py
----------------
OCR + intelligenter Parser fuer Grading-Slab-Labels (CGC/PSA/BGS/...).

Der Parser kennt den typischen Label-Aufbau:
    [Firma/Logo]  CGC CERTIFIED GUARANTY COMPANY
    [Kartenname]  Mega Gengar ex
    [Grade-Text]  GEM MINT
    [Info]        Pokemon (2026) German
    [Note]        10
    [Set+Nummer]  Ascended Heroes - 125/217
    [Zertifikat]  6147877154

Attacken-/Regeltext der Karte selbst wird ignoriert (Name/Note werden nur
im oberen Label-Bereich gesucht, HP-/Schadenszahlen herausgefiltert).
"""

import re
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np

GRADING_KEYWORDS = {
    "CGC": ["CGC", "GUARANTY"],
    "PSA": ["PSA", "PROFESSIONAL SPORTS AUTHENTICATOR"],
    "BGS": ["BGS", "BECKETT"],
    "SGC": ["SGC"],
    "ACE": ["ACE GRADING", "ACE "],
}

NOISE_WORDS = [
    "CERTIFIED", "GUARANTY", "COMPANY", "GEM", "MINT", "PRISTINE",
    "AUTHENTIC", "HOLO", "REVERSE", "GRADED", "PHASE",
]

SET_NUMBER_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z ]{2,40}?)\s*[-–]\s*(\d{1,3})\s*/\s*(\d{1,3})"
)
FRACTION_PATTERN = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
YEAR_PATTERN = re.compile(r"\((20\d{2})\)")
CERT_PATTERN = re.compile(r"\b(\d{7,12})\b")
GRADE_TOKEN_PATTERN = re.compile(r"^(10|[1-9](?:\.5)?)$")

_rapidocr_engine = None


@dataclass
class RecognitionResult:
    raw_text: str = ""
    guessed_name: str = ""
    card_number: Optional[str] = None      # z.B. "125/217"
    set_name: Optional[str] = None         # z.B. "Ascended Heroes"
    set_code: Optional[str] = None         # z.B. "s10b" (japanische Sets)
    year: Optional[str] = None
    grading_company: Optional[str] = None
    grade: Optional[str] = None
    cert_number: Optional[str] = None
    search_query: str = ""                 # fertiger pricecharting-Suchbegriff
    engine_used: Optional[str] = None
    error: Optional[str] = None
    debug_info: str = ""


# ---------------- OCR-Engines ----------------

def _ocr_via_rapidocr(pil_image):
    global _rapidocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None, "RapidOCR nicht installiert"
    try:
        if _rapidocr_engine is None:
            _rapidocr_engine = RapidOCR()
        result, _ = _rapidocr_engine(np.array(pil_image.convert("RGB")))
        if not result:
            return None, "RapidOCR: kein Text erkannt"
        text = "\n".join(item[1] for item in result)
        return (text if text.strip() else None), "RapidOCR ok"
    except Exception as exc:
        return None, f"RapidOCR-Fehler: {exc}"


def _ocr_via_winocr(pil_image):
    if sys.platform != "win32":
        return None, "winocr: nicht unter Windows"
    try:
        import winocr
    except ImportError:
        return None, "winocr nicht installiert"
    for lang in ("de-DE", "en-US"):
        try:
            result = winocr.recognize_pil_sync(pil_image, lang=lang)
            if result and result.text and result.text.strip():
                return result.text, f"winocr ok ({lang})"
        except Exception:
            continue
    return None, "winocr: kein Sprachpaket nutzbar"


def _ocr_via_tesseract(pil_image):
    try:
        import pytesseract
    except ImportError:
        return None, "pytesseract nicht installiert"
    try:
        text = pytesseract.image_to_string(pil_image, lang="eng")
        return (text if text.strip() else None), "Tesseract ok"
    except Exception as exc:
        return None, f"Tesseract-Fehler: {exc}"


# ---------------- Parser (generisch fuer alle Grading-Firmen) ----------------

KNOWN_COMPANIES = {
    "PSA": ["PSA", "PROFESSIONAL SPORTS"],
    "CGC": ["CGC", "GUARANTY"],
    "BGS": ["BGS", "BECKETT"],
    "SGC": ["SGC"],
    "ACE": ["ACE GRADING"],
    "RGS": ["RGS", "RUBIN"],
    "TAG": ["TAG GRADING"],
    "AGS": ["AGS"],
}
SUBGRADE_LABELS = ["CENTERING", "CORNERS", "EDGES", "SURFACE"]
# PSA-Notenskala: GEM MT 10, MINT 9, NM-MT 8, NM 7, EX-MT 6, EX 5, VG-EX 4 ...
GRADE_WORDS = [
    "GEM MINT", "GEMMINT", "GEM MT", "GEMMT", "PRISTINE", "BLACK LABEL",
    "NM-MT", "NMMT", "NM MT", "EX-MT", "EXMT", "VG-EX", "VGEX",
    "MINT", "NM", "EX", "VG",
]
# Text-Note -> Zahl (falls die Ziffer selbst nicht gelesen wurde)
GRADE_WORD_TO_NUM = {
    "GEM MINT": "10", "GEMMINT": "10", "GEM MT": "10", "GEMMT": "10",
    "PRISTINE": "10", "BLACK LABEL": "10",
    "MINT": "9", "NM-MT": "8", "NMMT": "8", "NM MT": "8",
    "NM": "7", "EX-MT": "6", "EXMT": "6", "EX": "5", "VG-EX": "4", "VGEX": "4",
}
NOISE = SUBGRADE_LABELS + [
    "GRADING", "SERVICE", "COMPANY", "CERTIFIED", "GUARANTY", "AUTHENTIC",
    "HOLO", "ILLUS", "POKEMON", "NINTENDO", "CREATURES", "GAMEFREAK",
    "NIANTIC", "PHASE", "REVERSE",
]

NUM_RE = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?![\d/])")
SETCODE_RE = re.compile(r"\b([sS][vV]?\d{1,2}[a-zA-Z]?)\b")
SETNAME_RE = re.compile(r"([A-Za-z][A-Za-z ]{2,40}?)\s*[-\u2013]\s*\d{1,3}\s*/\s*\d{1,3}")
YEAR_RE = re.compile(r"(20\d{2})")
CERT_RE = re.compile(r"\b(\d{7,12})\b")


def _strip_subgrades(text: str) -> str:
    """Entfernt 'EDGES 9.5' etc., damit Subgrades nicht als Note gelesen werden."""
    out = text
    for lbl in SUBGRADE_LABELS:
        out = re.sub(lbl + r"\s*:?\s*(10|[1-9](?:\.5)?)", " ", out, flags=re.I)
    return out


def _detect_company(upper_text: str):
    for comp, kws in KNOWN_COMPANIES.items():
        if any(k in upper_text for k in kws):
            return comp
    # generisch: irgendein Wort vor "GRADING" -> auch unbekannte Firmen werden erkannt
    m = re.search(r"\b([A-Z]{2,20})\s+GRADING\b", upper_text)
    return m.group(1).title() if m else None


# Kurze Notenwoerter sind mehrdeutig ("Charizard ex", "EX" = Kartentyp!) und
# zaehlen nur, wenn direkt eine Ziffer daneben steht.
AMBIGUOUS_GRADE_WORDS = {"EX", "NM", "VG", "MINT"}


def _find_grade(text: str):
    """Note finden. Die Ziffer muss DIREKT am Notenwort stehen ("GEM MT 10",
    "NM-MT 8"), sonst wird das Notenwort selbst in eine Zahl uebersetzt
    (PSA-Skala). Subgrades wurden vorher entfernt."""
    upper = _strip_subgrades(text).upper()

    for gw in GRADE_WORDS:
        for m in re.finditer(r"\b" + re.escape(gw) + r"\b", upper):
            # Ziffer unmittelbar davor oder dahinter (max. ein Trennzeichen)
            after = upper[m.end(): m.end() + 6]
            before = upper[max(0, m.start() - 6): m.start()]
            for chunk in (after, before):
                dm = re.search(r"(?<![\d.])(10|[1-9](?:\.5)?)(?![\d.])", chunk)
                if dm:
                    return dm.group(1)

    m = re.search(r"\b(?:PSA|CGC|BGS|SGC|RGS|ACE|TAG|AGS)\s+(10|[1-9](?:\.5)?)(?![\d])",
                  upper)
    if m:
        return m.group(1)

    # Ziffer nicht lesbar -> eindeutiges Notenwort in Zahl uebersetzen
    for gw in GRADE_WORDS:
        if gw in AMBIGUOUS_GRADE_WORDS:
            continue
        if re.search(r"\b" + re.escape(gw) + r"\b", upper):
            num = GRADE_WORD_TO_NUM.get(gw)
            if num:
                return num
    return None


def _find_number(text: str):
    """Kartennummer. Bevorzugt 'x/y'; sonst PSA-Stil '#173'."""
    for a, b in NUM_RE.findall(text):
        # a > b ist erlaubt: Art-/Secret-Rares (173/165) liegen ueber dem Total
        if int(b) > 1 and 0 < int(a) < 1000:
            return f"{a}/{b}"
    m = re.search(r"#\s?(\d{1,4})\b", text)   # PSA-Label schreibt nur "#173"
    if m:
        return m.group(1)
    return None


def _find_setcode(text: str):
    m = SETCODE_RE.search(text)
    if m:
        return m.group(1)
    m = re.search(r"\b5(\d{1,2}[a-z])\b", text)  # OCR liest "s10b" oft als "510b"
    return f"s{m.group(1)}" if m else None


NAME_STRIP_TOKENS = {
    "GEM", "MT", "MINT", "GEMMT", "GEMMINT", "PRISTINE", "RARE", "ARTRARE",
    "ART", "HOLO", "REVERSE", "PROMO", "JP", "EN", "DE",
}


def _clean_name(line: str) -> str:
    line = " ".join(
        t for t in line.split() if t.upper() not in NAME_STRIP_TOKENS
    )
    name = re.sub(r"(?<=[a-z\u00e4\u00f6\u00fc])(ex|EX)\b", r" ex", line)
    return re.sub(r"\s{2,}", " ", name).strip(" -\u2013")


# Varianten-/Rarity-Codes, die PSA hinter den Namen schreibt
VARIANT_TOKENS = {
    "CEC", "GERMAN", "ENGLISH", "JAPANESE", "SECRET", "FA", "AR", "SIR", "SR",
    "FULLART", "FULL", "RAINBOW", "GOLD", "ALT", "HOLO", "REVERSE", "PROMO",
    "RARE", "ARTRARE", "ART", "TRAINER", "STAFF", "PRERELEASE",
}
# Suffixe, die zum Kartennamen gehoeren (kleben oft am Namen: "ZEKROMGX")
NAME_SUFFIXES = ["VMAX", "VSTAR", "GX", "EX", "V"]


def _polish_name(raw: str) -> str:
    """'RESHIRAM&ZEKROMGX' -> 'Reshiram & Zekrom GX'"""
    s = raw.replace("&", " & ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    out = []
    for tok in s.split():
        if tok == "&":
            out.append("&")
            continue
        up = tok.upper()
        matched = False
        for suf in NAME_SUFFIXES:  # angeklebtes Suffix abtrennen
            if up.endswith(suf) and len(up) > len(suf) + 2:
                out.append(tok[: -len(suf)].capitalize())
                out.append(suf if suf != "EX" else "ex")
                matched = True
                break
        if not matched:
            out.append(tok.capitalize() if tok.isupper() or tok.islower() else tok)
    return " ".join(out).strip()


def _find_name(text: str) -> str:
    """Kartenname finden.

    PSA-Label hat eine feste Struktur:
        JAHR SET  #NUMMER  <NAME>  NOTENWORT  VARIANTE  PSA  ZERTIFIKAT
    Der Name steht also zwischen '#Nummer' und dem ersten Notenwort - genau
    das wird hier ausgeschnitten. Danach folgen allgemeinere Fallbacks.
    Bei japanischen Karten bleibt das Feld leer -> Nummern-Lookup uebernimmt.
    """
    company_tokens = [c for c in KNOWN_COMPANIES] + \
                     [kw for kws in KNOWN_COMPANIES.values() for kw in kws]

    def is_junk(tok: str) -> bool:
        up = tok.upper()
        if len(tok) < 3 and up not in ("&", "V"):
            return True
        if up in NAME_STRIP_TOKENS or up in VARIANT_TOKENS:
            return True
        if up in [g.replace(" ", "") for g in GRADE_WORDS] or up in GRADE_WORDS:
            return True
        if any(n in up for n in NOISE):
            return True
        if any(ct in re.sub(r"[^A-Z]", "", up) for ct in company_tokens) and len(up) <= 12:
            return True
        if re.search(r"[a-z][A-Z]", tok) and len(tok) <= 4:
            return True
        return False

    # --- Pass 1: PSA-Struktur - Text zwischen '#Nummer' und Notenwort ---
    m = re.search(r"#\s?\d{1,4}\s+(.+)", text)
    if m:
        segment = m.group(1)
        # am ersten Notenwort abschneiden
        cut = len(segment)
        for gw in GRADE_WORDS:
            gm = re.search(r"\b" + re.escape(gw) + r"\b", segment, re.I)
            if gm:
                cut = min(cut, gm.start())
        segment = segment[:cut]
        tokens = [t for t in re.split(r"[\s,]+", segment) if t]
        keep = [t for t in tokens if not is_junk(re.sub(r"[^A-Za-z&]", "", t))]
        cand = _polish_name(" ".join(re.sub(r"[^A-Za-z&]", "", t) for t in keep))
        if len(cand.replace("&", "").strip()) >= 4:
            return cand

    # --- Pass 2: erste brauchbare Zeile ---
    for line in [l.strip() for l in text.splitlines() if l.strip()][:10]:
        if re.match(r"^i?l+us", line, re.I):
            continue
        toks = [re.sub(r"[^A-Za-z&\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc]", "", t)
                for t in line.split()]
        keep = [t for t in toks if t and not is_junk(t)]
        cand = _polish_name(" ".join(keep))
        if len(cand.replace("&", "").strip()) >= 4:
            return cand
    return ""


def parse_slab_text(text: str) -> dict:
    upper = text.upper()
    company = _detect_company(upper)
    grade = _find_grade(text)
    number = _find_number(text)
    setcode = _find_setcode(text)
    name = _find_name(text)

    set_name = None
    m = SETNAME_RE.search(text)
    if m:
        set_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1).strip())

    year_m = YEAR_RE.search(text)
    year = year_m.group(1) if year_m else None

    cert = None
    for cand in CERT_RE.findall(text):
        if cand != (year or ""):
            cert = cand
            break

    parts = [name]
    if number:
        parts.append(number.split("/")[0])
    if set_name:
        parts.append(set_name)
    search_query = " ".join(p for p in parts if p).strip()

    return dict(
        guessed_name=name, grading_company=company, grade=grade,
        set_name=set_name, card_number=number, set_code=setcode,
        year=year, cert_number=cert, search_query=search_query,
    )


def recognize_card(pil_image) -> RecognitionResult:
    attempts = []
    text, engine = None, None

    for fn, engine_name in (
        (_ocr_via_rapidocr, "RapidOCR"),
        (_ocr_via_winocr, "Windows-OCR"),
        (_ocr_via_tesseract, "Tesseract"),
    ):
        result, info = fn(pil_image)
        attempts.append(info)
        if result:
            text, engine = result, engine_name
            break

    debug = " | ".join(attempts)
    if text is None:
        return RecognitionResult(
            error="Keine OCR-Engine hat Text erkannt - bitte manuell ausfüllen.",
            debug_info=debug,
        )

    parsed = parse_slab_text(text)
    return RecognitionResult(
        raw_text=text, engine_used=engine, debug_info=debug, **parsed
    )
