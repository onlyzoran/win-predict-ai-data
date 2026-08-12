#!/usr/bin/env python3
"""Migrate legacy data/ + data/history/ into data/contests/."""

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
DATA_DIR = ROOT / "data"

# Football leagues with round-based standings -> tour/matchday layout.
MATCHDAY_CONTESTS = frozenset(
    {
        "rpl-26-27",
        "epl-26-27",
        "la-liga-26-27",
        "serie-a-26-27",
        "bundesliga-26-27",
        "ligue-1-26-27",
        "mls-cup-26",
    }
)

# Contests already on the new layout (legacy files removed).
ALREADY_MIGRATED = frozenset({"rpl-26-27", "mlb-world-series-26"})


def infer_metric(contest_id: str) -> str:
    hist = HISTORY_DIR / contest_id
    if not hist.is_dir():
        return "points"
    days = sorted(hist.glob("????-??-??.json"))
    if not days:
        return "points"
    payload = json.loads(days[-1].read_text(encoding="utf-8"))
    return str(payload.get("metric") or "points")


def build_contests_config() -> dict[str, dict[str, Any]]:
    leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
    contests: dict[str, dict[str, Any]] = {}

    for entry in leagues:
        contest_id = entry["id"]
        has_history = (HISTORY_DIR / contest_id).is_dir()
        pred_file = DATA_DIR / f"{contest_id}.json"
        has_predictions = pred_file.exists()

        sport = entry.get("sport") or "unknown"
        category = "politics" if sport == "politics" else "sport"
        grain = "matchday" if contest_id in MATCHDAY_CONTESTS else "day"

        meta: dict[str, Any] = {
            "id": contest_id,
            "title": entry["title"],
            "fullTitle": entry["fullTitle"],
            "category": category,
            "sport": sport,
            "target": "champion",
            "season": {"start": entry["startDate"], "end": entry["endDate"]},
            "hasFacts": has_history,
            "predictionTarget": "win_probability",
            "predictionModel": {"name": "legacy-import", "version": "migrated"},
        }

        if has_history:
            meta["metric"] = infer_metric(contest_id)
            meta["factKinds"] = ["standings"]
            meta["factsGrain"] = grain
        if has_predictions:
            meta["legacyPredictionFile"] = f"{contest_id}.json"

        contests[contest_id] = meta

    return contests


CONTESTS = build_contests_config()


def collect_names(contest_id: str, prediction_path: Path | None) -> tuple[set[str], set[str]]:
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
    if prediction_path and prediction_path.exists():
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
    legacy_file = meta.get("legacyPredictionFile")
    if not legacy_file:
        return False
    pred_path = DATA_DIR / legacy_file
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


def contest_json_payload(meta: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": meta["id"],
        "title": meta["title"],
        "fullTitle": meta["fullTitle"],
        "category": meta["category"],
        "sport": meta["sport"],
        "target": meta["target"],
        "season": meta["season"],
        "hasFacts": meta["hasFacts"],
        "predictionTarget": meta["predictionTarget"],
    }
    if meta["hasFacts"]:
        payload["metric"] = meta["metric"]
        payload["factKinds"] = meta["factKinds"]
        payload["factsGrain"] = meta.get("factsGrain") or "day"
    return payload


def update_leagues_catalog() -> None:
    leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
    migrated = {
        path.name
        for path in CONTESTS_DIR.iterdir()
        if path.is_dir() and (path / "contest.json").exists()
    }
    for entry in leagues:
        contest_id = entry.get("id")
        if contest_id not in migrated:
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
    legacy_file = meta.get("legacyPredictionFile")
    if legacy_file:
        pred = DATA_DIR / legacy_file
        if pred.exists():
            pred.unlink()


def migrate_one(contest_id: str, *, purge_legacy: bool) -> None:
    meta = CONTESTS[contest_id]
    pred_path = DATA_DIR / meta["legacyPredictionFile"] if meta.get("legacyPredictionFile") else None
    fact_names, pred_names = collect_names(contest_id, pred_path)

    path = CONTESTS_DIR / contest_id
    if path.exists():
        shutil.rmtree(path)

    write_json(path / "contest.json", contest_json_payload(meta))

    seed_participants(contest_id, fact_names, pred_names)
    facts_count = migrate_facts(contest_id) if meta["hasFacts"] else 0
    preds_ok = migrate_predictions(contest_id, meta)
    if meta["hasFacts"]:
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


def default_contest_ids(*, include_migrated: bool) -> list[str]:
    ids = sorted(CONTESTS.keys())
    if include_migrated:
        return ids
    return [cid for cid in ids if cid not in ALREADY_MIGRATED]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contest",
        action="append",
        dest="contests",
        choices=sorted(CONTESTS.keys()),
        help="Contest id to migrate (repeatable). Default: all not yet migrated.",
    )
    parser.add_argument(
        "--include-migrated",
        action="store_true",
        help="Include rpl-26-27 and mlb-world-series-26 in the default set.",
    )
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Do not delete data/history/{id} or data/{id}.json after migration.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contest_ids = args.contests or default_contest_ids(include_migrated=args.include_migrated)
    purge = not args.keep_legacy

    for contest_id in contest_ids:
        migrate_one(contest_id, purge_legacy=purge)

    update_leagues_catalog()
    write_contests_index()
    if purge:
        rebuild_legacy_history_index()

    print(f"contests index -> {CONTESTS_DIR / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
