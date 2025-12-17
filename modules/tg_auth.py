from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Tuple

from telethon import TelegramClient
from telethon.errors import PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError


def _session_path_from_settings(settings: dict) -> str:
    session_path = (settings.get("telegram_session_path") or "secrets/telethon.session").strip()
    path = Path(session_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def _get_client(settings: dict) -> TelegramClient:
    api_id_raw = settings.get("telegram_api_id", "")
    api_hash = settings.get("telegram_api_hash", "")
    if not api_hash:
        raise ValueError("telegram_api_hash is required")
    try:
        api_id = int(api_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("telegram_api_id must be an integer") from exc

    session_path = _session_path_from_settings(settings)
    return TelegramClient(session_path, api_id, api_hash)


async def is_authorized(settings: dict) -> bool:
    client = await _get_client(settings)
    async with client:
        return await client.is_user_authorized()


async def send_login_code(settings: dict, phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("phone is required")

    client = await _get_client(settings)
    async with client:
        try:
            sent = await client.send_code_request(phone)
            return sent.phone_code_hash
        except PhoneNumberInvalidError as exc:
            raise ValueError("Invalid phone number") from exc


async def sign_in_with_code(settings: dict, phone: str, code: str, phone_code_hash: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (authorized, next_step) where next_step can be "password" for 2FA.
    """
    phone = (phone or "").strip()
    code = (code or "").strip()
    phone_code_hash = (phone_code_hash or "").strip()

    if not phone or not code or not phone_code_hash:
        raise ValueError("phone, code and phone_code_hash are required")

    client = await _get_client(settings)
    async with client:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            return True, None
        except PhoneCodeInvalidError as exc:
            raise ValueError("Invalid code") from exc
        except SessionPasswordNeededError:
            return False, "password"


async def sign_in_with_password(settings: dict, password: str) -> bool:
    password = (password or "").strip()
    if not password:
        raise ValueError("password is required")

    client = await _get_client(settings)
    async with client:
        await client.sign_in(password=password)
        return await client.is_user_authorized()


def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Async loop is running; call the async function directly.")

