"""
Bramka jakosci repozytorium: czy prace agenta wolno scalic do galezi glownej.

Decyzja wlasciciela 12.09.2026: praca agenta idzie na osobna galaz, a po ZIELONEJ
bramce jest scalana automatycznie. Ten modul odpowiada wylacznie na pytanie
"czy testy przechodza" — samo scalanie robi repo_publish.py.

Polecenie bierzemy z config/repos.yaml (quality_gate). Puste = wykrywamy po tym,
co w repozytorium realnie jest:
  - self_check.py          -> python self_check.py   (konwencja tego repo)
  - package.json ze skryptem "test" -> npm test
  - pytest.ini / tests/    -> pytest

Repozytorium bez zadnych testow przechodzi bramke (zielone, powod opisany) —
inaczej nowy projekt nigdy nie moglby niczego scalic. To jest swiadomy wybor,
nie przeoczenie: bramka ma blokowac ZEPSUTE testy, nie karac za ich brak.
"""

import json
import subprocess
from pathlib import Path

DOMYSLNY_TIMEOUT = 900


def _run(cmd, cwd, timeout, runner):
    return runner(cmd, cwd=str(cwd), capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=timeout)


def _ma_skrypt_test(repo_path):
    """package.json ze skryptem "test" (i to nie zaslepka npm init)."""
    plik = repo_path / "package.json"
    if not plik.is_file():
        return False
    try:
        dane = json.loads(plik.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    skrypt = (dane.get("scripts") or {}).get("test") or ""
    return bool(skrypt) and "no test specified" not in skrypt


def wykryj_polecenie(repo_path, config=None):
    """Polecenie bramki dla tego repozytorium albo None, gdy testow nie ma."""
    jawne = (config or {}).get("quality_gate")
    if jawne:
        return jawne if isinstance(jawne, list) else str(jawne).split()

    repo_path = Path(repo_path)
    if (repo_path / "self_check.py").is_file():
        return ["python", "self_check.py"]
    if (repo_path / "app" / "self_check.py").is_file():
        return ["python", "app/self_check.py"]
    if _ma_skrypt_test(repo_path):
        return ["npm", "test"]
    if (repo_path / "pytest.ini").is_file() or (repo_path / "tests").is_dir():
        return ["pytest", "-q"]
    return None


def sprawdz(repo_path, config=None, runner=subprocess.run):
    """Uruchamia bramke. Nigdy nie rzuca.

    Zwraca {"zielona": bool, "polecenie": str|None, "powod": str, "log": str}."""
    config = config or {}
    polecenie = wykryj_polecenie(repo_path, config)
    if not polecenie:
        return {"zielona": True, "polecenie": None,
                "powod": "repozytorium nie ma testów — nie ma czego sprawdzić", "log": ""}

    timeout = int(config.get("quality_gate_timeout_seconds", DOMYSLNY_TIMEOUT))
    try:
        wynik = _run(polecenie, repo_path, timeout, runner)
    except subprocess.TimeoutExpired:
        return {"zielona": False, "polecenie": " ".join(polecenie),
                "powod": f"testy nie skończyły się w {timeout}s", "log": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        # Brak narzedzia (np. npm) NIE moze przepuscic pracy jako zielonej:
        # nie wiemy, czy testy przechodza, wiec fail-closed.
        return {"zielona": False, "polecenie": " ".join(polecenie),
                "powod": f"nie udało się uruchomić testów: {exc}", "log": ""}

    log = ((getattr(wynik, "stdout", "") or "") + (getattr(wynik, "stderr", "") or "")).strip()
    if getattr(wynik, "returncode", 1) == 0:
        return {"zielona": True, "polecenie": " ".join(polecenie),
                "powod": "testy przeszły", "log": log[-2000:]}
    return {"zielona": False, "polecenie": " ".join(polecenie),
            "powod": "testy nie przeszły", "log": log[-2000:]}
