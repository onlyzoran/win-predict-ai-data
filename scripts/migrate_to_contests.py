#!/usr/bin/env python3
"""Migrate RPL and MLB from legacy data/ + data/history/ into data/contests/."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import (
    ALIAS_TO_CANONICAL,
    CONTESTS_DIR,
    ROOT,
    build_name_index,
    load_participants,
    resolve_or_create_participant,
    row_to_fact_row,
    save_participants,
    slugify,
    utc_now_iso,
    write_contests_index,
    write_facts_index,
    write_json,
    write_prediction_snapshot,
    write_predictions_index,
    write_standings_fact,
)

HISTORY_DIR = ROOT / "data" / "history"
LEAGUES_PATH = ROOT / "data" / "leagues.json"

CONTESTS: dict[str, dict[str, Any]] = {
    "rpl-26-27": {
        "id": "rpl-26-27",
        "title": "RPL",
        "fullTitle": "Russian Premier League",
        "category": "sport",
        "sport": "football",
        "target": "champion",
        "season": {"start": "2026-07-24", "end": "2027-05-29"},
        "metric": "points",
        "hasFacts": True,
        "factKinds": ["standings"],
        "factsGrain": "matchday",
        "predictionTarget": "win_probability",
        "legacyPredictionFile": "rpl-26-27.json",
        "predictionModel": {"name": "cursor-cloud", "version": "composer-2.5"},
    },
    "mlb-world-series-26": {
        "id": "mlb-world-series-26",
        "title": "MLB World Series",
        "fullTitle": "Major League Baseball | World Series",
        "category": "sport",
        "sport": "baseball",
        "target": "champion",
        "season": {"start": "2026-03-26", "end": "2026-11-01"},
        "metric": "wins",
        "hasFacts": True,
        "factKinds": ["standings"],
        "factsGrain": "day",
        "predictionTarget": "win_probability",
        "legacyPredictionFile": "mlb-world-series-26.json",
        "predictionModel": {"name": "legacy-import", "version": "migrated"},
    },
}


def collect_names(contest_id: str, prediction_path: Path) -> tuple[set[str], set[str]]:
    fact_names: set[str] = set()
    hist = HISTORY_DIR / contest_id
    if hist.is_dir():
        for path in hist.glob("????-??-??.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("standings") or []:
                name = row.get("team")
                if name:
                    fact_names.add(str(name))

    pred_names: set[str] = set()
    if prediction_path.exists():
        for item in json.loads(prediction_path.read_text(encoding="utf-8")):
            name = item.get("team")
            if name:
                pred_names.add(str(name))
    return fact_names, pred_names


def seed_participants(contest_id: str, fact_names: set[str], pred_names: set[str]) -> None:
    alias_map = ALIAS_TO_CANONICAL.get(contest_id) or {}
    buckets: dict[str, set[str]] = {}

    for name in sorted(fact_names):
        buckets.setdefault(name, set())

    for pred_name in sorted(pred_names):
        canonical = alias_map.get(pred_name, pred_name)
        fact_match = next((f for f in fact_names if f.casefold() == canonical.casefold()), None)
        if fact_match:
            canonical = fact_match
        elif canonical not in buckets and pred_name.casefold() in {f.casefold() for f in fact_names}:
            canonical = next(f for f in fact_names if f.casefold() == pred_name.casefold())
        bucket = buckets.setdefault(canonical, set())
        if pred_name != canonical:
            bucket.add(pred_name)

    participants = []
    used_ids: set[str] = set()
    for canonical, aliases in sorted(buckets.items(), key=lambda kv: kv[0].casefold()):
        participant_id = slugify(canonical)
        if participant_id in used_ids:
            suffix = 2
            while f"{participant_id}-{suffix}" in used_ids:
                suffix += 1
            participant_id = f"{participant_id}-{suffix}"
        used_ids.add(participant_id)
        participants.append(
            {
                "id": participant_id,
                "name": canonical,
                "aliases": sorted(aliases, key=str.casefold),
            }
        )

    save_participants(contest_id, {"contestId": contest_id, "participants": participants})


def migrate_facts(contest_id: str) -> int:
    hist = HISTORY_DIR / contest_id
    if not hist.is_dir():
        return 0

    days = sorted(path for path in hist.glob("????-??-??.json"))
    count = 0
    for i, path in enumerate(days):
        legacy = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for row in legacy.get("standings") or []:
            team = row.get("team")
            if not team:
                continue
            participant_id, _ = resolve_or_create_participant(contest_id, str(team))
            rows.append(row_to_fact_row(row, participant_id))

        is_last = i == len(days) - 1
        write_standings_fact(
            contest_id,
            snapshot_date=legacy.get("date") or path.stem,
            fetched_at=legacy.get("fetchedAt") or utc_now_iso(),
            provider=legacy.get("source") or "unknown",
            metric=legacy.get("metric") or "points",
            season_year=legacy.get("seasonYear"),
            rows=rows,
            update_latest=is_last,
            refresh_index=False,
        )
        count += 1

    write_facts_index(contest_id)
    return count


def migrate_predictions(contest_id: str, meta: dict[str, Any]) -> bool:
    pred_path = ROOT / "data" / meta["legacyPredictionFile"]
    if not pred_path.exists():
        return False

    items_raw = json.loads(pred_path.read_text(encoding="utf-8"))
    items = []
    for item in items_raw:
        team = item.get("team")
        if not team:
            continue
        participant_id, _ = resolve_or_create_participant(contest_id, str(team))
        probability = item.get("win_predict")
        if probability is None:
            continue
        items.append({"participantId": participant_id, "probability": probability})

    facts_index = CONTESTS_DIR / contest_id / "facts" / "index.json"
    based_on = None
    snapshot_date = None
    if facts_index.exists():
        based_on = json.loads(facts_index.read_text(encoding="utf-8")).get("last")
        snapshot_date = based_on
    if not snapshot_date:
        snapshot_date = utc_now_iso()[:10]

    write_prediction_snapshot(
        contest_id,
        snapshot_date=snapshot_date,
        generated_at=utc_now_iso(),
        model=meta["predictionModel"],
        based_on_facts_date=based_on,
        items=items,
        update_latest=True,
        refresh_index=True,
    )
    return True


def update_leagues_catalog(contest_ids: list[str]) -> None:
    leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
    by_id = {c: CONTESTS[c] for c in contest_ids}
    for entry in leagues:
        contest_id = entry.get("id")
        if contest_id not in by_id:
            continue
        entry.pop("file", None)
        entry.pop("marketPath", None)
        entry["layout"] = "contests"
        entry["contestPath"] = f"contests/{contest_id}"
    write_json(LEAGUES_PATH, leagues)


def rebuild_legacy_history_index() -> None:
    """Rewrite data/history/index.json without migrated contests."""
    leagues: dict[str, Any] = {}
    if HISTORY_DIR.is_dir():
        for path in sorted(HISTORY_DIR.iterdir()):
            if not path.is_dir():
                continue
            league_id = path.name
            days = sorted(p.stem for p in path.glob("????-??-??.json"))
            days_payload = {
                "leagueId": league_id,
                "count": len(days),
                "first": days[0] if days else None,
                "last": days[-1] if days else None,
                "days": days,
            }
            (path / "days.json").write_text(
                json.dumps(days_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            leagues[league_id] = {
                "count": days_payload["count"],
                "first": days_payload["first"],
                "last": days_payload["last"],
                "daysFile": f"{league_id}/days.json",
                "latestFile": f"{league_id}/latest.json" if (path / "latest.json").exists() else None,
            }
    payload = {"updatedAt": utc_now_iso(), "leagues": leagues}
    write_json(HISTORY_DIR / "index.json", payload)


def remove_legacy(contest_id: str, meta: dict[str, Any]) -> None:
    hist = HISTORY_DIR / contest_id
    if hist.exists():
        shutil.rmtree(hist)
    pred = ROOT / "data" / meta["legacyPredictionFile"]
    if pred.exists():
        pred.unlink()


def migrate_one(contest_id: str, *, purge_legacy: bool) -> None:
    meta = CONTESTS[contest_id]
    pred_path = ROOT / "data" / meta["legacyPredictionFile"]
    fact_names, pred_names = collect_names(contest_id, pred_path)

    path = CONTESTS_DIR / contest_id
    if path.exists():
        shutil.rmtree(path)

    write_json(
        path / "contest.json",
        {
            "id": meta["id"],
            "title": meta["title"],
            "fullTitle": meta["fullTitle"],
            "category": meta["category"],
            "sport": meta["sport"],
            "target": meta["target"],
            "season": meta["season"],
            "metric": meta["metric"],
            "hasFacts": meta["hasFacts"],
            "factKinds": meta["factKinds"],
            "factsGrain": meta.get("factsGrain") or "day",
            "predictionTarget": meta["predictionTarget"],
        },
    )

    seed_participants(contest_id, fact_names, pred_names)
    facts_count = migrate_facts(contest_id)
    preds_ok = migrate_predictions(contest_id, meta)
    write_facts_index(contest_id)
    write_predictions_index(contest_id)

    participants = load_participants(contest_id)
    index = build_name_index(participants)
    unresolved = [n for n in pred_names if n.casefold() not in index]
    if unresolved:
        raise SystemExit(f"{contest_id}: unresolved prediction names: {unresolved}")

    print(
        f"{contest_id}: participants={len(participants['participants'])} "
        f"fact_days={facts_count} predictions={'yes' if preds_ok else 'no'}"
    )

    if purge_legacy:
        remove_legacy(contest_id, meta)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contest",
        action="append",
        dest="contests",
        choices=sorted(CONTESTS.keys()),
        help="Contest id to migrate (repeatable). Default: all.",
    )
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Do not delete data/history/{id} or data/{id}.json after migration.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contest_ids = args.contests or list(CONTESTS.keys())
    purge = not args.keep_legacy

    for contest_id in contest_ids:
        migrate_one(contest_id, purge_legacy=purge)

    update_leagues_catalog(contest_ids)
    write_contests_index()
    if purge:
        rebuild_legacy_history_index()

    print(f"contests index -> {CONTESTS_DIR / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
