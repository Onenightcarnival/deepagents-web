"""文件树：以会话工作目录为根，提供目录懒加载列表与文本文件预览。

根锁死在会话 cwd：path 一律传相对路径，resolve 后校验未逃逸出根目录。
软链指向根外时，下钻或预览会被同一校验拦下（列表里仍可见其名字）。
"""

import contextlib
import pathlib
from enum import StrEnum

import anyio
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.sessions.service import get_session
from src.utils.app_config import json_response
from src.utils.database import get_db

router = APIRouter(prefix="/files")

# 文本预览大小上限，超过直接拒绝；前端提示用户用别的方式看
MAX_PREVIEW_BYTES = 1024 * 1024


class FileCode(StrEnum):
    """files 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-06-00"
    SESSION_NOT_FOUND = "WA-06-01"
    PATH_NOT_FOUND = "WA-06-02"
    PATH_FORBIDDEN = "WA-06-03"
    FILE_TOO_LARGE = "WA-06-04"
    FILE_NOT_TEXT = "WA-06-05"


MESSAGES: dict[FileCode, str] = {
    FileCode.OK: "成功",
    FileCode.SESSION_NOT_FOUND: "会话不存在",
    FileCode.PATH_NOT_FOUND: "路径不存在",
    FileCode.PATH_FORBIDDEN: "路径越界或无权限访问",
    FileCode.FILE_TOO_LARGE: "文件过大，不支持预览",
    FileCode.FILE_NOT_TEXT: "二进制文件，不支持预览",
}


async def _locate(db: Session, session_id: str, path: str):
    """把相对 path 定位到会话 cwd 内的绝对路径。

    返回 (target, None) 或 (None, 错误响应)。resolve 之后做前缀校验，
    `..` 与逃逸软链都会在这里被拦下。"""
    sess = get_session(db, session_id)
    if not sess:
        return None, json_response(
            status.HTTP_404_NOT_FOUND, FileCode.SESSION_NOT_FOUND, MESSAGES[FileCode.SESSION_NOT_FOUND]
        )
    root = await anyio.Path(sess["cwd"]).resolve()
    target = await anyio.Path(pathlib.PurePath(str(root), path)).resolve()
    if not pathlib.PurePath(str(target)).is_relative_to(str(root)):
        return None, json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.PATH_FORBIDDEN,
            f"{MESSAGES[FileCode.PATH_FORBIDDEN]}: {path}",
        )
    return target, None


@router.get("/{session_id}")
async def list_dir(session_id: str, path: str = "", db: Session = Depends(get_db)):
    """列出 cwd 内某目录的子项（目录在前、按名排序），供前端逐层展开。"""
    target, err = await _locate(db, session_id, path)
    if err:
        return err
    if not await target.is_dir():
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.PATH_NOT_FOUND,
            f"{MESSAGES[FileCode.PATH_NOT_FOUND]}: {path or '.'}",
        )
    entries = []
    try:
        async for child in target.iterdir():
            if child.name == ".git":
                continue
            # 个别子项 stat 失败（权限、坏软链）跳过即可，不该拖垮整个列表
            with contextlib.suppress(OSError):
                if await child.is_dir():
                    entries.append({"name": child.name, "type": "dir"})
                else:
                    entries.append({"name": child.name, "type": "file", "size": (await child.stat()).st_size})
    except PermissionError:
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.PATH_FORBIDDEN,
            f"{MESSAGES[FileCode.PATH_FORBIDDEN]}: {path or '.'}",
        )
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return json_response(
        status.HTTP_200_OK, FileCode.OK, MESSAGES[FileCode.OK], data={"path": path, "entries": entries}
    )


@router.get("/{session_id}/content")
async def file_content(session_id: str, path: str, db: Session = Depends(get_db)):
    """读取 cwd 内文本文件用于预览；超限或二进制拒绝。"""
    target, err = await _locate(db, session_id, path)
    if err:
        return err
    if not await target.is_file():
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.PATH_NOT_FOUND,
            f"{MESSAGES[FileCode.PATH_NOT_FOUND]}: {path}",
        )
    try:
        size = (await target.stat()).st_size
        if size > MAX_PREVIEW_BYTES:
            return json_response(
                status.HTTP_400_BAD_REQUEST,
                FileCode.FILE_TOO_LARGE,
                f"{MESSAGES[FileCode.FILE_TOO_LARGE]}: {size // 1024} KB",
            )
        raw = await target.read_bytes()
    except (PermissionError, OSError):
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.PATH_FORBIDDEN,
            f"{MESSAGES[FileCode.PATH_FORBIDDEN]}: {path}",
        )
    # 头部含 NUL 视为二进制，这是最简单可靠的文本探测
    if b"\0" in raw[:8192]:
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            FileCode.FILE_NOT_TEXT,
            f"{MESSAGES[FileCode.FILE_NOT_TEXT]}: {path}",
        )
    return json_response(
        status.HTTP_200_OK,
        FileCode.OK,
        MESSAGES[FileCode.OK],
        data={"path": path, "size": size, "content": raw.decode("utf-8", errors="replace")},
    )
