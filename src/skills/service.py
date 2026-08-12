"""Skills: directories containing SKILL.md (Claude-Code-style, consumed by
deepagents' SkillsMiddleware). The app only stores a list of source
directories; whatever they contain is loaded automatically.
"""
import os
import re
from pathlib import Path

from ..settings.service import get_setting

DEFAULT_SKILL_DIR = str(Path.home() / ".deepagent" / "skills")


def expand_path(p: str) -> str:
    return str(Path(os.path.expanduser(p)).resolve())


def get_skill_dirs() -> list[str]:
    return get_setting("skillDirs", [DEFAULT_SKILL_DIR])


def parse_frontmatter(md: str) -> dict:
    """Minimal YAML-frontmatter parser: scalar values + block/inline string lists."""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", md)
    if not m:
        return {}
    out: dict = {}
    list_key = None
    for raw_line in re.split(r"\r?\n", m.group(1)):
        line = raw_line.replace("\t", "  ")
        item = re.match(r"^\s+-\s*(.+)$", line)
        if item and list_key:
            out[list_key].append(item.group(1).strip().strip("\"'"))
            continue
        kv = re.match(r"^([\w-]+):\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2)
        if value == "":
            out[key] = []
            list_key = key
        elif value.startswith("["):
            out[key] = [s.strip() for s in value.strip("[]").split(",") if s.strip()]
            list_key = None
        else:
            out[key] = value.strip("\"'")
            list_key = None
    return out


def scan_skills(dirs: list[str]) -> dict:
    """Scan configured directories for skills.

    Later directories override earlier ones for same-name skills (matches
    deepagents' "last one wins").
    """
    by_name: dict = {}
    errors: list[str] = []
    for d in dirs:
        abs_dir = Path(expand_path(d))
        if not abs_dir.exists():
            continue
        try:
            entries = list(abs_dir.iterdir())
        except OSError as e:
            errors.append(f"{d}: {e}")
            continue
        for ent in entries:
            if not ent.is_dir():
                continue
            skill_md = ent / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                md = skill_md.read_text(encoding="utf-8")
                fm = parse_frontmatter(md)
                name = fm.get("name") or ent.name
                by_name[name] = {
                    "name": name,
                    "description": fm.get("description") or "",
                    "allowedTools": fm.get("allowed-tools") or fm.get("allowedTools") or [],
                    "dir": d,
                    "path": str(skill_md),
                }
            except OSError as e:
                errors.append(f"{skill_md}: {e}")
    return {"skills": list(by_name.values()), "errors": errors}


def read_skill_file(dirs: list[str], path: str) -> str:
    """Read a SKILL.md, but only if it lives inside one of the configured dirs."""
    abs_path = Path(path).resolve()
    allowed = any(
        str(abs_path).startswith(expand_path(d) + "/") or str(abs_path) == expand_path(d)
        for d in dirs
    )
    if not allowed or abs_path.name != "SKILL.md":
        raise ValueError("path outside configured skill directories")
    if not abs_path.is_file():
        raise ValueError("file not found")
    return abs_path.read_text(encoding="utf-8")
