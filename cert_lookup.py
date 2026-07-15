"""
cert_lookup.py
----------------
Prueft Zertifikatsnummern direkt bei der Grading-Firma (PSA / CGC) und
liest die dort hinterlegten Kartendaten aus (Best-Effort-Scraping der
oeffentlichen Verifikationsseiten - Layoutaenderungen koennen das brechen,
der Link wird deshalb immer mit angezeigt).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

# PSA blockt "nackte" Requests (403). Vollstaendige Browser-Header helfen oft -
# garantiert ist es nicht: PSA setzt Bot-Schutz ein. Bei 403 zeigt die App den
# direkten Link an, damit du das Zertifikat mit einem Klick selbst pruefen kannst.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "no-cache",
}
TIMEOUT = 25


@dataclass
class CertResult:
    url: str = ""
    fields: dict = field(default_factory=dict)  # Label -> Wert von der Seite
    name: Optional[str] = None
    grade: Optional[str] = None
    set_name: Optional[str] = None
    year: Optional[str] = None
    error: Optional[str] = None


def _collect_pairs(soup) -> dict:
    """Sammelt Label/Wert-Paare aus Tabellen und dt/dd-Listen."""
    pairs = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) == 2:
            k = cells[0].get_text(" ", strip=True)
            v = cells[1].get_text(" ", strip=True)
            if k and v and len(k) < 40 and len(v) < 120:
                pairs[k] = v
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            k = dt.get_text(" ", strip=True)
            v = dd.get_text(" ", strip=True)
            if k and v:
                pairs[k] = v
    return pairs


def _map_fields(pairs: dict) -> dict:
    out = {}
    for k, v in pairs.items():
        ku = k.upper()
        if not out.get("name") and any(w in ku for w in ("CARD", "SUBJECT", "PLAYER", "NAME", "KARTE")):
            out["name"] = v
        if not out.get("grade") and any(w in ku for w in ("GRADE", "NOTE", "BEWERTUNG")):
            m = re.search(r"(10|[1-9](?:\.5)?)", v)
            out["grade"] = m.group(1) if m else v
        if not out.get("set_name") and any(w in ku for w in ("SET", "SERIES", "SERIE")):
            out["set_name"] = v
        if not out.get("year") and any(w in ku for w in ("YEAR", "JAHR")):
            m = re.search(r"(20\d{2}|19\d{2})", v)
            if m:
                out["year"] = m.group(1)
    return out


# PSA blockt automatisierte Abrufe zuverlaessig (403, Bot-Schutz). Ein
# "Workaround" waere ein Umgehen ihres Schutzes - das machen wir nicht.
# Stattdessen: PSA-Zertifikate werden gar nicht erst automatisch abgefragt,
# die Felder kommen aus OCR + Kartendatenbank (funktioniert bei PSA gut).
# Der Link zur PSA-Seite wird trotzdem angezeigt, zum Selbst-Nachschauen.
AUTO_LOOKUP_COMPANIES = {"CGC"}


def supports_auto_lookup(company: str) -> bool:
    return (company or "").upper() in AUTO_LOOKUP_COMPANIES


def cert_url(company: str, cert_number: str) -> Optional[str]:
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return None
    comp = (company or "").upper()
    if "CGC" in comp:
        return f"https://www.cgccards.de/certlookup/{cert_number}/"
    if "PSA" in comp:
        return f"https://www.psacard.com/cert/{cert_number}/psa"
    return None


def lookup_cert(company: str, cert_number: str) -> CertResult:
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return CertResult(error="Keine Zertifikatsnummer angegeben.")

    comp = (company or "").upper()
    if "CGC" in comp:
        url = f"https://www.cgccards.de/certlookup/{cert_number}/"
    elif "PSA" in comp:
        url = f"https://www.psacard.com/cert/{cert_number}/psa"
    else:
        return CertResult(error="Online-Prüfung derzeit nur für PSA und CGC verfügbar.")

    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=TIMEOUT)
        if resp.status_code == 403:
            return CertResult(
                url=url,
                error=(
                    "PSA blockiert automatisierte Abrufe (403). Bitte den Link unten "
                    "anklicken und die Daten von der PSA-Seite übernehmen - oder die "
                    "Felder per OCR/Kartendatenbank füllen lassen."
                ),
            )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return CertResult(url=url, error=f"Seite nicht erreichbar: {exc}")

    soup = BeautifulSoup(resp.text, "html.parser")
    text_upper = soup.get_text(" ", strip=True).upper()
    if "NOT FOUND" in text_upper or "KEINE ERGEBNISSE" in text_upper or "NO RESULTS" in text_upper:
        return CertResult(url=url, error="Zertifikat nicht gefunden - Nummer prüfen.")

    pairs = _collect_pairs(soup)
    if not pairs:
        return CertResult(
            url=url,
            error="Seite geladen, aber Daten nicht automatisch lesbar - bitte Link öffnen.",
        )

    mapped = _map_fields(pairs)
    return CertResult(url=url, fields=pairs, **mapped)
