"""
Dokonczenie zakladania repozytorium projektu: GitHub + zapis adresow w Projectly.

Podzial pracy (swiadomy, zeby nie duplikowac gita):
  - repo_workspace.przygotuj()  -> zaklada repozytorium lokalnie (git init,
    commit "00 - pusty") w folderze projektow (config new_projects_root),
  - agentic_worker              -> kopiuje wiedze z Projectly i uruchamia subagenta,
  - repo_publish.zamknij()      -> commituje prace wg konwencji,
  - TEN modul                   -> zaklada repozytorium na GitHubie, wypycha
    galaz glowna i zapisuje OBA adresy w ustawieniach projektu (MCP
    zbot_set_project_repo), zeby kolejne zadania trafialy juz prosto do kodu.

Dostep do GitHuba (kolejnosc prob):
  1. GITHUB_TOKEN z secrets/.env  -> REST API (urllib, zero nowych zaleznosci),
  2. `gh repo create`             -> gdy ktos zalogowal GitHub CLI na maszynie.
Brak obu -> repozytorium zostaje LOKALNE, a wynik mowi wprost, czego brakuje.
Zadne ciche "udalo sie": bez adresu na GitHubie nie zapisujemy tez nic w Projectly.
"""

import json
import os
import subprocess
import urllib.error
import urllib.request

import repo_publish

GITHUB_API = "https://api.github.com"
TIMEOUT_API = 30


def _run(cmd, cwd, runner, timeout=300):
    return runner(cmd, cwd=str(cwd), capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=timeout)


def _blad(wynik, domyslny="nieznany blad"):
    tekst = ((getattr(wynik, "stderr", "") or "") + (getattr(wynik, "stdout", "") or "")).strip()
    return tekst.splitlines()[-1] if tekst else domyslny


def _adres_z_api(dane):
    return (dane or {}).get("clone_url") or (dane or {}).get("html_url")


def utworz_przez_api(nazwa, config, opener=urllib.request.urlopen):
    """Tworzy repozytorium na GitHubie przez REST API. Zwraca {"ok", "url"/"powod"}.

    `opener` wstrzykiwalny, zeby test dymny nie dotykal sieci."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"ok": False, "powod": "brak GITHUB_TOKEN w sekretach maszyny"}

    owner = (config or {}).get("github_owner")
    url = f"{GITHUB_API}/orgs/{owner}/repos" if owner else f"{GITHUB_API}/user/repos"
    payload = json.dumps({"name": nazwa, "private": True,
                          "description": "Repozytorium projektu zalozone przez wirtualnego pracownika"})
    request = urllib.request.Request(
        url, data=payload.encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "wirtualny-pracownik"})
    try:
        with opener(request, timeout=TIMEOUT_API) as odpowiedz:
            dane = json.loads(odpowiedz.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "powod": f"GitHub odrzucil utworzenie repozytorium (HTTP {exc.code})"}
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return {"ok": False, "powod": f"nie udalo sie polaczyc z GitHubem: {exc}"}

    adres = _adres_z_api(dane)
    return {"ok": True, "url": adres} if adres else {"ok": False, "powod": "GitHub nie zwrocil adresu repozytorium"}


def utworz_przez_gh(nazwa, repo_path, config, runner=subprocess.run):
    """Tworzy repozytorium przez GitHub CLI (gdy ktos zrobil `gh auth login`)."""
    gh = repo_publish.znajdz_gh()
    if not gh:
        return {"ok": False, "powod": "GitHub CLI nie jest zainstalowany ani zalogowany"}

    owner = (config or {}).get("github_owner")
    pelna_nazwa = f"{owner}/{nazwa}" if owner else nazwa
    wynik = _run([gh, "repo", "create", pelna_nazwa, "--private", "--source", ".", "--push"],
                 repo_path, runner)
    if getattr(wynik, "returncode", 1) != 0:
        return {"ok": False, "powod": f"gh repo create: {_blad(wynik)}"}
    return {"ok": True, "url": f"https://github.com/{pelna_nazwa}", "wypchniete": True}


def _wypchnij(repo_path, url, base_branch, runner):
    _run(["git", "remote", "remove", "origin"], repo_path, runner)
    dodanie = _run(["git", "remote", "add", "origin", url], repo_path, runner)
    if getattr(dodanie, "returncode", 1) != 0:
        return {"ok": False, "powod": f"nie moge ustawic zdalnego repozytorium: {_blad(dodanie)}"}
    push = _run(["git", "push", "-u", "origin", base_branch], repo_path, runner)
    if getattr(push, "returncode", 1) != 0:
        return {"ok": False, "powod": f"push na GitHuba nie powiodl sie: {_blad(push)}"}
    return {"ok": True}


def dokoncz(client, task, sandbox, runner=subprocess.run, opener=urllib.request.urlopen):
    """Zaklada repozytorium na GitHubie i zapisuje adresy w Projectly. Nigdy nie rzuca.

    Zwraca {"ok", "url", "powod", "zapisane_w_projectly"}. ok=False oznacza, ze
    repozytorium zostalo LOKALNE — zadanie ma wtedy trafic do czlowieka."""
    wynik = {"ok": False, "url": None, "powod": "", "zapisane_w_projectly": False}
    if not sandbox or not sandbox.get("ok") or sandbox.get("tryb") != "init":
        wynik["powod"] = "to nie jest zakladanie nowego repozytorium"
        return wynik

    project_id = (task or {}).get("project_id")
    if client is None or not project_id:
        wynik["powod"] = "brak projektu w Projectly, nie mam gdzie zapisac adresow"
        return wynik

    config = sandbox.get("config") or {}
    repo_path = sandbox["path"]
    base_branch = sandbox.get("base_branch") or "main"
    nazwa = os.path.basename(str(repo_path).rstrip("\\/"))

    utworzenie = utworz_przez_api(nazwa, config, opener=opener)
    if not utworzenie["ok"]:
        powod_api = utworzenie["powod"]
        utworzenie = utworz_przez_gh(nazwa, repo_path, config, runner=runner)
        if not utworzenie["ok"]:
            wynik["powod"] = (f"repozytorium zostalo lokalnie — {powod_api}; "
                              f"{utworzenie['powod']}")
            return wynik

    wynik["url"] = utworzenie["url"]
    if not utworzenie.get("wypchniete"):
        push = _wypchnij(repo_path, utworzenie["url"], base_branch, runner)
        if not push["ok"]:
            wynik["powod"] = push["powod"]
            return wynik

    try:
        client.set_project_repo(project_id, utworzenie["url"], str(repo_path))
        wynik["zapisane_w_projectly"] = True
    except Exception as exc:  # noqa: BLE001 — repozytorium juz istnieje, to tylko zapis adresu
        wynik["powod"] = f"repozytorium powstalo, ale nie zapisalem adresow w Projectly: {exc}"
        return wynik

    wynik["ok"] = True
    wynik["powod"] = f"repozytorium {utworzenie['url']} zalozone i zapisane w projekcie"
    return wynik
