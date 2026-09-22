"""Stufe 1 der Pipeline: HTML einer Produktseite laden.

Dies ist die einzige Stelle, die bei Bot-Schutz ausgetauscht wird (Plan B:
Playwright). Die Signatur `fetch_html(url) -> str` bleibt dabei gleich, der
Rest der Pipeline merkt vom Wechsel nichts.
"""

import requests

# Browserähnliche Header. Accept-Language ist wichtig: ohne sie liefert Amazon
# teils die englische Seite ("In Stock" statt "Auf Lager").
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
}

# Statuscodes, mit denen Shops typischerweise Bots abweisen.
BLOCK_STATUS_CODES = {403, 429, 503}

# Heuristik: Textfragmente, die auf einer Captcha-/Challenge-Seite stehen.
# Bewusst spezifisch gewählt, damit normale Produktseiten nicht fälschlich
# als blockiert erkannt werden.
BLOCK_MARKERS = (
    "/errors/validatecaptcha",                      # Amazon-Captcha
    "geben sie die unten angezeigten zeichen ein",  # Amazon-Captcha (DE)
    "enter the characters you see below",           # Amazon-Captcha (EN)
    "awswafintegration",                            # AWS-WAF-JS-Challenge (Amazon, HTTP 202)
    "cf-challenge",                                 # Cloudflare-Challenge
    "<title>just a moment...</title>",              # Cloudflare-Challenge
)


class BotBlockedError(Exception):
    """Der Shop hat die Anfrage als Bot erkannt und blockiert."""


def fetch_html(url: str, timeout: int = 20) -> str:
    """Lädt die Seite und gibt das HTML zurück.

    Wirft BotBlockedError bei erkanntem Bot-Schutz und
    requests.RequestException bei Netzwerk- oder HTTP-Fehlern (z.B. 404).
    """
    response = requests.get(url, headers=HEADERS, timeout=timeout)

    # Bot-Schutz vor raise_for_status() prüfen, damit wir eine
    # verständliche Meldung statt eines generischen HTTP-Fehlers bekommen.
    if response.status_code in BLOCK_STATUS_CODES:
        raise BotBlockedError(
            f"Shop antwortet mit HTTP {response.status_code} – vermutlich Bot-Schutz."
        )

    response.raise_for_status()  # z.B. 404 -> requests.HTTPError

    html = response.text
    lowered = html.lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        raise BotBlockedError("Shop liefert eine Captcha-/Challenge-Seite statt der Produktseite.")

    return html
