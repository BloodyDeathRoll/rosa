#!/usr/bin/env python3
"""Rosa's GA4 numbers, as the questions worth asking rather than a dashboard.

No SDK. The Analytics Data API is REST, and a service account authenticates with a
self-signed JWT - about forty lines here against a dependency tree that would dwarf the
pipeline's. Signing needs an RSA key, which `pywebpush` already brings in via
`cryptography`, so this runs under the pipeline venv with nothing new installed.

    export GA_SA_KEY=~/.config/rosa/ga-sa.json
    uv run --project pipeline python tools/ga-report/report.py --days 28

The key never lives in the repo. GA4 is aggregated and sampled; for raw per-event work
use the BigQuery export instead (see README).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROPERTY_ID = "553528140"  # rosa.surf - Admin > Property settings > Property
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
API = f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY_ID}:runReport"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def access_token(key_path: Path) -> str:
    """Service-account JWT -> OAuth access token (RFC 7523)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    sa = json.loads(key_path.read_text(encoding="utf-8"))
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": sa["private_key_id"]}
    claims = {
        "iss": sa["client_email"],
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    assertion = f"{signing_input}.{_b64(sig)}"

    body = urllib.parse.urlencode(
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def run_report(token: str, body: dict) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # the API explains itself; surface it verbatim
        raise SystemExit(f"GA4 API {e.code}: {e.read().decode()[:400]}") from e


def rows(res: dict) -> list[tuple[list[str], list[str]]]:
    return [
        ([d["value"] for d in r.get("dimensionValues", [])],
         [m["value"] for m in r.get("metricValues", [])])
        for r in res.get("rows", [])
    ]


def query(token, dims, mets, days, limit=25, order=None, dim_filter=None):
    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": d} for d in dims],
        "metrics": [{"name": m} for m in mets],
        "limit": limit,
    }
    if order:
        body["orderBys"] = [{"metric": {"metricName": order}, "desc": True}]
    if dim_filter:
        body["dimensionFilter"] = dim_filter
    return rows(run_report(token, body))


def event_filter(name: str) -> dict:
    return {"filter": {"fieldName": "eventName", "stringFilter": {"value": name}}}


def table(title: str, header: tuple[str, ...], data: list[tuple], widths: tuple[int, ...]) -> None:
    print(f"\n{title}")
    if not data:
        print("  (no rows yet)")
        return
    print("  " + "  ".join(h.ljust(w) for h, w in zip(header, widths)))
    for row in data:
        print("  " + "  ".join(str(c)[:w].ljust(w) for c, w in zip(row, widths)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--key", type=Path, default=None, help="service-account JSON (or GA_SA_KEY)")
    ap.add_argument("--json", action="store_true", help="machine-readable, for a report page")
    a = ap.parse_args()

    key = a.key or (Path(os.path.expanduser(os.environ["GA_SA_KEY"])) if "GA_SA_KEY" in os.environ else None)
    if key is None or not key.exists():
        print(
            "no service-account key: set GA_SA_KEY or pass --key (see tools/ga-report/README.md)",
            file=sys.stderr,
        )
        return 2
    token = access_token(key)
    d = a.days

    out: dict[str, list] = {}
    out["countries"] = query(token, ["country"], ["activeUsers", "sessions"], d, 15, "activeUsers")
    out["cities"] = query(token, ["city", "country"], ["activeUsers"], d, 15, "activeUsers")
    out["screens"] = query(token, ["pageTitle"], ["screenPageViews", "activeUsers"], d, 15, "screenPageViews")
    out["spots"] = query(
        token, ["customEvent:spot_id", "customEvent:region"], ["eventCount", "activeUsers"],
        d, 25, "eventCount", event_filter("spot_view"),
    )
    out["regions"] = query(
        token, ["customEvent:region"], ["eventCount", "activeUsers"], d, 20, "eventCount",
        event_filter("spot_view"),
    )
    out["favorites"] = query(
        token, ["customEvent:spot_id"], ["eventCount"], d, 25, "eventCount",
        event_filter("favorite_add"),
    )
    out["events"] = query(token, ["eventName"], ["eventCount"], d, 20, "eventCount")
    # installs by kind: `via` is play | pwa since 2026-09-19; blank = sent before that, or
    # today's rows GA has not finished processing
    out["installs"] = query(
        token, ["customEvent:via"], ["eventCount"], d, 10, "eventCount",
        event_filter("app_install"),
    )
    out["installs_daily"] = query(
        token, ["date", "customEvent:via"], ["eventCount"], d, 100, None,
        event_filter("app_install"),
    )
    for prop in ("units", "theme", "signed_in", "installed"):
        out[f"pref_{prop}"] = query(token, [f"customUser:{prop}"], ["activeUsers"], d, 10, "activeUsers")
    # swim mode (2026-09-28): "mode" is a user-scoped custom dimension the operator has to
    # register before the Data API accepts it - until then the query fails, so it is
    # reported as missing instead of taking the whole report down
    try:
        out["pref_mode"] = query(token, ["customUser:mode"], ["activeUsers"], d, 10, "activeUsers")
    except SystemExit as e:  # run_report turns an API refusal into SystemExit
        print(f"mode: not queryable yet - register the user property ({str(e)[:80]})")
        out["pref_mode"] = []

    if a.json:
        print(json.dumps(out, indent=1))
        return 0

    print(f"Rosa - GA4 property {PROPERTY_ID}, last {d} days")
    table("WHERE", ("country", "users", "sessions"),
          [(r[0][0], r[1][0], r[1][1]) for r in out["countries"]], (28, 8, 8))
    table("WHERE (city)", ("city", "country", "users"),
          [(r[0][0], r[0][1], r[1][0]) for r in out["cities"]], (24, 20, 8))
    table("SCREENS", ("screen", "views", "users"),
          [(r[0][0], r[1][0], r[1][1]) for r in out["screens"]], (24, 8, 8))
    table("SPOTS OPENED", ("spot", "region", "views", "users"),
          [(r[0][0], r[0][1], r[1][0], r[1][1]) for r in out["spots"]], (26, 22, 7, 7))
    table("REGIONS", ("region", "views", "users"),
          [(r[0][0], r[1][0], r[1][1]) for r in out["regions"]], (26, 8, 8))
    table("EVENTS", ("event", "count"),
          [(r[0][0], r[1][0]) for r in out["events"]], (26, 10))
    via = lambda v: v if v and v != "(not set)" else "(no via)"
    table("INSTALLS", ("via", "count"),
          [(via(r[0][0]), r[1][0]) for r in out["installs"]], (26, 10))
    table("INSTALLS BY DAY", ("date", "via", "count"),
          [(r[0][0], via(r[0][1]), r[1][0]) for r in sorted(out["installs_daily"], reverse=True)],
          (10, 16, 8))

    # opened often, favourited rarely - the closest thing Rosa has to a disappointment signal
    favs = {r[0][0]: int(r[1][0]) for r in out["favorites"]}
    cold = []
    for r in out["spots"]:
        sid, views = r[0][0], int(r[1][0])
        if views >= 10:
            cold.append((sid, views, favs.get(sid, 0), f"{100 * favs.get(sid, 0) / views:.0f}%"))
    cold.sort(key=lambda t: (t[2] / t[1], -t[1]))
    table("OPENED, NOT KEPT (views >= 10, lowest favourite rate first)",
          ("spot", "views", "favs", "rate"), cold[:15], (26, 7, 6, 6))

    for prop in ("units", "theme", "signed_in", "installed", "mode"):
        table(f"PREFERENCE: {prop}", (prop, "users"),
              [(r[0][0] or "(unset)", r[1][0]) for r in out[f"pref_{prop}"]], (20, 8))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
