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
  `commit_and_push()`. All pipeline scripts import from here — don't re-duplicate
  these into individual scripts.
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

See `.env.example`. `MONGO_AI_URI` has **no hardcoded fallback** — every script
raises `RuntimeError` if it's unset. Never hardcode credentials in scripts; this
repo is public and a hardcoded Mongo URI was already leaked and rotated once
(see `LOG.md`).

## Conventions

- **Never add a `Co-Authored-By: Claude` (or similar) trailer to commits.**
- Routine refinement commits (docs, `.gitignore`, dedup, log updates) can be pushed
  directly to `main` — no PR flow in this repo.
- Anything destructive (force-push, history rewrite, deleting reports) needs
  explicit user confirmation first, even mid-loop.
- Log notable changes to `LOG.md` each session/cycle for observability.
