"""Skills: directories containing SKILL.md (Claude-Code-style, consumed by
deepagents' SkillsMiddleware). The app only stores a list of source
directories; whatever they contain is loaded automatically.
"""

import io
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from src.settings.service import get_setting

DEFAULT_SKILL_DIR = str(Path.home() / ".deepagent" / "skills")

# 上传技能包的硬限制：条目数与解压后总字节数（防 zip bomb）
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
# 技能名要当落盘目录名，只放行安全字符
SKILL_NAME_RE = re.compile(r"^[\w][\w.-]*$")


class SkillExistsError(Exception):
    """同名技能已存在且未允许覆盖。"""


def expand_path(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def get_skill_dirs(db: Session) -> list[str]:
    return get_setting(db, "skillDirs", [DEFAULT_SKILL_DIR])


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


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """zip 条目名解码。无 UTF-8 标志位时 zipfile 按 cp437 解码，而 Windows
    自带压缩工具写入的实际是 GBK——中文文件名必须回转一次。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("gbk")
    except UnicodeError:
        return info.filename


def _validate_entries(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """安全校验所有条目，返回 {解码后路径: 条目}（不含目录条目）。"""
    files: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in zf.infolist():
        name = _decode_zip_name(info)
        if name.endswith("/"):
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"条目路径不安全: {name}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"不支持符号链接条目: {name}")
        total += info.file_size
        files[name] = info
        if len(files) > MAX_ZIP_ENTRIES:
            raise ValueError(f"条目数超过上限 {MAX_ZIP_ENTRIES}")
        if total > MAX_ZIP_TOTAL_BYTES:
            raise ValueError(f"解压后总大小超过上限 {MAX_ZIP_TOTAL_BYTES // 1024 // 1024}MB")
    if not files:
        raise ValueError("zip 内没有文件")
    return files


def _find_skill_root(files: dict[str, zipfile.ZipInfo]) -> str:
    """定位 SKILL.md 所在层，返回应剥掉的前缀（"" 或 "顶层目录/"）。
    约定只接受两种形态：SKILL.md 在 zip 根，或在唯一顶层目录下。"""
    if "SKILL.md" in files:
        return ""
    tops = {name.split("/", 1)[0] for name in files}
    if len(tops) == 1:
        top = next(iter(tops))
        if f"{top}/SKILL.md" in files:
            return f"{top}/"
    raise ValueError("zip 内找不到 SKILL.md（须位于 zip 根或唯一顶层目录下）")


def install_skill_zip(target_dir: str, data: bytes, overwrite: bool) -> dict:
    """校验技能 zip 并安装到 target_dir 下，返回 {name, description}。

    先整体解压到临时目录，全部通过后一次性移入目标位置，避免半成品目录
    被 scan_skills 扫到。格式不合法抛 ValueError，重名未允许覆盖抛
    SkillExistsError。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"不是有效的 zip 文件: {e}") from e
    with zf:
        files = _validate_entries(zf)
        prefix = _find_skill_root(files)
        md = zf.read(files[f"{prefix}SKILL.md"]).decode("utf-8", errors="replace")
        fm = parse_frontmatter(md)
        name = fm.get("name") or ""
        if not SKILL_NAME_RE.fullmatch(name):
            raise ValueError(f"SKILL.md frontmatter 缺少合法的 name（当前值: {name!r}）")
        dest = Path(expand_path(target_dir)) / name
        if dest.exists() and not overwrite:
            raise SkillExistsError(name)
        tmp = Path(tempfile.mkdtemp(prefix="skill-upload-"))
        try:
            written = 0
            for entry_name, info in files.items():
                rel = entry_name[len(prefix) :]
                if not rel:
                    continue
                out = tmp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                # 逐块落盘并复核实际字节数，条目头里的 file_size 可以造假
                with zf.open(info) as src, out.open("wb") as dst:
                    while chunk := src.read(1 << 16):
                        written += len(chunk)
                        if written > MAX_ZIP_TOTAL_BYTES:
                            raise ValueError(f"解压后总大小超过上限 {MAX_ZIP_TOTAL_BYTES // 1024 // 1024}MB")
                        dst.write(chunk)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(tmp), str(dest))
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    return {"name": name, "description": fm.get("description") or ""}


def delete_skill(dirs: list[str], path: str) -> str:
    """按 SKILL.md 路径删除其所在技能目录，返回被删目录名。

    只允许删除已配置技能目录的直接子目录，杜绝借路径删到别处。
    """
    abs_path = Path(path).resolve()
    if abs_path.name != "SKILL.md":
        raise ValueError("path 必须指向 SKILL.md")
    skill_dir = abs_path.parent
    if not any(str(skill_dir.parent) == expand_path(d) for d in dirs):
        raise ValueError("path outside configured skill directories")
    if not abs_path.is_file():
        raise ValueError("file not found")
    shutil.rmtree(skill_dir)
    return skill_dir.name


def read_skill_file(dirs: list[str], path: str) -> str:
    """Read a SKILL.md, but only if it lives inside one of the configured dirs."""
    abs_path = Path(path).resolve()
    allowed = any(str(abs_path).startswith(expand_path(d) + "/") or str(abs_path) == expand_path(d) for d in dirs)
    if not allowed or abs_path.name != "SKILL.md":
        raise ValueError("path outside configured skill directories")
    if not abs_path.is_file():
        raise ValueError("file not found")
    return abs_path.read_text(encoding="utf-8")
