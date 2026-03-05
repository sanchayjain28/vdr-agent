from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

LOGGER = logging.getLogger(__name__)

_bedrock_client = None


class ClaudeClientError(Exception):
    def __init__(self, message: str, original_exc: Exception | None = None) -> None:
        super().__init__(message)
        self.original_exc = original_exc


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        settings = get_settings()
        _bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=settings.aws_region,
            config=BotocoreConfig(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 0},
            ),
        )
    return _bedrock_client


async def invoke(prompt: str, system_prompt: Optional[str] = None) -> str:
    settings = get_settings()
    client = _get_bedrock_client()

    body: dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.bedrock_max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt is not None:
        body["system"] = system_prompt

    def _call() -> dict:
        resp = client.invoke_model(
            modelId=settings.bedrock_model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        return json.loads(resp["body"].read())

    try:
        response_body = await asyncio.to_thread(_call)
    except (ClientError, BotoCoreError) as exc:
        raise ClaudeClientError(f"Bedrock call failed: {exc}", exc) from exc

    stop_reason = response_body.get("stop_reason")
    if stop_reason != "end_turn":
        LOGGER.warning(
            "Bedrock response stop_reason=%r (expected 'end_turn') — response may be truncated",
            stop_reason,
        )

    return response_body["content"][0]["text"]
