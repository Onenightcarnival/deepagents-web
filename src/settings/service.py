"""应用设置：KV 存取（供各业务模块使用）与项目级配置写入。"""

import json

from sqlalchemy.orm import Session

from src.settings.model import SettingRecord


def get_setting(db: Session, key: str, fallback=None):
    row = db.get(SettingRecord, key)
    return json.loads(row.value) if row else fallback


def set_setting(db: Session, key: str, value) -> None:
    db.merge(SettingRecord(key=key, value=json.dumps(value)))
    db.commit()


def update_project_config(db: Session, key: str, model, params, has_model: bool, has_params: bool) -> dict:
    """更新一个项目的模型/参数配置，返回更新后的条目。"""
    cfg = get_setting(db, "projectConfig", {})
    entry = cfg.get(key) or {}
    if has_model:
        entry["model"] = model
    if has_params:
        entry["params"] = params
    cfg[key] = entry
    set_setting(db, "projectConfig", cfg)
    return entry
