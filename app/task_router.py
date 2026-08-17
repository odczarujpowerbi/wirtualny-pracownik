"""
Dopasowuje zadanie do właściciela na podstawie słów kluczowych z
clients_routing.yaml (PLAN-WDROZENIA.md sekcja 11, SKALOWANIE.md sekcja 2 —
mapowanie żyje w configu firmy, nie na sztywno w kodzie).

Czysty Python bez AI (sekcja 12) — AI wchodzi dopiero gdy to dopasowanie
jest niejednoznaczne (np. tytuł zadania pasuje do dwóch klientów naraz).
"""

from pathlib import Path

import yaml

ROUTING_PATH = Path(__file__).parent / "config" / "clients_routing.yaml"


def load_routing(path=ROUTING_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def route_task(title, routing=None):
    """Zwraca (owner, confident: bool). confident=False -> routing_confidence_check.py
    (PLAN-WDROZENIA.md sekcja 11) powinien eskalować, nie zgadywać dalej."""
    routing = routing or load_routing()
    title_lower = title.lower()

    matches = []
    for route in routing.get("routes", []):
        if any(keyword in title_lower for keyword in route["keywords"]):
            matches.append(route["owner"])

    if len(matches) == 1:
        return matches[0], True
    if len(matches) > 1:
        return routing.get("default_owner", "unassigned_pool"), False
    return routing.get("default_owner", "unassigned_pool"), False


if __name__ == "__main__":
    routing = load_routing()
    for sample_title in ["Indeka: przepięcie raportu", "Magnapharm Fabric", "coś zupełnie innego"]:
        print(sample_title, "->", route_task(sample_title, routing))
