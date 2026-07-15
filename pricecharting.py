"""
pricecharting.py
------------------
Sucht eine Karte auf pricecharting.com. Gibt eine LISTE von Treffern
zurueck, aus der der Nutzer in der App den richtigen auswaehlt (der
automatisch erste Treffer war zu oft falsch). Danach werden die Preise
der gewaehlten Produktseite ausgelesen.

Hinweis: pricecharting.com bietet ein offizielles (kostenpflichtiges)
API an. Ohne API-Key wird die oeffentliche Seite geparst (Best-Effort).
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pricecharting.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@dataclass
class SearchCandidate:
    name: str
    url: str
    console: str = ""  # bei Pokemon: Set-Name, steht in der Trefferliste


@dataclass
class PriceResult:
    product_name: str = ""
    product_url: str = ""
    prices: dict = field(default_factory=dict)
    error: Optional[str] = None


def search_candidates(query: str, max_results: int = 8):
    """Sucht auf pricecharting.com, gibt Liste von SearchCandidate zurueck."""
    if not query.strip():
        return [], "Kein Suchbegriff angegeben."

    search_url = f"{BASE_URL}/search-products?q={quote(query)}&type=prices"
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Netzwerkfehler: {exc}"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Eindeutiger Treffer -> direkte Weiterleitung auf Produktseite
    if "/game/" in resp.url:
        title = soup.find("h1")
        name = title.get_text(strip=True) if title else query
        return [SearchCandidate(name=name, url=resp.url)], None

    candidates = []
    for row in soup.select("table#games_table tbody tr"):
        link = row.select_one("td a[href*='/game/']")
        if not link:
            continue
        href = link.get("href", "")
        if href.startswith("/"):
            href = BASE_URL + href
        cells = row.find_all("td")
        console = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        candidates.append(SearchCandidate(
            name=link.get_text(strip=True), url=href, console=console
        ))
        if len(candidates) >= max_results:
            break

    if not candidates:
        # Fallback: irgendwelche /game/-Links auf der Seite
        for link in soup.select("a[href*='/game/']")[:max_results]:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            text = link.get_text(strip=True)
            if text:
                candidates.append(SearchCandidate(name=text, url=href))

    if not candidates:
        return [], f"Keine Treffer für '{query}' gefunden. Tipp: englische Schreibweise + Kartennummer verwenden (z. B. 'Pikachu ex 238 Surging Sparks')."

    return candidates, None


def get_prices_for_url(product_url: str, product_name: str = "") -> PriceResult:
    """Liest die Preistabelle einer konkreten Produktseite aus."""
    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return PriceResult(error=f"Netzwerkfehler: {exc}", product_url=product_url)

    soup = BeautifulSoup(resp.text, "html.parser")
    prices = {}

    for row in soup.select("table#price_data tr, #full-prices tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if label and re.search(r"\d", value):
                prices[label] = value

    if not prices:
        for el in soup.select(".price, .js-price"):
            label_el = el.find_previous(class_=re.compile("title|label"))
            label = label_el.get_text(strip=True) if label_el else "Preis"
            value = el.get_text(strip=True)
            if re.search(r"\d", value):
                prices[label] = value

    if not prices:
        return PriceResult(
            product_name=product_name, product_url=product_url,
            error="Preistabelle konnte nicht ausgelesen werden - bitte Link manuell öffnen.",
        )

    return PriceResult(product_name=product_name, product_url=product_url, prices=prices)


# ---------------- Euro-Umrechnung ----------------

_cached_rate = None


def get_usd_eur_rate() -> Optional[float]:
    """Holt den aktuellen USD->EUR-Kurs (frankfurter.app, kostenlos, kein Key).
    Gibt None zurueck, wenn nicht erreichbar - dann werden nur USD angezeigt."""
    global _cached_rate
    if _cached_rate is not None:
        return _cached_rate
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=8
        )
        resp.raise_for_status()
        _cached_rate = float(resp.json()["rates"]["EUR"])
        return _cached_rate
    except Exception:
        return None


def usd_string_to_eur(usd_str: str, rate: float) -> str:
    """Wandelt '$123.45' in '113,58 €' um. Gibt '' zurueck, wenn nicht parsbar."""
    m = re.search(r"([\d,]+\.?\d*)", usd_str.replace(",", ""))
    if not m:
        return ""
    try:
        value = float(m.group(1)) * rate
        return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return ""
