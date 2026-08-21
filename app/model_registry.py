"""
Rejestr modeli AI dla całego projektu — jedno miejsce, z którego kod czyta,
jaki model użyć i ile to kosztuje. Wzorzec identyczny do `tool_registry.py`/
`skill_registry.py`: config YAML jest źródłem prawdy, kod tylko odczytuje.

`config/models.yaml` — jakie modele istnieją, jaki mają ID, jaka cena.
`config/model_tiers.yaml` — który "caller" (identyfikator wywołania w kodzie,
np. "web_answer.answer") używa którego poziomu (high/low), i który model
odpowiada każdemu poziomowi.

Powstało z realnej dziury: model AI był wpisany na trwałe w 11 miejscach w
kodzie, zmiana wymagała grepowania po całym repo, a koszt wywołania SDK był
liczony zawsze wg cennika Opusa niezależnie od realnie użytego modelu.

Fail-closed w dwóch miejscach: nieznany `caller` -> tier "high" (lepiej
przepłacić niż przepuścić błędny materiał na słabszym modelu); nieznany
tier/rola -> "opus_5". Uszkodzony/brakujący plik konfiguracji degraduje się
do tych samych bezpiecznych domyślnych, nigdy nie rzuca wyjątku.
"""

from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent
MODELS_PATH = APP_DIR / "config" / "models.yaml"
TIERS_PATH = APP_DIR / "config" / "model_tiers.yaml"

DEFAULT_TIER = "high"
DEFAULT_ROLE = "opus_5"


def _load_yaml(path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def load_models(path=MODELS_PATH):
    return _load_yaml(path)


def load_tiers(path=TIERS_PATH):
    return _load_yaml(path)


def tier_for_caller(caller, path=TIERS_PATH):
    """Identyfikator wywołania (np. "web_answer.answer") -> "high"/"low".
    Nieznany caller -> DEFAULT_TIER (fail-closed)."""
    tiers = load_tiers(path).get("tiers") or {}
    return tiers.get(caller, DEFAULT_TIER)


def role_for_tier(tier, path=TIERS_PATH):
    """"high"/"low" -> rola w models.yaml (np. "opus_5").
    Nieznany tier -> DEFAULT_ROLE (fail-closed)."""
    poziomy = load_tiers(path).get("poziomy") or {}
    return poziomy.get(tier, DEFAULT_ROLE)


def model_id(role, provider="anthropic", path=MODELS_PATH):
    """Rola (np. "opus_5") -> ID modelu Anthropic (np. "claude-opus-5").
    Nieznana rola -> ID roli domyślnej, nie wyjątek."""
    modele = load_models(path).get(provider) or {}
    wpis = modele.get(role) or modele.get(DEFAULT_ROLE) or {}
    return wpis.get("id")


def pricing(role, provider="anthropic", path=MODELS_PATH):
    """Rola -> (input_per_million, output_per_million) w USD.
    Nieznana rola -> cennik roli domyślnej."""
    modele = load_models(path).get(provider) or {}
    wpis = modele.get(role) or modele.get(DEFAULT_ROLE) or {}
    return wpis.get("input_per_million", 0.0), wpis.get("output_per_million", 0.0)


def resolve(caller, tiers_path=TIERS_PATH, models_path=MODELS_PATH):
    """Jedno wywołanie robi całą ścieżkę: caller -> tier -> rola -> ID modelu.
    Zwraca (rola, model_id) — rola potrzebna dalej do cost_estimator.pricing()."""
    tier = tier_for_caller(caller, tiers_path)
    role = role_for_tier(tier, tiers_path)
    return role, model_id(role, path=models_path)


if __name__ == "__main__":
    import sys

    caller = sys.argv[1] if len(sys.argv) > 1 else "task_thinker.think"
    role, model = resolve(caller)
    print(f"caller={caller} -> tier={tier_for_caller(caller)} -> role={role} -> model={model}")
    print("cennik (USD/1M):", pricing(role))
