"""Application metadata store (sessions, MCP server configs, settings).

Uses sqlite3 directly. Conversation state itself lives in the LangGraph
checkpointer database (see main.py lifespan).
"""
import json
import sqlite3
import threading
import time


def _now_ms() -> int:
    return int(time.time() * 1000)


class AppDb:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL DEFAULT 'New session',
              cwd TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mcp_servers (
              name TEXT PRIMARY KEY,
              config TEXT NOT NULL,   -- JSON: {transport:"http", url, headers?, disabledTools?}
              enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        # migration: per-session model override (JSON {provider, model} or NULL)
        cols = [r["name"] for r in self._db.execute("PRAGMA table_info(sessions)")]
        if "model" not in cols:
            self._db.execute("ALTER TABLE sessions ADD COLUMN model TEXT")
        self._db.commit()

    def _exec(self, sql: str, params=()):
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _query(self, sql: str, params=()):
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # --- sessions ---

    def create_session(self, id: str, title: str, cwd: str) -> dict:
        now = _now_ms()
        self._exec(
            "INSERT INTO sessions (id, title, cwd, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (id, title, cwd, now, now),
        )
        return self.get_session(id)

    def get_session(self, id: str) -> dict | None:
        rows = self._query("SELECT * FROM sessions WHERE id = ?", (id,))
        return dict(rows[0]) if rows else None

    def list_sessions(self) -> list[dict]:
        return [dict(r) for r in self._query("SELECT * FROM sessions ORDER BY updated_at DESC")]

    def touch_session(self, id: str, title: str | None = None):
        if title is not None:
            self._exec(
                "UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?",
                (_now_ms(), title, id),
            )
        else:
            self._exec("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now_ms(), id))

    def delete_session(self, id: str):
        self._exec("DELETE FROM sessions WHERE id = ?", (id,))

    def update_session(self, id: str, title=None, model="__unset__") -> dict | None:
        if title is not None:
            self._exec("UPDATE sessions SET title = ? WHERE id = ?", (title, id))
        if model != "__unset__":
            # model: {provider, model} dict or None to clear the override
            self._exec(
                "UPDATE sessions SET model = ? WHERE id = ?",
                (json.dumps(model) if model else None, id),
            )
        return self.get_session(id)

    # --- MCP servers ---

    def list_mcp_servers(self) -> list[dict]:
        out = []
        for r in self._query("SELECT * FROM mcp_servers ORDER BY name"):
            out.append({"name": r["name"], "enabled": bool(r["enabled"]), **json.loads(r["config"])})
        return out

    def upsert_mcp_server(self, name: str, config: dict, enabled: bool = True):
        self._exec(
            """INSERT INTO mcp_servers (name, config, enabled) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET config = excluded.config, enabled = excluded.enabled""",
            (name, json.dumps(config), 1 if enabled else 0),
        )

    def delete_mcp_server(self, name: str):
        self._exec("DELETE FROM mcp_servers WHERE name = ?", (name,))

    # --- settings ---

    def get_setting(self, key: str, fallback=None):
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else fallback

    def set_setting(self, key: str, value):
        self._exec(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, json.dumps(value)),
        )
