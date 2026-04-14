"""
工具函数模块。

提供 base64 编解码、文件 I/O、JSON 字段提取等通用工具。
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


# ============================================================
# Base64 编解码
# ============================================================

def image_to_base64(path: str | Path, *, with_prefix: bool = True) -> str:
    """
    将图片文件编码为 base64 字符串。

    Args:
        path: 图片文件路径
        with_prefix: 是否添加 data URI 前缀

    Returns:
        base64 编码字符串
    """
    path = Path(path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    if with_prefix:
        # 根据后缀推断 MIME 类型
        suffix_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime = suffix_map.get(path.suffix.lower(), "image/png")
        return f"data:{mime};base64,{b64}"
    return b64


def video_to_base64(path: str | Path, *, with_prefix: bool = True) -> str:
    """
    将视频文件编码为 base64 字符串。

    Args:
        path: 视频文件路径
        with_prefix: 是否添加 data URI 前缀

    Returns:
        base64 编码字符串
    """
    path = Path(path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    if with_prefix:
        suffix_map = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
        }
        mime = suffix_map.get(path.suffix.lower(), "video/mp4")
        return f"data:{mime};base64,{b64}"
    return b64


def save_base64_file(b64_str: str, path: str | Path) -> Path:
    """
    将 base64 字符串解码后保存为文件。

    支持带 data URI 前缀和不带前缀的 base64 字符串。

    Args:
        b64_str: base64 编码字符串
        path: 保存路径

    Returns:
        保存后的文件路径
    """
    # 去除 data URI 前缀（如果有）
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64_str))
    return path


async def download_url(url: str, path: str | Path, *, client: httpx.AsyncClient | None = None) -> Path:
    """
    异步下载 URL 资源到本地文件。

    Args:
        url: 资源 URL
        path: 保存路径
        client: 可复用的 httpx 客户端

    Returns:
        保存后的文件路径
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=120)

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    finally:
        if should_close:
            await client.aclose()

    return path


# ============================================================
# JSON 字段提取
# ============================================================

def extract_field(data: Any, field_path: str) -> Any:
    """
    用点分路径从嵌套字典/列表中提取值。

    支持的路径格式示例：
    - "data[0].b64_json"  → data[0]["b64_json"]
    - "result.url"        → result["url"]
    - "items[2].name"     → items[2]["name"]

    Args:
        data: 嵌套字典/列表
        field_path: 点分路径表达式

    Returns:
        提取到的值

    Raises:
        KeyError: 路径不存在
        IndexError: 索引越界
    """
    # 将 "data[0].b64_json" 拆分为 ["data", "[0]", "b64_json"]
    tokens = re.split(r"\.|\[", field_path)
    current = data

    for token in tokens:
        if not token:
            continue
        # 处理数组索引 "0]"
        if token.endswith("]"):
            idx = int(token[:-1])
            current = current[idx]
        else:
            current = current[token]

    return current


# ============================================================
# 通用辅助
# ============================================================

def generate_task_id(params: dict[str, Any]) -> str:
    """
    根据请求参数生成稳定的任务 ID。

    使用参数内容的 MD5 哈希作为唯一标识，确保相同参数生成相同 ID，
    从而支持断点续跑的幂等性。

    Args:
        params: 请求参数字典

    Returns:
        16 位十六进制任务 ID
    """
    # 将参数序列化为稳定的字符串表示
    # 对于 base64 内容，只取前 64 字符避免哈希过慢
    def _truncate(v: Any) -> Any:
        if isinstance(v, str) and len(v) > 128:
            return v[:64] + "..." + v[-64:]
        if isinstance(v, dict):
            return {k: _truncate(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [_truncate(vv) for vv in v]
        return v

    content = str(sorted(_truncate(params).items()))
    return hashlib.md5(content.encode()).hexdigest()[:16]


def resolve_timestamp_template(template: str) -> str:
    """
    将模板字符串中的 {timestamp} 替换为当前时间戳。

    Args:
        template: 包含 {timestamp} 占位符的字符串

    Returns:
        替换后的字符串
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return template.replace("{timestamp}", ts)
