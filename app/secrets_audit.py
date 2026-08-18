"""
Audyt sekretów: pokazuje, których zmiennych środowiskowych realnie SZUKA kod
w tym folderze, które z nich masz wypełnione w secrets/.env, a których brak —
oraz który skrypt czego używa. NIGDY nie wypisuje wartości sekretów (tylko
"ustawiony ✓" / "brak").

Uruchom na maszynie docelowej:
    python secrets_audit.py

Mapa poniżej jest wyciągnięta wprost z kodu (os.environ.get / os.environ[...]),
nie z .env.example — .env.example wymienia też klucze "na przyszłość", których
ŻADEN skrypt jeszcze nie czyta. Tu widać różnicę: co jest realnie używane teraz.
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env do środowiska, tak jak robią to skrypty

# (zmienna, [skrypty które ją czytają], obowiązkowość, uwaga)
USED_BY_CODE = [
    ("PROJECTLY_API_KEY", ["projectly_client.py"], "zalecany",
     "Bez niego działa MockProjectlyClient (pliki mock_data/runs), nic realnego w Projectly."),
    ("PROJECTLY_BASE_URL", ["projectly_client.py"], "zalecany",
     "Endpoint MCP Projectly. Domyślny produkcyjny jest w .env.example."),
    ("ANTHROPIC_API_KEY", ["task_thinker.py (fallback)", "validators.py (wizja)",
                           "ad_copy_generator.py", "email_draft_generator.py",
                           "mailerlite_report_analyzer.py", "weekly_team_report.py"], "opcjonalny",
     "Główna pętla myśli przez Claude Code (claude login), nie ten klucz. Bez klucza te skrypty degradują się (nie zmyślają), nie crashują."),
    ("MAILERLITE_API_KEY", ["mailerlite_client.py"], "opcjonalny",
     "Tylko gdy używasz raportów MailerLite."),
    ("MS_GRAPH_CLIENT_ID", ["email_client.py"], "jeszcze nieaktywny",
     "Konektor Microsoft Graph NIE jest jeszcze napisany. Nawet z sekretami działa tryb mock (runs/mock_outbox), aż powstanie konektor."),
    ("MS_GRAPH_CLIENT_SECRET", ["email_client.py"], "jeszcze nieaktywny", "jw."),
    ("MS_GRAPH_TENANT_ID", ["email_client.py"], "jeszcze nieaktywny", "jw."),
    ("MS_GRAPH_MAILBOX", ["email_client.py"], "jeszcze nieaktywny", "jw."),
]

# Zadeklarowane w .env.example, ale ŻADEN skrypt jeszcze ich nie czyta —
# wpisanie ich niczego nie uruchomi (konektor nie istnieje). Nie panikuj brakiem.
DECLARED_NOT_USED = [
    "OPENROUTER_API_KEY", "OLLAMA_HOST", "OLLAMA_VISION_MODEL", "OLLAMA_TEXT_MODEL",
    "ZOHO_CRM_MCP_TOKEN", "ZOHO_CRM_MCP_URL", "ZANFIA_MCP_TOKEN", "ZANFIA_MCP_URL",
    "GOOGLE_APPLICATION_CREDENTIALS", "META_APP_ID", "META_APP_SECRET", "META_ACCESS_TOKEN",
    "META_AD_ACCOUNT_ID", "TIKTOK_ADS_ACCESS_TOKEN", "TIKTOK_ADS_ADVERTISER_ID",
    "GITHUB_TOKEN", "MIRO_CLIENT_ID", "MIRO_CLIENT_SECRET", "INFAKT_API_KEY",
    "DAILY_COST_LIMIT_USD",
]


def run():
    print("=" * 70)
    print("  AUDYT SEKRETÓW — co kod realnie czyta i co masz ustawione")
    print("=" * 70)
    print("\n[1] Zmienne UŻYWANE przez kod:\n")
    for name, scripts, level, note in USED_BY_CODE:
        set_flag = "ustawiony ✓" if os.environ.get(name) else "BRAK"
        print(f"  {name:<26} [{level:<18}] {set_flag}")
        print(f"       używa: {', '.join(scripts)}")
        print(f"       uwaga: {note}\n")

    print("[2] Zadeklarowane w .env.example, ale kod ICH JESZCZE NIE CZYTA")
    print("    (wpisanie ich nic nie uruchomi — konektor nie istnieje):\n")
    for name in DECLARED_NOT_USED:
        set_flag = "ustawiony (nieużywany)" if os.environ.get(name) else "brak (OK)"
        print(f"  {name:<32} {set_flag}")

    print("\n" + "=" * 70)
    print("  Podsumowanie: crash maila naprawiony (MS_GRAPH nie aktywuje")
    print("  niedokończonego konektora). Realnie działają dziś: Projectly")
    print("  (jeśli klucz), MailerLite (jeśli klucz), Anthropic (opcjonalnie).")
    print("=" * 70)


if __name__ == "__main__":
    run()
