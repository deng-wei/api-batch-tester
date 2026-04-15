"""
结果追踪模块。

使用 JSONL 格式记录每个任务的执行状态，支持断点续跑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ResultTracker:
    """
    任务结果追踪器。

    将每个任务的执行结果以 JSONL 格式追加写入日志文件，
    启动时加载已有日志以支持断点续跑。
    """

    def __init__(self, log_path: str | Path) -> None:
        """
        初始化结果追踪器。

        Args:
            log_path: JSONL 日志文件路径
        """
        self._log_path = Path(log_path)
        self._completed: dict[str, dict[str, Any]] = {}  # task_id → 记录
        self._stats = {"success": 0, "failed": 0, "skipped": 0}

        # 加载已有日志
        self._load_existing()

    def _load_existing(self) -> None:
        """从已有的 JSONL 文件加载历史记录。"""
        if not self._log_path.exists():
            return

        count = 0
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    task_id = record.get("task_id")
                    status = record.get("status")
                    if task_id and status == "success":
                        self._completed[task_id] = record
                        count += 1
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse log line {line_num}, skipped")

        if count > 0:
            logger.info(f"Loaded {count} completed records from log (resume mode supported)")

    def is_completed(self, task_id: str) -> bool:
        """
        检查指定任务是否已成功完成。

        Args:
            task_id: 任务 ID

        Returns:
            是否已完成
        """
        return task_id in self._completed

    def record(
        self,
        task_id: str,
        status: str,
        *,
        params: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        output_files: list[str] | None = None,
        elapsed: float = 0.0,
        error: str | None = None,
    ) -> None:
        """
        记录一条任务执行结果。

        Args:
            task_id: 任务 ID
            status: 执行状态 ("success" / "failed" / "skipped")
            params: 请求参数（不含超长 base64 内容）
            response: API 响应（可选）
            output_files: 输出文件路径列表
            elapsed: 耗时（秒）
            error: 错误信息（失败时）
        """
        record = {
            "task_id": task_id,
            "status": status,
            "elapsed": round(elapsed, 3),
        }

        if params is not None:
            # 截断过长的 base64 值，避免日志文件过大
            record["params"] = _truncate_params(params)
        if output_files:
            record["output_files"] = output_files
        if error:
            record["error"] = error

        # 更新统计
        if status in self._stats:
            self._stats[status] += 1

        # 追加写入日志
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 标记为已完成
        if status == "success":
            self._completed[task_id] = record

    def summary(self) -> dict[str, int]:
        """
        返回执行统计摘要。

        Returns:
            包含 success/failed/skipped 计数的字典
        """
        return dict(self._stats)


def _truncate_params(params: dict[str, Any], max_len: int = 100) -> dict[str, Any]:
    """
    截断参数字典中的超长字符串值（如 base64），避免日志过大。

    Args:
        params: 原始参数字典
        max_len: 字符串最大保留长度

    Returns:
        截断后的参数字典（原字典不会被修改）
    """
    truncated = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > max_len:
            truncated[key] = value[:50] + f"...<truncated {len(value)} chars>"
        elif isinstance(value, list):
            truncated[key] = [
                v[:50] + f"...<truncated {len(v)} chars>"
                if isinstance(v, str) and len(v) > max_len
                else v
                for v in value
            ]
        else:
            truncated[key] = value
    return truncated
