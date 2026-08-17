"""
Generuje wiele wariantów tekstu reklamowego (nagłówek, treść, CTA) do testów
Meta/TikTok Ads, korzystając z buyer person z ../persony-sprzedaz/ jako
kontekstu (PLAN-WDROZENIA.md sekcja 20). Zielone — sam tekst to draft,
dopiero uruchomienie go jako testu (ad_set_launcher.py) wydaje pieniądze.

Wymaga pakietu `anthropic` i ANTHROPIC_API_KEY — bez klucza zwraca jasny
stub zamiast fałszywych wariantów (ten sam wzorzec fail-closed co
validators.py::validator_visual).
"""

import json
import os
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem ANTHROPIC_API_KEY

PERSONY_DIR = Path(__file__).parent.parent.parent / "persony-sprzedaz"


def load_persona_context(persona_file="persony-odczaruj.md"):
    path = PERSONY_DIR / persona_file
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def generate_variants(brief, persona_file="persony-odczaruj.md", n_variants=3):
    """brief: krótki opis oferty/produktu do zareklamowania.
    Zwraca listę wariantów {"headline":..., "body":..., "cta":..., "target_persona":...}
    albo, bez klucza API, jasny stub — nie zmyślone teksty."""
    persona_context = load_persona_context(persona_file)
    if persona_context is None:
        return {
            "error": f"Brak pliku person: {persona_file} w {PERSONY_DIR} — nie mogę dopasować tekstu do odbiorcy."
        }

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "error": "Brak ANTHROPIC_API_KEY — generator nie tworzy wariantów bez modelu (do podłączenia na docelowej maszynie).",
            "would_use_persona_file": persona_file,
            "brief": brief,
        }

    try:
        import anthropic
    except ImportError:
        return {"error": "Pakiet 'anthropic' niezainstalowany (pip install -r requirements.txt)."}

    prompt = (
        f"Kontekst buyer person (do dopasowania tonu i argumentów):\n{persona_context}\n\n"
        f"Brief oferty: {brief}\n\n"
        f"Wygeneruj {n_variants} różnych wariantów reklamy (różne kąty/persony z powyższego kontekstu, "
        "nie ten sam tekst przeformułowany). Zwróć WYŁĄCZNIE poprawny JSON: lista obiektów z polami "
        "headline, body, cta, target_persona (która persona z pliku jest głównym adresatem)."
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "Model nie zwrócił poprawnego JSON.", "raw_response": text}


if __name__ == "__main__":
    print(json.dumps(generate_variants("Mentoring 1:1 Power BI dla managerów"), ensure_ascii=False, indent=2))
