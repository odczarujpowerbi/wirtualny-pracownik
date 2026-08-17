"""
Analizuje wyniki testowanych wariantów reklam (Meta + TikTok) co 48h
(PLAN-WDROZENIA.md sekcja 20). Czysty Python, bez AI — liczy CTR/CPC/CPA
i klasyfikuje warianty, żeby model wchodził dopiero do interpretacji
wyników i pisania raportu (ad_test_report.py), nie do liczenia dzielenia.

Wymaga realnego `meta_ads_api_client.py`/`tiktok_ads_api_client.py` (jeszcze
nie napisane — SKRYPTY.md kategoria G) do pobrania danych; tu operuje na
`mock_data/sample_ad_metrics.json` do czasu ich podłączenia.
"""

import json
from pathlib import Path

MOCK_METRICS_PATH = Path(__file__).parent / "mock_data" / "sample_ad_metrics.json"

MIN_SPEND_BEFORE_JUDGEMENT = 20.0  # poniżej tego progu za wcześnie na werdykt


def load_mock_metrics():
    with open(MOCK_METRICS_PATH, encoding="utf-8") as f:
        return json.load(f)


def analyze_variants(metrics):
    """Zwraca listę wariantów z policzonymi metrykami i werdyktem:
    'pause_candidate' | 'scale_candidate' | 'keep_testing'."""
    analyzed = []
    for m in metrics:
        ctr = m["clicks"] / m["impressions"] if m["impressions"] else 0
        cpc = m["spend"] / m["clicks"] if m["clicks"] else None
        cpa = m["spend"] / m["conversions"] if m["conversions"] else None
        analyzed.append({**m, "ctr": round(ctr, 4), "cpc": round(cpc, 2) if cpc else None, "cpa": round(cpa, 2) if cpa else None})

    converting = [v for v in analyzed if v["cpa"] is not None]
    best_cpa_variant_id = min(converting, key=lambda v: v["cpa"])["variant_id"] if converting else None

    for v in analyzed:
        if v["spend"] < MIN_SPEND_BEFORE_JUDGEMENT:
            v["verdict"] = "keep_testing"
        elif v["conversions"] == 0:
            v["verdict"] = "pause_candidate"
        elif v["variant_id"] == best_cpa_variant_id:
            v["verdict"] = "scale_candidate"
        else:
            v["verdict"] = "keep_testing"

    return analyzed


if __name__ == "__main__":
    result = analyze_variants(load_mock_metrics())
    print(json.dumps(result, ensure_ascii=False, indent=2))
