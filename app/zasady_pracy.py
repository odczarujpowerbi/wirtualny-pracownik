"""
Standardy pracy wstrzykiwane do promptu subagenta, to samo zrodlo, z ktorego
korzysta czlowiek i Claude Code w tym repo: pliki `.claude/rules/*.md`.

Powod: subagent (agentic_worker.py) dostawal kontekst firmy, projektu i wiedzy z
Projectly, ale ZERO standardow wykonania, nie wiedzial, jak nazwac commit
("NN - opis po polsku"), ze zmiany ida branchem i PR-em, nigdy prosto do main,
ze plik ponad 300 linii sie refaktoruje, ze em dash jest zakazany, ze raport
Power BI ma format PBIP z PBIR i canvas 1920x1080. Ta wiedza nie wynika z tresci
zadania ani z kodu, wiec musi przyjsc z zewnatrz, dokladnie jak kontekst firmy
(kontekst_firmy.py, ten sam wzorzec).

Zasady sa WKLEJANE DOSLOWNIE, nie streszczane: streszczenie rozjechaloby sie z
plikiem regul przy pierwszej jego zmianie. `.claude/rules/` zostaje JEDYNYM
zrodlem prawdy, ten modul jest tylko doborem i hydraulika.

Dobor jest jawny i przewidywalny:
  - `git-workflow.md`   -> gdy zadanie realnie dotyka repozytorium (praca_w_repo),
  - `coding-rules.md`   -> praca w repo albo tresc zadania wskazuje na kod,
  - `power-bi-standards.md` -> tresc zadania wskazuje na Power BI / PBIP / DAX.
Zadanie "napisz posta na LinkedIn" nie dostaje nic, nie ma po co.

Uzycie:
    python zasady_pracy.py "Popraw walidacje w repo, commituj i zrob PR"
"""

import sys
from pathlib import Path

import env_bootstrap  # noqa: F401, UTF-8 na stdout (Windows)

APP_DIR = Path(__file__).parent
RULES_DIR = APP_DIR.parent / ".claude" / "rules"
MAX_ZNAKOW = 24000

GIT_RULES = "git-workflow.md"
CODE_RULES = "coding-rules.md"
POWER_BI_RULES = "power-bi-standards.md"

# Slowa musza byc jednoznaczne, ten sam wniosek co w kontekst_firmy.MARKI:
# zbyt ogolne slowo (samo "strona", samo "plik") doklejalo standardy kodu do
# zadan czysto tekstowych, czyli placilo tokenami za nic.
#
# Dopasowanie idzie po GRANICY SLOWA (patrz _trafia), nie po zwyklym `in`. Zlapane
# przy pierwszym uruchomieniu tego modulu: "NAPIsz posta na LinkedIn" zawiera "api"
# jako podciag, wiec zadanie czysto tekstowe dostawalo caly plik standardow kodu.
# Slowa sa PRZEDROSTKAMI tokenow: "kod" ma trafiac w "kodu"/"kodzie",
# "aplikacj" w "aplikacja"/"aplikacji".
SLOWA_KOD = ("kod", "repozytorium", "repo", "commit", "branch", "pull request",
             "python", "javascript", "typescript", "react", "node", "aplikacj",
             "skrypt", "refaktor", "bug", "testy jednostkowe", "api", "sql",
             "landing", "git")
SLOWA_POWER_BI = ("power bi", "powerbi", "pbip", "pbix", "pbir", "dax", "tmdl",
                  "semantyczn", "miara", "miary", "dataflow", "fabric", "ibcs")


def _wczytaj(nazwa, rules_dir=RULES_DIR):
    """Fail-soft: brak pliku/katalogu regul -> pusty string (zasady sa dodatkiem
    do promptu, nie warunkiem wykonania zadania)."""
    sciezka = Path(rules_dir) / nazwa
    if not sciezka.is_file():
        return ""
    return sciezka.read_text(encoding="utf-8").strip()


def _trafia(tekst, slowa):
    """Czy ktorekolwiek slowo trafia w tekst na granicy slowa.

    Tekst jest normalizowany do tokenow (wszystko poza znakami alfanumerycznymi
    staje sie spacja), a slowa dopasowywane jako PRZEDROSTKI tokenow: "kod"
    trafia w "kodu", ale nie w "napisz". Frazy wielowyrazowe ("pull request")
    dopasowywane w tekscie znormalizowanym."""
    tokeny = "".join(znak if znak.isalnum() else " " for znak in tekst).split()
    znormalizowany = " ".join(tokeny)
    for slowo in slowa:
        if " " in slowo and slowo in znormalizowany:
            return True
        if " " not in slowo and any(token.startswith(slowo) for token in tokeny):
            return True
    return False


def wykryj_zakres(task, praca_w_repo=False):
    """Nazwy plikow regul, ktore trafia do promptu TEGO zadania."""
    tekst = " ".join(str((task or {}).get(k) or "") for k in
                     ("title", "description", "expected_result", "acceptance_criteria")).lower()
    zakres = []
    if praca_w_repo:
        zakres.append(GIT_RULES)
    if praca_w_repo or _trafia(tekst, SLOWA_KOD):
        zakres.append(CODE_RULES)
    if _trafia(tekst, SLOWA_POWER_BI):
        zakres.append(POWER_BI_RULES)
    return zakres


def blok(task, praca_w_repo=False, rules_dir=RULES_DIR):
    """Blok promptu ze standardami albo "" gdy zadanie ich nie potrzebuje.

    Nie zaczyna sie od "-": CLI Claude Code parsuje pierwszy token argv
    zaczynajacy sie od "-" jako nieznana opcje (zywy incydent 25.08.2026 z
    naglowkiem "--- KONTEKST FIRMY ---", patrz agentic_worker.run)."""
    czesci = []
    for nazwa in wykryj_zakres(task, praca_w_repo):
        tresc = _wczytaj(nazwa, rules_dir)
        if tresc:
            czesci.append(f"### {nazwa}\n{tresc}")
    if not czesci:
        return ""
    blok_tekst = ("STANDARDY OBOWIAZUJACE W TEJ FIRMIE (nie sugestie, praca niezgodna "
                  "z nimi zostanie odrzucona przez bramke jakosci):\n\n" + "\n\n".join(czesci))
    return blok_tekst[:MAX_ZNAKOW]


def main():
    tekst = " ".join(sys.argv[1:]) or "Popraw walidacje w repozytorium i otworz PR"
    task = {"title": tekst}
    for praca_w_repo in (False, True):
        zakres = wykryj_zakres(task, praca_w_repo=praca_w_repo)
        print(f"praca_w_repo={praca_w_repo}: {zakres or '(brak regul)'}, "
              f"{len(blok(task, praca_w_repo=praca_w_repo))} znakow")


if __name__ == "__main__":
    main()
