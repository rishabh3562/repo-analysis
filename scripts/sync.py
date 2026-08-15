#!/usr/bin/env python3
"""
Incremental GitHub sync. Fetches new commits, issues, PRs since last run.
"""
import os
import re
import sys
import subprocess
import requests
import pymongo
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
API = "https://api.github.com"

def get_github_token():
    env_path = os.path.expanduser("~/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("GITHUB_TOKEN="):
                    return line.strip().split("=", 1)[1].strip().strip('"')
    cred_path = os.path.expanduser("~/.git-credentials")
    if os.path.exists(cred_path):
        with open(cred_path) as f:
            for line in f:
                m = re.search(r'(github_pat_[^:@]+)@', line)
                if m:
                    return m.group(1)
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except:
        pass
    raise RuntimeError("No GitHub token found")

def get_mongo_client():
    return pymongo.MongoClient(
        MONGO_URI,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )

def get_last_sync(mongo, repo_full_name):
    db = mongo["ai_agents"]
    sync = db["sync_state"]
    doc = sync.find_one({"repo": repo_full_name})
    return doc.get("last_sync") if doc else None

def update_last_sync(mongo, repo_full_name):
    db = mongo["ai_agents"]
    sync = db["sync_state"]
    sync.update_one(
        {"repo": repo_full_name},
        {"$set": {"last_sync": datetime.utcnow()}},
        upsert=True
    )

def fetch_repo_events(token, repo_full_name, since):
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    params = {"per_page": 100}
    if since:
        params["since"] = since.isoformat() + "Z"
    
    events = []
    page = 1
    while True:
        r = requests.get(f"{API}/repos/{repo_full_name}/events", headers=headers, params={**params, "page": page}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        events.extend(batch)
        page += 1
    return events

def main():
    token = get_github_token()
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    dumps = db["dumps"]
    repos_coll = db["repos"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": "github-sync",
        "status": "running",
        "started_at": datetime.utcnow(),
    }).inserted_id
    
    try:
        # Get tracked repos from cache
        tracked = list(repos_coll.find({"private": False}, {"full_name": 1}))
        print(f"Syncing {len(tracked)} public repos...")
        
        total_events = 0
        for repo in tracked:
            full_name = repo["full_name"]
            last_sync = get_last_sync(mongo, full_name)
            events = fetch_repo_events(token, full_name, last_sync)
            
            if events:
                dump_doc = {
                    "source": "github-sync",
                    "repo": full_name,
                    "payload": {"events": events, "count": len(events)},
                    "tags": ["sync", "events", "github"],
                    "created_at": datetime.utcnow(),
                }
                dumps.insert_one(dump_doc)
                total_events += len(events)
                print(f"  {full_name}: {len(events)} new events")
            
            update_last_sync(mongo, full_name)
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "events_synced": total_events}}
        )
        print(f"Sync complete. {total_events} new events.")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()