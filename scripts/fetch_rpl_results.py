#!/usr/bin/env python3
"""Fetch free RPL match results from the ESPN public scoreboard API (no key).

Examples:
  python3 scripts/fetch_rpl_results.py
  python3 scripts/fetch_rpl_results.py --from 20260724 --to 20260806
  python3 scripts/fetch_rpl_results.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/rus.1/scoreboard"
USER_AGENT = "win-predict-ai-data/1.0 (+rpl-results)"


def http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_ymd(value: str) -> date:
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").date()


def format_ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def iter_dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def competitor(teams: list[dict[str, Any]], side: str) -> dict[str, Any]:
    for team in teams:
        if team.get("homeAway") == side:
            return team
    raise KeyError(side)


def parse_event(event: dict[str, Any]) -> dict[str, Any] | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    comp = competitions[0]
    teams = comp.get("competitors") or []
    if len(teams) < 2:
        return None
    home = competitor(teams, "home")
    away = competitor(teams, "away")
    status = (event.get("status") or {}).get("type") or {}
    return {
        "date": event.get("date"),
        "status": status.get("name") or status.get("description") or "UNKNOWN",
        "completed": bool(status.get("completed")),
        "home": (home.get("team") or {}).get("displayName") or "Unknown",
        "away": (away.get("team") or {}).get("displayName") or "Unknown",
        "homeScore": home.get("score"),
        "awayScore": away.get("score"),
    }


def fetch_day(day: date) -> list[dict[str, Any]]:
    url = f"{ESPN_SCOREBOARD}?dates={format_ymd(day)}"
    payload = http_get_json(url)
    out: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        parsed = parse_event(event)
        if parsed:
            out.append(parsed)
    return out


def default_range() -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=14), today


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch RPL results from ESPN (free, no key).")
    parser.add_argument("--from", dest="date_from", help="Start date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="End date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--completed-only", action="store_true", help="Only finished matches")
    args = parser.parse_args()

    start, end = default_range()
    if args.date_from:
        start = parse_ymd(args.date_from)
    if args.date_to:
        end = parse_ymd(args.date_to)
    if end < start:
        print("--to must be on or after --from", file=sys.stderr)
        return 2

    matches: list[dict[str, Any]] = []
    for day in iter_dates(start, end):
        try:
            matches.extend(fetch_day(day))
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code} for {day}: {exc}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"Network error for {day}: {exc}", file=sys.stderr)
            return 1

    # De-dupe by date+home+away (scoreboard calendars can overlap)
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for match in matches:
        key = (str(match["date"]), match["home"], match["away"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)

    if args.completed_only:
        unique = [m for m in unique if m.get("completed") or str(m.get("status", "")).endswith("FULL_TIME") or m.get("status") == "STATUS_FINAL"]

    unique.sort(key=lambda m: str(m.get("date") or ""))

    if args.json:
        json.dump(
            {
                "league": "rpl-26-27",
                "source": "espn",
                "path": "soccer/rus.1",
                "from": format_ymd(start),
                "to": format_ymd(end),
                "matches": unique,
            },
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        print()
        return 0

    print(f"RPL results {format_ymd(start)} → {format_ymd(end)} ({len(unique)} matches, source=espn)")
    for match in unique:
        score = f"{match.get('awayScore', '?')} - {match.get('homeScore', '?')}"
        print(f"{match['date']}  {match['status']:<18}  {match['away']} {score} {match['home']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
