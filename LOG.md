# Activity Log

Observability log for this repo. Entries are appended by the Claude Code loop
session (runs ~every 30 min, pulling and refining whatever Hermes pushed since
the last cycle) and, where noted, by manual sessions. Newest entries on top.

**Last checked:** 2026-08-23 17:12 UTC — see entry below. This line updates in
place each cycle that finds nothing new from Hermes; a full dated entry is only
added when a cycle actually changes something, to keep this file from bloating
over a multi-day loop.

**Credential rotation — user decision (2026-08-23):** rotation is deferred
intentionally, not overlooked. Do not re-raise this as an open question each
cycle; only act if the user brings it up again or asks for a history rewrite.

---

## 2026-08-23 16:58 UTC — Resumed loop session; confirmed leak still live, found silent report-push failures (Claude, loop resumed after a gap)

The `/loop` session hit a usage cap and was dark for about a week; this is the
first cycle back. The scheduled cron job (`e42d5ddf`, session-only, 7-day
expiry) is confirmed dead (`CronList` → no scheduled jobs) — **the loop is not
currently running on its own; it needs to be recreated if still wanted.**

**Independently re-verified the 2026-08-23 reconciliation entry below is
correct:** `git grep Hermes54 $(git rev-list origin/main)` still finds the
plaintext Mongo password in 7 commits reachable from `origin/main`
(`af56b3c` … `9d82f9f`). The original 2026-08-15 `filter-repo` + force-push
never stuck — confirmed by direct query against `origin/main` right now, not
assumed from the prior entry. **This is still a live, public leak.**

**Deliberately did not re-run `filter-repo` this cycle.** A second purge is
worthless if whatever pushed the old lineage back last time (most likely
Hermes's persistent clone at `REPO_PATH=/opt/data/repo-analysis`, which the
Aug 15 rewrite never touched) can still do the same thing again. Need from the
user before attempting another rewrite: (1) confirmation the Atlas password has
been rotated, and (2) confirmation Hermes's persistent clone can be paused or
re-cloned around the rewrite. Asked in chat, not assumed.

**Found and fixed (non-destructive, pushed):** GitHub Actions (`audit.yml`,
`sync.yml`) have been running successfully since the Aug 23 fixes (`gh run
list` shows 5 green runs Aug 22–23), but **no report has actually landed in
`reports/` since 2026-08-15** despite that. Pulled the raw job log for the
2026-08-23 12:11 sync run (`gh api .../actions/jobs/<id>/logs`, redirected to
D: — see disk-space note below) and found:

```
[GIT] Pulled latest changes
[GIT] Commit failed: 
```

`safe_git_commit_push` only ever printed `result.stdout` on failure, never
`result.stderr` — so the actual git error was invisible in every prior run's
logs. Fixed in `common.py` to print combined stdout+stderr (and to check the
`git push` exit code, which was previously unchecked and could fail silently
too). Also: all 5 pipeline scripts called `safe_git_commit_push()` without
checking its return value, so `complete_job(status="completed", ...)` fired
regardless of whether the push actually succeeded — `cron_runs` in Mongo has
been recording false-positive "completed" statuses. Fixed all 5 to record
`status="completed_push_failed"` and `report_pushed=<bool>` when the push
fails, without failing the whole job (the audit/sync/analyze data itself is
still good even if publishing the report isn't). Not yet confirmed this
actually fixes the underlying push failure — no workflow has run since this
fix landed; next scheduled sync run will be the first real test.

**Blocking issue, not mine to fix:** the machine's `C:` drive is at 0 bytes
free. This broke `gh run view --log` (`There is not enough space on the disk`)
and even basic `tail`/redirects to `/tmp`. Worked around it by redirecting
diagnostic output to `D:` (which has ~49G free) for this session, but this
will keep breaking tooling — including, likely, this repo's own git operations
if `C:` is where the working clone or its temp files live — until the user
clears space.

**Symptom:** `main` had diverged 17 local / 11 remote and neither push nor pull
would go through. Root cause: `git merge-base HEAD origin/main` returned nothing
— the two branches shared **no common ancestor at all**. The 2026-08-15
`git filter-repo` rewrite (see entry below) replaced the local history wholesale
but never reached `origin`, so local was a parallel rewritten lineage of the same
commits. Confirmed by identical trees at the two `Initial commit`s (`84b99a0` /
`da741c1`) and by `af56b3c`↔`cf22b5d` differing only in the 5 credential lines.

**Fixed — local history reset onto `origin/main`, Hermes's work preserved:**
- Backed the old lineage up as branch `backup/pre-reconcile` (nothing discarded).
- `git reset --hard origin/main`, then cherry-picked the one commit with unique
  content (`036d5f1` — `.gitignore`, `.env.example`, `CLAUDE.md`, `LOG.md`).
  Dropped the 11 no-op "log cycle check" commits and the 6 rewritten duplicates
  of commits already present in `origin`'s lineage.
- Hand-ported the `common.py` refactor onto Hermes's post-observability scripts
  (the old `780b5b1` patch no longer applied). Kept everything from Hermes:
  observability instrumentation, the GH-token resolution fix, pull-before-push.
- Re-removed the hardcoded Mongo URI fallback — this time from **six** files;
  `scripts/observability.py` had grown its own copy that the 2026-08-15 pass
  predated. Verified with `git grep cluster0.rzg43g9` (no hits outside this log)
  and by importing all seven modules.
- Moved the git helpers into `common.py` and made `safe_git_pull()` **abort** a
  failed rebase instead of falling back to `git merge origin/main`. That merge
  fallback was the mechanism that would have papered over the divergence.
- Reordered `safe_git_commit_push()` to `add → commit → rebase → push`. It used
  to pull first, but `git rebase` refuses to run with a dirty worktree, and
  `reports/<date>-*.md` is a modified tracked file on every run after the day's
  first — so with the strict rebase, 3 of `sync.yml`'s 4 daily runs would have
  silently dropped their report. Committing first also means a failed rebase
  parks the report as a local commit for the next run to retry.

**Fixed — root cause of the drift, in `.github/workflows/{audit,sync}.yml`:**
- `fetch-depth: 0` on checkout. The default shallow clone cannot rebase onto
  `origin/main`, so every scheduled run's pull-before-push was silently failing.
- `token: ${{ secrets.GH_PAT }}` on checkout, so pushes use the PAT.
- Added a git identity step — `git commit` on a bare runner fails without one.

**Verified:** `git merge-base HEAD origin/main` now resolves; `main` fast-forwards
onto `origin/main`; all scripts byte-compile and import.

**Still outstanding — user action:** the leaked Atlas password remains in public
git history on GitHub (reachable from `origin/main`). Rotation is confirmed
necessary, not precautionary. Purging it now requires a fresh `filter-repo` +
force-push, which is destructive and was not done without explicit sign-off.

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
  **CORRECTION (2026-08-23): the force-push never landed on `origin`.** The
  rewrite only ever existed in the local clone; the plaintext password is still
  reachable from `origin/main` on public GitHub via commit `af56b3c` and its
  descendants. See the 2026-08-23 entry.

**User action required (outside this session):** rotate the `Hermes` Mongo
Atlas user's password — the leaked value should be treated as compromised
regardless of the history rewrite, since it was public before the rewrite.

**Also noted, not yet acted on:** `reports/2026-08-15-audit.md` lists private
repo names (e.g. `GeoScout`, `c--bank-admin`, `linear-clone`) in a public repo.
This is a byproduct of the audit's purpose (surfacing repos needing cleanup),
not a bug, but worth a conscious call on whether private repo names should be
redacted/hashed in published reports. Flagged to user, no change made yet.
