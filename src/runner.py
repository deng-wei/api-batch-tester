"""
批量测试执行引擎模块。

编排整个批量测试流程：参数展开 → 断点过滤 → 异步并发请求 → 结果提取 → 日志记录。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .api_client import APIClient
from .config import TaskConfig
from .param_resolver import build_task_list
from .result_tracker import ResultTracker
from .utils import (
    download_url,
    extract_field,
    generate_task_id,
    resolve_timestamp_template,
    save_base64_file,
)

logger = logging.getLogger(__name__)


class BatchRunner:
    """
    批量测试执行器。

    负责编排完整的批量测试流程，包括：
    1. 参数展开为任务列表
    2. 过滤已完成任务（断点续跑）
    3. 异步并发控制
    4. 输出文件提取与保存
    5. 结果记录与统计
    """

    def __init__(
        self,
        config: TaskConfig,
        config_dir: Path | None = None,
    ) -> None:
        """
        初始化执行器。

        Args:
            config: 已验证的任务配置
            config_dir: 配置文件所在目录，用于解析相对路径
        """
        self._config = config
        self._config_dir = config_dir or Path(".")

        # 解析输出路径中的时间戳
        self._output_dir = Path(
            resolve_timestamp_template(config.output.dir)
        )
        self._log_path = Path(
            resolve_timestamp_template(config.result_log)
        )

    async def run(self) -> dict[str, int]:
        """
        执行批量测试主流程。

        Returns:
            执行统计摘要字典 {"success": n, "failed": n, "skipped": n}
        """
        # ---- 步骤 1: 生成任务列表 ----
        logger.info("正在生成任务列表...")
        tasks = build_task_list(
            self._config.params,
            self._config.combination,
            base_dir=self._config_dir,
        )
        logger.info(f"共生成 {len(tasks)} 个任务")

        if not tasks:
            logger.warning("任务列表为空，无需执行")
            return {"success": 0, "failed": 0, "skipped": 0}

        # ---- 步骤 2: 初始化结果追踪器，过滤已完成任务 ----
        tracker = ResultTracker(self._log_path)

        # 为每个任务计算 ID 并过滤
        task_items: list[tuple[str, dict[str, Any]]] = []
        skipped = 0
        for params in tasks:
            task_id = generate_task_id(params)
            if tracker.is_completed(task_id):
                skipped += 1
                tracker.record(task_id, "skipped")
            else:
                task_items.append((task_id, params))

        if skipped > 0:
            logger.info(f"跳过 {skipped} 个已完成任务（断点续跑）")

        if not task_items:
            logger.info("所有任务均已完成，无需执行")
            return tracker.summary()

        logger.info(f"待执行任务: {len(task_items)} 个")

        # 创建输出目录
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # ---- 步骤 3: 异步并发执行 ----
        semaphore = asyncio.Semaphore(self._config.api.concurrency)
        progress = tqdm(total=len(task_items), desc="批量测试", unit="task")

        async with APIClient(self._config.api) as client:
            async def _run_single(task_id: str, params: dict[str, Any]) -> None:
                async with semaphore:
                    await self._execute_task(client, tracker, task_id, params)
                    progress.update(1)

            await asyncio.gather(
                *[_run_single(tid, p) for tid, p in task_items]
            )

        progress.close()

        # ---- 步骤 4: 打印统计摘要 ----
        summary = tracker.summary()
        logger.info(
            f"执行完毕 — 成功: {summary['success']}, "
            f"失败: {summary['failed']}, "
            f"跳过: {summary['skipped']}"
        )
        return summary

    async def _execute_task(
        self,
        client: APIClient,
        tracker: ResultTracker,
        task_id: str,
        params: dict[str, Any],
    ) -> None:
        """
        执行单个任务。

        Args:
            client: HTTP 客户端
            tracker: 结果追踪器
            task_id: 任务 ID
            params: 请求参数
        """
        start_time = time.monotonic()
        try:
            # 发送请求
            response = await client.send(params)
            elapsed = time.monotonic() - start_time

            # 保存完整响应 JSON（可选）
            output_files: list[str] = []
            if self._config.output.save_response:
                resp_path = self._output_dir / f"{task_id}_response.json"
                resp_path.write_text(
                    json.dumps(response, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                output_files.append(str(resp_path))

            # 根据提取规则保存输出文件
            for i, rule in enumerate(self._config.output.extract):
                try:
                    value = extract_field(response, rule.field)
                except (KeyError, IndexError, TypeError) as e:
                    logger.warning(
                        f"任务 {task_id}: 提取字段 '{rule.field}' 失败: {e}"
                    )
                    continue

                suffix = rule.suffix
                file_path = self._output_dir / f"{task_id}_{i}{suffix}"

                if rule.type == "base64_image" or rule.type == "base64_video":
                    save_base64_file(value, file_path)
                    output_files.append(str(file_path))
                elif rule.type == "url":
                    await download_url(value, file_path, client=client._client)
                    output_files.append(str(file_path))
                else:
                    logger.warning(f"未知的提取类型: {rule.type}")

            # 记录成功
            tracker.record(
                task_id,
                "success",
                params=params,
                output_files=output_files,
                elapsed=elapsed,
            )

        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error(f"任务 {task_id} 失败 ({elapsed:.1f}s): {e}")
            tracker.record(
                task_id,
                "failed",
                params=params,
                elapsed=elapsed,
                error=str(e),
            )
