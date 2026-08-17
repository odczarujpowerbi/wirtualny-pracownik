# Testowanie na VPS-ie, zanim przyjedzie laptop 32 GB

Krótka odpowiedź: **tak, da się, i to już jest sprawdzone** — cały kod w `app/` był w tej sesji uruchamiany i testowany na Linuksie (nie na Windows), więc wiadomo, że działa na zwykłym, tanim VPS-ie, nie tylko teoretycznie. Ten dokument to szybka ścieżka, żeby zacząć testować mechanizm w tym tygodniu, zamiast czekać na docelową maszynę.

To NIE zastępuje `INSTRUKCJA-WDROZENIA.md` (docelowe wdrożenie na dedykowanym Windows) — to most na czas, zanim laptop dojedzie.

## Co da się przetestować na VPS-ie już dziś

Wszystko poza jedną rzeczą. Cały silnik (klasyfikacja ryzyka, routing, walidatory, eskalacja, kill switch, koszt) i wszystkie skrypty raportowo-analityczne są czystym Pythonem bez żadnej zależności od Windows:

- `runner_loop.py` — pełen cykl: klasyfikacja → routing → walidacja/eskalacja → status → koszt (na mock danych, dopóki nie ma prawdziwego Projectly)
- `digest_generator.py`, `weekly_team_report.py`, `task_feedback_requester.py` — świeżo dodane, testowane w tej sesji
- `source_schema_watcher.py`, `data_contract_validator.py`, `stale_time_entry_nudger.py`, `report_builder.py`
- `mailerlite_client.py` / `mailerlite_report_analyzer.py`, `ad_copy_generator.py` / `ad_performance_analyzer.py` / `ad_test_report.py`
- `email_client.py` / `email_draft_generator.py` (tryb mock — drafty/"wysyłki" lądują jako pliki, nic nie wychodzi naprawdę, dopóki nie podepniesz Microsoft Graph)

**Czego VPS nie zrobi:** kroków wymagających realnie zainstalowanego Power BI Desktop — zrzutów ekranu raportu, PBI-01/02. To jedyny fragment całego repo zależny od Windows (potrzebuje fizycznego Power BI Desktop Bridge). Zostaje na laptopa.

Jeśli chodzi o pytanie "czy ten mechanizm będzie nam działał" — mechanizm to właśnie ta pierwsza grupa (silnik + skrypty), nie zrzuty PBI. VPS w pełni na to odpowie.

## Minimalne wymagania VPS-a

Lekko — to skrypty wywołujące zdalne API, nie lokalne obliczenia:

- 1-2 vCPU, 2 GB RAM w zupełności wystarczy (śmiało też 1 GB, jeśli akurat taki masz pod ręką)
- Ubuntu 22.04/24.04 (albo Debian) — dowolny tani dostawca (Hetzner, OVH, DigitalOcean...), rzędu 20-40 zł/mies.
- Dostęp SSH

## Instalacja (2 minuty)

Na VPS-ie, po zalogowaniu przez SSH:

```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip

curl -O https://raw.githubusercontent.com/odczarujpowerbi/wirtualny-pracownik/main/app/bootstrap_install_vps.sh
chmod +x bootstrap_install_vps.sh
./bootstrap_install_vps.sh
```

(Adres repo jest opcjonalny — domyślnie `odczarujpowerbi/wirtualny-pracownik` z gałęzi `main`. Podaj własny adres jako pierwszy argument, jeśli używasz forka.)

Skrypt sam sprawdzi git/python3, sklonuje repo, założy wirtualne środowisko i zainstaluje zależności. Na końcu wypisze dokładnie te kroki:

```bash
cd ~/AIWorker/wirtualny-pracownik/app
cp .env.example .env && nano .env     # uzupełnij ANTHROPIC_API_KEY
source venv/bin/activate
python bootstrap_smoke_test.py
python bootstrap_register.py dev      # albo inna rola
```

**Po czym poznasz, że działa:** `bootstrap_smoke_test.py` kończy się "Wszystkie testy przeszły" — dokładnie tak samo jak w `INSTRUKCJA-WDROZENIA.md` na Windows, bo to ten sam kod.

## Uruchomienie cykliczne (zamiast Harmonogramu zadań Windows)

**Zalecane: `job_scheduler.py` — jeden proces, jeden serwis systemd.** To centralny scheduler, który sam w środku odpala wszystkie skrypty cykliczne (dziś: zadania z Projectly co 30s, monitor zdrowia co 2 min, raport statusu co godzinę) wg `config/schedule.yaml` — nie trzeba już osobnego wpisu cron/systemd na każdy skrypt, ani przy dzisiejszych trzech, ani przy kolejnych, które kiedyś dojdą.

```bash
sudo tee /etc/systemd/system/wirtualny-pracownik.service << 'EOF'
[Unit]
Description=Wirtualny Pracownik AI — scheduler
After=network.target

[Service]
WorkingDirectory=%h/AIWorker/wirtualny-pracownik/app
ExecStart=%h/AIWorker/wirtualny-pracownik/app/venv/bin/python job_scheduler.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now wirtualny-pracownik.service
sudo systemctl status wirtualny-pracownik.service
```

Sprawdzenie stanu i zmiana harmonogramu bez dotykania systemd:

```bash
cd ~/AIWorker/wirtualny-pracownik/app
venv/bin/python job_scheduler.py --status
venv/bin/python job_scheduler.py --set-interval system_health_monitor 60   # zadziała na żywo, bez restartu serwisu
```

<details>
<summary>Starsze podejście: osobny cron/systemd na każdy skrypt (rozwiń, jeśli wolisz to podejście)</summary>

**Cron, do szybkich testów** (`crontab -e`):

```
*/5 * * * * cd ~/AIWorker/wirtualny-pracownik/app && venv/bin/python runner_loop.py >> runs/cron.log 2>&1
*/2 * * * * cd ~/AIWorker/wirtualny-pracownik/app && venv/bin/python system_health_monitor.py >> runs/health.log 2>&1
0 * * * * cd ~/AIWorker/wirtualny-pracownik/app && venv/bin/python machine_status_reporter.py >> runs/machine_status.log 2>&1
```

**Trzy osobne serwisy systemd** (ta sama recepta co wyżej, inna nazwa i `ExecStart` każdorazowo): `runner_loop.py --loop`, `system_health_monitor.py --loop`, `machine_status_reporter.py --loop`.

</details>

Zacznij od `job_scheduler.py --status` po chwili działania — łatwo podejrzeć, czy coś w ogóle działa, zanim zostawisz to bez nadzoru na dłużej.

## Co konkretnie przetestować w pierwszym tygodniu

1. `python bootstrap_smoke_test.py` — mechanika w ogóle działa.
2. `python weekly_team_report.py` — na razie na mock zadaniach, ale możesz podać mu prawdziwy eksport godzin: `python -c "from weekly_team_report import run_weekly_team_report; print(run_weekly_team_report(time_entries_csv='/scieżka/do/eksportu.csv'))"`.
3. `python stale_time_entry_nudger.py /scieżka/do/eksportu.csv` — realny wynik na Twoich danych, bez czekania na nic więcej.
4. Gdy dojdzie dostęp do Projectly — wpisz `PROJECTLY_API_KEY`/`PROJECTLY_BASE_URL` w `.env` i sprawdź, czy runner realnie się z nim komunikuje (dziś wciąż mock, patrz `PROJECTLY-ROZWOJ.md`).
5. Gdy dojdzie dostęp do skrzynki — wpisz `MS_GRAPH_*` w `.env`; do tego czasu maile lądują jako pliki w `runs/mock_outbox/`, co i tak wystarcza do oceny treści.

## Co się zmieni, gdy przyjedzie laptop 32 GB

Nic w kodzie. `SKALOWANIE.md` od początku zakłada, że silnik jest ten sam na każdej maszynie, zmienia się tylko konfiguracja/lokalny stan (sekcja 2 tamtego dokumentu). Na laptopie dochodzi jedna rzecz, której VPS nie mógł dać: Power BI Desktop i realne zrzuty raportów (PBI-01/02). Możesz nawet zostawić VPS działający równolegle (np. pod raporty/maile/CRM), a laptopa użyć tylko do części związanej z Power BI — to zgodne z docelową architekturą "jeden komputer = jeden pracownik" z `ZESPOL-BOTOW.md`, tylko wcześniej niż planowano.
