"""Stufe 2 der Pipeline: HTML in kompakten Text für das LLM umwandeln.

Zwei Teile, in dieser Reihenfolge:
1. Strukturierte Daten (JSON-LD nach schema.org) – enthalten oft schon Preis
   und Verfügbarkeit in maschinenlesbarer Form.
2. Sichtbarer Fließtext der Seite, ohne Skripte, Navigation, Footer usw.

Weil die JSON-LD-Daten vorne stehen, überleben sie auch eine Kürzung.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Obergrenze für den Text, der an das Modell geht (~3-4k Token).
# Begrenzt Kosten pro Lauf; bei Kürzung wird eine Warnung ausgegeben.
MAX_CHARS = 12_000

# Elemente ohne Informationswert für die Produktprüfung.
# <title> steht hier, weil wir ihn vorher separat auslesen (sonst doppelt im Text).
NOISE_TAGS = ["title", "script", "style", "noscript", "template", "svg", "iframe", "nav", "header", "footer"]


def _extract_json_ld(soup: BeautifulSoup) -> list[str]:
    """Sammelt JSON-LD-Blöcke, die Produkt- oder Angebotsdaten enthalten."""
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue  # kaputtes JSON auf der Seite ignorieren
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        # Nur relevante Blöcke behalten (z.B. keine Breadcrumbs oder Logos).
        if '"Product"' in compact or '"Offer"' in compact:
            blocks.append(compact)
    return blocks


def html_to_text(html: str, max_chars: int = MAX_CHARS) -> str:
    """Wandelt HTML in einen kompakten Text für das LLM um."""
    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD muss VOR dem Entfernen der <script>-Tags gelesen werden.
    json_ld_blocks = _extract_json_ld(soup)
    title = soup.title.get_text(strip=True) if soup.title else ""

    for tag in soup(NOISE_TAGS):
        tag.decompose()

    body_text = soup.get_text(separator=" ", strip=True)
    body_text = re.sub(r"\s+", " ", body_text)  # Mehrfach-Leerzeichen zusammenfassen

    parts = []
    if title:
        parts.append(f"Seitentitel: {title}")
    if json_ld_blocks:
        parts.append("Strukturierte Daten (JSON-LD):\n" + "\n".join(json_ld_blocks))
    parts.append("Seitentext:\n" + body_text)
    text = "\n\n".join(parts)

    if len(text) > max_chars:
        # Nicht still kürzen: sichtbar machen, dass Information fehlen könnte.
        logger.warning(
            "Seitentext von %d auf %d Zeichen gekürzt – Angaben weiter hinten fehlen evtl.",
            len(text),
            max_chars,
        )
        text = text[:max_chars]

    return text
