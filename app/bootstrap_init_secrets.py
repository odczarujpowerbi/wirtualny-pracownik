"""
Tworzy jedno, scentralizowane miejsce na dostępy — `secrets/.env` i
szkielety integracji MCP (`secrets/mcp/*.json`) — zamiast ręcznego
kopiowania plików z pamięci na każdej nowej maszynie. Odpowiedź na wprost
zadane wymaganie: "skrypt wyzwalający je tworzy, potem człowiek je
uzupełnia, a maszyna wykonuje resztę za nas".

Uruchom RAZ, zaraz po `pip install -r requirements.txt`:
    python bootstrap_init_secrets.py

`secrets/` jest w `.gitignore` — te pliki nigdy nie trafiają do repo,
niezależnie od tego, na której maszynie je wypełnisz.

Idempotentne: NIGDY nie nadpisuje istniejącego pliku, tylko tworzy
brakujące. Bezpieczne do wielokrotnego uruchomienia — np. gdy dojdzie
nowa integracja do `config/integrations.yaml`, uruchom ponownie: dostaniesz
tylko szablon dla NOWEJ integracji, pliki z już wpisanymi danymi zostają
nietknięte.
"""

import json
import shutil
from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent
SECRETS_DIR = APP_DIR / "secrets"
ENV_EXAMPLE_PATH = APP_DIR / ".env.example"
ENV_TARGET_PATH = SECRETS_DIR / ".env"
MCP_DIR = SECRETS_DIR / "mcp"
INTEGRATIONS_PATH = APP_DIR / "config" / "integrations.yaml"


def ensure_env_file():
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_TARGET_PATH.exists():
        return {"path": str(ENV_TARGET_PATH), "created": False}
    shutil.copy(ENV_EXAMPLE_PATH, ENV_TARGET_PATH)
    return {"path": str(ENV_TARGET_PATH), "created": True}


def load_integrations(path=INTEGRATIONS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("integrations", {})


def ensure_mcp_templates():
    """Jeden szablon JSON na integrację, dla której `integrations.yaml`
    deklaruje mechanizm MCP — reużywa istniejący rejestr integracji zamiast
    trzymać drugą, osobną listę, która mogłaby się z nim rozjechać."""
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    integrations = load_integrations()

    created, skipped = [], []
    for name, info in integrations.items():
        if "MCP" not in (info.get("mechanism") or ""):
            continue

        target = MCP_DIR / f"{name}.json"
        if target.exists():
            skipped.append(name)
            continue

        template = {
            "integration": name,
            "mechanism": info.get("mechanism", ""),
            "access_oczekiwany": info.get("access", ""),
            "notatki_z_integrations_yaml": info.get("notes", ""),
            "credentials": {
                "TODO": (
                    "Wypełnij ręcznie — dokładne pola zależą od konkretnej konfiguracji MCP "
                    "(adres serwera, token itp.). Nigdy nie commituj tego pliku."
                )
            },
        }
        target.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(name)

    return {"created": created, "skipped_existing": skipped}


def run():
    env_result = ensure_env_file()
    mcp_result = ensure_mcp_templates()

    print(f"Plik .env: {'utworzony' if env_result['created'] else 'już istniał, pominięto'} -> {env_result['path']}")
    print(f"Szablony MCP utworzone: {mcp_result['created'] or '(brak nowych)'}")
    print(f"Szablony MCP pominięte (już istniały): {mcp_result['skipped_existing'] or '(brak)'}")
    print(f"\nWypełnij ręcznie pliki w: {SECRETS_DIR}")
    return {"env": env_result, "mcp": mcp_result}


if __name__ == "__main__":
    run()
