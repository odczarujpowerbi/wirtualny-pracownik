"""
Kontrola zuzycia Claude i estymacja "ile zadan jeszcze" (na prosbe wlasciciela:
agent ma miec kontrole nad limitami widocznymi w statuslinii terminala).

Zrodlo danych: ~/.claude/powerline/usage/today.json - ten sam surowy log zuzycia,
z ktorego statuslinia (claude-powerline) liczy blok 5h / dzis. Kazdy rekord:
{timestamp, usage:{input/output/cache...}, costUSD, model}.

Co liczymy:
- block_5h_usd / today_usd : realny koszt w oknie 5h i dzis (jak w statuslinii),
- estimate_remaining_tasks : ILE zadan jeszcze zmiescimy w budzecie okna 5h,
  na podstawie sredniego kosztu zadania (z wlasnego dziennika decyzji state.db,
  a gdy brak danych - z ostatnich wywolan).

UCZCIWIE: twardy limit subskrypcji (dokladny sufit okna 5h/tygodnia) NIE jest
dostepny programowo - statuslinia pokazuje %, ale liczba progu nie jest w tym
pliku. Dlatego estymacja jest wzgledem BUDZETU, ktory ustawiasz (block_budget_usd),
nie wobec ukrytego limitu Anthropic. To swiadome, jawne zalozenie.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

USAGE_PATH = Path.home() / ".claude" / "powerline" / "usage" / "today.json"

# Budzet okna 5h w USD - punkt odniesienia estymacji. Ustawiany przez wlasciciela
# (nie jest to ukryty limit Anthropic, tylko Twoj prog ostroznosci). Domyslnie
# zachowawczo; docelowo do config/usage_budget.yaml.
DEFAULT_BLOCK_BUDGET_USD = 40.0
BLOCK_HOURS = 5

# Prog, przy ktorym runner_loop.run_once() przestaje przyjmowac NOWE zadania
# (decyzja wlasciciela 29.08.2026: pierwotnie "90%", finalnie obnizone do 85% -
# biezace zadania w kolejce koncza sie normalnie, tylko nowe nie startuja, jak
# przy cost_tracker.budget_state "warning"/"exceeded"). Dzis liczone wzgledem
# PROXY (block_budget_used_pct, wlasny budzet $ w oknie 5h) - docelowo wzgledem
# realnego % z hookData.rate_limits (patrz WS6 w planie), bez zmiany API tej
# funkcji: over_threshold() czyta cokolwiek summary() akurat zwroci.
THRESHOLD_PAUSE_PERCENT = 85.0

# Realny budzet okna 5h (USD), swiadomie ustawiony przez wlasciciela - ODDZIELNY
# od DEFAULT_BLOCK_BUDGET_USD wyzej. Zywy przypadek znaleziony 29.08.2026 przy
# wdrazaniu progu blokujacego: na tej maszynie DEFAULT_BLOCK_BUDGET_USD (40 USD)
# dawal 198% (realna sesja jest znacznie kosztowniejsza niz ten zachowawczy
# domyslny placeholder) - gdyby over_threshold() blokowal prace na SAMYM
# DEFAULT_BLOCK_BUDGET_USD, wlaczenie tej funkcji zatrzymaloby WSZYSTKIE boty od
# razu, bez swiadomej decyzji wlasciciela o realnym progu. Dlatego blokada
# (over_threshold) dziala WYLACZNIE, gdy ten plik istnieje - brak pliku = funkcja
# jest tylko WYSWIETLANA (dashboard), nigdy nie blokuje.
BLOCK_BUDGET_PATH = Path(__file__).parent / "config" / "usage_block_budget_usd.txt"


def _skonfigurowany_budzet_usd():
    if not BLOCK_BUDGET_PATH.exists():
        return None
    try:
        return float(BLOCK_BUDGET_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def over_threshold(podsumowanie, threshold=THRESHOLD_PAUSE_PERCENT):
    """Czy zuzycie z summary() osiagnelo/przekroczylo prog. ZAWSZE False, dopoki
    wlasciciel swiadomie nie ustawi realnego budzetu okna 5h
    (config/usage_block_budget_usd.txt, patrz BLOCK_BUDGET_PATH) - bez tego
    DEFAULT_BLOCK_BUDGET_USD (40 USD) to tylko wartosc do WYSWIETLENIA, zbyt
    zachowawcza, zeby cokolwiek blokowac bez jawnej decyzji. Fail-soft: brak
    danych (available=False) albo brak procentu -> False."""
    if _skonfigurowany_budzet_usd() is None:
        return False
    if not podsumowanie.get("available"):
        return False
    procent = podsumowanie.get("block_budget_used_pct")
    return procent is not None and procent >= threshold


# Po ilu godzinach od PIERWSZEGO wykrycia przekroczenia progu bot ma wznowic
# przyjmowanie nowych zadan BEZ WZGLEDU na to, czy % akurat spadl (decyzja
# wlasciciela 30.08.2026: "po 4h od alertu bot powinien na nowo zaczac dzialac
# i przywrocic kolejke"). Bez tego wznowienie zalezaloby WYLACZNIE od
# naturalnego "starzenia sie" okna 5h (BLOCK_HOURS) - w praktyce bardzo bliskie,
# ale nie identyczne, i niejawne (wlasciciel nie widzialby jednego, pewnego
# terminu powrotu).
RESUME_AFTER_HOURS = 4

PAUSE_STATE_DIR = Path(__file__).parent / "runs"


def _pause_state_path(role=None):
    suffix = "" if not role or role == "dev" else f"_{role}"
    return PAUSE_STATE_DIR / f"usage_pause_state{suffix}.json"


def _load_pause_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_pause_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_pause_for_usage(role=None, now=None, podsumowanie=None):
    """Decyzja "czy wstrzymać nowe zadania z powodu zużycia", Z ZEGAREM
    POWROTU: pierwsze wykrycie przekroczenia progu zapisuje znacznik czasu
    (per rola, runs/usage_pause_state<_rola>.json); po RESUME_AFTER_HOURS (4h)
    od TEGO znacznika funkcja zwraca False (wznów) BEZ WZGLĘDU na aktualny %.
    Spadek poniżej progu przed upływem 4h też czyści znacznik (naturalny powrót,
    nie trzeba czekać do końca okna). Nigdy nie rzuca."""
    now = now or datetime.now(timezone.utc)
    podsumowanie = podsumowanie if podsumowanie is not None else summary()
    path = _pause_state_path(role)
    state = _load_pause_state(path)

    if not over_threshold(podsumowanie):
        if state.get("first_crossed_at"):
            _save_pause_state({}, path)
        return False

    pierwsze = state.get("first_crossed_at")
    if not pierwsze:
        _save_pause_state({"first_crossed_at": now.isoformat()}, path)
        return True

    try:
        minelo = now - datetime.fromisoformat(pierwsze)
    except ValueError:
        _save_pause_state({"first_crossed_at": now.isoformat()}, path)
        return True

    if minelo >= timedelta(hours=RESUME_AFTER_HOURS):
        _save_pause_state({}, path)
        return False
    return True


def _now():
    return datetime.now(timezone.utc)


def load_records(path=USAGE_PATH):
    """Lista rekordow zuzycia. Pusta lista, gdy pliku brak (np. przed pierwsza
    sesja Claude na maszynie) - nie wywalamy sie, degradujemy lagodnie."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return raw.get("data", []) if isinstance(raw, dict) else (raw or [])


def _parse_ts(rec):
    ts = rec.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _sum_cost(records):
    return round(sum(r.get("costUSD", 0) or 0 for r in records), 4)


def window_usage(records, hours=BLOCK_HOURS, now=None):
    """Koszt i liczba wywolan w ostatnich `hours` godzinach."""
    now = now or _now()
    cutoff = now - timedelta(hours=hours)
    inside = [r for r in records if (_parse_ts(r) or now) >= cutoff]
    return {"cost_usd": _sum_cost(inside), "calls": len(inside)}


def today_usage(records):
    """Caly plik to 'dzis' wg claude-powerline - sumujemy wszystko."""
    return {"cost_usd": _sum_cost(records), "calls": len(records)}


def _avg_task_cost(default_from_records):
    """Sredni koszt JEDNEGO zadania. Preferujemy wlasny dziennik decyzji
    (state.db, wpisy execution z cost_usd per task) - to realny koszt zadania
    agenta. Fallback: sredni koszt wywolania z today.json (grubsze przyblizenie)."""
    try:
        import state_store
        conn = state_store.get_connection()
        rows = conn.execute(
            "SELECT cost_usd FROM events WHERE event_type='execution' AND cost_usd IS NOT NULL AND cost_usd > 0"
        ).fetchall()
        conn.close()
        costs = [r[0] for r in rows]
        if costs:
            return sum(costs) / len(costs), "dziennik decyzji (execution)"
    except Exception:  # noqa: BLE001 - brak bazy/kolumny nie moze wywrocic monitora
        pass
    return default_from_records, "srednia z ostatnich wywolan Claude"


def summary(path=USAGE_PATH, block_budget_usd=None, now=None):
    """Zbiorczy widok dla dashboardu i eskalacji: zuzycie 5h/dzis + estymacja
    ile zadan jeszcze zmiescimy w budzecie okna 5h.

    block_budget_usd=None (domyslne) -> realny budzet wlasciciela z
    BLOCK_BUDGET_PATH, gdy skonfigurowany, inaczej DEFAULT_BLOCK_BUDGET_USD
    (placeholder do WYSWIETLENIA, patrz over_threshold). Zywy bug znaleziony
    29.08.2026 przy ustawianiu realnego budzetu: parametr domyslny wiazacy sie
    RAZ przy imporcie modulu (block_budget_usd=DEFAULT_BLOCK_BUDGET_USD w
    sygnaturze) nigdy by nie zobaczyl pozniej utworzonego BLOCK_BUDGET_PATH -
    ten sam wzorzec bledu co state_store.DB_PATH/ASKED_PATH gdzie indziej w
    repo, naprawiony tu przez odczyt WEWNATRZ ciala funkcji."""
    if block_budget_usd is None:
        block_budget_usd = _skonfigurowany_budzet_usd() or DEFAULT_BLOCK_BUDGET_USD
    records = load_records(path)
    if not records:
        return {"available": False,
                "reason": "Brak danych zuzycia (~/.claude/powerline/usage/today.json) - jeszcze zadnej sesji Claude."}

    block = window_usage(records, hours=BLOCK_HOURS, now=now)
    today = today_usage(records)

    avg_call = (today["cost_usd"] / today["calls"]) if today["calls"] else 0.0
    avg_task, basis = _avg_task_cost(avg_call)

    remaining_budget = max(0.0, block_budget_usd - block["cost_usd"])
    est_tasks = int(remaining_budget / avg_task) if avg_task > 0 else None

    return {
        "available": True,
        "block_5h_usd": block["cost_usd"],
        "block_5h_calls": block["calls"],
        "today_usd": today["cost_usd"],
        "today_calls": today["calls"],
        "block_budget_usd": block_budget_usd,
        "block_budget_used_pct": round(100 * block["cost_usd"] / block_budget_usd, 1) if block_budget_usd else None,
        "avg_task_cost_usd": round(avg_task, 4),
        "avg_task_cost_basis": basis,
        "estimated_tasks_remaining": est_tasks,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    if "--brief" in sys.argv:
        s = summary()
        if s["available"]:
            print(f"\n5h: ${s['block_5h_usd']} / ${s['block_budget_usd']} "
                  f"({s['block_budget_used_pct']}%) | dzis: ${s['today_usd']} | "
                  f"szac. zadan jeszcze: {s['estimated_tasks_remaining']}")
