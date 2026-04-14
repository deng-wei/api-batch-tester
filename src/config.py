"""
配置模型定义模块。

使用 Pydantic 定义 YAML 配置文件的数据结构，提供类型校验和默认值。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# ============================================================
# 辅助函数
# ============================================================

def _load_env_file(config_path: Path) -> None:
    """
    加载 .env 文件中的环境变量。

    查找优先级：
      1. 配置文件所在目录的 .env
      2. 项目根目录（向上查找包含 pyproject.toml 的目录）的 .env
      3. dotenv 默认行为（从 cwd 向上查找）

    注意：override=False 保证已设置的系统环境变量不会被 .env 覆盖。
    """
    # 策略 1：配置文件同级 .env
    config_dir_env = config_path.parent / ".env"
    if config_dir_env.is_file():
        load_dotenv(config_dir_env, override=False)
        logger.info("已加载 .env 文件: %s", config_dir_env)
        return

    # 策略 2：向上查找项目根目录（含 pyproject.toml）的 .env
    current = config_path.parent.resolve()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").is_file():
            project_env = parent / ".env"
            if project_env.is_file():
                load_dotenv(project_env, override=False)
                logger.info("已加载 .env 文件: %s", project_env)
                return
            break  # 找到项目根但没有 .env，跳出

    # 策略 3：回退到 dotenv 默认查找
    found = load_dotenv(override=False)
    if found:
        logger.info("已通过 dotenv 默认查找加载 .env 文件")
    else:
        logger.debug("未找到 .env 文件，将仅使用系统环境变量")


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
    suffix: str = ".png"                    # 保存文件的后缀名 (仅在 filename 未指定时使用)
    filename: str | None = None             # 自定义文件名模板，支持 {param_name} 占位符


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

    # 在解析配置前加载 .env 文件，确保环境变量可用
    _load_env_file(config_path)

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件格式错误，期望字典结构: {config_path}")

    config = TaskConfig.model_validate(raw)

    # 解析 API 配置中的环境变量
    config.api.resolve()

    return config
