#!/usr/bin/env python3
"""
Full GitHub profile audit. Stores results in MongoDB dumps collection.
"""
import os
import re
import sys
import json
import subprocess
import requests
import pymongo
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
GITHUB_USER = "rishabh3562"
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

def fetch_all_repos(token):
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    repos = []
    page = 1
    while True:
        r = requests.get(f"{API}/user/repos", headers=headers, params={
            "per_page": 100, "page": page, "sort": "updated"
        }, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos

def fetch_user(token):
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"{API}/user", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def analyze_repos(repos):
    import fnmatch
    TUTORIAL_PATTERNS = [
        "*tut*", "*practice*", "*-tut", "*-practice",
        "g*-backend-tut", "g*-tut", "react-tut", "js-tut",
        "ts-practice", "python-practice", "js-practice",
        "c--bank-admin", "c-hash-*", "dotent-*", "exercism",
    ]
    
    empty_desc = [r for r in repos if not r.get("description")]
    no_topics = [r for r in repos if not r.get("topics")]
    private = [r for r in repos if r["private"]]
    public = [r for r in repos if not r["private"]]
    
    tutorial_matches = []
    for pattern in TUTORIAL_PATTERNS:
        tutorial_matches.extend([r for r in repos if fnmatch.fnmatch(r["name"].lower(), pattern.lower())])
    
    seen = set()
    tutorials = []
    for r in tutorial_matches:
        if r["id"] not in seen:
            seen.add(r["id"])
            tutorials.append(r)
    
    return {
        "total": len(repos),
        "private_count": len(private),
        "public_count": len(public),
        "empty_descriptions": len(empty_desc),
        "no_topics": len(no_topics),
        "tutorial_repos": len(tutorials),
        "empty_desc_names": [{"name": r["name"], "private": r["private"]} for r in empty_desc],
        "tutorial_names": [{"name": r["name"], "private": r["private"], "language": r.get("language")} for r in tutorials],
        "top_private_by_updated": sorted(private, key=lambda r: r["updated_at"], reverse=True)[:20],
        "top_public_by_stars": sorted(public, key=lambda r: r["stargazers_count"], reverse=True)[:20],
    }

def main():
    token = get_github_token()
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    dumps = db["dumps"]
    repos_coll = db["repos"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": "github-audit",
        "status": "running",
        "started_at": datetime.utcnow(),
    }).inserted_id
    
    try:
        print("Fetching user...")
        user = fetch_user(token)
        
        print("Fetching all repos...")
        repos = fetch_all_repos(token)
        
        print(f"Analyzing {len(repos)} repos...")
        analysis = analyze_repos(repos)
        analysis["user"] = {
            "login": user["login"],
            "name": user.get("name"),
            "bio": user.get("bio"),
            "public_repos": user["public_repos"],
            "followers": user["followers"],
            "following": user["following"],
        }
        
        # Store in dumps
        dump_doc = {
            "source": "github-audit",
            "payload": analysis,
            "tags": ["audit", "profile", "github"],
            "created_at": datetime.utcnow(),
        }
        dumps.insert_one(dump_doc)
        
        # Update repos cache
        for r in repos:
            repos_coll.update_one(
                {"github_id": r["id"]},
                {"$set": {
                    "github_id": r["id"],
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "description": r.get("description"),
                    "private": r["private"],
                    "stargazers_count": r["stargazers_count"],
                    "forks_count": r["forks_count"],
                    "language": r.get("language"),
                    "topics": r.get("topics", []),
                    "updated_at": r["updated_at"],
                    "pushed_at": r["pushed_at"],
                    "html_url": r["html_url"],
                    "last_analyzed": datetime.utcnow(),
                }},
                upsert=True
            )
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "repos_analyzed": len(repos)}}
        )
        
        print(f"Audit complete. {len(repos)} repos analyzed.")
        print(f"Private: {analysis['private_count']}, Public: {analysis['public_count']}")
        print(f"Empty descriptions: {analysis['empty_descriptions']}")
        print(f"Tutorial repos: {analysis['tutorial_repos']}")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()