"""
配置模型定义模块。

使用 Pydantic 定义 YAML 配置文件的数据结构，提供类型校验和默认值。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


# ============================================================
# 辅助函数
# ============================================================

def _resolve_env_vars(text: str) -> str:
    """解析字符串中的 ${ENV_VAR} 引用，替换为环境变量值。"""
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(f"环境变量 '{var_name}' 未设置")
        return value
    return re.sub(r"\$\{(\w+)}", _replacer, text)


# ============================================================
# 配置数据模型
# ============================================================

class APIConfig(BaseModel):
    """API 连接配置。"""
    base_url: str                                       # API 端点地址
    api_key: str = ""                                   # API Key，支持 ${ENV} 引用
    method: Literal["POST", "GET"] = "POST"             # HTTP 方法
    timeout: int = 300                                  # 单次请求超时（秒）
    max_retries: int = 3                                # 最大重试次数
    retry_backoff: float = 1.0                          # 退避因子
    concurrency: int = 5                                # 最大并发数
    headers: dict[str, str] = Field(default_factory=dict)  # 额外请求头

    def resolve(self) -> "APIConfig":
        """解析环境变量引用。"""
        self.api_key = _resolve_env_vars(self.api_key)
        self.base_url = _resolve_env_vars(self.base_url)
        # 解析 headers 中的环境变量
        self.headers = {k: _resolve_env_vars(v) for k, v in self.headers.items()}
        return self


class ParamValue(BaseModel):
    """
    灵活参数值定义。

    支持四种模式：
    - 固定值:    直接指定 value
    - 随机选一:  pick: ["a", "b", "c"]
    - 文件扫描:  glob: "inputs/*.png", as: "base64" | "path" | "filename"
    - 文件内容:  file: "prompts.txt", split: "line" | 指定分隔符
    """
    # 互斥字段 — 四种模式只能指定一种
    value: Any | None = None                # 固定值
    pick: list[Any] | None = None           # 随机选一
    glob: str | None = None                 # 文件扫描 glob 模式
    file: str | None = None                 # 读取文件内容

    # glob 模式的附加选项
    as_format: Literal["base64", "path", "filename"] = "base64"
    # file 模式的切分方式
    split: str = "line"

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any) -> Any:
        """将简写形式标准化为完整字典。"""
        # 简单标量值 → value 模式
        if not isinstance(data, dict):
            return {"value": data}
        # 将 YAML 中的 "as" 映射到 "as_format"（避免 Python 关键字冲突）
        if "as" in data:
            data["as_format"] = data.pop("as")
        return data

    @model_validator(mode="after")
    def _check_exclusive(self) -> "ParamValue":
        """校验互斥：四种模式只能指定一种。"""
        modes = [
            self.value is not None,
            self.pick is not None,
            self.glob is not None,
            self.file is not None,
        ]
        if sum(modes) != 1:
            raise ValueError(
                "参数定义必须且只能指定 value / pick / glob / file 中的一种"
            )
        return self


class OutputExtractRule(BaseModel):
    """从 API 响应中提取输出文件的规则。"""
    field: str                              # JSON 字段路径，如 "data[0].b64_json"
    type: Literal["base64_image", "base64_video", "url"]  # 数据类型
    suffix: str = ".png"                    # 保存文件的后缀名


class OutputConfig(BaseModel):
    """输出配置。"""
    dir: str = "outputs/{timestamp}"        # 输出目录模板
    save_response: bool = True              # 是否保存完整响应 JSON
    extract: list[OutputExtractRule] = Field(default_factory=list)


class TaskConfig(BaseModel):
    """顶层配置对象，对应一个完整的 YAML 配置文件。"""
    api: APIConfig
    params: dict[str, ParamValue]           # 请求参数定义
    combination: Literal["product", "zip", "random"] = "product"
    output: OutputConfig = Field(default_factory=OutputConfig)
    result_log: str = "outputs/{timestamp}/results.jsonl"

    @model_validator(mode="before")
    @classmethod
    def _normalize_params(cls, data: Any) -> Any:
        """将 params 中的原始值转换为 ParamValue 可接受的格式。"""
        if isinstance(data, dict) and "params" in data:
            raw_params = data["params"]
            if isinstance(raw_params, dict):
                normalized = {}
                for key, val in raw_params.items():
                    # ParamValue 的 model_validator 会处理标量 → {"value": ...}
                    normalized[key] = val
                data["params"] = normalized
        return data


# ============================================================
# 配置加载入口
# ============================================================

def load_config(config_path: str | Path) -> TaskConfig:
    """
    从 YAML 文件加载并验证配置。

    Args:
        config_path: 配置文件路径

    Returns:
        验证通过的 TaskConfig 实例
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件格式错误，期望字典结构: {config_path}")

    config = TaskConfig.model_validate(raw)

    # 解析 API 配置中的环境变量
    config.api.resolve()

    return config
