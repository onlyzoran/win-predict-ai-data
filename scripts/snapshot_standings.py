#!/usr/bin/env python3
"""Snapshot league standings into data/history/{leagueId}/{YYYY-MM-DD}.json."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = Path(__file__).resolve().parent / "sources.json"
HISTORY_DIR = ROOT / "data" / "history"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/{path}/standings"
ESPN_RANKINGS = "https://site.api.espn.com/apis/site/v2/sports/{path}/rankings"
USER_AGENT = "win-predict-ai-data/1.0 (+standings-snapshot)"


def load_sources() -> dict[str, dict[str, Any]]:
    with SOURCES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stat_map(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for s in entry.get("stats") or []:
        name = s.get("name")
        if not name:
            continue
        value = s.get("value")
        if value is None:
            display = s.get("displayValue")
            out[name] = display
        else:
            out[name] = value
            out[f"{name}Display"] = s.get("displayValue")
    return out


def team_name(team: dict[str, Any] | None) -> str:
    if not team:
        return "Unknown"
    for key in ("displayName", "name"):
        value = team.get(key)
        if value:
            return str(value)
    location = team.get("location") or ""
    nickname = team.get("name") or team.get("nickname") or ""
    combined = f"{location} {nickname}".strip()
    return combined or str(team.get("abbreviation") or "Unknown")


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_record(summary: str | None) -> tuple[int | None, int | None, int | None]:
    if not summary:
        return None, None, None
    parts = summary.replace("–", "-").split("-")
    if len(parts) == 2:
        return to_int(parts[0]), None, to_int(parts[1])
    if len(parts) == 3:
        return to_int(parts[0]), to_int(parts[1]), to_int(parts[2])
    return None, None, None


def sort_key_for_metric(row: dict[str, Any], metric: str) -> tuple:
    if metric == "points":
        return (
            row.get("points") is not None,
            row.get("points") or 0,
            row.get("wins") or 0,
            -(row.get("losses") or 0),
        )
    if metric == "wins":
        return (
            row.get("winPercent") is not None,
            row.get("winPercent") or 0.0,
            row.get("wins") or 0,
            -(row.get("losses") or 0),
        )
    # rank / poll: already ordered by source
    return (True, -(row.get("rank") or 10_000),)


def assign_ranks(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    if metric == "rank":
        return rows
    ranked = sorted(rows, key=lambda r: sort_key_for_metric(r, metric), reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


def parse_standings_payload(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    season = data.get("season") or {}
    returned_year = to_int(season.get("year"))

    rows: list[dict[str, Any]] = []
    for child in data.get("children") or []:
        group = child.get("name") or child.get("abbreviation")
        entries = (child.get("standings") or {}).get("entries") or []
        for entry in entries:
            stats = stat_map(entry)
            rank = to_int(stats.get("rank")) or to_int(stats.get("playoffSeed"))
            row = {
                "team": team_name(entry.get("team")),
                "played": to_int(stats.get("gamesPlayed")),
                "wins": to_int(stats.get("wins")),
                "draws": to_int(stats.get("ties")),
                "losses": to_int(stats.get("losses")),
                "otLosses": to_int(stats.get("otLosses")),
                "points": to_int(stats.get("points")),
                "winPercent": to_float(stats.get("winPercent")),
                "playoffSeed": to_int(stats.get("playoffSeed")),
                "group": group,
            }
            if rank is not None:
                row["sourceRank"] = rank
            rows.append(row)

    return rows, returned_year


def fetch_espn_standings(path: str, season_year: int | None) -> tuple[list[dict[str, Any]], int | None]:
    """Fetch current ESPN standings.

    Prefer the default (no season query): for some leagues ``?season=YYYY`` returns
    an empty table even when the default payload already has that season.
    If the default season does not match ``season_year``, retry with an explicit
    query — then the caller validates the returned year.
    """
    url = ESPN_STANDINGS.format(path=path)
    rows, returned_year = parse_standings_payload(http_get_json(url))

    if season_year is None or returned_year == season_year:
        return rows, returned_year

    # Wrong/off-season default (e.g. UCL still on previous year) — try explicit season.
    explicit_url = f"{url}?{urllib.parse.urlencode({'season': str(season_year)})}"
    return parse_standings_payload(http_get_json(explicit_url))


def fetch_espn_rankings(path: str, poll: str) -> tuple[list[dict[str, Any]], int | None]:
    url = ESPN_RANKINGS.format(path=path)
    data = http_get_json(url)
    season = (data.get("latestSeason") or data.get("requestedSeason") or {})
    returned_year = to_int(season.get("year"))

    rankings = data.get("rankings") or []
    selected = None
    for block in rankings:
        if str(block.get("type") or "").lower() == poll.lower():
            selected = block
            break
        if poll.lower() in str(block.get("name") or "").lower():
            selected = block
            break
    if selected is None and rankings:
        selected = rankings[0]
    if not selected:
        return [], returned_year

    rows: list[dict[str, Any]] = []
    for item in selected.get("ranks") or []:
        team = item.get("team") or {}
        name = team.get("displayName")
        if not name:
            location = team.get("location") or ""
            nickname = team.get("name") or team.get("nickname") or ""
            name = f"{location} {nickname}".strip() or team.get("abbreviation") or "Unknown"
        wins, draws, losses = parse_record(item.get("recordSummary"))
        rows.append(
            {
                "rank": to_int(item.get("current")),
                "team": name,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "points": to_float(item.get("points")),
                "group": selected.get("name"),
            }
        )
    return rows, returned_year


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            continue
        cleaned[key] = value
    return cleaned


def snapshot_league(
    league_id: str,
    source: dict[str, Any],
    snapshot_date: date,
    dry_run: bool,
) -> str:
    provider = source.get("provider")
    if provider == "unsupported":
        note = source.get("note") or "no provider configured"
        return f"skip {league_id}: unsupported ({note})"

    if provider != "espn":
        return f"skip {league_id}: unknown provider {provider}"

    kind = source.get("kind")
    path = source.get("path")
    metric = source.get("metric") or "points"
    expected_year = to_int(source.get("seasonYear"))

    try:
        if kind == "standings":
            rows, returned_year = fetch_espn_standings(path, expected_year)
        elif kind == "rankings":
            rows, returned_year = fetch_espn_rankings(path, source.get("poll") or "ap")
        else:
            return f"skip {league_id}: unknown kind {kind}"
    except urllib.error.HTTPError as exc:
        return f"error {league_id}: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return f"error {league_id}: {exc.reason}"

    if expected_year is not None and returned_year is not None and returned_year != expected_year:
        return (
            f"skip {league_id}: ESPN season {returned_year} != expected {expected_year} "
            "(season not available yet)"
        )

    if not rows:
        return f"skip {league_id}: empty standings"

    # ESPN puts a non-table "points" value on NBA/NFL rows; keep points only for table sports.
    if metric == "wins":
        for row in rows:
            row.pop("points", None)
            row.pop("draws", None)

    ranked = assign_ranks(rows, metric)
    payload = {
        "leagueId": league_id,
        "date": snapshot_date.isoformat(),
        "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "espn",
        "metric": metric,
        "seasonYear": returned_year if returned_year is not None else expected_year,
        "standings": [clean_row(row) for row in ranked],
    }

    out_dir = HISTORY_DIR / league_id
    out_path = out_dir / f"{snapshot_date.isoformat()}.json"
    latest_path = out_dir / "latest.json"

    if dry_run:
        return f"dry-run {league_id}: {len(ranked)} teams -> {out_path.relative_to(ROOT)}"

    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    return f"ok {league_id}: {len(ranked)} teams -> {out_path.relative_to(ROOT)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="League id to snapshot (repeatable). Default: all configured leagues.",
    )
    parser.add_argument(
        "--date",
        help="Snapshot date YYYY-MM-DD (default: today UTC).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = load_sources()

    if args.date:
        snapshot_date = date.fromisoformat(args.date)
    else:
        snapshot_date = datetime.now(timezone.utc).date()

    league_ids = args.leagues or list(sources.keys())
    unknown = [league_id for league_id in league_ids if league_id not in sources]
    if unknown:
        print(f"Unknown league ids: {', '.join(unknown)}", file=sys.stderr)
        return 2

    statuses: list[str] = []
    errors = 0
    for league_id in league_ids:
        status = snapshot_league(league_id, sources[league_id], snapshot_date, args.dry_run)
        print(status)
        statuses.append(status)
        if status.startswith("error"):
            errors += 1

    ok_count = sum(1 for s in statuses if s.startswith("ok") or s.startswith("dry-run"))
    skip_count = sum(1 for s in statuses if s.startswith("skip"))
    print(f"done: ok={ok_count} skip={skip_count} error={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
