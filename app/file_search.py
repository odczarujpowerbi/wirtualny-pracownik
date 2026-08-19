"""
Szybkie czytanie/przeszukiwanie plików dla skryptów deterministycznych (nie
modelu). Model, gdy działa przez Claude Code, ma własne szybkie czytanie — ten
moduł jest dla WORKERÓW/skryptów, które muszą coś znaleźć w repo klienta bez
angażowania modelu (np. znajdź plik .pbip, znajdź miarę po nazwie w TMDL).

Backend: ripgrep (`rg`, jeśli w PATH — bardzo szybki), z czystym fallbackiem w
Pythonie, gdy rg nie ma. Wyniki ZAWSZE ograniczone (max_results) — nie ładujemy
całego drzewa do pamięci (reguła wydajności: pobieraj subset, nie kolekcję).
"""

import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_MAX_RESULTS = 100
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _rg_available():
    return shutil.which("rg") is not None


def find_files(root, name_glob, max_results=200):
    """Ścieżki plików pasujących do wzorca glob (np. '*.pbip', '**/*.tmdl').
    Zwraca listę str, ograniczoną do max_results."""
    base = Path(root)
    if not base.exists():
        return []
    results = []
    for path in base.rglob(name_glob):
        if path.is_file() and not any(part in _SKIP_DIRS for part in path.parts):
            results.append(str(path))
            if len(results) >= max_results:
                break
    return results


def _search_ripgrep(root, pattern, globs, max_results, ignore_case):
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never", "-m", str(max_results)]
    if ignore_case:
        cmd.append("--ignore-case")
    for g in globs or []:
        cmd += ["--glob", g]
    # Te same pomijane katalogi co w fallbacku Pythona — spójny wynik niezależnie
    # od backendu (katalog tymczasowy nie ma .gitignore, więc rg sam ich nie pomija).
    for d in _SKIP_DIRS:
        cmd += ["--glob", f"!**/{d}/**"]
    cmd += [pattern, str(root)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=30)
    # rg: kod 1 = brak trafień (nie błąd), 2 = błąd rzeczywisty.
    if proc.returncode == 2:
        raise RuntimeError((proc.stderr or "ripgrep error").strip())
    hits = []
    for line in (proc.stdout or "").splitlines():
        path, _, rest = line.partition(":")
        lineno, _, text = rest.partition(":")
        if path and lineno.isdigit():
            hits.append({"path": path, "line": int(lineno), "text": text.strip()})
            if len(hits) >= max_results:
                break
    return hits


def _search_python(root, pattern, globs, max_results, ignore_case):
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    globs = globs or ["*"]
    base = Path(root)
    hits = []
    for g in globs:
        for path in base.rglob(g):
            if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
                continue
            try:
                with path.open(encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, start=1):
                        if regex.search(line):
                            hits.append({"path": str(path), "line": lineno, "text": line.strip()})
                            if len(hits) >= max_results:
                                return hits
            except OSError:
                continue
    return hits


def search_content(root, pattern, globs=None, max_results=DEFAULT_MAX_RESULTS, ignore_case=True):
    """Szuka wzorca (regex) w treści plików pod `root`. Zwraca listę
    {path, line, text}, ograniczoną do max_results. Używa ripgrep, gdy dostępny,
    inaczej czystego Pythona — ten sam kształt wyniku."""
    if not Path(root).exists():
        return []
    if _rg_available():
        try:
            return _search_ripgrep(root, pattern, globs, max_results, ignore_case)
        except (subprocess.SubprocessError, RuntimeError, OSError):
            pass  # ripgrep zawiódł — spadamy na Pythona
    return _search_python(root, pattern, globs, max_results, ignore_case)


if __name__ == "__main__":
    import sys

    where = sys.argv[1] if len(sys.argv) > 1 else "."
    what = sys.argv[2] if len(sys.argv) > 2 else "def "
    for hit in search_content(where, what, max_results=20):
        print(f"{hit['path']}:{hit['line']}: {hit['text']}")
