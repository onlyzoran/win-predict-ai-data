"""Shared helpers for the contests/ facts + predictions layout."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTESTS_DIR = ROOT / "data" / "contests"

PREDICTION_CARD_TOP_N = 5
PREDICTION_CARD_OTHERS_ID = "others"

# Prediction display names that differ from ESPN/MLB fact names.
# Keys are prediction-side names; values are preferred fact-side (canonical) names.
ALIAS_TO_CANONICAL: dict[str, dict[str, str]] = {
    "rpl-26-27": {
        "Zenit": "Zenit St Petersburg",
        "FC Krasnodar": "Krasnodar",
        "Baltica": "FC Baltika Kaliningrad",
        "Dynamo Moscow": "Dinamo Moscow",
        "FC Rostov": "Rostov",
        "FC Orenburg": "Gazovik Orenburg",
        "Akhmat": "Akhmat Grozny",
    },
    "mlb-world-series-26": {},
    "epl-26-27": {
        "Brighton": "Brighton & Hove Albion",
        "Tottenham": "Tottenham Hotspur",
        "Bournemouth": "AFC Bournemouth",
    },
    "la-liga-26-27": {
        "Betis": "Real Betis",
        "Athletic Bilbao": "Athletic Club",
        "Deportivo La Coruña": "Deportivo",
    },
    "serie-a-26-27": {
        "Inter Milan": "Internazionale",
        "Roma": "AS Roma",
    },
    "bundesliga-26-27": {
        "1. FC Köln": "FC Cologne",
        "Hamburger SV": "Hamburg SV",
        "Mainz 05": "Mainz",
        "SC Paderborn": "SC Paderborn 07",
        "Union Berlin": "1. FC Union Berlin",
    },
    "ligue-1-26-27": {
        "Monaco": "AS Monaco",
        "Rennes": "Stade Rennais",
        "Auxerre": "AJ Auxerre",
        "Le Havre": "Le Havre AC",
    },
    "mls-cup-26": {
        "Los Angeles FC": "LAFC",
        "Vancouver Whitecaps FC": "Vancouver Whitecaps",
        "New York Red Bulls": "Red Bull New York",
    },
    "nba-26-27": {
        "Los Angeles Clippers": "LA Clippers",
    },
    "f1-drivers-26": {
        "Carlos Sainz Jr.": "Carlos Sainz",
    },
    "f1-constructors-26": {
        "Red Bull Racing": "Red Bull",
    },
    "nhl-stanley-cup-26-27": {
        "Montréal Canadiens": "Montreal Canadiens",
        "St Louis Blues": "St. Louis Blues",
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(name: str) -> str:
    text = name.casefold().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "unknown"


def contest_dir(contest_id: str) -> Path:
    return CONTESTS_DIR / contest_id


def load_contest(contest_id: str) -> dict[str, Any]:
    path = contest_dir(contest_id) / "contest.json"
    if not path.exists():
        return {"id": contest_id}
    return read_json(path)


def facts_grain(contest_id: str) -> str:
    """Return 'matchday' (tour + slices) or 'day' (flat date files)."""
    return str(load_contest(contest_id).get("factsGrain") or "day")


def facts_standings_dir(contest_id: str) -> Path:
    return contest_dir(contest_id) / "facts" / "standings"


def predictions_dir(contest_id: str) -> Path:
    return contest_dir(contest_id) / "predictions"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_participants(contest_id: str) -> dict[str, Any]:
    path = contest_dir(contest_id) / "participants.json"
    if not path.exists():
        return {"contestId": contest_id, "participants": []}
    return read_json(path)


def save_participants(contest_id: str, payload: dict[str, Any]) -> None:
    write_json(contest_dir(contest_id) / "participants.json", payload)


def build_name_index(participants_payload: dict[str, Any]) -> dict[str, str]:
    """Map any known display name (casefold) -> participantId."""
    index: dict[str, str] = {}
    for participant in participants_payload.get("participants") or []:
        participant_id = participant["id"]
        names = [participant.get("name"), *(participant.get("aliases") or [])]
        for name in names:
            if name:
                index[str(name).casefold()] = participant_id
    return index


def resolve_or_create_participant(
    contest_id: str,
    display_name: str,
    *,
    prefer_canonical: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (participantId, updated participants payload). Creates participant if missing."""
    payload = load_participants(contest_id)
    index = build_name_index(payload)

    alias_map = ALIAS_TO_CANONICAL.get(contest_id) or {}
    canonical = prefer_canonical or alias_map.get(display_name) or display_name

    for candidate in (display_name, canonical):
        found = index.get(candidate.casefold())
        if found:
            changed = False
            for participant in payload["participants"]:
                if participant["id"] != found:
                    continue
                aliases = list(participant.get("aliases") or [])
                for name in (display_name, canonical):
                    if name and name != participant.get("name") and name not in aliases:
                        aliases.append(name)
                        changed = True
                if changed:
                    participant["aliases"] = aliases
                break
            if changed:
                save_participants(contest_id, payload)
            return found, payload

    participant_id = slugify(canonical)
    existing_ids = {p["id"] for p in payload["participants"]}
    if participant_id in existing_ids:
        suffix = 2
        while f"{participant_id}-{suffix}" in existing_ids:
            suffix += 1
        participant_id = f"{participant_id}-{suffix}"

    aliases = []
    if display_name != canonical:
        aliases.append(display_name)
    payload["participants"].append(
        {
            "id": participant_id,
            "name": canonical,
            "aliases": aliases,
        }
    )
    payload["participants"].sort(key=lambda p: p["name"].casefold())
    save_participants(contest_id, payload)
    return participant_id, payload


def infer_tour_state(rows: list[dict[str, Any]]) -> tuple[int, str]:
    """Infer (tour_number, status) from played counts.

    status:
      - preseason: nobody has played
      - in_progress: teams disagree on played (tour underway)
      - final: all teams have the same played = tour N
    """
    played = [int(r.get("played") or 0) for r in rows]
    if not played:
        return 0, "preseason"
    lo, hi = min(played), max(played)
    if hi == 0:
        return 0, "preseason"
    if lo == hi:
        return hi, "final"
    return hi, "in_progress"


def tour_dirname(tour: int) -> str:
    return f"tour-{tour:02d}"


def standings_fingerprint(rows: list[dict[str, Any]]) -> tuple:
    return tuple(
        (
            r.get("participantId"),
            r.get("played"),
            r.get("wins"),
            r.get("draws"),
            r.get("losses"),
            r.get("goalsFor"),
            r.get("goalsAgainst"),
            r.get("goalDifference"),
            r.get("points"),
            r.get("rank"),
        )
        for r in rows
    )


def list_standings_days(contest_id: str) -> list[str]:
    """All slice dates (YYYY-MM-DD), including under tour-*/ for matchday grain."""
    standings = facts_standings_dir(contest_id)
    if not standings.is_dir():
        return []
    days = {path.stem for path in standings.glob("????-??-??.json")}
    days.update(path.stem for path in standings.glob("tour-*/????-??-??.json"))
    return sorted(days)


def list_tour_dirs(contest_id: str) -> list[Path]:
    standings = facts_standings_dir(contest_id)
    if not standings.is_dir():
        return []
    return sorted(
        path for path in standings.iterdir() if path.is_dir() and path.name.startswith("tour-")
    )


def list_prediction_days(contest_id: str) -> list[str]:
    preds = predictions_dir(contest_id)
    if not preds.is_dir():
        return []
    return sorted(path.stem for path in preds.glob("????-??-??.json"))


def participant_id_to_name(participants_payload: dict[str, Any]) -> dict[str, str]:
    return {
        participant["id"]: participant.get("name") or participant["id"]
        for participant in participants_payload.get("participants") or []
    }


def build_prediction_card_items(
    items: list[dict[str, Any]],
    name_by_id: dict[str, str],
    *,
    top_n: int = PREDICTION_CARD_TOP_N,
) -> list[dict[str, Any]]:
    sorted_items = sorted(items, key=lambda item: float(item.get("probability") or 0), reverse=True)
    top_items = sorted_items[:top_n]
    rest_items = sorted_items[top_n:]

    card_items: list[dict[str, Any]] = [
        {
            "participantId": item["participantId"],
            "name": name_by_id.get(item["participantId"], item["participantId"]),
            "probability": float(item["probability"]),
        }
        for item in top_items
    ]

    if rest_items:
        card_items.append(
            {
                "participantId": PREDICTION_CARD_OTHERS_ID,
                "name": "Others",
                "probability": round(sum(float(item["probability"]) for item in rest_items), 4),
                "othersCount": len(rest_items),
            }
        )

    return card_items


def build_prediction_card_payload(
    contest_id: str,
    snapshot: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    name_by_id = participant_id_to_name(load_participants(contest_id))
    return {
        "kind": "predictionCard",
        "contestId": contest_id,
        "date": snapshot["date"],
        "generatedAt": snapshot["generatedAt"],
        "basedOnFactsDate": snapshot.get("basedOnFactsDate"),
        "basedOnTour": snapshot.get("basedOnTour"),
        "target": snapshot.get("target", "champion"),
        "unit": snapshot.get("unit", "percent"),
        "topN": PREDICTION_CARD_TOP_N,
        "items": build_prediction_card_items(items, name_by_id),
    }


def write_prediction_card(
    contest_id: str,
    snapshot: dict[str, Any],
    items: list[dict[str, Any]],
) -> Path:
    payload = build_prediction_card_payload(contest_id, snapshot, items)
    out_path = predictions_dir(contest_id) / "card.json"
    write_json(out_path, payload)
    return out_path


def write_facts_index(contest_id: str) -> dict[str, Any]:
    grain = facts_grain(contest_id)
    facts_root = contest_dir(contest_id) / "facts"

    if grain == "matchday":
        tours_meta: list[dict[str, Any]] = []
        for tour_path in list_tour_dirs(contest_id):
            try:
                tour_num = int(tour_path.name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            slices = sorted(path.stem for path in tour_path.glob("????-??-??.json"))
            latest_path = tour_path / "latest.json"
            latest_date = None
            status = "in_progress"
            if latest_path.exists():
                latest_payload = read_json(latest_path)
                latest_date = latest_payload.get("date")
                status = latest_payload.get("tourStatus") or status
            tours_meta.append(
                {
                    "tour": tour_num,
                    "status": status,
                    "slices": slices,
                    "latestDate": latest_date,
                    "latestFile": f"standings/{tour_path.name}/latest.json" if latest_date else None,
                }
            )
        days = list_standings_days(contest_id)
        latest_tour = tours_meta[-1]["tour"] if tours_meta else None
        payload = {
            "contestId": contest_id,
            "kind": "facts",
            "factKind": "standings",
            "grain": "matchday",
            "count": len(days),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "latestTour": latest_tour,
            "tours": tours_meta,
            "days": days,
        }
    else:
        days = list_standings_days(contest_id)
        payload = {
            "contestId": contest_id,
            "kind": "facts",
            "factKind": "standings",
            "grain": "day",
            "count": len(days),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "days": days,
        }

    write_json(facts_root / "index.json", payload)
    return payload


def write_predictions_index(contest_id: str) -> dict[str, Any]:
    days = list_prediction_days(contest_id)
    payload = {
        "contestId": contest_id,
        "kind": "predictions",
        "count": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "days": days,
    }
    write_json(predictions_dir(contest_id) / "index.json", payload)
    return payload


def write_contests_index() -> dict[str, Any]:
    contests: dict[str, Any] = {}
    if CONTESTS_DIR.is_dir():
        for path in sorted(CONTESTS_DIR.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            contest_id = path.name
            contest_file = path / "contest.json"
            if not contest_file.exists():
                continue
            contest = read_json(contest_file)
            facts_meta = None
            facts_index = path / "facts" / "index.json"
            if facts_index.exists():
                facts_meta = read_json(facts_index)
            preds_meta = None
            preds_index = path / "predictions" / "index.json"
            if preds_index.exists():
                preds_meta = read_json(preds_index)
            contests[contest_id] = {
                "title": contest.get("title"),
                "category": contest.get("category"),
                "sport": contest.get("sport"),
                "hasFacts": bool(contest.get("hasFacts")),
                "factsGrain": contest.get("factsGrain") or "day",
                "facts": {
                    "count": (facts_meta or {}).get("count", 0),
                    "first": (facts_meta or {}).get("first"),
                    "last": (facts_meta or {}).get("last"),
                    "latestTour": (facts_meta or {}).get("latestTour"),
                    "latestFile": f"{contest_id}/facts/latest.json",
                    "indexFile": f"{contest_id}/facts/index.json",
                }
                if contest.get("hasFacts")
                else None,
                "predictions": {
                    "count": (preds_meta or {}).get("count", 0),
                    "first": (preds_meta or {}).get("first"),
                    "last": (preds_meta or {}).get("last"),
                    "latestFile": f"{contest_id}/predictions/latest.json",
                    "cardFile": f"{contest_id}/predictions/card.json",
                    "indexFile": f"{contest_id}/predictions/index.json",
                },
            }

    payload = {
        "updatedAt": utc_now_iso(),
        "contests": contests,
    }
    CONTESTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(CONTESTS_DIR / "index.json", payload)
    return payload


def row_to_fact_row(row: dict[str, Any], participant_id: str) -> dict[str, Any]:
    """Convert legacy standings row (team=...) to facts row (participantId=...)."""
    out: dict[str, Any] = {"participantId": participant_id}
    for key, value in row.items():
        if key == "team" or value is None:
            continue
        out[key] = value
    return out


def prune_fact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop redundant fields: sourceRank always; group when the table is a single group."""
    groups = {row.get("group") for row in rows if row.get("group")}
    drop_group = len(groups) <= 1
    pruned: list[dict[str, Any]] = []
    for row in rows:
        item = {k: v for k, v in row.items() if k != "sourceRank"}
        if drop_group:
            item.pop("group", None)
        pruned.append(item)
    return pruned


def write_standings_fact(
    contest_id: str,
    *,
    snapshot_date: str,
    fetched_at: str,
    provider: str,
    metric: str,
    season_year: int | None,
    rows: list[dict[str, Any]],
    update_latest: bool = True,
    refresh_index: bool = True,
    skip_unchanged: bool = True,
) -> Path | None:
    """Write a facts/standings snapshot. `rows` must already use participantId.

    For factsGrain=matchday writes:
      standings/tour-NN/YYYY-MM-DD.json
      standings/tour-NN/latest.json  (newest state of this tour)
    """
    rows = prune_fact_rows(rows)
    grain = facts_grain(contest_id)
    tour: int | None = None
    status: str | None = None

    if grain == "matchday":
        tour, status = infer_tour_state(rows)
        if status == "preseason":
            # Keep a flat preseason bucket until tour 1 starts.
            out_dir = facts_standings_dir(contest_id) / "tour-00"
        else:
            out_dir = facts_standings_dir(contest_id) / tour_dirname(tour)
        out_path = out_dir / f"{snapshot_date}.json"
    else:
        out_path = facts_standings_dir(contest_id) / f"{snapshot_date}.json"

    payload: dict[str, Any] = {
        "kind": "standings",
        "contestId": contest_id,
        "date": snapshot_date,
        "fetchedAt": fetched_at,
        "provider": provider,
        "metric": metric,
        "seasonYear": season_year,
        "rows": rows,
    }
    if grain == "matchday":
        payload["tour"] = tour
        payload["tourStatus"] = status

    if skip_unchanged and out_path.exists():
        existing = read_json(out_path)
        if standings_fingerprint(existing.get("rows") or []) == standings_fingerprint(rows):
            if grain == "matchday":
                write_json(out_path.parent / "latest.json", payload)
            if update_latest:
                write_json(contest_dir(contest_id) / "facts" / "latest.json", payload)
            if refresh_index:
                write_facts_index(contest_id)
                write_contests_index()
            return out_path

    # For matchday grain: skip writing a new idle slice identical to previous in same tour.
    if grain == "matchday" and skip_unchanged and status == "final":
        prev_slices = sorted(out_path.parent.glob("????-??-??.json")) if out_path.parent.exists() else []
        if prev_slices:
            prev = read_json(prev_slices[-1])
            if standings_fingerprint(prev.get("rows") or []) == standings_fingerprint(rows):
                latest_payload = {**payload, "date": prev.get("date") or snapshot_date}
                write_json(out_path.parent / "latest.json", latest_payload)
                if update_latest:
                    write_json(contest_dir(contest_id) / "facts" / "latest.json", latest_payload)
                if refresh_index:
                    write_facts_index(contest_id)
                    write_contests_index()
                return out_path.parent / "latest.json"

    write_json(out_path, payload)

    if grain == "matchday":
        write_json(out_path.parent / "latest.json", payload)

    if update_latest:
        write_json(contest_dir(contest_id) / "facts" / "latest.json", payload)
    if refresh_index:
        write_facts_index(contest_id)
        write_contests_index()
    return out_path


def write_prediction_snapshot(
    contest_id: str,
    *,
    snapshot_date: str,
    generated_at: str,
    model: dict[str, Any],
    based_on_facts_date: str | None,
    items: list[dict[str, Any]],
    target: str = "champion",
    unit: str = "percent",
    based_on_tour: int | None = None,
    update_latest: bool = True,
    refresh_index: bool = True,
) -> Path:
    if based_on_tour is None and based_on_facts_date:
        latest = contest_dir(contest_id) / "facts" / "latest.json"
        if latest.exists():
            latest_payload = read_json(latest)
            if latest_payload.get("date") == based_on_facts_date:
                based_on_tour = latest_payload.get("tour")

    payload = {
        "kind": "prediction",
        "contestId": contest_id,
        "date": snapshot_date,
        "generatedAt": generated_at,
        "model": model,
        "basedOnFactsDate": based_on_facts_date,
        "basedOnTour": based_on_tour,
        "target": target,
        "unit": unit,
        "items": items,
    }
    out_path = predictions_dir(contest_id) / f"{snapshot_date}.json"
    write_json(out_path, payload)
    if update_latest:
        write_json(predictions_dir(contest_id) / "latest.json", payload)
        write_prediction_card(contest_id, payload, items)
    if refresh_index:
        write_predictions_index(contest_id)
        write_contests_index()
    return out_path
