import sqlite3
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
            score INTEGER,
            level TEXT,
            smarts INTEGER,
            followers INTEGER,
            searched_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_result(username, score, level, smarts, followers):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """INSERT INTO search_history
           (username, score, level, smarts, followers, searched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username.lower(), score, level, smarts, followers,
         datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_last_result(username: str) -> dict | None:
    """Most recent PREVIOUS result (offset 1 = before the current one)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT score, level, smarts, followers, searched_at
           FROM search_history WHERE username = ?
           ORDER BY searched_at DESC LIMIT 1 OFFSET 1""",
        (username.lower(),),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "score": row[0], "level": row[1],
            "smarts": row[2], "followers": row[3],
            "searched_at": row[4],
        }
    return None
