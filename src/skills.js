/**
 * Skills: directories containing SKILL.md (Claude-Code-style, consumed by
 * deepagents' SkillsMiddleware). The app only stores a list of source
 * directories; whatever they contain is loaded automatically.
 */
import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { resolve, join } from "node:path";
import { homedir } from "node:os";

export const DEFAULT_SKILL_DIR = join(homedir(), ".deepagent", "skills");

export function expandPath(p) {
  if (p === "~") return homedir();
  if (p.startsWith("~/")) return join(homedir(), p.slice(2));
  return resolve(p);
}

export function getSkillDirs(db) {
  return db.getSetting("skillDirs", [DEFAULT_SKILL_DIR]);
}

/** Minimal YAML-frontmatter parser: scalar values + block/inline string lists. */
function parseFrontmatter(md) {
  const m = md.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return {};
  const out = {};
  let listKey = null;
  for (const rawLine of m[1].split(/\r?\n/)) {
    const line = rawLine.replace(/\t/g, "  ");
    const item = line.match(/^\s+-\s*(.+)$/);
    if (item && listKey) {
      out[listKey].push(item[1].trim().replace(/^["']|["']$/g, ""));
      continue;
    }
    const kv = line.match(/^([\w-]+):\s*(.*)$/);
    if (!kv) continue;
    const [, key, value] = kv;
    if (value === "") {
      out[key] = [];
      listKey = key;
    } else if (value.startsWith("[")) {
      out[key] = value.replace(/^\[|\]$/g, "").split(",").map((s) => s.trim()).filter(Boolean);
      listKey = null;
    } else {
      out[key] = value.replace(/^["']|["']$/g, "");
      listKey = null;
    }
  }
  return out;
}

/**
 * Scan configured directories for skills.
 * Later directories override earlier ones for same-name skills (matches
 * deepagents' "last one wins").
 */
export function scanSkills(dirs) {
  const byName = new Map();
  const errors = [];
  for (const dir of dirs) {
    const abs = expandPath(dir);
    if (!existsSync(abs)) continue;
    let entries;
    try {
      entries = readdirSync(abs, { withFileTypes: true });
    } catch (e) {
      errors.push(`${dir}: ${String(e?.message ?? e)}`);
      continue;
    }
    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      const skillMd = join(abs, ent.name, "SKILL.md");
      if (!existsSync(skillMd)) continue;
      try {
        const md = readFileSync(skillMd, "utf8");
        const fm = parseFrontmatter(md);
        byName.set(fm.name || ent.name, {
          name: fm.name || ent.name,
          description: fm.description || "",
          allowedTools: fm["allowed-tools"] ?? fm.allowedTools ?? [],
          dir,
          path: skillMd,
        });
      } catch (e) {
        errors.push(`${skillMd}: ${String(e?.message ?? e)}`);
      }
    }
  }
  return { skills: [...byName.values()], errors };
}

/** Read a SKILL.md, but only if it lives inside one of the configured dirs. */
export function readSkillFile(dirs, path) {
  const abs = resolve(path);
  const allowed = dirs.some((d) => {
    const root = expandPath(d);
    return abs.startsWith(root + "/") || abs === root;
  });
  if (!allowed || !abs.endsWith("SKILL.md")) {
    throw new Error("path outside configured skill directories");
  }
  if (!existsSync(abs) || !statSync(abs).isFile()) throw new Error("file not found");
  return readFileSync(abs, "utf8");
}
