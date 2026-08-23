#!/usr/bin/env python3
"""Shared helpers for the audit/sync/analyze/embed/report pipeline.

Holds the pieces every pipeline script needs: Mongo connection, GitHub token
resolution, and git commit/push with pull-before-push safety. Import from here
rather than re-defining these per script.
"""
import os
import re
import subprocess
import pymongo

REPO_PATH = os.environ.get("REPO_PATH", "/opt/data/repo-analysis")


def get_mongo_client():
    """Connect to Mongo using MONGO_AI_URI. No fallback — this repo is public."""
    uri = os.environ.get("MONGO_AI_URI")
    if not uri:
        raise RuntimeError("MONGO_AI_URI not set")
    return pymongo.MongoClient(
        uri,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )


def get_github_token():
    # 1. Environment variables (GitHub Actions, CI, etc.)
    for env_var in ["GITHUB_TOKEN", "GITHUB_PAT", "GH_PAT", "GH_TOKEN"]:
        token = os.environ.get(env_var)
        if token:
            return token

    # 2. ~/.env file
    env_path = os.path.expanduser("~/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("GITHUB_TOKEN="):
                    return line.strip().split("=", 1)[1].strip().strip('"')

    # 3. git credential store
    cred_path = os.path.expanduser("~/.git-credentials")
    if os.path.exists(cred_path):
        with open(cred_path) as f:
            for line in f:
                m = re.search(r'(github_pat_[^:@]+)@', line)
                if m:
                    return m.group(1)

    # 4. gh CLI
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception:
        pass

    raise RuntimeError("No GitHub token found. Set GITHUB_TOKEN or GH_PAT env var.")


def safe_git_pull(repo_path: str = None) -> bool:
    """Rebase local commits onto origin/main. Returns True if the tree is in sync.

    Never falls back to `git merge` — if the rebase fails the working copy is
    left alone and we report failure. A blind merge here is what produced the
    unrelated-history divergence this repo had to be untangled from.
    """
    repo_path = repo_path or REPO_PATH
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"[GIT] Fetch failed: {e}")
        return False

    result = subprocess.run(["git", "rebase", "origin/main"], cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[GIT] Rebase failed, aborting cleanly: {result.stderr.strip()}")
        subprocess.run(["git", "rebase", "--abort"], cwd=repo_path, capture_output=True)
        return False

    print("[GIT] Pulled latest changes")
    return True


def safe_git_commit_push(repo_path: str, file_path: str, message: str) -> bool:
    """Commit a file, rebase onto origin/main, then push. Returns True if pushed.

    Order matters: commit *before* pulling. `git rebase` refuses to run with a
    dirty worktree, and reports/<date>-*.md is a modified tracked file on every
    run after the day's first — pulling first would fail on those runs and drop
    the report. Committing first also means a failed rebase leaves the report as
    a local commit for the next run to retry, instead of losing it.
    """
    try:
        subprocess.run(["git", "add", file_path], cwd=repo_path, check=True, capture_output=True)
        result = subprocess.run(["git", "commit", "-m", message], cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout:
                print("[GIT] Nothing to commit")
                return True
            print(f"[GIT] Commit failed: {result.stdout.strip()}")
            return False

        if not safe_git_pull(repo_path):
            print("[GIT] Could not rebase onto origin — commit kept locally, not pushing")
            return False

        subprocess.run(["git", "push"], cwd=repo_path, check=True, capture_output=True)
        print(f"[GIT] Committed and pushed: {file_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GIT] Push failed: {e}")
        return False


def commit_and_push(report_file, message):
    """Back-compat wrapper around safe_git_commit_push using REPO_PATH."""
    return safe_git_commit_push(REPO_PATH, report_file, message)
