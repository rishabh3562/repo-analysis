#!/usr/bin/env python3
"""
Generate embeddings for dumps and chats for semantic search.
"""
import os
import sys
import pymongo
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.environ.get("MONGO_AI_URI", "mongodb+srv://Hermes:Hermes54*@cluster0.rzg43g9.mongodb.net/?appName=Cluster0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

def get_mongo_client():
    return pymongo.MongoClient(
        MONGO_URI,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=30000
    )

def get_embedding(text):
    import requests
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDING_MODEL, "input": text[:8000]},
        timeout=30
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]

def extract_text(doc):
    """Extract searchable text from a dump or chat document."""
    if "payload" in doc:
        payload = doc["payload"]
        if isinstance(payload, dict):
            # For audit dumps
            if "user" in payload:
                u = payload["user"]
                text = f"{u.get('login', '')} {u.get('name', '')} {u.get('bio', '')} "
                text += f"{payload.get('total', 0)} repos. "
                text += " ".join([r["name"] for r in payload.get("top_public_by_stars", [])[:10]])
                return text
            # For sync dumps
            if "events" in payload:
                return " ".join([e.get("type", "") for e in payload["events"][:20]])
        return json.dumps(payload)[:2000]
    return ""

def main():
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    
    mongo = get_mongo_client()
    db = mongo["ai_agents"]
    dumps = db["dumps"]
    chats = db["chats"]
    embeddings = db["embeddings"]
    cron_runs = db["cron_runs"]
    
    run_id = cron_runs.insert_one({
        "job_name": "embed-new",
        "status": "running",
        "started_at": datetime.utcnow(),
    }).inserted_id
    
    try:
        embedded = 0
        
        # Embed unembedded dumps
        unembedded_dumps = list(dumps.find({
            "_id": {"$nin": [e["source_id"] for e in embeddings.find({"source_type": "dump"}, {"source_id": 1})]}
        }).limit(50))
        
        for dump in unembedded_dumps:
            text = extract_text(dump)
            if text.strip():
                vector = get_embedding(text)
                embeddings.insert_one({
                    "source_type": "dump",
                    "source_id": dump["_id"],
                    "vector": vector,
                    "model": EMBEDDING_MODEL,
                    "text_preview": text[:200],
                    "created_at": datetime.utcnow(),
                })
                embedded += 1
        
        # Embed unembedded chats
        unembedded_chats = list(chats.find({
            "_id": {"$nin": [e["source_id"] for e in embeddings.find({"source_type": "chat"}, {"source_id": 1})]}
        }).limit(50))
        
        for chat in unembedded_chats:
            text = chat.get("content", "")
            if text.strip():
                vector = get_embedding(text)
                embeddings.insert_one({
                    "source_type": "chat",
                    "source_id": chat["_id"],
                    "vector": vector,
                    "model": EMBEDDING_MODEL,
                    "text_preview": text[:200],
                    "created_at": datetime.utcnow(),
                })
                embedded += 1
        
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "embedded": embedded}}
        )
        print(f"Embedding complete. {embedded} new vectors.")
        
    except Exception as e:
        cron_runs.update_one(
            {"_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}}
        )
        print(f"Error: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()