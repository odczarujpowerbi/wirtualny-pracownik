# Instrukcja wdrożenia — krok po kroku

Ten dokument jest dla osoby, która fizycznie usiądzie przy komputerze i uruchomi na nim Wirtualnego Pracownika — niekoniecznie dla osoby technicznej. Czytaj po kolei, od góry, nie przeskakuj kroków. Każdy krok mówi: co robisz, dlaczego, i po czym poznasz, że się udało.

Jeśli w którymś miejscu coś nie zadziała tak, jak opisano — zatrzymaj się, skopiuj cały komunikat błędu (na czerwono/w konsoli) i prześlij go osobie technicznej albo do Claude Code, zamiast zgadywać dalej.

## Zanim zaczniesz — czego będziesz potrzebować

- **Komputer** — Windows 11, minimum 16 GB RAM (lepiej 32 GB), stały dostęp do prądu i internetu. To ma być komputer dedykowany, nie ten, na którym ktoś pracuje codziennie.
- **Karta płatnicza** — do założenia konta z dostępem do API Anthropic (płatność za realne zużycie, z ustawionym limitem — patrz Krok 4).
- **Dostęp do internetu w trakcie całej instalacji.**
- **Lista kont i haseł do zebrania** — zanim zaczniesz, dobrze mieć pod ręką dostęp do: konta Anthropic (API), konta Projectly, konta Microsoft 365 (mail), konta Google, Zoho CRM, zanfia.com, GitHub, MailerLite. Nie wszystkie są potrzebne od razu — w Kroku 4 jest jasno napisane, co jest obowiązkowe na start, a co można dograć później.

## Krok 1 — Przygotowanie komputera

1. Zainstaluj/zaktualizuj Windows 11 do najnowszej wersji.
2. Podłącz komputer na stałe do prądu (nie na baterii) i do internetu — najlepiej kablem, nie Wi-Fi, jeśli to możliwe.
3. Wyłącz usypianie komputera: **Ustawienia → System → Zasilanie → Ekran i uśpienie → nigdy** (dla trybu podłączonego do zasilania).
4. Utwórz dwa konta użytkownika Windows: jedno zwykłe (standardowe) — to będzie konto, na którym pracuje bot — i jedno administratora, używane tylko do instalacji. Nie loguj się na koncie bota jako administrator na co dzień.

**Po czym poznasz, że ten krok się udał:** komputer jest włączony, podłączony do prądu i internetu, ekran się nie wygasza, są dwa konta użytkownika widoczne na ekranie logowania.

## Szybka ścieżka — jedno polecenie zamiast Kroków 2-5

Jeśli nie chcesz klikać przez każdy krok osobno, `bootstrap_all.ps1` robi Kroki 2-5 za Ciebie automatycznie — instaluje git/Python/Claude Code, pobiera projekt, zakłada folder na dostępy, i na koniec pokazuje **czytelne podsumowanie: który krok, ile trwał, czy się udał**:

```powershell
irm https://raw.githubusercontent.com/odczarujpowerbi/szkolenia-powerbi/claude/new-repo-i29t2e/wirtualny-pracownik/app/bootstrap_all.ps1 -OutFile bootstrap_all.ps1
.\bootstrap_all.ps1 -RepoUrl "https://github.com/odczarujpowerbi/szkolenia-powerbi.git"
```

Wygląda to tak (przykład, wszystko się udało):

```
[1/6] Git...
Git już jest zainstalowany: git version 2.43.0
[1/6] Git -> OK (0.6s)

[2/6] Python 3.11+...
...
=== Podsumowanie ===
[OK]   Git                                              0.6s
[OK]   Python 3.11+                                     0.5s
[OK]   Claude Code (CLI)                                1.1s
[OK]   Pobranie repo + zależności Pythona               4.2s
[OK]   Inicjalizacja sekretów (secrets/)                0.1s
[OK]   Test dymny                                       0.2s
```

Krok **wymagany** (git, Python, pobranie repo, sekrety, test dymny), który się nie uda, **zatrzymuje cały przebieg** — nie jedzie dalej na niepełnej instalacji. Claude Code jest **opcjonalny**: jeśli akurat zawiedzie, skrypt tylko ostrzega i leci dalej. Claude Desktop celowo nie jest w tej liście (to instalator z oknem, wymaga klikania) — uruchom go osobno, patrz Krok 2 niżej.

Jeśli wolisz zrozumieć/kontrolować każdy krok osobno (albo coś w szybkiej ścieżce nie zadziała) — czytaj dalej, Kroki 2-5 robią dokładnie to samo, tylko ręcznie.

## Krok 2 — Instalacja programów

Instaluj w tej kolejności. Każdy program pobierasz z oficjalnej strony, klikasz "Dalej"/"Next" z ustawieniami domyślnymi, chyba że napisano inaczej.

**Ważne dla maszyn wirtualnych/Windows Server:** świeża maszyna wirtualna (w odróżnieniu od zwykłego komputera dewelopera) zwykle **nie ma gita** — to pierwsza rzecz, która się wywali, jeśli spróbujesz od razu klonować repozytorium. Jeśli nie masz wygodnego dostępu do przeglądarki na tej maszynie (np. łączysz się samym pulpitem zdalnym), możesz zainstalować gita automatycznie, jednym poleceniem w PowerShell, zamiast pobierać instalator ręcznie:

```powershell
irm https://raw.githubusercontent.com/odczarujpowerbi/szkolenia-powerbi/claude/new-repo-i29t2e/wirtualny-pracownik/app/bootstrap_install_git.ps1 -OutFile bootstrap_install_git.ps1
.\bootstrap_install_git.ps1
```

(Jeśli repo jest prywatne i `irm` nie zadziała bez logowania — pobierz plik ręcznie z GitHuba i uruchom lokalnie, albo po prostu zainstaluj gita ze strony w tabeli niżej.) Skrypt sam sprawdza, czy git już jest, próbuje `winget`, a w razie braku pobiera najnowszy instalator bezpośrednio i instaluje go cicho, bez klikania okienek.

| # | Program | Skąd pobrać | Uwaga przy instalacji |
|---|---|---|---|
| 1 | Git | [git-scm.com](https://git-scm.com/download/win) (albo skrypt powyżej) | Ustawienia domyślne wystarczą |
| 2 | Python 3.11 lub nowszy | [python.org/downloads](https://www.python.org/downloads/windows/) (albo skrypt niżej) | **WAŻNE (instalacja ręczna):** na pierwszym ekranie instalatora zaznacz "Add python.exe to PATH", zanim klikniesz Install |
| 3 | Power BI Desktop | Microsoft Store albo [powerbi.microsoft.com](https://powerbi.microsoft.com/desktop/) | Potrzebne dopiero, gdy dojdziemy do automatyzacji raportów Power BI — możesz zainstalować teraz albo później. **Uwaga na Windows Server:** Power BI Desktop nie jest oficjalnie wspierany przez Microsoft na tym systemie |

Python też da się zainstalować automatycznie, jednym poleceniem (dodaje do PATH samo, bez zaznaczania okienek):

```powershell
irm https://raw.githubusercontent.com/odczarujpowerbi/szkolenia-powerbi/claude/new-repo-i29t2e/wirtualny-pracownik/app/bootstrap_install_python.ps1 -OutFile bootstrap_install_python.ps1
.\bootstrap_install_python.ps1
```

Node.js **nie jest już potrzebny** — Claude Code instaluje się dziś bezpośrednio, bez npm (starsza metoda przez Node.js nadal działa, ale to nie jest już zalecana ścieżka).

**Claude Code (narzędzie terminalowe)** — potrzebne, żeby dalej rozwijać/poprawiać ten mechanizm na tej maszynie, tak jak robiliśmy to dotąd. Jedna komenda w PowerShell:

```powershell
irm https://claude.ai/install.ps1 | iex
```

Albo automatycznie, tym samym skryptem co dalsze kroki (sam wykrywa, czy Claude Code już jest):

```powershell
irm https://raw.githubusercontent.com/odczarujpowerbi/szkolenia-powerbi/claude/new-repo-i29t2e/wirtualny-pracownik/app/bootstrap_install_claude_code.ps1 -OutFile bootstrap_install_claude_code.ps1
.\bootstrap_install_claude_code.ps1
```

**Claude Desktop (aplikacja z zakładkami Chat/Cowork/Code, w tym sesje w chmurze)** — opcjonalna, ale wygodna, jeśli wolisz interfejs okienkowy zamiast samego terminala:

```powershell
irm https://raw.githubusercontent.com/odczarujpowerbi/szkolenia-powerbi/claude/new-repo-i29t2e/wirtualny-pracownik/app/bootstrap_install_claude_desktop.ps1 -OutFile bootstrap_install_claude_desktop.ps1
.\bootstrap_install_claude_desktop.ps1
```

Ten drugi skrypt pobiera instalator automatycznie, ale samo kliknięcie "Dalej" w oknie instalatora zostaje po Twojej stronie — to zwykła aplikacja okienkowa, nie da się jej w pełni zainstalować bez klikania.

**Jak sprawdzić, czy wszystko się zainstalowało:** otwórz Wiersz polecenia i po kolei wpisz poniższe komendy — każda powinna pokazać numer wersji, nie komunikat błędu:

```
git --version
python --version
claude --version
```

Jeśli którakolwiek komenda pokazuje błąd typu "nie jest rozpoznawana jako polecenie" — ten program nie zainstalował się poprawnie albo trzeba zrestartować komputer, żeby zmiany się zastosowały. Zrestartuj i spróbuj ponownie, zanim przejdziesz dalej.

## Krok 3 — Pobranie projektu

Wybierz jedną z dwóch opcji.

**Opcja A — prościej, jednorazowo:** wejdź na stronę repozytorium na GitHubie, kliknij zielony przycisk **Code → Download ZIP**, rozpakuj pobrany plik do `C:\AIWorker\`.

**Opcja B — wygodniej na później** (łatwiejsze aktualizacje): otwórz Wiersz polecenia i wpisz:

```
git clone <adres repozytorium> C:\AIWorker
```

(adres repozytorium dostaniesz od osoby, która Cię wdraża).

**Po czym poznasz, że się udało:** folder `C:\AIWorker\wirtualny-pracownik\app\` istnieje i widać w nim pliki takie jak `runner_loop.py`, `README.md`.

## Krok 4 — Zebranie i wpisanie dostępów (kluczy)

To najważniejszy krok do zrobienia uważnie — te dane działają jak hasła. **Nigdy nie wysyłaj ich mailem, na czacie ani nikomu nie pokazuj zrzutu ekranu z nimi.**

Nie twórz nic ręcznie — jest do tego skrypt, który sam zakłada jedno, stałe miejsce na wszystkie dostępy:

```
cd C:\AIWorker\wirtualny-pracownik\app
python bootstrap_init_secrets.py
```

Tworzy to folder `secrets\` (nigdy niewysyłany do repozytorium, nawet przez pomyłkę — jest na stałej liście wykluczeń), a w nim:

- **`secrets\.env`** — tu wpisujesz klucze API (Anthropic, Projectly, MailerLite, Microsoft Graph...).
- **`secrets\mcp\*.json`** — po jednym pliku-szablonie na każdą integrację połączoną przez MCP (dziś: Zoho CRM, Projectly, zanfia.com) — skrypt sam je zakłada na podstawie `config/integrations.yaml`, Ty tylko wypełniasz dane w środku.

Uruchom ten skrypt ponownie za każdym razem, gdy dojdzie nowa integracja — nigdy nie nadpisze tego, co już wpisałeś, dorobi tylko brakujące pliki.

1. Otwórz `secrets\.env` Notatnikiem (kliknij prawym przyciskiem → Otwórz za pomocą → Notatnik).
2. Wpisz klucze w odpowiednich miejscach, po znaku `=`, bez spacji i bez cudzysłowów.

| Klucz w pliku `secrets\.env` | Skąd go wziąć | Czy obowiązkowy na start |
|---|---|---|
| `ANTHROPIC_API_KEY` | Załóż konto na [console.anthropic.com](https://console.anthropic.com), zakładka "API Keys", stwórz nowy klucz. Ustaw tam też miesięczny limit wydatków (zalecane: zacznij od małej kwoty, np. 20 USD) | **Tak, obowiązkowy** |
| `PROJECTLY_API_KEY` / `PROJECTLY_BASE_URL` | Z ustawień konta w Projectly | **Tak, obowiązkowy** |
| Reszta (Google, MailerLite...) | Osobno dla każdej usługi — pełna lista i status w pliku `config/integrations.yaml` w tym samym folderze | Nie od razu — dograj, gdy dana funkcja zacznie być używana |
| Integracje MCP (Zoho CRM, Projectly, zanfia.com) | Osobne pliki `secrets\mcp\zoho_crm.json` itd. — nie w `.env` | Nie od razu — dograj, gdy dana integracja zacznie być używana |

**Po czym poznasz, że się udało:** folder `secrets\` istnieje, ma w środku `.env` (wypełniony przynajmniej kluczem Anthropic i danymi do Projectly) oraz podfolder `mcp\` z plikami `.json`.

## Krok 5 — Pierwsze uruchomienie i test

1. Otwórz Wiersz polecenia.
2. Przejdź do folderu projektu:
   ```
   cd C:\AIWorker\wirtualny-pracownik\app
   ```
3. Zainstaluj wymagane biblioteki Pythona:
   ```
   pip install -r requirements.txt
   ```
4. Uruchom test dymny (sprawdza, czy wszystko działa, zanim cokolwiek zacznie robić prawdziwą pracę):
   ```
   python bootstrap_smoke_test.py
   ```

**Czego się spodziewać:** na ekranie pojawi się kilka linijek z zielonymi ✅, a na końcu napis:

```
Wszystkie testy przeszły. Komputer gotowy do rejestracji (bootstrap_register.py).
```

Jeśli zamiast tego widzisz czerwony błąd — zatrzymaj się tutaj i skopiuj cały komunikat do osoby technicznej.

## Krok 6 — Nadanie temu komputerowi roli

Ten komputer musi wiedzieć, czym się zajmuje (np. sprawami deweloperskimi, marketingiem). W Wierszu polecenia (w tym samym folderze) wpisz:

```
python bootstrap_register.py dev
```

(zamiast `dev` wpisz właściwą rolę — dostępne role są wypisane, jeśli wpiszesz samo `python bootstrap_register.py` bez niczego po nim).

**Po czym poznasz, że się udało:** na ekranie pojawi się "Zarejestrowano komputer jako rola '...'" i krótkie podsumowanie statusu.

## Krok 7 — Gdzie wgrywać nowe umiejętności (skille)

Nowe umiejętności bota (np. jak dobrze pracować z konkretnym narzędziem) trzymane są w folderze na OneDrive — np. `AI Worker\Skills\`. Żeby dodać nową umiejętność: wrzuć jej folder do tego miejsca na OneDrive. Komputer sam sprawdza ten folder co jakiś czas i pobiera nowości — nie trzeba nic więcej robić ręcznie.

Lista umiejętności, które są już zaplanowane (część gotowa, część czeka na napisanie), jest w pliku `config/skills_manifest.yaml`.

## Krok 8 — Uruchomienie na stałe (żeby działało bez Ciebie)

Żeby program uruchamiał się sam po restarcie komputera i działał w tle, wystarczy **jedno** zadanie w Harmonogramie — `job_scheduler.py`. To centralny scheduler, który sam odpala w środku wszystkie skrypty cykliczne (dziś: pobieranie zadań z Projectly co 30s, monitor zdrowia maszyny co 2 min, raport statusu co godzinę) i sam pilnuje ich harmonogramów — nie trzeba już zakładać osobnego zadania w Harmonogramie na każdy nowy skrypt, który kiedyś dojdzie.

1. Otwórz **Harmonogram zadań** (wpisz w wyszukiwarce Windows "Harmonogram zadań" / "Task Scheduler").
2. Kliknij **Utwórz zadanie podstawowe** (Create Basic Task).
3. Nazwa: np. "Wirtualny Pracownik — Scheduler".
4. Wyzwalacz: **Przy uruchomieniu komputera** (When the computer starts).
5. Akcja: **Uruchom program** (Start a program).
6. W polu "Program/skrypt" wpisz: `python`
7. W polu "Argumenty" wpisz: `job_scheduler.py`
8. W polu "Rozpocznij w" wpisz: `C:\AIWorker\wirtualny-pracownik\app`
9. Zapisz zadanie.

To wszystko — jedna, samodziałająca pętla zamiast trzech. Nie musisz nic więcej klikać — to jest właśnie ten "dzieje się samo", o który chodziło.

**Jak sprawdzić, co się dzieje w środku i zmienić harmonogram, bez grzebania w Harmonogramie zadań Windows:**

```
python job_scheduler.py --status
```

Pokaże każde zadanie: interwał, czy włączone, ostatni status, ile trwało, kiedy odpali się następny raz. Żeby zmienić, jak często coś się odpala:

```
python job_scheduler.py --set-interval system_health_monitor 60
```

Działa na żywo — scheduler podchwyci zmianę, bez restartu, bo czyta `config/schedule.yaml` na nowo co kilka sekund. Żeby czasowo wyłączyć jakieś zadanie: `python job_scheduler.py --disable nazwa` (i `--enable`, żeby wrócić).

**Uwaga:** wysyłka do Projectly przez `machine_status_reporter.py` dziś działa w trybie mock (wypisuje status, nie wysyła naprawdę) — czeka na dedykowaną funkcję MCP po stronie Projectly. Gdy powstanie, podłącza się w jednym miejscu (`projectly_client.py`), bez zmiany tego skryptu.

**Po czym poznasz, że się udało:** po restarcie komputera, po kilku minutach, `python job_scheduler.py --status` pokazuje świeże "Ostatni status: ok" przy `runner_loop` i `system_health_monitor`, a w Projectly pojawia się wpis statusu ("status na żywo") z etykietą "system-health".

<details>
<summary>Starsze podejście: trzy osobne zadania w Harmonogramie (rozwiń, jeśli już to skonfigurowałeś albo wolisz to podejście)</summary>

Zamiast jednego `job_scheduler.py` można założyć trzy osobne zadania w Harmonogramie, każde z inną komendą w polu "Argumenty" (reszta pól identyczna jak wyżej):

- `runner_loop.py --loop`
- `system_health_monitor.py --loop`
- `machine_status_reporter.py --loop`

Działa tak samo, tylko trzy niezależne procesy zamiast jednego — i każdy nowy skrypt cykliczny w przyszłości wymaga ręcznego założenia kolejnego zadania w Harmonogramie, zamiast jednej linijki w `config/schedule.yaml`.

</details>

## Krok 9 — Jak sprawdzić, że wszystko działa na żywo

Otwórz Projectly. Powinieneś widzieć:
- Nowe zadania testowe przechodzące przez statusy (od "queued" do "done" albo "needs_approval").
- Komentarze zostawiane przy zadaniach z podsumowaniem, co bot zrobił.
- Wpis "status na żywo" dla tego komputera, aktualizowany co 1-2 minuty.

Jeśli nic się nie dzieje przez dłuższy czas — sprawdź Krok 8 (czy zadanie w Harmonogramie faktycznie wystartowało) i plik `secrets\.env` (czy klucze są poprawnie wpisane).

## Krok 10 — Bezpieczeństwo: jak natychmiast wszystko zatrzymać

Jeśli coś wygląda niepokojąco (bot robi coś, czego nie powinien, albo zwyczajnie chcesz przerwać na chwilę) — otwórz Wiersz polecenia w folderze `app` i wpisz:

```
python kill_switch.py stop
```

To natychmiast zatrzymuje wszystkie działania, bez wykonywania kolejnych akcji, dopóki sam nie odblokujesz komendą:

```
python kill_switch.py resume
```

Nie musisz się bać używać tego zbyt często — to jest dokładnie po to, żeby dawało się bezpiecznie zatrzymać w każdej chwili.

## Checklist końcowy

- [ ] Komputer przygotowany (prąd, internet, usypianie wyłączone, dwa konta użytkownika)
- [ ] Zainstalowane: Git, Python, Claude Code, opcjonalnie Claude Desktop (Power BI Desktop w miarę potrzeby)
- [ ] Projekt pobrany do `C:\AIWorker\`
- [ ] `python bootstrap_init_secrets.py` uruchomiony, folder `secrets\` istnieje i jest wypełniony (minimum: Anthropic + Projectly)
- [ ] `pip install -r requirements.txt` wykonane bez błędów
- [ ] `python bootstrap_smoke_test.py` pokazuje "Wszystkie testy przeszły"
- [ ] Komputer zarejestrowany z właściwą rolą (`bootstrap_register.py`)
- [ ] Folder skilli na OneDrive znaleziony i znany
- [ ] OBA zadania w Harmonogramie zadań Windows utworzone i przetestowane — runner i monitor zdrowia (restart komputera)
- [ ] W Projectly widać status na żywo i przetworzone zadania
- [ ] Wiadomo, jak i kiedy użyć `kill_switch.py stop`
