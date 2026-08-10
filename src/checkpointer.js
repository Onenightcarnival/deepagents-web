/**
 * SQLite checkpointer for Bun.
 *
 * @langchain/langgraph-checkpoint-sqlite depends on better-sqlite3 (a native
 * Node addon that Bun cannot load). SqliteSaver's constructor accepts any
 * database object with a better-sqlite3-compatible surface, so we wrap
 * Bun's built-in `bun:sqlite` Database in a thin shim:
 *
 *   - `.pragma(str)`            -> exec(`PRAGMA ${str}`)
 *   - statement `.get()`        -> better-sqlite3 returns undefined for no
 *                                  row, bun:sqlite returns null; normalize.
 *   - `.transaction(fn)`        -> both return a callable; pass through.
 */
import { Database } from "bun:sqlite";
import { SqliteSaver } from "@langchain/langgraph-checkpoint-sqlite";

class BunStatementShim {
  constructor(stmt) {
    this.stmt = stmt;
  }
  run(...args) {
    return this.stmt.run(...args);
  }
  all(...args) {
    return this.stmt.all(...args);
  }
  get(...args) {
    const row = this.stmt.get(...args);
    return row === null ? undefined : row;
  }
}

class BunDatabaseShim {
  constructor(path) {
    this.db = new Database(path, { create: true });
  }
  pragma(str) {
    return this.db.exec(`PRAGMA ${str};`);
  }
  exec(sql) {
    return this.db.exec(sql);
  }
  prepare(sql) {
    return new BunStatementShim(this.db.prepare(sql));
  }
  transaction(fn) {
    return this.db.transaction(fn);
  }
  close() {
    this.db.close();
  }
}

export function createCheckpointer(dbPath) {
  return new SqliteSaver(new BunDatabaseShim(dbPath));
}
