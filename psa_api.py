"""
psa_api.py
------------
Anbindung an die OFFIZIELLE PSA Public API (Bearer-Token), wie im
PSA API End User Agreement vorgesehen - kein Scraping mehr fuer PSA.

Token besorgen:
  1. https://www.psacard.com/publicapi -> einloggen -> Access Token generieren.
  2. Den Token in der App (Sidebar -> "PSA API Token") eintragen.
     Optional "Token merken" anhaken - dann landet er in psa_token.txt in
     diesem Ordner (liegt lokal bei dir, wird nirgendwo hochgeladen).

API-Dokumentation: https://api.psacard.com/publicapi/swagger
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import requests

API_BASE = "https://api.psacard.com/publicapi"
TIMEOUT = 20
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_token.txt")
# Merkt sich pro Token (gehasht, nicht im Klartext), wann zuletzt ein
# echter API-Pull gemacht wurde - PSA erlaubt nur 1 Pull/Tag/Token.
PULL_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_pull_log.json")


@dataclass
class PsaCertResult:
    raw: dict = field(default_factory=dict)
    name: Optional[str] = None
    grade: Optional[str] = None
    set_name: Optional[str] = None
    year: Optional[str] = None
    card_number: Optional[str] = None
    error: Optional[str] = None
    blocked: bool = False  # True = kein API-Call gemacht (Tageslimit)


def load_saved_token() -> str:
    if os.path.exists(TOKEN_FILE):
        try:
            return open(TOKEN_FILE, "r", encoding="utf-8").read().strip()
        except Exception:
            return ""
    return ""


def save_token(token: str) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token.strip())


def _token_key(token: str) -> str:
    """Hash statt Klartext-Token als Schluessel im Pull-Log - der Token
    selbst landet dadurch nicht zusaetzlich in einer zweiten Datei."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()[:16]


def _load_pull_log() -> dict:
    if os.path.exists(PULL_LOG_FILE):
        try:
            with open(PULL_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_pull_log(log: dict) -> None:
    try:
        with open(PULL_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass  # Log ist best-effort - ein Schreibfehler soll den Pull nicht verhindern


def last_pull_today(token: str) -> Optional[dict]:
    """Gibt die Log-Eintraege von heute fuer diesen Token zurueck (dict mit
    'time' und 'cert'), oder None wenn heute noch nicht gepullt wurde."""
    if not token or not token.strip():
        return None
    log = _load_pull_log()
    entry = log.get(_token_key(token))
    if entry and entry.get("date") == date.today().isoformat():
        return entry
    return None


def can_pull_today(token: str) -> bool:
    return last_pull_today(token) is None


def _record_pull(token: str, cert_number: str) -> None:
    log = _load_pull_log()
    log[_token_key(token)] = {
        "date": date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M:%S"),
        "cert": cert_number,
    }
    _save_pull_log(log)


def _first_match(d: dict, keywords) -> Optional[str]:
    """Sucht in einem (ggf. verschachtelten) Dict den ersten Wert, dessen
    Schluessel eines der Keywords enthaelt. PSA's genaues JSON-Schema ist
    uns nicht dokumentiert bekannt, deshalb robust/generisch gehalten."""
    stack = [d]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                ku = k.upper()
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif any(kw in ku for kw in keywords) and str(v).strip():
                    return str(v).strip()
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def lookup_psa_cert(cert_number: str, token: str) -> PsaCertResult:
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return PsaCertResult(error="Keine Zertifikatsnummer angegeben.")
    if not token.strip():
        return PsaCertResult(
            error="Kein PSA API Token hinterlegt - in der Sidebar eintragen "
                  "(Token unter psacard.com/publicapi erzeugen)."
        )

    prev = last_pull_today(token)
    if prev:
        return PsaCertResult(
            blocked=True,
            error=(
                f"Für diesen Token wurde heute bereits um {prev.get('time', '?')} Uhr "
                f"ein PSA-API-Pull gemacht (Zertifikat {prev.get('cert', '?')}). "
                "Nur 1 Pull pro Tag und Token - bitte morgen erneut versuchen, "
                "oder das Zertifikat manuell über den Link prüfen."
            ),
        )

    url = f"{API_BASE}/cert/GetByCertNumber/{cert_number}"
    try:
        resp = requests.get(
            url, headers={"authorization": f"bearer {token.strip()}"}, timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        return PsaCertResult(error=f"PSA-API nicht erreichbar: {exc}")

    # Das Kontingent wird durch den Request selbst verbraucht (unabhaengig
    # vom Ergebnis) - deshalb wird hier direkt nach dem Call protokolliert.
    _record_pull(token, cert_number)

    if resp.status_code == 401:
        return PsaCertResult(error="Token ungültig/abgelaufen - bitte in der Sidebar neu generieren.")
    if resp.status_code == 404:
        return PsaCertResult(error=f"Kein PSA-Zertifikat mit Nummer {cert_number} gefunden.")
    if resp.status_code != 200:
        return PsaCertResult(error=f"PSA-API-Fehler (HTTP {resp.status_code}): {resp.text[:200]}")

    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError):
        return PsaCertResult(error="Antwort der PSA-API konnte nicht gelesen werden (kein JSON).")

    name = _first_match(data, ["SUBJECT", "CARDNAME", "CARD_NAME", "PLAYER"])
    grade = _first_match(data, ["GRADE"])
    if grade:
        m = re.search(r"(10|[1-9](?:\.5)?)", grade)
        grade = m.group(1) if m else grade
    set_name = _first_match(data, ["BRAND", "SET", "SERIES"])
    year = _first_match(data, ["YEAR"])
    card_number = _first_match(data, ["CARDNUMBER", "CARD_NUMBER"])

    return PsaCertResult(
        raw=data, name=name, grade=grade, set_name=set_name,
        year=year, card_number=card_number,
    )
