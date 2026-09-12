"""
Scalanie pracy agenta do galezi glownej i publikacja jej dalej.

Decyzja wlasciciela 12.09.2026 (przeplyw):
  1. praca powstaje na galezi zadania w piaskownicy,
  2. bramka jakosci (repo_quality_gate.py) mowi, czy testy przechodza,
  3. ZIELONA -> scalamy do galezi glownej i publikujemy,
  4. CZERWONA -> galaz zostaje, glowna nietknieta, czlowiek dostaje zadanie.

Gdzie ladzie wynik:
  - ZRODLO to folder firmowy projektu (repoLocalPath z Projectly). Aktualizujemy
    go `fetch` + `merge --ff-only` i TYLKO wtedy, gdy jego drzewo robocze jest
    czyste i stoi na galezi glownej. Brudne/rozjechane -> nie ruszamy, zglaszamy
    powod. Folder lezy w OneDrive, wiec kazda inna operacja to proszenie sie o
    uszkodzenie repozytorium.
  - KOPIA to GitHub (repoUrl z Projectly). Push idzie WPROST z piaskownicy, wiec
    nie zalezy od stanu kopii firmowej.

Nigdy nie rzuca: kazdy krok zwraca opis tego, co sie stalo.
"""

import subprocess

REMOTE_GITHUB = "github"


def _run(cmd, cwd, runner, timeout=180):
    return runner(cmd, cwd=str(cwd), capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=timeout)


def _blad(wynik, domyslny="nieznany blad git"):
    tekst = ((getattr(wynik, "stderr", "") or "") + (getattr(wynik, "stdout", "") or "")).strip()
    return tekst.splitlines()[-1] if tekst else domyslny


def scal_w_piaskownicy(sandbox, runner=subprocess.run):
    """Przelacza piaskownice na galaz glowna i scala do niej galaz zadania."""
    path = sandbox["path"]
    base = sandbox.get("base_branch") or "main"
    branch = sandbox["branch"]

    checkout = _run(["git", "checkout", base], path, runner)
    if getattr(checkout, "returncode", 1) != 0:
        return {"ok": False, "powod": f"nie moge przejsc na {base}: {_blad(checkout)}"}

    merge = _run(["git", "merge", "--no-ff", branch, "-m", f"Scalenie pracy z galezi {branch}"], path, runner)
    if getattr(merge, "returncode", 1) != 0:
        # Konflikt scalania zostawiamy CZLOWIEKOWI: przerywamy scalanie, zeby
        # piaskownica nie zostala w stanie "w trakcie merge".
        _run(["git", "merge", "--abort"], path, runner)
        return {"ok": False, "powod": f"konflikt przy scalaniu do {base}: {_blad(merge)}"}
    return {"ok": True, "powod": f"scalono {branch} do {base}"}


def zaktualizuj_zrodlo(sandbox, runner=subprocess.run):
    """Dociaga scalona prace do folderu firmowego (zrodla). Tylko przy czystym
    drzewie roboczym i na galezi glownej — inaczej zostawiamy jak jest."""
    zrodlo = sandbox.get("zrodlo")
    base = sandbox.get("base_branch") or "main"
    if not zrodlo or str(zrodlo).startswith(("http", "git@")):
        return {"ok": False, "pominiete": True, "powod": "zrodlem jest zdalne repozytorium, nie folder"}

    status = _run(["git", "status", "--porcelain"], zrodlo, runner)
    if getattr(status, "returncode", 1) != 0:
        return {"ok": False, "powod": f"nie moge sprawdzic stanu folderu firmowego: {_blad(status)}"}
    if (getattr(status, "stdout", "") or "").strip():
        return {"ok": False, "powod": "folder firmowy ma niezapisane zmiany — nie dotykam go"}

    galaz = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], zrodlo, runner)
    if (getattr(galaz, "stdout", "") or "").strip() != base:
        return {"ok": False, "powod": f"folder firmowy nie stoi na galezi {base} — nie dotykam go"}

    fetch = _run(["git", "fetch", sandbox["path"], base], zrodlo, runner)
    if getattr(fetch, "returncode", 1) != 0:
        return {"ok": False, "powod": f"nie moge pobrac zmian z piaskownicy: {_blad(fetch)}"}

    merge = _run(["git", "merge", "--ff-only", "FETCH_HEAD"], zrodlo, runner)
    if getattr(merge, "returncode", 1) != 0:
        return {"ok": False, "powod": f"folder firmowy rozjechal sie z praca agenta: {_blad(merge)}"}
    return {"ok": True, "powod": "folder firmowy zaktualizowany"}


def wypchnij_kopie(sandbox, runner=subprocess.run):
    """Push galezi glownej na GitHuba (kopia). Brak adresu -> pomijamy."""
    url = sandbox.get("github_url")
    base = sandbox.get("base_branch") or "main"
    path = sandbox["path"]
    if not url:
        return {"ok": False, "pominiete": True, "powod": "projekt nie ma adresu na GitHubie"}

    # Remote moze juz istniec (powtorzone zadanie w tej samej piaskownicy).
    _run(["git", "remote", "remove", REMOTE_GITHUB], path, runner)
    dodanie = _run(["git", "remote", "add", REMOTE_GITHUB, url], path, runner)
    if getattr(dodanie, "returncode", 1) != 0:
        return {"ok": False, "powod": f"nie moge dodac zdalnego repozytorium: {_blad(dodanie)}"}

    push = _run(["git", "push", REMOTE_GITHUB, f"{base}:{base}"], path, runner, timeout=300)
    if getattr(push, "returncode", 1) != 0:
        return {"ok": False, "powod": f"push na GitHuba nie powiodl sie: {_blad(push)}"}
    return {"ok": True, "powod": "kopia na GitHubie zaktualizowana"}


def opublikuj(sandbox, runner=subprocess.run):
    """Pelna publikacja po zielonej bramce: scalenie, zrodlo, kopia.

    Zwraca {"ok", "powod", "zrodlo", "kopia"} — ok=False tylko wtedy, gdy nie
    udalo sie samo SCALENIE. Nieudana aktualizacja zrodla albo kopii jest
    raportowana, ale nie unieważnia pracy: commit i tak istnieje w piaskownicy
    i na galezi zadania."""
    scalenie = scal_w_piaskownicy(sandbox, runner)
    if not scalenie["ok"]:
        return {"ok": False, "powod": scalenie["powod"], "zrodlo": None, "kopia": None}
    return {
        "ok": True,
        "powod": scalenie["powod"],
        "zrodlo": zaktualizuj_zrodlo(sandbox, runner),
        "kopia": wypchnij_kopie(sandbox, runner),
    }
