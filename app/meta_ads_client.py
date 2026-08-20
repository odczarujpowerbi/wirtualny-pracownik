"""
Konektor Meta Ads (Facebook/Instagram) - READ-ONLY na start: odczyt kampanii i
wydatkow. Zgodnie z zasada bezpieczenstwa zmiana budzetu/publikacja to `red` /
bounded_red (approval_policy.yaml), wiec sterowanie dokladamy pozniej POD KONTROLA
polityki, nie tutaj na goraco.

Uwierzytelnianie: System User z Business Managera (dlugozyjacy token). Cztery
wartosci w secrets/.env: META_APP_ID, META_APP_SECRET, META_ACCESS_TOKEN,
META_AD_ACCOUNT_ID (format act_...). Do samego ODCZYTU wystarcza token +
account id (ads_read).

Bez SDK facebook-business - czyste wywolania Graph API przez `requests` (mniejsza
zaleznosc). Import 'requests' jest leniwy, zeby sam import modulu go nie wymagal.
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env

GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_VERSION = os.environ.get("META_API_VERSION", "v21.0")
HTTP_TIMEOUT_SECONDS = 30


class MetaAdsError(RuntimeError):
    """Graph API Meta zwrocil blad albo brak konfiguracji."""


class MetaAdsClient:
    def __init__(self, access_token, ad_account_id, version=DEFAULT_VERSION):
        if not access_token or not ad_account_id:
            raise MetaAdsError("Brak META_ACCESS_TOKEN lub META_AD_ACCOUNT_ID.")
        self.access_token = access_token
        # Graph wymaga prefiksu act_ przy koncie reklamowym.
        self.ad_account_id = ad_account_id if str(ad_account_id).startswith("act_") else f"act_{ad_account_id}"
        self.version = version

    @classmethod
    def from_env(cls):
        """Klient z secrets/.env albo None, gdy brakuje danych (nie rzuca)."""
        token = os.environ.get("META_ACCESS_TOKEN")
        account = os.environ.get("META_AD_ACCOUNT_ID")
        if not token or not account:
            return None
        return cls(token, account)

    def _get(self, path, params=None):
        import requests
        url = f"{GRAPH_BASE}/{self.version}/{path}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params or {},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise MetaAdsError(f"Graph {resp.status_code}: {err.get('message', resp.text[:200])}")
        return data

    def list_campaigns(self, limit=100):
        """Lista kampanii: id, nazwa, status, budzety, cel. Sam ODCZYT."""
        fields = "id,name,status,effective_status,objective,daily_budget,lifetime_budget"
        data = self._get(f"{self.ad_account_id}/campaigns", {"fields": fields, "limit": limit})
        return data.get("data", [])

    def account_insights(self, date_preset="last_7d"):
        """Zbiorcze wydatki/statystyki konta reklamowego (spend, CTR, CPC...)."""
        fields = "spend,impressions,clicks,cpc,ctr,reach"
        data = self._get(f"{self.ad_account_id}/insights", {"fields": fields, "date_preset": date_preset})
        rows = data.get("data", [])
        return rows[0] if rows else {}


def verify():
    """Zwraca {ok, detail}. Bez danych w env -> ok=False (nie rzuca)."""
    client = MetaAdsClient.from_env()
    if client is None:
        return {"ok": False, "detail": "Brak META_ACCESS_TOKEN / META_AD_ACCOUNT_ID w secrets/.env."}
    try:
        campaigns = client.list_campaigns(limit=5)
        insights = client.account_insights()
        return {"ok": True,
                "detail": f"OK - kampanii (probka): {len(campaigns)}, wydatek 7d: {insights.get('spend', '0')}"}
    except MetaAdsError as exc:
        return {"ok": False, "detail": str(exc)}


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = verify()
    print(("OK   " if r["ok"] else "BLAD ") + r["detail"])
    sys.exit(0 if r["ok"] else 1)
