"""
Cykliczny raport testu reklam (Meta + TikTok) — co 48h, NIE co tydzień jak
`weekly_business_review.py` (PLAN-WDROZENIA.md sekcja 18). To osobny,
częstszy cykl specyficzny dla aktywnych testów kreatyw (sekcja 20), nie
zamiennik cotygodniowego podsumowania całej firmy.

Publikuje raport w Projectly i od razu tworzy zadania follow-up:
- warianty do wstrzymania (`ad_variant_pause`, żółte) — zadanie dla bota,
  przejdzie zwykłą ścieżkę walidacji/auto-zatwierdzenia.
- warianty do skalowania (`budget_change`, czerwone) — zawsze zadanie dla
  człowieka, bo to realne przesunięcie budżetu, nie tylko zatrzymanie strat.
"""

from ad_performance_analyzer import analyze_variants, load_mock_metrics
from projectly_client import get_client


def build_report_text(analyzed):
    lines = ["📊 Raport testu reklam (cykl 48h)", ""]
    for v in analyzed:
        ctr_pct = f"{v['ctr'] * 100:.2f}%"
        lines.append(
            f"- {v['variant_id']} ({v['platform']}): CTR {ctr_pct}, CPC {v['cpc']}, "
            f"CPA {v['cpa']}, wydatek {v['spend']} zł → {v['verdict']}"
        )
    return "\n".join(lines)


def run_test_cycle(client=None, metrics=None):
    client = client or get_client()
    analyzed = analyze_variants(metrics or load_mock_metrics())
    report_text = build_report_text(analyzed)
    client.post_comment("AD-TEST-CYCLE", report_text)

    created_tasks = []
    for v in analyzed:
        if v["verdict"] == "pause_candidate":
            task_id = client.create_task(
                title=f"Wstrzymaj słabo działający wariant {v['variant_id']}",
                description=(
                    f"0 konwersji przy wydatku {v['spend']} zł (CTR {v['ctr']*100:.2f}%). "
                    "Rekomendacja: pauza (ad_variant_pause, żółte — ogranicza wydatek)."
                ),
                assigned_to="bot",
            )
            created_tasks.append({"variant_id": v["variant_id"], "action": "pause", "task_id": task_id})

        elif v["verdict"] == "scale_candidate":
            task_id = client.create_task(
                title=f"Zwiększ budżet zwycięskiego wariantu {v['variant_id']}",
                description=(
                    f"Najlepszy CPA w cyklu: {v['cpa']} zł ({v['platform']}). "
                    "Rekomendacja: skalowanie budżetu — wymaga Twojej decyzji (budget_change = czerwone, "
                    "chyba że w przyszłości ustawisz bounded_red dla tego typu akcji)."
                ),
                assigned_to="pawel",
            )
            created_tasks.append({"variant_id": v["variant_id"], "action": "scale", "task_id": task_id})

    return {"report": report_text, "created_tasks": created_tasks}


if __name__ == "__main__":
    result = run_test_cycle()
    print("\n--- Utworzone zadania follow-up ---")
    for t in result["created_tasks"]:
        print(t)
