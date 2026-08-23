# repo-analysis

Automated pipeline that audits and analyzes `rishabh3562`'s GitHub account, stores
results in MongoDB, and publishes markdown reports back into this repo. **This repo
is public** — treat everything committed here as world-readable.

## How it runs

An external agent ("Hermes") runs the scripts below on a schedule (GitHub Actions,
see `.github/workflows/`) and pushes generated reports directly to `main`. A Claude
Code session is looped alongside it (every 30 min) to pull Hermes's latest work,
refine/fix it, and keep the repo's hygiene (docs, `.gitignore`, dedup) up to date.
Because both sides push independently, always `git pull` before making changes.

## Layout

- `scripts/common.py` — shared helpers: `get_mongo_client()`, `get_github_token()`,
  `safe_git_pull()`, `safe_git_commit_push()` (+ `commit_and_push()` wrapper). All
  pipeline scripts import from here — don't re-duplicate these into individual
  scripts. `safe_git_pull()` rebases onto `origin/main` and **aborts** on conflict
  rather than merging; a blind merge fallback is what produced the unrelated-history
  divergence untangled on 2026-08-23.
- `scripts/observability.py` — job lifecycle for the cron scripts: `init_job()`,
  `timed_step()`, `log_metric()`, `complete_job()`, `fail_job()`, writing to the
  `cron_runs` collection. Re-exports the git helpers from `common.py` for
  back-compat; it imports `common`, never the other way round.
- `scripts/audit.py` — full GitHub profile audit (repo stats, tutorial-repo
  detection, missing descriptions). Writes to Mongo `dumps` + `repos` collections,
  commits `reports/<date>-audit.md`. Runs daily (`.github/workflows/audit.yml`).
- `scripts/sync.py` — incremental sync of repo events since last run. Commits
  `reports/<date>-sync.md`. Runs every 6h (`.github/workflows/sync.yml`).
- `scripts/analyze.py` — LLM pass (OpenRouter, Nemotron free tier by default) over
  unanalyzed dumps, writes `analyses` collection, commits `reports/<date>-analysis.md`.
- `scripts/embed.py` — generates embeddings for dumps/chats for semantic search,
  writes `embeddings` collection, commits `reports/<date>-embeddings.md`.
- `scripts/report.py` — rolls up the last 24h of `analyses` into a daily digest,
  commits `reports/<date>-report.md`.
- `reports/` — generated markdown, one file per script per day. Treat as output,
  not something to hand-edit — fix the generator instead.

## MongoDB (`ai_agents` database)

Collections: `dumps` (raw audit/sync payloads), `repos` (repo cache), `analyses`,
`embeddings`, `sync_state`, `cron_runs` (per-run status tracking).

## Required environment

See `.env.example`. `MONGO_AI_URI` has **no hardcoded fallback** — `get_mongo_client()`
raises `RuntimeError` if it's unset. Never hardcode credentials in scripts; this
repo is public and a hardcoded Mongo URI leaked here and is **still reachable in
public git history** (see `LOG.md` — a 2026-08-15 history rewrite never landed on
`origin`). Confirm with the user whether the credential has been rotated before
assuming it's safe.

Workflows must check out with `fetch-depth: 0` and `token: ${{ secrets.GH_PAT }}`,
and configure a git identity, or the scripts' pull-before-push cannot rebase or
push and each run drifts from `main`.

## Conventions

- **Never add a `Co-Authored-By: Claude` (or similar) trailer to commits.**
- Routine refinement commits (docs, `.gitignore`, dedup, log updates) can be pushed
  directly to `main` — no PR flow in this repo.
- Anything destructive (force-push, history rewrite, deleting reports) needs
  explicit user confirmation first, even mid-loop.
- Log notable changes to `LOG.md` each session/cycle for observability.
