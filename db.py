import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            source TEXT NOT NULL,
            score REAL,
            smart_followers INTEGER,
            raw_data TEXT,
            searched_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_result(username: str, source: str, score, smart_followers, raw_data: dict = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO search_history (username, source, score, smart_followers, raw_data, searched_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        username.lower(),
        source,
        score,
        smart_followers,
        json.dumps(raw_data or {}),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()


def get_last_result(username: str, source: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT score, smart_followers, raw_data, searched_at
        FROM search_history
        WHERE username = ? AND source = ?
        ORDER BY searched_at DESC
        LIMIT 1 OFFSET 1
    """, (username.lower(), source))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "score": row[0],
            "smart_followers": row[1],
            "raw_data": json.loads(row[2]) if row[2] else {},
            "searched_at": row[3]
        }
    return None
