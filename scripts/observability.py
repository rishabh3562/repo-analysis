#!/usr/bin/env python3
"""
Observability utilities for cron jobs: structured logging, metrics, timing.
Also provides safe git operations with pull-before-push.
"""
import os
import sys
import time
import json
import functools
import subprocess
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Dict, Any, Optional

# Global metrics store
_metrics = {}
_current_job = None

def init_job(job_name: str) -> str:
    """Initialize a job run, return run_id."""
    global _current_job
    import pymongo
    MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:***@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
    mongo = pymongo.MongoClient(
        MONGO_URI,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )
    db = mongo["ai_agents"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": job_name,
        "status": "running",
        "started_at": datetime.now(timezone.utc),
        "metrics": {}
    }).inserted_id
    _current_job = {"run_id": run_id, "job_name": job_name, "mongo": mongo, "start_time": time.time()}
    return str(run_id)

def log_metric(key: str, value: Any):
    """Log a metric for the current job."""
    global _metrics
    _metrics[key] = value
    if _current_job:
        _current_job["mongo"]["ai_agents"]["cron_runs"].update_one(
            {"_id": _current_job["run_id"]},
            {"$set": {f"metrics.{key}": value}}
        )

def log_step(step_name: str, **kwargs):
    """Log a step with timing."""
    elapsed = time.time() - _current_job["start_time"] if _current_job else 0
    metric_key = f"step_{step_name}"
    _metrics[metric_key] = {"elapsed_sec": elapsed, **kwargs}
    if _current_job:
        _current_job["mongo"]["ai_agents"]["cron_runs"].update_one(
            {"_id": _current_job["run_id"]},
            {"$set": {f"metrics.{metric_key}": {"elapsed_sec": elapsed, **kwargs}}}
        )
    print(f"[STEP] {step_name} | elapsed={elapsed:.2f}s | {kwargs}")

@contextmanager
def timed_step(step_name: str):
    """Context manager for timing a step."""
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        log_step(step_name, duration_sec=elapsed)

def safe_git_pull(repo_path: str) -> bool:
    """Pull latest changes with rebase. Returns True if successful."""
    try:
        # Fetch first
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True)
        # Rebase local commits on top of origin
        result = subprocess.run(["git", "rebase", "origin/main"], cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            # If rebase fails, try merge as fallback
            print(f"[GIT] Rebase failed, trying merge: {result.stderr}")
            subprocess.run(["git", "merge", "origin/main", "--no-edit"], cwd=repo_path, check=True, capture_output=True)
        print("[GIT] Pulled latest changes")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GIT] Pull failed: {e}")
        return False

def safe_git_commit_push(repo_path: str, file_path: str, message: str) -> bool:
    """Commit and push a file with pull-first safety. Returns True if successful."""
    try:
        # Pull latest first
        if not safe_git_pull(repo_path):
            print("[GIT] Could not pull latest, attempting push anyway...")
        
        # Add and commit
        subprocess.run(["git", "add", file_path], cwd=repo_path, check=True, capture_output=True)
        result = subprocess.run(["git", "commit", "-m", message], cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout:
                print(f"[GIT] Nothing to commit")
                return True
            print(f"[GIT] Commit failed: {result.stdout}")
            return False
        
        # Push
        subprocess.run(["git", "push"], cwd=repo_path, check=True, capture_output=True)
        print(f"[GIT] Committed and pushed: {file_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GIT] Push failed: {e}")
        return False

def complete_job(status: str = "completed", **final_metrics):
    """Mark job as complete with final metrics."""
    global _current_job
    if not _current_job:
        return
    
    elapsed = time.time() - _current_job["start_time"]
    final = {
        "total_duration_sec": elapsed,
        "status": status,
        "completed_at": datetime.now(timezone.utc),
        **final_metrics,
        **_metrics,
    }
    
    _current_job["mongo"]["ai_agents"]["cron_runs"].update_one(
        {"_id": _current_job["run_id"]},
        {"$set": final}
    )
    print(f"[JOB COMPLETE] {_current_job['job_name']} | status={status} | duration={elapsed:.2f}s")
    _current_job = None
    _metrics.clear()

def fail_job(error: Exception, **extra):
    """Mark job as failed with error details."""
    global _current_job
    if not _current_job:
        return
    
    elapsed = time.time() - _current_job["start_time"]
    _current_job["mongo"]["ai_agents"]["cron_runs"].update_one(
        {"_id": _current_job["run_id"]},
        {"$set": {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc),
            "total_duration_sec": elapsed,
            "error": str(error),
            "error_type": type(error).__name__,
            **extra,
            **_metrics,
        }}
    )
    print(f"[JOB FAILED] {_current_job['job_name']} | error={error} | duration={elapsed:.2f}s")
    _current_job = None
    _metrics.clear()

def get_run_id() -> Optional[str]:
    """Get current run_id."""
    return _current_job["run_id"] if _current_job else None