/**
 * Application metadata store (sessions, MCP server configs, settings).
 * Uses bun:sqlite directly. Conversation state itself lives in the
 * LangGraph checkpointer database (see checkpointer.js).
 */
import { Database } from "bun:sqlite";

export function createAppDb(path) {
  const db = new Database(path, { create: true });
  db.exec(`PRAGMA journal_mode=WAL;`);
  db.exec(`
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT 'New session',
      cwd TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS mcp_servers (
      name TEXT PRIMARY KEY,
      config TEXT NOT NULL,   -- JSON: {transport:"stdio"|"http", command?, args?, url?, headers?, env?}
      enabled INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);

  return {
    // --- sessions ---
    createSession({ id, title, cwd }) {
      const now = Date.now();
      db.prepare(
        `INSERT INTO sessions (id, title, cwd, created_at, updated_at) VALUES (?, ?, ?, ?, ?)`
      ).run(id, title, cwd, now, now);
      return this.getSession(id);
    },
    getSession(id) {
      return db.prepare(`SELECT * FROM sessions WHERE id = ?`).get(id) ?? null;
    },
    listSessions() {
      return db.prepare(`SELECT * FROM sessions ORDER BY updated_at DESC`).all();
    },
    touchSession(id, title) {
      if (title !== undefined) {
        db.prepare(`UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?`).run(
          Date.now(), title, id
        );
      } else {
        db.prepare(`UPDATE sessions SET updated_at = ? WHERE id = ?`).run(Date.now(), id);
      }
    },
    deleteSession(id) {
      db.prepare(`DELETE FROM sessions WHERE id = ?`).run(id);
    },

    // --- MCP servers ---
    listMcpServers() {
      return db
        .prepare(`SELECT * FROM mcp_servers ORDER BY name`)
        .all()
        .map((r) => ({ name: r.name, enabled: !!r.enabled, ...JSON.parse(r.config) }));
    },
    upsertMcpServer(name, config, enabled = true) {
      db.prepare(
        `INSERT INTO mcp_servers (name, config, enabled) VALUES (?, ?, ?)
         ON CONFLICT(name) DO UPDATE SET config = excluded.config, enabled = excluded.enabled`
      ).run(name, JSON.stringify(config), enabled ? 1 : 0);
    },
    deleteMcpServer(name) {
      db.prepare(`DELETE FROM mcp_servers WHERE name = ?`).run(name);
    },

    // --- settings ---
    getSetting(key, fallback = null) {
      const row = db.prepare(`SELECT value FROM settings WHERE key = ?`).get(key);
      return row ? JSON.parse(row.value) : fallback;
    },
    setSetting(key, value) {
      db.prepare(
        `INSERT INTO settings (key, value) VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value`
      ).run(key, JSON.stringify(value));
    },
  };
}
