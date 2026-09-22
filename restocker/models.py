"""Antwortschema: So sieht das Ergebnis einer Produktprüfung aus.

Das JSON-Schema dieses Modells wird an Ollama übergeben. Ollama schränkt die
Token-Auswahl beim Generieren darauf ein – wir bekommen also JSON in genau dieser
Form zurück und müssen keinen Freitext parsen.

Die `description`-Texte landen im JSON-Schema und dienen dem Modell als
Ausfüllhinweis pro Feld.
"""

from pydantic import BaseModel, Field


class ProductStatus(BaseModel):
    """Strukturierte Auswertung einer einzelnen Produktseite."""

    product_name: str | None = Field(
        description="Produktname, wie er auf der Seite steht. null, wenn nicht erkennbar."
    )

    # Bewusst dreiwertig: True / False / None.
    # None heißt "steht nicht auf der Seite" – so muss das Modell nicht raten.
    available: bool | None = Field(
        description=(
            "true, wenn das Produkt bestellbar/auf Lager ist; false, wenn es "
            "ausverkauft oder nicht verfügbar ist; null, wenn die Seite dazu "
            "keine Aussage enthält."
        )
    )

    available_sizes: list[str] = Field(
        description=(
            "Liste der aktuell verfügbaren Größen/Varianten. Leere Liste, wenn "
            "das Produkt keine Größen hat oder keine erkennbar sind."
        )
    )

    price: float | None = Field(
        description="Aktueller Preis als Zahl (z.B. 49.99). null, wenn nicht erkennbar."
    )

    currency: str | None = Field(
        description="Währung als ISO-Code, z.B. EUR. null, wenn nicht erkennbar."
    )

    on_sale: bool = Field(
        description="true, wenn ein Rabatt, Streichpreis oder Sale-Hinweis sichtbar ist."
    )

    original_price: float | None = Field(
        description="Ursprünglicher Preis (Streichpreis), falls ein Rabatt läuft, sonst null."
    )

    # Beleg für die Verfügbarkeitsaussage – macht jede Antwort nachprüfbar.
    evidence: str = Field(
        description=(
            "Wörtliches, kurzes Zitat aus dem Seitentext, auf das sich die "
            "Verfügbarkeitsaussage stützt. Leerer String, wenn es keins gibt."
        )
    )
