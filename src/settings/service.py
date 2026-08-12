"""应用设置：KV 存取（供各业务模块使用）与项目级配置写入。"""
import json

from ..utils.resource_loader import resources
from .model import SettingRecord


def get_setting(key: str, fallback=None):
    with resources.db_session() as s:
        row = s.get(SettingRecord, key)
        return json.loads(row.value) if row else fallback


def set_setting(key: str, value) -> None:
    with resources.db_session() as s:
        s.merge(SettingRecord(key=key, value=json.dumps(value)))
        s.commit()


def update_project_config(key: str, model, params, has_model: bool, has_params: bool) -> dict:
    """更新一个项目的模型/参数配置，返回更新后的条目。"""
    cfg = get_setting("projectConfig", {})
    entry = cfg.get(key) or {}
    if has_model:
        entry["model"] = model
    if has_params:
        entry["params"] = params
    cfg[key] = entry
    set_setting("projectConfig", cfg)
    return entry
