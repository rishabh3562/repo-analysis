#!/usr/bin/env python3
"""
LLM analysis pipeline. Processes unanalyzed dumps and stores insights.
"""
import os
import sys
import json
import pymongo
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

def get_mongo_client():
    return pymongo.MongoClient(
        MONGO_URI,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )

def analyze_with_llm(prompt, system_prompt=None):
    import requests
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json={"model": OPENROUTER_MODEL, "messages": messages, "temperature": 0.3},
        timeout=60
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def main():
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    dumps = db["dumps"]
    analyses = db["analyses"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": "analyze-dumps",
        "status": "running",
        "started_at": datetime.utcnow(),
    }).inserted_id
    
    try:
        # Find unanalyzed dumps
        unanalyzed = list(dumps.find({
            "tags": {"$in": ["audit", "sync"]},
            "_id": {"$nin": [a["dump_id"] for a in analyses.find({}, {"dump_id": 1})]}
        }).limit(10))
        
        print(f"Found {len(unanalyzed)} unanalyzed dumps")
        
        for dump in unanalyzed:
            source = dump.get("source")
            payload = dump.get("payload", {})
            
            if source == "github-audit":
                # Summarize audit
                user = payload.get("user", {})
                summary = f"GitHub profile audit for {user.get('login', 'unknown')}: "
                summary += f"{payload.get('total', 0)} repos ({payload.get('private_count', 0)} private, {payload.get('public_count', 0)} public). "
                summary += f"Empty descriptions: {payload.get('empty_descriptions', 0)}. "
                summary += f"Tutorial repos to archive: {payload.get('tutorial_repos', 0)}. "
                summary += f"Top starred: {', '.join([r['name'] for r in payload.get('top_public_by_stars', [])[:3]])}."
                
                # LLM enhancement
                prompt = f"""Analyze this GitHub profile audit and provide 3-5 actionable insights:

{json.dumps(payload, indent=2)}

Focus on: repo hygiene, portfolio signal, missing opportunities, quick wins."""
                
                try:
                    insights = analyze_with_llm(prompt, "You are a senior developer reviewing a GitHub profile for career impact.")
                    result = {"summary": summary, "insights": insights, "model": OPENROUTER_MODEL}
                except Exception as e:
                    result = {"summary": summary, "insights": f"LLM failed: {e}", "model": OPENROUTER_MODEL}
                
                analyses.insert_one({
                    "dump_id": dump["_id"],
                    "type": "profile_audit",
                    "result": result,
                    "model": OPENROUTER_MODEL,
                    "created_at": datetime.utcnow(),
                })
                print(f"  Analyzed audit dump {dump['_id']}")
            
            elif source == "github-sync":
                # Summarize sync events
                repo = dump.get("repo")
                events = payload.get("events", [])
                event_types = {}
                for e in events:
                    event_types[e.get("type", "unknown")] = event_types.get(e.get("type", "unknown"), 0) + 1
                
                summary = f"Sync for {repo}: {len(events)} events. Types: {event_types}"
                
                analyses.insert_one({
                    "dump_id": dump["_id"],
                    "type": "sync_summary",
                    "result": {"summary": summary, "event_types": event_types, "count": len(events)},
                    "model": OPENROUTER_MODEL,
                    "created_at": datetime.utcnow(),
                })
                print(f"  Analyzed sync dump {dump['_id']} ({repo})")
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "dumps_analyzed": len(unanalyzed)}}
        )
        print(f"Analysis complete. {len(unanalyzed)} dumps processed.")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()