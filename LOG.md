# Activity Log

Observability log for this repo. Entries are appended by the Claude Code loop
session (runs ~every 30 min, pulling and refining whatever Hermes pushed since
the last cycle) and, where noted, by manual sessions. Newest entries on top.

---

## 2026-08-15 20:57 UTC — Initial refinement pass (Claude, session start)

**Pulled:** repo was already up to date (Hermes's initial commits: pipeline
scaffolding, `2026-08-15-audit.md`, model default change).

**Found — critical:** every script (`sync.py`, `report.py`, `analyze.py`,
`embed.py`, `audit.py`) hardcoded a live MongoDB Atlas credential
(`mongodb+srv://Hermes:***@cluster0.rzg43g9.mongodb.net/`) as the `MONGO_AI_URI`
fallback default, present since the first commit (`af56b3c`). Repo is public —
credential was live and exposed. User confirmed: rotate the Atlas password, fix
the code, and rewrite git history to purge the string from all past commits.

**Fixed:**
- Extracted `scripts/common.py` (`get_mongo_client`, `get_github_token`,
  `commit_and_push`) — was duplicated near-verbatim across all 5 scripts.
- Removed the hardcoded Mongo URI fallback everywhere; `get_mongo_client()` now
  raises `RuntimeError` if `MONGO_AI_URI` is unset. No default secret, ever.
- Added `.env.example` documenting required env vars.
- Added `.gitignore` (secrets/`.env`, Python artifacts, OS/editor cruft,
  `.qodo/`) — repo had none before this.
- Added `CLAUDE.md` describing repo purpose, layout, Mongo schema, and
  conventions (no co-author trailers, routine commits auto-push, destructive
  ops need confirmation).
- Ran `git filter-repo` to strip the leaked credential string from every commit
  in history, then force-pushed the rewritten history to `origin/main`.

**User action required (outside this session):** rotate the `Hermes` Mongo
Atlas user's password — the leaked value should be treated as compromised
regardless of the history rewrite, since it was public before the rewrite.

**Also noted, not yet acted on:** `reports/2026-08-15-audit.md` lists private
repo names (e.g. `GeoScout`, `c--bank-admin`, `linear-clone`) in a public repo.
This is a byproduct of the audit's purpose (surfacing repos needing cleanup),
not a bug, but worth a conscious call on whether private repo names should be
redacted/hashed in published reports. Flagged to user, no change made yet.
