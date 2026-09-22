# Restock-Checker-Agent

Ein Agent, der für einen Produktlink prüft, ob das Produkt verfügbar ist, welche Größen es gibt,
was es kostet und ob ein Rabatt läuft. Statt starrer CSS-Selektoren wertet ein lokales LLM
(`gpt-oss:20b` über Ollama) den Seiteninhalt aus und antwortet in einem fest vorgegebenen
JSON-Schema.

**Warum ein LLM statt HTML-Parsing?** Shops wie Amazon oder MediaMarkt ändern ihr HTML ständig,
und Verfügbarkeit steht dort oft als Fließtext ("Nur noch 2 auf Lager"). Feste Selektoren brechen
bei jedem Redesign, ein LLM liest die Seite dagegen wie ein Mensch. Der Preis dafür: mehr Latenz
und das Risiko von Halluzinationen. Dagegen helfen ein erzwungenes Schema, eine explizite
"nicht raten"-Regel und ein Pflichtfeld mit wörtlichem Beleg.

**Warum lokal?** Das Modell läuft auf dem eigenen Rechner, also ohne API-Key und ohne Kosten pro
Lauf. Bei einem geplanten Lauf alle zwei Tage zählt vor allem, dass Ausprobieren nichts kostet.

## Ausbaustufen

| Stufe | Inhalt | Status |
|---|---|---|
| 1 | Minimalversion: URL → Text → LLM → JSON → Konsole | **umgesetzt**, Tests teilweise offen |
| 2 | Zustand speichern, nur bei Änderung reagieren | offen |
| 3 | Benachrichtigung per E-Mail oder Telegram | offen |
| 4 | Webhook an zweiten Kanal (Discord/Slack/Notion) | offen |
| 5 | Mehrere Links, erweiterte Prompt-Varianten | offen |
| 6 | Scheduling über GitHub Actions (alle 2 Tage) | offen |
| 7 | Tests und Dokumentation je Stufe | laufend |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dazu [Ollama](https://ollama.com) installieren und das Modell holen:

```bash
ollama pull gpt-oss:20b
```

**Der Ollama-Server muss laufen, bevor das Skript startet.** Ollama besteht aus zwei Teilen: dem
Server (`ollama serve`), der das Modell im Speicher hält und auf `localhost:11434` lauscht, und
den Clients – dem `ollama`-Befehl und diesem Skript. Das Skript lädt das Modell also nie selbst,
es schickt nur eine HTTP-Anfrage an diesen Port. Läuft dort nichts, gibt es eine klare Fehlermeldung.

Meist läuft der Server schon als systemd-Dienst (`systemctl status ollama`), sonst startet ihn
`ollama serve` in einem zweiten Terminal. Der erste Lauf nach dem Start dauert länger, weil das
20B-Modell erst in den Speicher geladen wird.

Ein anderes Modell lässt sich ohne Codeänderung setzen, per Umgebungsvariable oder `.env`
(die Datei ist per `.gitignore` vom Commit ausgeschlossen):

```
OLLAMA_MODEL=llama3.1:8b
```

## Nutzung

```bash
python main.py "https://www.mediamarkt.de/de/product/..."
python main.py "https://..." --debug    # extrahierten Text zusätzlich in debug_text.txt speichern
```

Die Ausgabe enthält eine lesbare Zusammenfassung, das JSON-Ergebnis sowie Token-Verbrauch und
Dauer des Modellaufrufs.

Exit-Codes: `0` Erfolg, `1` Fehler (Netzwerk, Konfiguration, Modell), `2` Seite blockiert oder ohne
verwertbaren Text.

## Architektur (Stufe 1)

```
main.py                 CLI: verbindet die drei Stufen, Fehlerbehandlung, Ausgabe
restocker/
  fetch.py              1. HTML laden (requests) + Bot-Schutz-Erkennung
  extract.py            2. HTML → kompakter Text (JSON-LD zuerst, dann Fließtext)
  analyze.py            3. Ollama-Aufruf mit erzwungenem Schema
  models.py             Antwortschema ProductStatus (Pydantic)
```

Jede Stufe ist eine Datei und einzeln austauschbar. Wenn ein Shop `requests` blockiert, wird nur
`fetch.py` ersetzt (Playwright), die Signatur `fetch_html(url) -> str` bleibt gleich.

### Designentscheidungen

- **Erzwungenes Schema statt Freitext-Parsing:** `format=ProductStatus.model_json_schema()` lässt
  Ollama beim Generieren nur Token zu, die zum Schema passen. Das Modell kann also gar kein
  anderes Format ausgeben – keine Markdown-Codeblöcke, keine Vorrede. Geprüft wird trotzdem noch
  einmal mit `model_validate_json()`.
- **`available` ist dreiwertig (`true`/`false`/`null`):** `null` bedeutet, dass die Seite keine
  Aussage enthält. Ohne diese Option müsste das Modell raten.
- **Pflichtfeld `evidence`:** Das Modell zitiert die Textstelle, auf die es sich stützt. So lässt
  sich jede Antwort sofort prüfen, und Fehler in der Textextraktion werden sichtbar.
- **JSON-LD vor Fließtext:** Viele Shops betten schema.org-Daten (Preis, Verfügbarkeit) ein. Die
  stehen vorne im Text und bleiben deshalb auch bei einer Kürzung erhalten.
- **Längenlimit 12.000 Zeichen:** Das begrenzt Prompt-Größe und Laufzeit. Wird gekürzt, erscheint
  eine Warnung.
- **Mindestlänge 200 Zeichen:** Ist der Text kürzer, gibt es keinen Modellaufruf. Das fängt
  unbekannte Sperrseiten ab, bevor sie Rechenzeit kosten.
- **Kontextfenster explizit auf 16.384 Token:** Ollamas Standard sind 4.096 – zu wenig für 12.000
  Zeichen Seitentext plus Schema. Ohne diese Einstellung sähe das Modell eine abgeschnittene Seite
  und würde trotzdem selbstbewusst antworten.
- **`temperature: 0` und `think="low"`:** Hier wird abgelesen, nicht gedichtet. Das macht die
  Antworten reproduzierbar und spart bei einem Reasoning-Modell spürbar Zeit.

### Fairness beim Abrufen

Ein Request pro Lauf, keine parallelen Abrufe, geplant ist ein Lauf alle zwei Tage, nur privater
Gebrauch. Zielgruppe sind kleinere Shops ohne aggressive Firewall. Die Captcha-Sperren der Shops werden nicht umgangen, sondern nur erkannt und
gemeldet.

## Tests und Ergebnisse – Stufe 1

Testdatum: 2026-09-16

### Bereits durchgeführt (ohne Modellaufruf)

| # | Fall | Erwartung | Ergebnis |
|---|---|---|---|
| T5a | Ungültige URL (`kein-link`) | Sauberer Fehler, kein Modellaufruf | ✅ `Invalid URL … No scheme supplied`, Exit 1 |
| T5b | Nicht existierende MediaMarkt-Produkt-URL | 404-Fehler | ⚠️ **Shop antwortet mit HTTP 200** (Soft 404). Die Seite geht an die Auswertung, T4 muss das abfangen. |
| T6 | Amazon mit `requests` | Sperre wird erkannt | ✅ erkannt, Exit 2 (siehe Befund unten) |
| T7 | Ollama läuft nicht | Klare Meldung statt Stacktrace | ✅ `Keine Verbindung zu Ollama …`, Exit 1 |
| T8 | Textextraktion (synthetisches HTML) | JSON-LD vorne, Skripte/Nav/Footer entfernt | ✅ |
| T9 | Kürzung über dem Limit | Warnung auf der Konsole | ✅ |
| T10 | MediaMarkt-Startseite mit `requests` | HTML kommt an | ✅ 917 KB HTML → 3.829 Zeichen Text |

### Mit lokalem Modell geprüft (2026-09-19, `gpt-oss:20b`)

| # | Fall | Erwartung | Ergebnis |
|---|---|---|---|
| T1+T3 | Synthetische Produktseite, 12.000 Zeichen, mit Sale | Preis, Streichpreis, Größen, Beleg | ✅ alle Felder korrekt, `evidence` zitiert "Auf Lager – Lieferung in 1-2 Werktagen", Größe `44,5` korrekt als **eine** Größe erkannt |

Bei derselben Seite auf 4 Zeilen gekürzt wurde `44,5` dagegen in `"44"` und `"5"` zerlegt – der
volle Kontext hilft dem Modell also. Für echte Seiten ist das der Normalfall.

### Offen (echte Shop-Seiten)

| # | Fall | Erwartung |
|---|---|---|
| T2 | Ausverkauftes Produkt | `available=false` mit passendem Beleg |
| T4 | Startseite bzw. Soft-404-Seite | `available=null`, das Modell darf nicht raten |

### Laufzeit: der eigentliche Haken

Gemessen auf diesem Rechner (Intel Iris Xe, **keine dedizierte GPU** – Ollama meldet `100% CPU`):

| Prompt | Modell | Dauer | Ergebnis |
|---|---|---|---|
| 4 Zeilen (304 Token) | `gpt-oss:20b` | 79 s | korrekt |
| volle Seite (3.316 Token) | `gpt-oss:20b` | **952 s (~16 min)** | korrekt |
| volle Seite (3.995 Token) | `qwen2.5-coder:7b` | **1.337 s (~22 min)** | korrekt |

**Überraschung: das kleinere Modell war langsamer.** `gpt-oss:20b` ist ein Mixture-of-Experts-
Modell – pro Token rechnen nur rund 3,6 der 20 Mrd. Parameter mit. Ein dichtes 7B-Modell rechnet
pro Token also *mehr*. "Kleiner = schneller" gilt hier nicht; entscheidend ist die Zahl der
*aktiven* Parameter, nicht die Modellgröße auf der Festplatte.

Was die Laufzeit tatsächlich senkt:

1. **`MAX_CHARS` senken** in `extract.py`. Die Laufzeit hängt fast linear an der Prompt-Länge
   (304 Token → 79 s, 3.316 Token → 952 s). Dank JSON-LD-zuerst stehen Preis und Verfügbarkeit
   ohnehin vorne im Text, eine Kürzung kostet also wenig Information.
2. **Ein echtes kleines Modell**, z.B. `llama3.2:3b` – nicht "kleiner als 20B", sondern wenige
   aktive Parameter. Über `OLLAMA_MODEL` in der `.env`, ohne Codeänderung.
3. **GPU**: Auf diesem Rechner gibt es nur Intel-Iris-Xe-Grafik, deshalb `100% CPU`. Mit einer
   dedizierten GPU fällt die Laufzeit um ein bis zwei Größenordnungen.

Für den geplanten Lauf alle zwei Tage ist die aktuelle Laufzeit verkraftbar – der Agent läuft im
Hintergrund, niemand wartet davor. Zum Entwickeln empfiehlt sich Variante 1 oder 2.

### Befund: Amazon blockiert `requests`

Amazon.de antwortet auf `requests` mit **HTTP 202** und einer 2 KB großen
**AWS-WAF-JavaScript-Challenge** statt der Produktseite. Diese Sperre lieferte weder 403 noch
Captcha-Text, deshalb erkannte die erste Version sie nicht. Die extrahierte Seite hätte 12 Zeichen
Text gehabt und trotzdem einen bezahlten API-Call ausgelöst.

Konsequenzen:
1. Neuer Marker `awswafintegration` in `fetch.py`.
2. Zusätzlich die Mindestlänge in `main.py` als Absicherung für künftige, unbekannte Sperrseiten.
3. Für Amazon bräuchte es einen echten Browser (Plan B: Playwright). MediaMarkt funktioniert mit
   `requests`. Da das Projekt auf kleinere Shops ohne starke Firewall zielt, wird Plan B vorerst
   nicht umgesetzt; die Sperr-Erkennung bleibt als Schutz bestehen.
