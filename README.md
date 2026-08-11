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

- Football / NHL / MLS / RPL / F1: `metric` is `points`
- NBA / NFL / MLB: `metric` is `wins` (sorted by win %)
- NCAAF / NCAAB: AP Top 25 via ESPN rankings (`metric`: `rank`)
- F1 Drivers / Constructors: ESPN `racing/f1` (filter via `group` in `sources.json`)
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

GitHub Action `.github/workflows/snapshot-standings.yml` runs daily at 20:00 UTC (23:00 MSK) and commits new files under `data/history/`.

If ESPN has not published the expected season yet (UCL 26/27, NCAA polls, KHL), the script skips that league instead of writing the previous season.

## Free RPL results + daily win_predict

Russian Premier League uses the **public ESPN API** (no key):

| Need | Endpoint / path |
| --- | --- |
| Standings | `site.api.espn.com/apis/v2/sports/soccer/rus.1/standings` (via `scripts/snapshot_standings.py`, league id `rpl-26-27`) |
| Match results / fixtures | `site.api.espn.com/apis/site/v2/sports/soccer/rus.1/scoreboard?dates=YYYYMMDD` |

Helper for recent results:

```bash
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only --json
```

Championship probabilities in `data/rpl-26-27.json` are refreshed by a **Cursor cloud agent** (Composer 2.5) on a daily schedule:

- Cron: every day **20:00 UTC / 23:00 MSK** (`0 20 * * *`), after typical evening matches
- Instructions live in the Cursor Automation (not in-repo)

Standings history and `win_predict` both update daily at 20:00 UTC (standings via GitHub Action, probabilities via cloud agent).
