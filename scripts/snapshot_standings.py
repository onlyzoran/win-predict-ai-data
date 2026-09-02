#!/usr/bin/env python3
"""Snapshot league standings into legacy history/ or contests/ facts layout."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import (
    resolve_or_create_participant,
    row_to_fact_row,
    utc_now_iso,
    write_facts_index,
    write_contests_index,
    write_standings_fact,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = Path(__file__).resolve().parent / "sources.json"
HISTORY_DIR = ROOT / "data" / "history"
ESPN_STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/{path}/standings"
ESPN_RANKINGS = "https://site.web.api.espn.com/apis/site/v2/sports/{path}/rankings"
MLB_STANDINGS = "https://statsapi.mlb.com/api/v1/standings"
MLB_TEAMS = "https://statsapi.mlb.com/api/v1/teams"
MLB_DIVISIONS = "https://statsapi.mlb.com/api/v1/divisions"
USER_AGENT = "win-predict-ai-data/1.0 (+standings-snapshot)"

_MLB_TEAM_NAMES: dict[int, str] | None = None
_MLB_DIVISION_META: dict[int, dict[str, str]] | None = None


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
    if isinstance(value, str) and value.startswith("."):
        value = f"0{value}"
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
            row.get("goalDifference")
            if row.get("goalDifference") is not None
            else (row.get("goalsFor") or 0) - (row.get("goalsAgainst") or 0),
            row.get("goalsFor") or 0,
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
    return (True, -(row.get("rank") or 10_000),)


def assign_ranks(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    if metric == "rank":
        return rows
    ranked = sorted(rows, key=lambda r: sort_key_for_metric(r, metric), reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


def child_matches_group(child: dict[str, Any], group_filter: str | None) -> bool:
    if not group_filter:
        return True
    needle = group_filter.casefold()
    for key in ("abbreviation", "name"):
        value = child.get(key)
        if value and needle in str(value).casefold():
            return True
    return False


def entry_display_name(entry: dict[str, Any]) -> str:
    if entry.get("athlete"):
        return team_name(entry.get("athlete"))
    return team_name(entry.get("team"))


def parse_standings_payload(
    data: dict[str, Any],
    group_filter: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    season = data.get("season") or {}
    returned_year = to_int(season.get("year"))
    if returned_year is None:
        seasons = data.get("seasons") or []
        if seasons:
            returned_year = to_int(seasons[0].get("year"))

    rows: list[dict[str, Any]] = []
    for child in data.get("children") or []:
        if not child_matches_group(child, group_filter):
            continue
        standings = child.get("standings") or {}
        child_year = to_int(standings.get("season"))
        if child_year is not None:
            returned_year = child_year
        group = child.get("name") or child.get("abbreviation")
        entries = standings.get("entries") or []
        for entry in entries:
            stats = stat_map(entry)
            rank = to_int(stats.get("rank")) or to_int(stats.get("playoffSeed"))
            points = to_int(stats.get("points"))
            if points is None:
                points = to_int(stats.get("championshipPts"))
            # Soccer (and similar): ESPN often exposes GF/GA as pointsFor/pointsAgainst.
            goals_for = to_int(stats.get("goalsFor"))
            goals_against = to_int(stats.get("goalsAgainst"))
            if "ties" in stats:
                if goals_for is None:
                    goals_for = to_int(stats.get("pointsFor"))
                if goals_against is None:
                    goals_against = to_int(stats.get("pointsAgainst"))
            goal_diff = to_int(stats.get("goalDifference"))
            if goal_diff is None:
                goal_diff = to_int(stats.get("pointDifferential"))
            if goal_diff is None:
                goal_diff = to_int(stats.get("differential"))
            if goal_diff is None and goals_for is not None and goals_against is not None:
                goal_diff = goals_for - goals_against
            row = {
                "team": entry_display_name(entry),
                "played": to_int(stats.get("gamesPlayed")) or to_int(stats.get("starts")),
                "wins": to_int(stats.get("wins")),
                "draws": to_int(stats.get("ties")),
                "losses": to_int(stats.get("losses")),
                "otLosses": to_int(stats.get("otLosses")),
                "goalsFor": goals_for,
                "goalsAgainst": goals_against,
                "goalDifference": goal_diff,
                "points": points,
                "winPercent": to_float(stats.get("winPercent")),
                "playoffSeed": to_int(stats.get("playoffSeed")),
                "group": group,
            }
            if rank is not None:
                row["sourceRank"] = rank
            rows.append(row)

    return rows, returned_year


def fetch_espn_standings(
    path: str,
    season_year: int | None,
    group_filter: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Fetch current ESPN standings.

    Prefer the default (no season query): for some leagues ``?season=YYYY`` returns
    an empty table even when the default payload already has that season.
    If the default season does not match ``season_year``, retry with an explicit query.
    """
    url = ESPN_STANDINGS.format(path=path)
    rows, returned_year = parse_standings_payload(http_get_json(url), group_filter)

    if season_year is None or returned_year == season_year:
        return rows, returned_year

    explicit_url = f"{url}?{urllib.parse.urlencode({'season': str(season_year)})}"
    return parse_standings_payload(http_get_json(explicit_url), group_filter)


def fetch_espn_rankings(path: str, poll: str) -> tuple[list[dict[str, Any]], int | None]:
    url = ESPN_RANKINGS.format(path=path)
    data = http_get_json(url)
    season = data.get("latestSeason") or data.get("requestedSeason") or {}
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
        entity = item.get("team") or item.get("athlete") or item.get("fighter") or {}
        name = entity.get("displayName")
        if not name:
            first = entity.get("firstName") or ""
            last = entity.get("lastName") or ""
            name = f"{first} {last}".strip()
        if not name:
            location = entity.get("location") or ""
            nickname = entity.get("name") or entity.get("nickname") or ""
            name = f"{location} {nickname}".strip() or entity.get("abbreviation") or "Unknown"
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


def mlb_team_names(season_year: int) -> dict[int, str]:
    global _MLB_TEAM_NAMES
    if _MLB_TEAM_NAMES is not None:
        return _MLB_TEAM_NAMES
    url = f"{MLB_TEAMS}?{urllib.parse.urlencode({'sportId': 1, 'season': season_year})}"
    data = http_get_json(url)
    names: dict[int, str] = {}
    for team in data.get("teams") or []:
        team_id = to_int(team.get("id"))
        if team_id is None:
            continue
        names[team_id] = str(team.get("name") or team.get("teamName") or team_id)
    _MLB_TEAM_NAMES = names
    return names


def mlb_division_meta() -> dict[int, dict[str, str]]:
    global _MLB_DIVISION_META
    if _MLB_DIVISION_META is not None:
        return _MLB_DIVISION_META
    url = f"{MLB_DIVISIONS}?{urllib.parse.urlencode({'sportId': 1})}"
    data = http_get_json(url)
    meta: dict[int, dict[str, str]] = {}
    for division in data.get("divisions") or []:
        division_id = to_int(division.get("id"))
        if division_id is None:
            continue
        league_id = to_int((division.get("league") or {}).get("id"))
        league_name = "American League" if league_id == 103 else "National League" if league_id == 104 else None
        meta[division_id] = {
            "division": str(division.get("nameShort") or division.get("name") or division_id),
            "league": league_name or str(league_id or ""),
        }
    _MLB_DIVISION_META = meta
    return meta


def fetch_mlb_standings(season_year: int, as_of: date) -> tuple[list[dict[str, Any]], int | None]:
    params = {
        "leagueId": "103,104",
        "season": str(season_year),
        "date": as_of.isoformat(),
        "standingsTypes": "regularSeason",
    }
    url = f"{MLB_STANDINGS}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    names = mlb_team_names(season_year)
    divisions = mlb_division_meta()

    rows: list[dict[str, Any]] = []
    for record in data.get("records") or []:
        division_id = to_int((record.get("division") or {}).get("id"))
        group_meta = divisions.get(division_id or -1, {})
        group = group_meta.get("league") or group_meta.get("division")
        for entry in record.get("teamRecords") or []:
            team = entry.get("team") or {}
            team_id = to_int(team.get("id"))
            name = names.get(team_id or -1) or team.get("name") or "Unknown"
            rows.append(
                {
                    "team": name,
                    "played": to_int(entry.get("gamesPlayed")),
                    "wins": to_int(entry.get("wins")),
                    "losses": to_int(entry.get("losses")),
                    "winPercent": to_float(entry.get("winningPercentage")),
                    "playoffSeed": to_int(entry.get("divisionRank")),
                    "sourceRank": to_int(entry.get("sportRank")),
                    "group": group,
                }
            )
    return rows, season_year


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            continue
        cleaned[key] = value
    return cleaned


def list_available_days(league_id: str) -> list[str]:
    out_dir = HISTORY_DIR / league_id
    if not out_dir.is_dir():
        return []
    return sorted(path.stem for path in out_dir.glob("????-??-??.json"))


def write_league_days_index(league_id: str) -> dict[str, Any]:
    days = list_available_days(league_id)
    payload = {
        "leagueId": league_id,
        "count": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "days": days,
    }
    out_dir = HISTORY_DIR / league_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "days.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def write_history_index() -> dict[str, Any]:
    leagues: dict[str, Any] = {}
    if HISTORY_DIR.is_dir():
        for path in sorted(HISTORY_DIR.iterdir()):
            if not path.is_dir():
                continue
            league_id = path.name
            days_meta = write_league_days_index(league_id)
            leagues[league_id] = {
                "count": days_meta["count"],
                "first": days_meta["first"],
                "last": days_meta["last"],
                "daysFile": f"{league_id}/days.json",
                "latestFile": f"{league_id}/latest.json" if (path / "latest.json").exists() else None,
            }

    payload = {
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "leagues": leagues,
    }
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def write_snapshot(
    league_id: str,
    snapshot_date: date,
    source_name: str,
    metric: str,
    season_year: int | None,
    rows: list[dict[str, Any]],
    dry_run: bool,
    update_latest: bool,
    refresh_index: bool = True,
    layout: str = "history",
) -> str:
    ranked = assign_ranks(rows, metric)
    day = snapshot_date.isoformat()

    if layout == "contests":
        fact_rows: list[dict[str, Any]] = []
        for row in ranked:
            cleaned = clean_row(row)
            team = cleaned.get("team")
            if not team:
                continue
            if dry_run:
                fact_rows.append(cleaned)
                continue
            participant_id, _ = resolve_or_create_participant(league_id, str(team))
            fact_rows.append(row_to_fact_row(cleaned, participant_id))

        if dry_run:
            from contest_io import facts_grain, infer_tour_state, tour_dirname

            if facts_grain(league_id) == "matchday":
                tour, status = infer_tour_state([{"played": r.get("played")} for r in ranked])
                folder = tour_dirname(tour) if status != "preseason" else "tour-00"
                out_rel = f"data/contests/{league_id}/facts/standings/{folder}/{day}.json"
                if status == "final":
                    out_rel += " (+ latest.json)"
            else:
                out_rel = f"data/contests/{league_id}/facts/standings/{day}.json"
            return f"dry-run {league_id}@{day}: {len(fact_rows)} teams -> {out_rel}"

        out_path = write_standings_fact(
            league_id,
            snapshot_date=day,
            fetched_at=utc_now_iso(),
            provider=source_name,
            metric=metric,
            season_year=season_year,
            rows=fact_rows,
            update_latest=update_latest,
            refresh_index=refresh_index,
        )
        if out_path is None:
            return f"skip {league_id}@{day}: unchanged"
        return f"ok {league_id}@{day}: {len(fact_rows)} teams -> {out_path.relative_to(ROOT)}"

    payload = {
        "leagueId": league_id,
        "date": day,
        "fetchedAt": utc_now_iso(),
        "source": source_name,
        "metric": metric,
        "seasonYear": season_year,
        "standings": [clean_row(row) for row in ranked],
    }

    out_dir = HISTORY_DIR / league_id
    out_path = out_dir / f"{day}.json"
    latest_path = out_dir / "latest.json"

    if dry_run:
        return f"dry-run {league_id}@{day}: {len(ranked)} teams -> {out_path.relative_to(ROOT)}"

    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(text, encoding="utf-8")
    if update_latest:
        latest_path.write_text(text, encoding="utf-8")
    if refresh_index:
        write_league_days_index(league_id)
        write_history_index()
    return f"ok {league_id}@{day}: {len(ranked)} teams -> {out_path.relative_to(ROOT)}"


def snapshot_league(
    league_id: str,
    source: dict[str, Any],
    snapshot_date: date,
    dry_run: bool,
    update_latest: bool = True,
    refresh_index: bool = True,
) -> str:
    provider = source.get("provider")
    if provider == "unsupported":
        note = source.get("note") or "no provider configured"
        return f"skip {league_id}: unsupported ({note})"

    kind = source.get("kind")
    metric = source.get("metric") or "points"
    expected_year = to_int(source.get("seasonYear"))
    source_name = provider if provider != "espn" else "espn"

    try:
        if provider == "espn" and kind == "standings":
            rows, returned_year = fetch_espn_standings(
                source.get("path"),
                expected_year,
                source.get("group"),
            )
        elif provider == "espn" and kind == "rankings":
            rows, returned_year = fetch_espn_rankings(source.get("path"), source.get("poll") or "ap")
        elif provider == "mlb-statsapi" and kind == "standings":
            if expected_year is None:
                return f"skip {league_id}: seasonYear required for mlb-statsapi"
            rows, returned_year = fetch_mlb_standings(expected_year, snapshot_date)
        else:
            return f"skip {league_id}: unknown provider/kind {provider}/{kind}"
    except urllib.error.HTTPError as exc:
        return f"error {league_id}@{snapshot_date.isoformat()}: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return f"error {league_id}@{snapshot_date.isoformat()}: {exc.reason}"

    if provider == "espn" and expected_year is not None and returned_year is not None and returned_year != expected_year:
        return (
            f"skip {league_id}: ESPN season {returned_year} != expected {expected_year} "
            "(season not available yet)"
        )

    if not rows:
        return f"skip {league_id}@{snapshot_date.isoformat()}: empty standings"

    if metric == "wins":
        for row in rows:
            row.pop("points", None)
            row.pop("draws", None)

    return write_snapshot(
        league_id=league_id,
        snapshot_date=snapshot_date,
        source_name=source_name,
        metric=metric,
        season_year=returned_year if returned_year is not None else expected_year,
        rows=rows,
        dry_run=dry_run,
        update_latest=update_latest,
        refresh_index=refresh_index,
        layout=str(source.get("layout") or "history"),
    )


def daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


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
        help="Snapshot date YYYY-MM-DD (default: today UTC). Ignored when --from is set.",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        help="Backfill start date YYYY-MM-DD (inclusive). Requires supportsHistory.",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        help="Backfill end date YYYY-MM-DD (inclusive). Default: today UTC.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.15,
        help="Seconds to sleep between historical day fetches (default: 0.15).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate without writing files.",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild data/history indexes and data/contests indexes from existing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = load_sources()
    today = datetime.now(timezone.utc).date()

    if args.rebuild_index:
        index = write_history_index()
        print(f"rebuilt index: {len(index['leagues'])} leagues -> data/history/index.json")
        for league_id, source in sources.items():
            if source.get("layout") == "contests":
                write_facts_index(league_id)
        contests_index = write_contests_index()
        print(f"rebuilt contests index: {len(contests_index['contests'])} contests -> data/contests/index.json")
        return 0

    league_ids = args.leagues or list(sources.keys())
    unknown = [league_id for league_id in league_ids if league_id not in sources]
    if unknown:
        print(f"Unknown league ids: {', '.join(unknown)}", file=sys.stderr)
        return 2

    statuses: list[str] = []
    errors = 0
    wrote_history = False
    wrote_contests = False

    if args.date_from:
        range_start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to) if args.date_to else today
        if end < range_start:
            print("--to must be on or after --from", file=sys.stderr)
            return 2

        for league_id in league_ids:
            source = sources[league_id]
            if not source.get("supportsHistory"):
                print(f"skip {league_id}: historical backfill not supported")
                continue

            start = range_start
            season_start = source.get("seasonStart")
            if season_start:
                start = max(start, date.fromisoformat(season_start))

            days = daterange(start, end)
            print(f"backfill {league_id}: {days[0]} -> {days[-1]} ({len(days)} days)")
            for i, day in enumerate(days):
                update_latest = day == days[-1]
                status = snapshot_league(
                    league_id,
                    source,
                    day,
                    args.dry_run,
                    update_latest=update_latest,
                    refresh_index=False,
                )
                # Keep output readable: print every day on errors/skips, else progress every 10 days + last.
                if (
                    status.startswith("error")
                    or status.startswith("skip")
                    or i == 0
                    or i == len(days) - 1
                    or (i + 1) % 10 == 0
                ):
                    print(status)
                statuses.append(status)
                if status.startswith("ok"):
                    if sources[league_id].get("layout") == "contests":
                        wrote_contests = True
                    else:
                        wrote_history = True
                if status.startswith("error"):
                    errors += 1
                if args.sleep > 0 and i < len(days) - 1:
                    time.sleep(args.sleep)
    else:
        snapshot_date = date.fromisoformat(args.date) if args.date else today
        for league_id in league_ids:
            status = snapshot_league(
                league_id,
                sources[league_id],
                snapshot_date,
                args.dry_run,
                refresh_index=False,
            )
            print(status)
            statuses.append(status)
            if status.startswith("ok"):
                if sources[league_id].get("layout") == "contests":
                    wrote_contests = True
                else:
                    wrote_history = True
            if status.startswith("error"):
                errors += 1

    if not args.dry_run:
        if wrote_history:
            index = write_history_index()
            print(f"index: {len(index['leagues'])} leagues -> data/history/index.json")
        if wrote_contests:
            for league_id in league_ids:
                if sources[league_id].get("layout") == "contests":
                    write_facts_index(league_id)
            contests_index = write_contests_index()
            print(f"contests index: {len(contests_index['contests'])} contests -> data/contests/index.json")

    ok_count = sum(1 for s in statuses if s.startswith("ok") or s.startswith("dry-run"))
    skip_count = sum(1 for s in statuses if s.startswith("skip"))
    print(f"done: ok={ok_count} skip={skip_count} error={errors}")
    return 1 if errors else 0



if __name__ == "__main__":
    raise SystemExit(main())
