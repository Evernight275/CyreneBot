# ----------------------------------------------------
# 此测试旨在测试能不能在真实情况跑通，不做强制要求
# ----------------------------------------------------
from __future__ import annotations

import asyncio
import os

import pytest
from dotenv import load_dotenv

from cyreneAI.core.errors.bot import BotError
from cyreneAI.infra.adapters.channels.telegram import TelegramBotClient


def _skip(reason: str) -> None:
    print(f"telegram bot real smoke skipped: {reason}")
    pytest.skip(reason)


def _real_token() -> str:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        _skip("TELEGRAM_BOT_TOKEN is required")
    return token


def _real_chat_id() -> str:
    load_dotenv()

    chat_id = os.getenv("TELEGRAM_BOT_CHAT_ID")
    if not chat_id:
        _skip("TELEGRAM_BOT_CHAT_ID is required")
    return chat_id


async def _run_real_get_me() -> None:
    client = TelegramBotClient(_real_token())
    try:
        result = await client.get_me()

        assert result["is_bot"] is True
        assert result.get("id") is not None

        print()
        print("telegram bot real getMe response:")
        print(f"  id: {result.get('id')}")
        print(f"  username: {result.get('username')}")
    except BotError as exc:
        _skip(f"configured Telegram Bot API rejected getMe: {exc}")
    finally:
        await client.close()


async def _run_real_send_message() -> None:
    client = TelegramBotClient(_real_token())
    try:
        result = await client.send_message(
            {
                "chat_id": _real_chat_id(),
                "text": "CyreneBot smoke test.",
            }
        )

        assert result.get("message_id") is not None

        print()
        print("telegram bot real sendMessage response:")
        print(f"  message_id: {result.get('message_id')}")
    except BotError as exc:
        _skip(f"configured Telegram Bot API rejected sendMessage: {exc}")
    finally:
        await client.close()


def test_telegram_bot_real_get_me() -> None:
    asyncio.run(_run_real_get_me())


def test_telegram_bot_real_send_message() -> None:
    asyncio.run(_run_real_send_message())
