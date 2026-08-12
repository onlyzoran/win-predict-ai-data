# win-predict-ai-data

Prediction odds snapshots and standings history for tracked tournaments.

## Layouts

Two layouts coexist while contests are migrated:

| Layout | Who | Paths |
| --- | --- | --- |
| **contests** (new) | RPL, MLB | `data/contests/{contestId}/…` |
| **legacy** | everyone else | `data/{league}.json` + `data/history/{leagueId}/` |

`data/leagues.json` is the catalog. Migrated entries use `layout: "contests"` and `contestPath` instead of `file`.

## Contests layout (RPL, MLB)

```text
data/contests/
  index.json
    {contestId}/
    contest.json             # metadata only (incl. factsGrain)
    participants.json        # stable participantId + name aliases
    facts/
      index.json
      latest.json
      standings/
        YYYY-MM-DD.json                    # factsGrain=day (MLB)
        tour-03/YYYY-MM-DD.json            # factsGrain=matchday (RPL) — срезы
        tour-03/latest.json                # последний срез тура
    predictions/
      index.json
      latest.json
      YYYY-MM-DD.json
```

### Terminology

| Term | Meaning |
| --- | --- |
| **contest** | Unit of prediction (RPL season, World Series, …) |
| **category** | `sport`, `politics`, … |
| **target** | What is predicted (`champion`) |
| **participant** | Team / player / candidate |
| **facts** | Observed data from providers |
| **predictions** | Model output (`probability`) |
| **factsGrain** | `day` or `matchday` (tour + slices + final) |

### Rules

- **Facts** never contain probabilities.
- **Predictions** never contain W/D/L/points.
- Join only via `participantId` (aliases live in `participants.json`).
- Predictions set `basedOnFactsDate` (and `basedOnTour` for matchday contests).

### RPL matchday standings

Tour number is inferred from `played`: all equal → tour N **final**; mixed → tour **in_progress**. Idle duplicate days after a final are not re-stored.

```text
facts/standings/tour-03/
  2026-08-09.json   # in_progress slice
  2026-08-10.json
  2026-08-11.json   # day tour completed
  latest.json       # последний срез тура 3 (tourStatus: final)
```

### Example fact row

```json
{
  "kind": "standings",
  "contestId": "rpl-26-27",
  "date": "2026-08-11",
  "tour": 3,
  "tourStatus": "final",
  "provider": "espn",
  "metric": "points",
  "rows": [
    { "participantId": "krasnodar", "rank": 1, "played": 3, "wins": 3, "draws": 0, "losses": 0, "goalsFor": 8, "goalsAgainst": 4, "goalDifference": 4, "points": 9 }
  ]
}
```

### Example prediction

```json
{
  "kind": "prediction",
  "contestId": "rpl-26-27",
  "date": "2026-08-11",
  "basedOnFactsDate": "2026-08-11",
  "basedOnTour": 3,
  "target": "champion",
  "unit": "percent",
  "items": [
    { "participantId": "zenit-st-petersburg", "probability": 39.8 }
  ]
}
```

Write predictions:

```bash
python3 scripts/write_prediction.py --contest rpl-26-27 --input probs.json
```

One-shot migration (already applied for RPL/MLB):

```bash
python3 scripts/migrate_to_contests.py --contest rpl-26-27 --contest mlb-world-series-26
```

## Legacy layout

| Path | Purpose |
| --- | --- |
| `data/leagues.json` | League catalog |
| `data/{league}.json` | Win-probability snapshots |
| `data/history/{leagueId}/{YYYY-MM-DD}.json` | Daily standings snapshot |
| `data/history/{leagueId}/latest.json` | Copy of the newest snapshot |
| `data/history/{leagueId}/days.json` | List of available snapshot dates |
| `data/history/index.json` | Catalog of legacy leagues with first/last/count |
| `scripts/sources.json` | Source mapping per league (`layout: "contests"` for migrated) |

### Legacy standings snapshot schema

```json
{
  "leagueId": "epl-26-27",
  "date": "2026-08-03",
  "fetchedAt": "2026-08-03T18:00:00Z",
  "source": "espn",
  "metric": "points",
  "seasonYear": 2026,
  "standings": [
    {
      "rank": 1,
      "team": "Arsenal",
      "played": 1,
      "wins": 1,
      "draws": 0,
      "losses": 0,
      "points": 3,
      "group": "2026-27 English Premier League"
    }
  ]
}
```

- Football / NHL / MLS / F1: `metric` is `points`
- NBA / NFL: `metric` is `wins` (sorted by win %)
- NCAAF / NCAAB: AP Top 25 via ESPN rankings (`metric`: `rank`)
- F1 Drivers / Constructors: ESPN `racing/f1` (filter via `group` in `sources.json`)
- Golf majors, US election: not tracked (no league table)
- KHL: no free ESPN feed yet (`unsupported` in `sources.json`)

## Snapshot standings

Uses the public ESPN API (no key). Idempotent: re-running the same day overwrites that date’s file. RPL/MLB write into `data/contests/…/facts/`; other leagues still use `data/history/`.

```bash
# All configured leagues (today)
python3 scripts/snapshot_standings.py

# One league / contest
python3 scripts/snapshot_standings.py --league epl-26-27
python3 scripts/snapshot_standings.py --league rpl-26-27

# MLB: backfill current season by date (official statsapi.mlb.com)
python3 scripts/snapshot_standings.py --league mlb-world-series-26 --from 2026-03-25

# Validate without writing
python3 scripts/snapshot_standings.py --dry-run

# Rebuild day indexes from existing files
python3 scripts/snapshot_standings.py --rebuild-index
```

Consumers:

- Contests (RPL/MLB): `data/contests/index.json`
- Legacy leagues: `data/history/index.json` or `data/history/{leagueId}/days.json`

MLB uses [MLB Stats API](https://statsapi.mlb.com) which supports standings **as of any date**, so the full season history can be loaded in one pass. Other leagues only snapshot the current day via ESPN.

GitHub Action `.github/workflows/snapshot-standings.yml` runs every 8 hours (`0 */8 * * *` — 00:00, 08:00, 16:00 UTC) and commits under `data/history/` and `data/contests/`.

If ESPN has not published the expected season yet (UCL 26/27, NCAA polls, KHL), the script skips that league instead of writing the previous season.

## Free RPL results + daily predictions

Russian Premier League uses the **public ESPN API** (no key):

| Need | Endpoint / path |
| --- | --- |
| Standings | `site.web.api.espn.com/apis/v2/sports/soccer/rus.1/standings` → `data/contests/rpl-26-27/facts/` |
| Match results / fixtures | `site.web.api.espn.com/apis/site/v2/sports/soccer/rus.1/scoreboard?dates=YYYYMMDD` |

Helper for recent results:

```bash
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only --json
```

Championship probabilities are refreshed by a **single Cursor cloud agent**
(`win-predict-all-refresh` in `cursor-cloud-agents`) on a daily schedule:

- Standings Action: **every 8 h** (`0 */8 * * *` — 02:00, 10:00, 18:00 GMT+2)
- Predictions agent: **push to main** after standings, or cron fallback **21:00 UTC / 23:00 GMT+2** (`0 21 * * *`)
- Contest list: `data/contests/prediction-refresh.json` (14 facts-backed leagues)
- Instructions live in the Cursor Automation (export in `cursor-cloud-agents`)
- Prefer `scripts/write_prediction.py --contest <id> --input …`

Standings update first; the cloud agent refreshes all contest predictions in one commit.
