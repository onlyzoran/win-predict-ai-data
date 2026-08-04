# win-predict-ai-data

Prediction odds snapshots and **standings history** for tracked tournaments.

## Data layout

| Path | Purpose |
| --- | --- |
| `data/leagues.json` | League catalog |
| `data/{league}.json` | Win-probability snapshots |
| `data/history/{leagueId}/{YYYY-MM-DD}.json` | Daily standings snapshot |
| `data/history/{leagueId}/latest.json` | Copy of the newest snapshot |
| `data/history/{leagueId}/days.json` | List of available snapshot dates for the league |
| `data/history/index.json` | Catalog of all leagues with first/last/count |
| `scripts/sources.json` | Source mapping per league |

### Standings snapshot schema

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

- Football / NHL / MLS / RPL: `metric` is `points`
- NBA / NFL / MLB: `metric` is `wins` (sorted by win %)
- NCAAF / NCAAB: AP Top 25 via ESPN rankings (`metric`: `rank`)
- Golf majors, US election: not tracked (no league table)
- KHL: no free ESPN feed yet (`unsupported` in `sources.json`)

## Snapshot standings

Uses the public ESPN API (no key). Idempotent: re-running the same day overwrites that date’s file.

```bash
# All configured leagues (today)
python3 scripts/snapshot_standings.py

# One league
python3 scripts/snapshot_standings.py --league epl-26-27

# MLB: backfill current season by date (official statsapi.mlb.com)
python3 scripts/snapshot_standings.py --league mlb-world-series-26 --from 2026-03-25

# Validate without writing
python3 scripts/snapshot_standings.py --dry-run

# Rebuild day indexes from existing files
python3 scripts/snapshot_standings.py --rebuild-index
```

Consumers should read `data/history/index.json` (summary) or `data/history/{leagueId}/days.json` (full date list) instead of scanning directories.

MLB uses [MLB Stats API](https://statsapi.mlb.com) which supports standings **as of any date**, so the full season history can be loaded in one pass. Other leagues only snapshot the current day via ESPN.

GitHub Action `.github/workflows/snapshot-standings.yml` runs daily at 06:00 UTC and commits new files under `data/history/`.

If ESPN has not published the expected season yet (UCL 26/27, NCAA polls, KHL), the script skips that league instead of writing the previous season.
