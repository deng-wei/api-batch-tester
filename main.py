"""
API 批量测试工具 — CLI 入口。

用法:
    uv run python main.py <config.yaml>       # 执行批量测试
    uv run python main.py <config.yaml> --dry  # 仅预览任务列表，不实际发送请求
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.config import load_config
from src.param_resolver import build_task_list
from src.runner import BatchRunner
from src.utils import generate_task_id


def _setup_logging() -> None:
    """配置日志格式和级别。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _dry_run(config_path: Path) -> None:
    """
    预览模式：仅展示将要执行的任务列表，不实际发送请求。

    Args:
        config_path: 配置文件路径
    """
    config = load_config(config_path)
    config_dir = config_path.parent

    tasks = build_task_list(config.params, config.combination, base_dir=config_dir)

    # 计算含重复在内的总任务数
    repeat = config.repeat
    total = len(tasks) * repeat

    print(f"\n{'='*60}")
    print(f"  配置文件: {config_path}")
    print(f"  API 地址: {config.api.base_url}")
    print(f"  组合策略: {config.combination}")
    print(f"  并发数量: {config.api.concurrency}")
    print(f"  参数组数: {len(tasks)}")
    if repeat > 1:
        print(f"  每组重复: {repeat} 次")
    print(f"  任务总数: {total}")
    print(f"{'='*60}\n")

    # 展示前 10 个任务的参数摘要
    show_count = min(10, len(tasks))
    for i, params in enumerate(tasks[:show_count]):
        task_id = generate_task_id(params)
        print(f"  [{i + 1}] task_id={task_id}")
        for key, value in params.items():
            display = _truncate_display(value)
            print(f"      {key}: {display}")
        print()

    if len(tasks) > show_count:
        print(f"  ... 省略剩余 {len(tasks) - show_count} 个任务\n")


def _truncate_display(value: object, max_len: int = 80) -> str:
    """将过长的值截断为可读格式。"""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


async def _run(config_path: Path) -> None:
    """
    执行批量测试。

    Args:
        config_path: 配置文件路径
    """
    config = load_config(config_path)
    config_dir = config_path.parent

    runner = BatchRunner(config, config_dir=config_dir)
    summary = await runner.run()

    # 返回码：有失败则返回 1
    if summary.get("failed", 0) > 0:
        sys.exit(1)


def main() -> None:
    """CLI 入口。"""
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="API 批量测试工具 — 批量测试生图/生视频 API",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="预览模式：仅展示任务列表，不实际发送请求",
    )

    args = parser.parse_args()

    if not args.config.exists():
        print(f"错误: 配置文件不存在: {args.config}", file=sys.stderr)
        sys.exit(1)

    if args.dry:
        _dry_run(args.config)
    else:
        asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
