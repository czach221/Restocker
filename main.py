"""Kommandozeilen-Einstieg für den Restock-Checker.

Aufruf:
    python main.py "https://www.amazon.de/dp/XXXXXXXXXX"
    python main.py "https://..." --debug   # extrahierten Text in debug_text.txt schreiben
"""

import argparse
import sys

import requests

from restocker.analyze import AnalysisError, ConfigError, analyze_product
from restocker.extract import html_to_text
from restocker.fetch import BotBlockedError, fetch_html

# Unterhalb dieser Textlänge lohnt sich keine Auswertung.
MIN_TEXT_CHARS = 200


def print_summary(status) -> None:
    """Gibt das Ergebnis lesbar auf der Konsole aus."""
    availability = {True: "JA", False: "NEIN", None: "unklar"}[status.available]
    price = f"{status.price:.2f} {status.currency or ''}".strip() if status.price is not None else "unbekannt"

    print("=" * 60)
    print(f"Produkt:    {status.product_name or 'unbekannt'}")
    print(f"Verfügbar:  {availability}")
    if status.available_sizes:
        print(f"Größen:     {', '.join(status.available_sizes)}")
    print(f"Preis:      {price}")
    if status.on_sale:
        original = f" (statt {status.original_price:.2f})" if status.original_price is not None else ""
        print(f"Sale:       JA{original}")
    print(f"Beleg:      \"{status.evidence}\"")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüft per lokalem LLM, ob ein Produkt verfügbar ist.")
    parser.add_argument("url", help="Link zur Produktseite")
    parser.add_argument("--debug", action="store_true", help="extrahierten Text in debug_text.txt speichern")
    args = parser.parse_args()

    # Stufe 1: HTML laden
    try:
        html = fetch_html(args.url)
    except BotBlockedError as e:
        print(f"Blockiert: {e}", file=sys.stderr)
        return 2
    except requests.RequestException as e:
        # Deckt ungültige URLs, 404, Timeouts und Netzwerkfehler ab.
        print(f"Seite konnte nicht geladen werden: {e}", file=sys.stderr)
        return 1

    # Stufe 2: Text aufbereiten
    page_text = html_to_text(html)
    if args.debug:
        with open("debug_text.txt", "w", encoding="utf-8") as f:
            f.write(page_text)
        print(f"[debug] {len(page_text)} Zeichen extrahiert -> debug_text.txt")

    # Sicherheitsnetz für unbekannte Sperrseiten: fast leerer Text wäre ein
    # Modellaufruf ohne jeden Informationsgehalt – und der dauert.
    if len(page_text) < MIN_TEXT_CHARS:
        print(
            f"Seite enthält kaum Text ({len(page_text)} Zeichen) – vermutlich "
            "JS-Rendering oder Bot-Schutz. Keine Auswertung.",
            file=sys.stderr,
        )
        return 2

    # Stufe 3: vom lokalen Modell auswerten lassen
    try:
        status, usage = analyze_product(page_text, args.url)
    except (ConfigError, AnalysisError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    # Ausgabe: lesbar, als JSON und mit Verbrauch
    print_summary(status)
    print(status.model_dump_json(indent=2))
    print(
        f"\nToken: {usage.input_tokens} Input / {usage.output_tokens} Output"
        f" – {usage.seconds:.1f}s (lokal, keine Kosten)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
