"""
Krok 3 bootstrapu (SKALOWANIE.md sekcja 4): odczytuje przypisaną rolę,
zapisuje lokalnie, ogłasza się w Projectly przez pierwszy status na żywo.
Uruchamiane raz, ręcznie, przy dołączaniu nowego komputera.

Użycie:
    python bootstrap_register.py dev
    python bootstrap_register.py marketing
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from live_status_publisher import publish
from projectly_client import get_client

ROLE_CONFIG_PATH = Path(__file__).parent / "config" / "role.json"
VALID_ROLES = {"dev", "marketing", "admin", "asystent", "strateg"}


def register(role):
    if role not in VALID_ROLES:
        print(f"Nieznana rola '{role}'. Oczekiwano jednej z: {', '.join(sorted(VALID_ROLES))}")
        sys.exit(1)

    ROLE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLE_CONFIG_PATH.write_text(json.dumps({"role": role}, ensure_ascii=False, indent=2), encoding="utf-8")

    client = get_client()
    status = publish(client, role=role)
    print(f"Zarejestrowano komputer jako rola '{role}'. Pierwszy status na żywo:")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Użycie: python bootstrap_register.py <rola>")
        print(f"Dostępne role: {', '.join(sorted(VALID_ROLES))}")
        sys.exit(1)
    register(sys.argv[1])
