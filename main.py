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
    # 禁用来自 httpx 和 httpcore 的详细请求日志，以免干扰 tqdm 进度条
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
    print(f"  Config file: {config_path}")
    print(f"  API Base URL: {config.api.base_url}")
    print(f"  Combination: {config.combination}")
    print(f"  Concurrency: {config.api.concurrency}")
    print(f"  Parameter sets: {len(tasks)}")
    if repeat > 1:
        print(f"  Repeats per set: {repeat}")
    print(f"  Total tasks: {total}")
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
        print(f"  ... omitting {len(tasks) - show_count} remaining tasks\n")


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
        description="API Batch Tester - Batch test image/video generation APIs",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Dry run mode: preview tasks without sending requests",
    )

    args = parser.parse_args()

    if not args.config.exists():
        print(f"Error: Config file does not exist: {args.config}", file=sys.stderr)
        sys.exit(1)

    if args.dry:
        _dry_run(args.config)
    else:
        asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
