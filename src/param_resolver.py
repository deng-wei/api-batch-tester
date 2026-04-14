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
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
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
) -> list[Any]:
    """
    解析单个参数定义，返回所有可能的值列表。

    Args:
        param: 参数定义对象
        base_dir: 相对路径的基准目录（通常为配置文件所在目录）

    Returns:
        值列表。对于固定值返回单元素列表 [value]
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
            raise FileNotFoundError(f"glob 模式 '{pattern}' 未匹配到任何文件")

        # 根据 as_format 转换
        if param.as_format == "base64":
            values = []
            for p in matched:
                if _is_image(p):
                    values.append(image_to_base64(p, with_prefix=True))
                elif _is_video(p):
                    values.append(video_to_base64(p, with_prefix=True))
                else:
                    # 其他文件类型直接 base64 编码
                    import base64 as b64mod
                    raw = p.read_bytes()
                    values.append(b64mod.b64encode(raw).decode("utf-8"))
            return values
        elif param.as_format == "path":
            return [str(p.resolve()) for p in matched]
        elif param.as_format == "filename":
            return [p.name for p in matched]
        else:
            raise ValueError(f"不支持的 as_format: {param.as_format}")

    # --- 模式 4: 文件内容读取 ---
    if param.file is not None:
        file_path = base_dir / param.file
        if not file_path.exists():
            raise FileNotFoundError(f"参数文件不存在: {file_path}")

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
    raise ValueError("无效的参数定义")


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

    每个任务是一个字典，key 为参数名，value 为该任务的具体参数值。

    Args:
        params: 参数名 → ParamValue 定义的映射
        combination: 组合策略 ("product" / "zip" / "random")
        base_dir: 相对路径基准目录

    Returns:
        任务参数字典列表
    """
    # 步骤 1: 解析所有参数的值列表
    resolved: dict[str, list[Any]] = {}
    for name, param in params.items():
        resolved[name] = resolve_param_value(param, base_dir)

    # 区分单值参数（固定参数）和多值参数（需要组合的参数）
    fixed_params: dict[str, Any] = {}
    variable_names: list[str] = []
    variable_values: list[list[Any]] = []

    for name, values in resolved.items():
        if len(values) == 1:
            fixed_params[name] = values[0]
        else:
            variable_names.append(name)
            variable_values.append(values)

    # 步骤 2: 根据策略进行组合
    if not variable_names:
        # 所有参数都是固定值，只有一个任务
        return [dict(fixed_params)]

    if combination == "product":
        # 笛卡尔积
        combos = list(itertools.product(*variable_values))
    elif combination == "zip":
        # 对齐（按最短列表截断）
        combos = list(zip(*variable_values))
    elif combination == "random":
        # 找出最大的非 pick 参数列表长度，作为任务数
        # pick 类型的参数每次随机选一个
        # 非 pick 类型的参数做笛卡尔积

        pick_names: list[str] = []
        pick_values: list[list[Any]] = []
        non_pick_names: list[str] = []
        non_pick_values: list[list[Any]] = []

        for name, values in zip(variable_names, variable_values):
            param_def = params[name]
            if param_def.pick is not None:
                pick_names.append(name)
                pick_values.append(values)
            else:
                non_pick_names.append(name)
                non_pick_values.append(values)

        # 非 pick 参数做笛卡尔积
        if non_pick_values:
            base_combos = list(itertools.product(*non_pick_values))
        else:
            base_combos = [()]

        tasks = []
        for combo in base_combos:
            task = dict(fixed_params)
            # 填入非 pick 参数
            for name, val in zip(non_pick_names, combo):
                task[name] = val
            # pick 参数随机选一个
            for name, vals in zip(pick_names, pick_values):
                task[name] = random.choice(vals)
            tasks.append(task)
        return tasks
    else:
        raise ValueError(f"不支持的组合策略: {combination}")

    # 组装最终任务列表
    tasks = []
    for combo in combos:
        task = dict(fixed_params)
        for name, val in zip(variable_names, combo):
            task[name] = val
        tasks.append(task)

    return tasks
