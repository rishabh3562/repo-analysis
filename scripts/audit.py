#!/usr/bin/env python3
"""
Full GitHub profile audit. Stores results in MongoDB dumps collection and commits report to GitHub.
"""
import os
import re
import sys
import json
import subprocess
import requests
import pymongo
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
GITHUB_USER = "rishabh3562"
API = "https://api.github.com"
REPO_PATH = os.environ.get("REPO_PATH", "/opt/data/repo-analysis")

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

def generate_markdown_report(analysis, user):
    """Generate markdown report from audit analysis."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = f"# GitHub Profile Audit — {date_str}\n\n"
    md += f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z\n\n"
    
    md += "## Profile Summary\n\n"
    md += f"- **User:** {user.get('login', 'unknown')}\n"
    md += f"- **Name:** {user.get('name', 'N/A')}\n"
    md += f"- **Bio:** {user.get('bio', 'N/A')}\n"
    md += f"- **Followers:** {user.get('followers', 0)} | **Following:** {user.get('following', 0)}\n\n"
    
    md += "## Repository Statistics\n\n"
    md += f"- **Total Repos:** {analysis['total']}\n"
    md += f"- **Private:** {analysis['private_count']}\n"
    md += f"- **Public:** {analysis['public_count']}\n"
    md += f"- **Empty Descriptions:** {analysis['empty_descriptions']}\n"
    md += f"- **No Topics:** {analysis['no_topics']}\n"
    md += f"- **Tutorial/Practice Repos:** {analysis['tutorial_repos']}\n\n"
    
    md += "## Top Public Repos by Stars\n\n"
    for i, r in enumerate(analysis.get("top_public_by_stars", [])[:10], 1):
        md += f"{i}. **{r['name']}** — ⭐ {r['stargazers_count']} — {r.get('description', 'No description')}\n"
    md += "\n"
    
    md += "## Recently Updated Private Repos\n\n"
    for i, r in enumerate(analysis.get("top_private_by_updated", [])[:10], 1):
        md += f"{i}. **{r['name']}** — Updated: {r['updated_at'][:10]}\n"
    md += "\n"
    
    md += "## Repos Needing Descriptions\n\n"
    for r in analysis.get("empty_desc_names", [])[:20]:
        md += f"- {r['name']} ({'private' if r['private'] else 'public'})\n"
    md += "\n"
    
    md += "## Tutorial/Practice Repos to Archive\n\n"
    for r in analysis.get("tutorial_names", []):
        md += f"- {r['name']} ({r.get('language', 'unknown')}) — {'private' if r['private'] else 'public'}\n"
    md += "\n"
    
    md += "---\n*Generated by automated audit pipeline*\n"
    return md

def commit_and_push(report_file, message):
    """Commit and push a file to the repo."""
    try:
        subprocess.run(["git", "add", report_file], cwd=REPO_PATH, check=True, capture_output=True)
        result = subprocess.run(["git", "commit", "-m", message], cwd=REPO_PATH, capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(["git", "push"], cwd=REPO_PATH, check=True, capture_output=True)
            print(f"Committed and pushed: {report_file}")
        else:
            if "nothing to commit" not in result.stdout:
                print(f"Commit skipped: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}")

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
        "started_at": datetime.now(timezone.utc),
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
            "created_at": datetime.now(timezone.utc),
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
                    "last_analyzed": datetime.now(timezone.utc),
                }},
                upsert=True
            )
        
        # Generate and save markdown report
        md = generate_markdown_report(analysis, user)
        reports_dir = os.path.join(REPO_PATH, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_file = os.path.join(reports_dir, f"{date_str}-audit.md")
        
        with open(report_file, "w") as f:
            f.write(md)
        
        # Commit and push
        commit_and_push(report_file, f"chore: audit report {date_str}")
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc), "repos_analyzed": len(repos)}}
        )
        
        print(f"Audit complete. {len(repos)} repos analyzed.")
        print(f"Private: {analysis['private_count']}, Public: {analysis['public_count']}")
        print(f"Empty descriptions: {analysis['empty_descriptions']}")
        print(f"Tutorial repos: {analysis['tutorial_repos']}")
        print(f"Report saved: {report_file}")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.now(timezone.utc), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()