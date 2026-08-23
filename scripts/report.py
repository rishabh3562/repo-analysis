#!/usr/bin/env python3
"""
Generate daily markdown report from analyses and commit to repo.
With full observability: timing, metrics, structured logging.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import REPO_PATH, get_mongo_client, safe_git_commit_push
from observability import init_job, log_step, log_metric, complete_job, fail_job, timed_step

def main():
    run_id = init_job("daily-report")
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    analyses = db["analyses"]
    
    try:
        # Get analyses from last 24h
        with timed_step("fetch_recent_analyses"):
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            recent = list(analyses.find({"created_at": {"$gte": since}}).sort("created_at", -1))
        
        log_metric("analyses_fetched", len(recent))
        
        # Group by type
        with timed_step("group_by_type"):
            by_type = {}
            for a in recent:
                t = a.get("type", "unknown")
                if t not in by_type:
                    by_type[t] = []
                by_type[t].append(a)
        
        log_metric("analysis_types", list(by_type.keys()))
        for t, items in by_type.items():
            log_metric(f"type_{t}_count", len(items))
        
        # Generate markdown
        with timed_step("generate_markdown"):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            md = f"# Daily Report — {date_str}\n\n"
            md += f"Generated: {datetime.now(timezone.utc).isoformat()}Z\n\n"
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
        with timed_step("write_report"):
            reports_dir = os.path.join(REPO_PATH, "reports")
            os.makedirs(reports_dir, exist_ok=True)
            report_file = os.path.join(reports_dir, f"{date_str}-report.md")
            
            with open(report_file, "w") as f:
                f.write(md)
        
        # Git commit and push with pull-first safety
        with timed_step("commit_push"):
            safe_git_commit_push(REPO_PATH, report_file, f"chore: daily report {date_str}")
        
        complete_job(
            status="completed",
            analyses_reported=len(recent),
            types=dict((k, len(v)) for k, v in by_type.items()),
            report_file=report_file,
        )
        print(f"Report generated and pushed: {report_file}")
        
    except Exception as e:
        fail_job(e)
        raise

if __name__ == "__main__":
    main()