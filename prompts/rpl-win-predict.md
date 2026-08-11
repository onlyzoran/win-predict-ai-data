# RPL daily win_predict (cloud agent playbook)

Scheduled cloud agent task for Russian Premier League championship probabilities.

## Goal

Update `data/rpl-26-27.json` with fresh `win_predict` values (probability each team wins the 2026/27 RPL title). Commit to the default branch (or open a PR if that is safer for the repo settings).

## Inputs (free)

1. **Standings history (preferred):** `data/history/rpl-26-27/latest.json` and recent daily files under `data/history/rpl-26-27/`.
2. **Match results (optional cross-check):** ESPN public scoreboard, no API key:

```bash
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only
# or JSON:
python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only --json
```

Standings are refreshed daily by GitHub Action `.github/workflows/snapshot-standings.yml` (ESPN `soccer/rus.1`).

## Output schema

Overwrite `data/rpl-26-27.json` as a JSON array only:

```json
[
  { "team": "Zenit", "win_predict": 38.40 },
  { "team": "Spartak Moscow", "win_predict": 16.50 }
]
```

Rules:

- Include **every** team currently in the file / ESPN RPL table (16 clubs).
- `win_predict` is a percentage with **2 decimal places**.
- Values must sum to **100.00** (±0.01). If drift remains after rounding, adjust the top team by 0.01.
- Sort by `win_predict` descending, then team name ascending.
- Do not edit other league JSON files unless explicitly asked.

## Canonical team names

Map ESPN display names to these canonical `team` strings used by the app:

| ESPN / standings name | Canonical `team` |
| --- | --- |
| Zenit St Petersburg | Zenit |
| Spartak Moscow | Spartak Moscow |
| Krasnodar | FC Krasnodar |
| CSKA Moscow | CSKA Moscow |
| Dinamo Moscow | Dynamo Moscow |
| Lokomotiv Moscow | Lokomotiv Moscow |
| Akhmat Grozny | Akhmat |
| Rubin Kazan | Rubin Kazan |
| FC Baltika Kaliningrad | Baltica |
| Rostov | FC Rostov |
| Akron Tolyatti | Akron Tolyatti |
| Dynamo Makhachkala | Dynamo Makhachkala |
| Gazovik Orenburg | FC Orenburg |
| Krylia Sovetov | Krylia Sovetov |
| Fakel Voronezh | Fakel Voronezh |
| Rodina Moscow | Rodina Moscow |

If ESPN adds/renames a club, keep the existing canonical name when it is clearly the same club; otherwise add the new club and remove relegated ones so the list matches the current season table.

## How to estimate probabilities

You are the model (no separate Monte Carlo script and no paid odds API required).

1. Read current points, played, W/D/L from `latest.json`.
2. Weigh **squad/club strength priors** (historic title contenders: Zenit, Spartak, Krasnodar, CSKA, Dynamo Moscow, Lokomotiv) against **current table and recent results**.
3. Early season: do not overreact to 1–3 match samples for small clubs; keep mass on traditional contenders unless the gap is sustained.
4. Late season: table position and remaining schedule dominate; long shots near zero are fine.
5. Every listed team gets a non-negative probability; extremely long shots may be `0.01`–`0.10`, not omitted.

## Commit

- Message example: `data: refresh rpl-26-27 win_predict`
- Only touch `data/rpl-26-27.json` unless fixing a bug discovered in the playbook/helper.
- After writing, verify the JSON parses and the percentages sum to ~100.

## Schedule

Cursor Automation cron: **daily 08:00 UTC** (`0 8 * * *`), after the 06:00 UTC standings snapshot.
