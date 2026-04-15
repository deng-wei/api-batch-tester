"""
参数解析器模块。

负责将 YAML 中声明的灵活参数定义展开为具体的请求参数列表。
支持固定值、随机选取、文件扫描、文件内容读取等模式，
以及笛卡尔积、对齐、随机等组合策略。
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

from .config import ParamValue
from .utils import image_to_base64, video_to_base64

# ============================================================
# 文件类型判断
# ============================================================

# 支持的图片和视频后缀
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".jfif"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".avi", ".mov", ".mkv"}


def _is_image(path: Path) -> bool:
    """判断文件是否为图片。"""
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _is_video(path: Path) -> bool:
    """判断文件是否为视频。"""
    return path.suffix.lower() in _VIDEO_SUFFIXES


# ============================================================
# 单参数值解析
# ============================================================


def resolve_param_value(
    param: ParamValue,
    base_dir: Path | None = None,
) -> list[Any | tuple[Any, dict[str, Any]]]:
    """
    解析单个参数定义，返回所有可能的值列表。

    对于带有文件信息的参数（如 glob），会返回 (value, metadata) 元组列表。
    """
    base_dir = base_dir or Path(".")

    # --- 模式 1: 固定值 ---
    if param.value is not None:
        return [param.value]

    # --- 模式 2: 随机选取列表 ---
    if param.pick is not None:
        return list(param.pick)

    # --- 模式 3: 文件扫描 (glob) ---
    if param.glob is not None:
        pattern = param.glob
        # 支持绝对路径和相对路径
        if Path(pattern).is_absolute():
            matched = sorted(Path("/").glob(pattern.lstrip("/")))
        else:
            matched = sorted(base_dir.glob(pattern))

        if not matched:
            raise FileNotFoundError(f"Glob pattern '{pattern}' matched no files")

        results = []
        for p in matched:
            # 基础元数据：文件名（不含后缀）
            meta = {"filename": p.stem}

            val: Any = None
            if param.as_format == "base64":
                if _is_image(p):
                    val = image_to_base64(
                        p,
                        with_prefix=True,
                        image_encode=param.image_encode,
                        jpeg_quality=param.jpeg_quality,
                    )
                elif _is_video(p):
                    val = video_to_base64(p, with_prefix=True)
                else:
                    import base64 as b64mod

                    val = b64mod.b64encode(p.read_bytes()).decode("utf-8")
            elif param.as_format == "path":
                val = str(p.resolve())
            elif param.as_format == "filename":
                val = p.name

            results.append((val, meta))
        return results

    # --- 模式 4: 文件内容读取 ---
    if param.file is not None:
        file_path = base_dir / param.file
        if not file_path.exists():
            raise FileNotFoundError(f"Parameter file does not exist: {file_path}")

        content = file_path.read_text(encoding="utf-8")

        if param.split == "line":
            # 按行切分，去空行
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            return lines
        else:
            # 按指定分隔符切分
            parts = [p.strip() for p in content.split(param.split) if p.strip()]
            return parts

    # 不应到达此处（Pydantic 校验已保证）
    raise ValueError("Invalid parameter definition")


# ============================================================
# 任务列表构建
# ============================================================


def build_task_list(
    params: dict[str, ParamValue],
    combination: str,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """
    根据参数定义和组合策略生成任务列表。

    返回的任务字典中，API 所需参数正常存储，
    元数据（如文件名）存储在以 `_meta_` 开头的键中。
    """
    # 步骤 1: 解析所有参数的值列表
    resolved: dict[str, list[Any]] = {}
    for name, param in params.items():
        resolved[name] = resolve_param_value(param, base_dir)

    # 步骤 2: 规范化数据形式（分离 value 和 meta）
    values_only: dict[str, list[Any]] = {}
    metadata_map: dict[str, list[dict[str, Any] | None]] = {}

    for name, items in resolved.items():
        v_list = []
        m_list = []
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                v_list.append(item[0])
                m_list.append(item[1])
            else:
                v_list.append(item)
                m_list.append(None)
        values_only[name] = v_list
        metadata_map[name] = m_list

    # 区分单值参数和多值参数
    fixed_params: dict[str, Any] = {}
    variable_names: list[str] = []
    variable_values: list[list[Any]] = []

    for name, values in values_only.items():
        if len(values) == 1:
            fixed_params[name] = values[0]
            # 如果固定参数有元数据，也带上
            if metadata_map[name][0]:
                for m_k, m_v in metadata_map[name][0].items():
                    fixed_params[f"_meta_{name}_{m_k}"] = m_v
        else:
            variable_names.append(name)
            variable_values.append(values)

    # 辅助函数：根据索引列表构建单个任务字典
    def _create_task(indices: tuple[int, ...]) -> dict[str, Any]:
        task = dict(fixed_params)
        for i, name in enumerate(variable_names):
            idx = indices[i]
            val = variable_values[i][idx]
            task[name] = val
            # 注入元数据
            meta = metadata_map[name][idx]
            if meta:
                for m_k, m_v in meta.items():
                    task[f"_meta_{name}_{m_k}"] = m_v
        return task

    # 步骤 3: 根据策略组合索引
    tasks = []
    if not variable_names:
        return [dict(fixed_params)]

    if combination == "product":
        ranges = [range(len(vals)) for vals in variable_values]
        for combo_indices in itertools.product(*ranges):
            tasks.append(_create_task(combo_indices))

    elif combination == "zip":
        min_len = min(len(vals) for vals in variable_values)
        for idx in range(min_len):
            tasks.append(_create_task(tuple([idx] * len(variable_names))))

    elif combination == "random":
        pick_indices = [
            i for i, name in enumerate(variable_names) if params[name].pick is not None
        ]
        non_pick_indices = [
            i for i, name in enumerate(variable_names) if params[name].pick is None
        ]

        if not non_pick_indices:
            tasks.append(
                _create_task(
                    tuple(random.randrange(len(vals)) for vals in variable_values)
                )
            )
        else:
            ranges = [range(len(variable_values[i])) for i in non_pick_indices]
            for non_pick_combo in itertools.product(*ranges):
                indices = [0] * len(variable_names)
                for i, val_idx in zip(non_pick_indices, non_pick_combo):
                    indices[i] = val_idx
                for i in pick_indices:
                    indices[i] = random.randrange(len(variable_values[i]))
                tasks.append(_create_task(tuple(indices)))
    else:
        raise ValueError(f"Unsupported combination strategy: {combination}")

    return tasks
