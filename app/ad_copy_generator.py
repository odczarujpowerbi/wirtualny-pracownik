"""
Generuje wiele wariantów tekstu reklamowego (nagłówek, treść, CTA) do testów
Meta/TikTok Ads, korzystając z realnych buyer person danej marki jako
kontekstu (PLAN-WDROZENIA.md sekcja 20). Zielone — sam tekst to draft,
dopiero uruchomienie go jako testu (ad_set_launcher.py) wydaje pieniądze.

Persony leżą w app/kontekst/persony/<marka>/*.md (kopia z realnych profili
buyer person, patrz app/kontekst/persony/README.md). Poprzednia wersja miała
zaszytą ścieżkę do folderu, który NIE ISTNIEJE na dysku (persony-sprzedaz/) —
dopasowanie do odbiorcy nigdy realnie nie działało, tylko cicho degradowało
się do błędu "brak pliku person". To naprawia ten błąd.

Wymaga pakietu `anthropic` i ANTHROPIC_API_KEY — bez klucza zwraca jasny
stub zamiast fałszywych wariantów (ten sam wzorzec fail-closed co
validators.py::validator_visual).
"""

import json
import os
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem ANTHROPIC_API_KEY
import model_registry

PERSONY_DIR = Path(__file__).parent / "kontekst" / "persony"


def load_persona_context(brand="odczaruj"):
    """Wszystkie profile buyer person danej marki, połączone — model dostaje
    pełny zestaw, żeby sam wybrał, która persona jest głównym adresatem
    (pole target_persona w wyniku), a nie żebyśmy zgadywali to za niego."""
    folder = PERSONY_DIR / brand
    if not folder.is_dir():
        return None
    pliki = sorted(folder.glob("*.md"))
    if not pliki:
        return None
    return "\n\n---\n\n".join(p.read_text(encoding="utf-8") for p in pliki)


def generate_variants(brief, brand="odczaruj", n_variants=3):
    """brief: krótki opis oferty/produktu do zareklamowania. brand: "odczaruj"
    albo "clickless" — którego zestawu person użyć (patrz app/kontekst/persony/).
    Zwraca {"brand": brand, "variants": [{"headline", "body", "cta", "target_persona"}, ...]}
    albo, bez klucza API, jasny stub — nie zmyślone teksty.

    `brand` w wyniku jest tu specjalnie, nie do zgadnięcia później: dwie marki
    mają persony o tym samym imieniu ("Tomek" — inny profil u Odczaruj, inny
    u Clickless), więc odbiór biznesowy (Bożena) MUSI wiedzieć, z którego
    zestawu brać profil person do oceny trafności, żeby nie ocenił materiału
    względem złej osoby."""
    persona_context = load_persona_context(brand)
    if persona_context is None:
        return {"error": f"Brak person marki '{brand}' w {PERSONY_DIR / brand} — nie mogę dopasować tekstu do odbiorcy."}

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "error": "Brak ANTHROPIC_API_KEY — generator nie tworzy wariantów bez modelu (do podłączenia na docelowej maszynie).",
            "would_use_brand": brand,
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
        "headline, body, cta, target_persona (imię persony z pliku, która jest głównym adresatem)."
    )

    client = anthropic.Anthropic()
    _, model = model_registry.resolve("ad_copy_generator.generate")
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text

    try:
        wariant = json.loads(_bez_ogrodzenia_markdown(text))
    except json.JSONDecodeError:
        return {"error": "Model nie zwrócił poprawnego JSON.", "raw_response": text}
    return {"brand": brand, "variants": wariant}


def _bez_ogrodzenia_markdown(text):
    """Model mimo instrukcji 'zwróć WYŁĄCZNIE JSON' czasem owija odpowiedź w
    ogrodzenie markdown (```json ... ```), co wywala json.loads. Zdejmujemy
    ogrodzenie, jeśli jest — realnie napotkane przy pierwszym żywym wywołaniu
    po naprawie ładowania person."""
    oczyszczony = text.strip()
    if oczyszczony.startswith("```"):
        oczyszczony = oczyszczony.split("\n", 1)[-1]
        if oczyszczony.rstrip().endswith("```"):
            oczyszczony = oczyszczony.rstrip()[:-3]
    return oczyszczony.strip()


if __name__ == "__main__":
    print(json.dumps(generate_variants("Mentoring 1:1 Power BI dla managerów"), ensure_ascii=False, indent=2))
