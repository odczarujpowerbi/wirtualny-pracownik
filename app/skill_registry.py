"""
Rejestr dostępnych skilli/narzędzi z metadanymi — opis, ryzyko, wersja
(SKRYPTY.md kategoria J). Wczytywany przy starcie runnera. Wersja per skill
jest podstawą wersjonowania floty (SKALOWANIE.md sekcja 7).
"""

from pathlib import Path

import yaml

MANIFEST_PATH = Path(__file__).parent / "config" / "skills_manifest.yaml"


def load_skills(path=MANIFEST_PATH):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {s["name"]: s for s in data.get("skills", [])}


def get_skill(name, skills=None):
    skills = skills or load_skills()
    return skills.get(name)


if __name__ == "__main__":
    for name, meta in load_skills().items():
        print(name, meta["version"], meta["risk"])
