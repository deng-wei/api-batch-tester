"""
异步 HTTP 客户端模块。

基于 httpx 实现，支持自动重试、指数退避和可配置超时。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import APIConfig

logger = logging.getLogger(__name__)


class APIClient:
    """
    异步 HTTP 客户端。

    封装 httpx.AsyncClient，提供自动重试和指数退避功能。
    """

    # 遇到以下状态码时自动重试
    _RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, config: APIConfig) -> None:
        """
        初始化客户端。

        Args:
            config: API 连接配置
        """
        self._config = config

        # 构建默认请求头
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        # 合并额外请求头
        headers.update(config.headers)

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout),
            headers=headers,
            # 禁用代理以避免公司内网代理干扰
            proxy=None,
        )

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        发送单个 API 请求，带自动重试。

        Args:
            payload: 请求体 JSON 数据

        Returns:
            解析后的响应 JSON 字典

        Raises:
            httpx.HTTPStatusError: 请求失败且重试次数耗尽
            Exception: 其他网络错误
        """
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                if self._config.method == "POST":
                    resp = await self._client.post(
                        self._config.base_url,
                        json=payload,
                    )
                else:
                    resp = await self._client.get(
                        self._config.base_url,
                        params=payload,
                    )

                # 检查可重试的状态码
                if resp.status_code in self._RETRIABLE_STATUS_CODES:
                    wait_time = self._config.retry_backoff * (2 ** attempt)
                    logger.warning(
                        f"请求返回 {resp.status_code}，"
                        f"{wait_time:.1f}s 后重试 ({attempt + 1}/{self._config.max_retries + 1})"
                    )
                    last_error = httpx.HTTPStatusError(
                        message=f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 其他错误直接抛出
                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError:
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                # 网络级错误，可重试
                wait_time = self._config.retry_backoff * (2 ** attempt)
                logger.warning(
                    f"网络错误: {e}，"
                    f"{wait_time:.1f}s 后重试 ({attempt + 1}/{self._config.max_retries + 1})"
                )
                last_error = e
                await asyncio.sleep(wait_time)
                continue

        # 重试次数耗尽
        raise Exception(f"请求失败（重试 {self._config.max_retries} 次后）: {last_error}")

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self._client.aclose()

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
