"""
card_lookup.py
----------------
Identifiziert Karten sprachunabhaengig ueber die kostenlose Pokemon TCG API
(https://api.pokemontcg.io - kein API-Key noetig fuer moderate Nutzung).

Kerngedanke: Die KARTENNUMMER ist auf jeder Karte gleich, egal ob deutsch,
japanisch, franzoesisch oder englisch ("125/217" bleibt "125/217"). Der
NAME dagegen ist uebersetzt und wird von der OCR bei fremden Sprachen oft
gar nicht oder falsch gelesen.

Ablauf:
  1. OCR liefert Nummer (z.B. 125/217) und ggf. Set-Fragment.
  2. Diese API-Suche liefert dazu den offiziellen ENGLISCHEN Namen.
  3. Der englische Name ist genau das, womit pricecharting.com sucht.

Damit funktionieren auch japanische Karten, bei denen die OCR den Namen
nicht lesen kann - solange die Nummer erkannt wird.
"""

from dataclasses import dataclass
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = "https://api.pokemontcg.io/v2"
TIMEOUT = (5, 30)  # (Verbindung, Lesen) - die API ist oft langsam

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, connect=3, read=3, backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
)))


@dataclass
class CardMatch:
    name: str            # offizieller englischer Name, z.B. "Mega Gengar ex"
    set_name: str        # z.B. "Ascended Heroes"
    number: str          # z.B. "125"
    printed_total: str   # z.B. "217"
    release_date: str = ""
    image_url: str = ""
    rarity: str = ""

    @property
    def full_number(self) -> str:
        return f"{self.number}/{self.printed_total}" if self.printed_total else self.number

    @property
    def label(self) -> str:
        parts = [self.name, f"#{self.full_number}", self.set_name]
        if self.release_date:
            parts.append(f"({self.release_date[:4]})")
        return " ".join(p for p in parts if p)

    @property
    def pricecharting_query(self) -> str:
        """Suchbegriff, der auf pricecharting.com am besten trifft."""
        return f"{self.name} {self.number} {self.set_name}".strip()


def _parse_cards(items) -> List[CardMatch]:
    matches = []
    for c in items:
        s = c.get("set", {}) or {}
        matches.append(
            CardMatch(
                name=c.get("name", ""),
                set_name=s.get("name", ""),
                number=str(c.get("number", "")),
                printed_total=str(s.get("printedTotal", "") or ""),
                release_date=s.get("releaseDate", "") or "",
                image_url=(c.get("images", {}) or {}).get("small", ""),
                rarity=c.get("rarity", "") or "",
            )
        )
    return matches


def _query(q: str, page_size: int = 12):
    resp = _session.get(
        f"{API_BASE}/cards",
        params={
            "q": q, "pageSize": page_size, "orderBy": "-set.releaseDate",
            # nur benoetigte Felder anfordern -> deutlich schnellere Antworten
            "select": "name,number,set,images,rarity",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_cards(resp.json().get("data", []))


def lookup_by_number(
    number: str,
    printed_total: Optional[str] = None,
    set_hint: Optional[str] = None,
):
    """Sucht Karten anhand der (sprachunabhaengigen) Kartennummer.

    number:        "125"  oder  "125/217"
    printed_total: "217"  (optional, macht den Treffer viel praeziser)
    set_hint:      z.B. "Ascended Heroes" (optional, aus dem Slab-Label)

    Rueckgabe: (Liste[CardMatch], Fehlermeldung|None)
    """
    if not number:
        return [], "Keine Kartennummer erkannt - Lookup nicht möglich."

    if "/" in number:
        number, printed_total = number.split("/", 1)
    number = number.strip().lstrip("0") or number.strip()
    printed_total = (printed_total or "").strip()

    # Suchstrategien, von praezise nach breit
    queries = []
    if set_hint and printed_total:
        queries.append(f'number:"{number}" set.printedTotal:{printed_total} set.name:"{set_hint}"')
    if printed_total:
        queries.append(f'number:"{number}" set.printedTotal:{printed_total}')
    if set_hint:
        queries.append(f'number:"{number}" set.name:"{set_hint}"')
    queries.append(f'number:"{number}"')

    try:
        for q in queries:
            results = _query(q)
            if results:
                return results, None
        return [], (
            f"Keine Karte mit Nummer {number}"
            + (f"/{printed_total}" if printed_total else "")
            + " in der Pokémon-TCG-Datenbank gefunden."
        )
    except requests.RequestException as exc:
        return [], f"Pokémon-TCG-API nicht erreichbar: {exc}"
    except Exception as exc:
        return [], f"Lookup-Fehler: {exc}"


def lookup_by_name(name: str, number: Optional[str] = None):
    """Fallback-Suche ueber den Namen (falls die Nummer nicht lesbar war)."""
    if not name.strip():
        return [], "Kein Name angegeben."
    q = f'name:"{name.strip()}"'
    if number:
        q += f' number:"{number.split("/")[0]}"'
    try:
        results = _query(q)
        if not results:
            # unscharfe Suche mit Wildcard
            results = _query(f'name:{name.strip().split()[0]}*')
        return results, (None if results else f"Keine Treffer für '{name}'.")
    except requests.RequestException as exc:
        return [], f"Pokémon-TCG-API nicht erreichbar: {exc}"
