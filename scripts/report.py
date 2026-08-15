#!/usr/bin/env python3
"""
Generate daily markdown report from analyses and commit to repo.
"""
import os
import sys
import json
import pymongo
import subprocess
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
REPO_PATH = os.environ.get("REPO_PATH", "/opt/data/repo-analysis")

def get_mongo_client():
    return pymongo.MongoClient(
        MONGO_URI,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )

def main():
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    analyses = db["analyses"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": "daily-report",
        "status": "running",
        "started_at": datetime.utcnow(),
    }).inserted_id
    
    try:
        # Get analyses from last 24h
        since = datetime.utcnow() - timedelta(hours=24)
        recent = list(analyses.find({"created_at": {"$gte": since}}).sort("created_at", -1))
        
        # Group by type
        by_type = {}
        for a in recent:
            t = a.get("type", "unknown")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(a)
        
        # Generate markdown
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        md = f"# Daily Report — {date_str}\n\n"
        md += f"Generated: {datetime.utcnow().isoformat()}Z\n\n"
        md += f"Total analyses: {len(recent)}\n\n"
        
        for t, items in by_type.items():
            md += f"## {t.replace('_', ' ').title()} ({len(items)})\n\n"
            for a in items[:5]:  # Top 5 per type
                result = a.get("result", {})
                if isinstance(result, dict):
                    if "summary" in result:
                        md += f"- {result['summary']}\n"
                    elif "insights" in result:
                        md += f"- {result['insights'][:200]}...\n"
                md += "\n"
        
        # Write report
        reports_dir = os.path.join(REPO_PATH, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        report_file = os.path.join(reports_dir, f"{date_str}-report.md")
        
        with open(report_file, "w") as f:
            f.write(md)
        
        # Git commit
        subprocess.run(["git", "add", report_file], cwd=REPO_PATH, check=True)
        subprocess.run(["git", "commit", "-m", f"chore: daily report {date_str}"], cwd=REPO_PATH, check=True)
        subprocess.run(["git", "push"], cwd=REPO_PATH, check=True)
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "report": report_file}}
        )
        print(f"Report generated and pushed: {report_file}")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()