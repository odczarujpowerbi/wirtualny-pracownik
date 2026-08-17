"""
Klasyfikuje planowaną akcję jako zielona/żółta/czerwona/bounded_red wg
approval_policy.yaml (PLAN-WDROZENIA.md sekcja 3, SKRYPTY.md kategoria C).

Celowo BEZ wywołania AI — to czysta reguła deterministyczna (sekcja 12,
"warstwa Python bez AI"). Nieznana akcja = red, nigdy nie zgadujemy w dół.
"""

from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).parent / "config" / "approval_policy.yaml"


def load_policy(path=POLICY_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify(action_type, policy=None):
    """Zwraca 'green' | 'yellow' | 'red'. Nieznana akcja -> 'red' (fail-closed)."""
    policy = policy or load_policy()
    return policy.get("action_risk", {}).get(action_type, "red")


def bounded_red_limit(action_type, policy=None):
    """Zwraca definicję granicy bounded_red dla akcji, albo None jeśli brak
    (czyli akcja pozostaje zwykłym czerwonym, sekcja 3)."""
    policy = policy or load_policy()
    return policy.get("bounded_red", {}).get(action_type)


def validator_requirements(action_type, policy=None):
    """Ile walidatorów i jaki próg zgody dla żółtej akcji tego typu."""
    policy = policy or load_policy()
    thresholds = policy.get("validator_thresholds", {})
    return thresholds.get(action_type, thresholds.get("default", {"validator_count": 3, "required_agreement": 2}))


if __name__ == "__main__":
    policy = load_policy()
    for action in ["read_file", "git_commit_branch", "budget_change", "unknown_action"]:
        print(action, "->", classify(action, policy))
