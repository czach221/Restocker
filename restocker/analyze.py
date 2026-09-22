"""Stufe 3 der Pipeline: Seitentext von einem lokalen LLM auswerten lassen.

Statt starrer CSS-Selektoren liest das Modell die Seite wie ein Mensch. Damit die
Antwort trotzdem maschinenlesbar bleibt, übergeben wir das Schema aus models.py
an Ollama, das die Ausgabe beim Generieren darauf festnagelt.

Das Modell läuft lokal über Ollama. Der Server (`ollama serve`, meist als
systemd-Dienst) hält das Modell im Speicher und lauscht auf Port 11434 – dieses
Modul ist nur der Client, der dort anfragt.
"""

import os
from dataclasses import dataclass

import ollama
import pydantic
from dotenv import load_dotenv

from .models import ProductStatus

# Über .env oder Umgebungsvariable austauschbar, ohne den Code anzufassen.
DEFAULT_MODEL = "gpt-oss:20b"

# Kontextfenster. Ollamas Standard sind 4096 Token – zu wenig für 12.000 Zeichen
# Seitentext plus Systemprompt und Schema. Zu klein hieße: das Modell sieht eine
# abgeschnittene Seite, antwortet aber trotzdem selbstbewusst.
NUM_CTX = 16384
# Obergrenze für die Antwort. Das JSON ist kurz, der Rest ist Denk-Spielraum.
NUM_PREDICT = 2048

SYSTEM_PROMPT = """\
Du wertest den Textinhalt einer Online-Shop-Produktseite aus.

Regeln:
- Antworte ausschließlich auf Basis des gelieferten Textes.
- Wenn eine Information dort nicht steht, gib null zurück. Rate nicht und \
ergänze nichts aus eigenem Wissen.
- Ist der Text gar keine Produktseite (z.B. Startseite, Fehlerseite), setze \
available auf null.
- Belege deine Verfügbarkeitsaussage im Feld evidence mit einem kurzen, \
wörtlichen Zitat aus dem Text."""


class ConfigError(Exception):
    """Konfiguration fehlt, z.B. Ollama läuft nicht oder das Modell fehlt."""


class AnalysisError(Exception):
    """Die Auswertung durch das Modell ist fehlgeschlagen."""


@dataclass
class Usage:
    """Verbrauch eines Aufrufs – lokal, also nur Token und Dauer, keine Kosten."""

    input_tokens: int
    output_tokens: int
    seconds: float


def _chat(model: str, messages: list[dict], think):
    """Ein Aufruf an Ollama. Ausgelagert, damit der Retry ohne `think` einfach bleibt."""
    return ollama.chat(
        model=model,
        messages=messages,
        # Ollama erzwingt dieses Schema schon beim Generieren: Das Modell kann
        # gar kein anderes Format produzieren.
        format=ProductStatus.model_json_schema(),
        think=think,
        options={
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            # Reproduzierbare Antworten: hier wird abgelesen, nicht gedichtet.
            "temperature": 0,
        },
    )


def analyze_product(page_text: str, url: str) -> tuple[ProductStatus, Usage]:
    """Schickt den Seitentext an das lokale Modell und gibt (ProductStatus, Usage) zurück."""
    # .env laden, damit OLLAMA_MODEL dort gesetzt werden kann. Fehlt die Datei,
    # passiert nichts – dann gilt der Standardwert.
    load_dotenv()
    model = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"URL: {url}\n\n{page_text}"},
    ]

    try:
        # gpt-oss ist ein Reasoning-Modell. Für "lies ab, was dasteht" reicht
        # wenig Denken und spart spürbar Zeit.
        response = _chat(model, messages, think="low")
    except ollama.ResponseError as e:
        # Modelle ohne Reasoning lehnen think mit 400 ab. Dann ohne wiederholen,
        # damit ein per OLLAMA_MODEL gesetztes Modell nicht am Parameter scheitert.
        if e.status_code == 400 and "thinking" in e.error:
            try:
                response = _chat(model, messages, think=None)
            except ollama.ResponseError as retry_error:
                raise AnalysisError(f"Ollama-Fehler: {retry_error.error}") from retry_error
        elif e.status_code == 404:
            raise ConfigError(
                f"Modell '{model}' nicht gefunden – hole es mit 'ollama pull {model}'."
            ) from e
        else:
            raise AnalysisError(f"Ollama-Fehler: {e.error}") from e
    except ConnectionError as e:
        raise ConfigError(
            "Keine Verbindung zu Ollama – läuft der Server? "
            "Starten mit 'ollama serve' oder 'systemctl start ollama'."
        ) from e

    # Auch eine erfolgreiche Antwort kann unbrauchbar sein.
    if response.done_reason == "length":
        raise AnalysisError("Antwort wurde abgeschnitten (num_predict erreicht).")

    # Ollama liefert einen JSON-String, kein fertiges Objekt – also selbst prüfen.
    try:
        status = ProductStatus.model_validate_json(response.message.content or "")
    except pydantic.ValidationError as e:
        raise AnalysisError("Antwort ließ sich nicht in das Schema überführen.") from e

    # Die Zähler fehlen, wenn Ollama den Prompt aus dem Cache bedient.
    usage = Usage(
        input_tokens=response.prompt_eval_count or 0,
        output_tokens=response.eval_count or 0,
        seconds=(response.total_duration or 0) / 1_000_000_000,
    )
    return status, usage
