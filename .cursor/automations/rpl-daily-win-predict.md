# Cursor Automation draft — RPL daily win_predict

Create this as a **Cursor Automation** (cloud agent) in the Automations editor. This repo cannot open the editor from a cloud run; paste/apply the settings below.

## Draft

| Field | Value |
| --- | --- |
| Name | RPL daily win_predict |
| Description | Each evening after matches, refresh RPL championship win probabilities from free ESPN standings/results and commit `data/rpl-26-27.json`. |
| Trigger | Schedule — every day at 20:00 UTC / 23:00 MSK (`0 20 * * *`) |
| Model | Composer 2.5 |
| Repo / branch | `onlyzoran/win-predict-ai-data` / `main` |
| Tools | Cloud agent repo access (read/write + commit). No MCP required. |
| Instructions | Follow `@prompts/rpl-win-predict.md` exactly. |
| To finish in editor | Confirm model = Composer 2.5; confirm cron timezone display matches daily 20:00 UTC; enable the automation. |

## Prompt to paste

```text
You are the daily RPL win_predict cloud agent for this repository.

Follow the playbook in @prompts/rpl-win-predict.md.

Steps:
1. Read data/history/rpl-26-27/latest.json (and recent history files if useful).
2. Optionally run: python3 scripts/fetch_rpl_results.py --from 20260724 --completed-only
3. Estimate championship title probabilities for every RPL club.
4. Overwrite data/rpl-26-27.json using the canonical team names and schema from the playbook.
5. Ensure win_predict values use 2 decimals and sum to 100.00.
6. Commit only that file with message: data: refresh rpl-26-27 win_predict

Do not modify other leagues.
```

## Cron

```
0 20 * * *
```

Every day, 20:00 UTC (23:00 MSK), after typical evening matchdays. Same window as the standings GitHub Action; if `latest.json` is still stale, use ESPN scoreboard/standings directly.
