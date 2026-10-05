from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any


DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
TOKEN_FILE = DATA_DIR / "tiktok_tokens.json"

ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()


def token_storage_ready() -> bool:
    """
    Проверяет, настроено ли хранилище токенов.
    """

    return bool(ENCRYPTION_KEY)


def _get_key() -> bytes:
    """
    Преобразует TOKEN_ENCRYPTION_KEY в стабильный 32-байтовый ключ.
    """

    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY не задан."
        )

    return hashlib.sha256(
        ENCRYPTION_KEY.encode("utf-8")
    ).digest()


def _xor_crypt(data: bytes) -> bytes:
    """
    Простое обратимое шифрование для хранения токенов.

    Один и тот же метод используется для шифрования
    и расшифровки.
    """

    key = _get_key()

    result = bytearray(
        len(data)
    )

    for i, value in enumerate(data):
        result[i] = value ^ key[i % len(key)]

    return bytes(result)


def _encrypt(value: str) -> str:
    """
    Шифрует строку и возвращает base64.
    """

    encrypted = _xor_crypt(
        value.encode("utf-8")
    )

    return base64.urlsafe_b64encode(
        encrypted
    ).decode("ascii")


def _decrypt(value: str) -> str:
    """
    Расшифровывает base64-строку.
    """

    try:
        encrypted = base64.urlsafe_b64decode(
            value.encode("ascii")
        )

        decrypted = _xor_crypt(encrypted)

        return decrypted.decode("utf-8")

    except Exception as exc:
        raise RuntimeError(
            "Не удалось расшифровать сохранённые TikTok-токены."
        ) from exc


def _ensure_directory() -> None:
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def save_tokens(tokens: dict[str, Any]) -> None:
    """
    Сохраняет TikTok OAuth-токены в /data.
    """

    if not token_storage_ready():
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY не настроен."
        )

    if not isinstance(tokens, dict):
        raise TypeError(
            "tokens должен быть dict."
        )

    _ensure_directory()

    encrypted_tokens: dict[str, Any] = {}

    for key, value in tokens.items():

        if value is None:
            encrypted_tokens[key] = None

        elif isinstance(value, (str, int, float, bool)):
            encrypted_tokens[key] = {
                "encrypted": True,
                "value": _encrypt(str(value)),
                "type": type(value).__name__,
            }

        else:
            encrypted_tokens[key] = value

    temporary_file = TOKEN_FILE.with_suffix(
        ".tmp"
    )

    temporary_file.write_text(
        json.dumps(
            encrypted_tokens,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_file.replace(
        TOKEN_FILE
    )


def load_tokens() -> dict[str, Any] | None:
    """
    Загружает TikTok OAuth-токены.

    Возвращает None, если токены ещё не сохранены.
    """

    if not token_storage_ready():
        return None

    if not TOKEN_FILE.exists():
        return None

    try:
        raw = json.loads(
            TOKEN_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Не удалось прочитать файл TikTok-токенов."
        ) from exc

    if not isinstance(raw, dict):
        raise RuntimeError(
            "Файл TikTok-токенов имеет неправильный формат."
        )

    result: dict[str, Any] = {}

    for key, value in raw.items():

        if (
            isinstance(value, dict)
            and value.get("encrypted") is True
        ):
            decrypted = _decrypt(
                value["value"]
            )

            value_type = value.get(
                "type",
                "str",
            )

            if value_type == "int":
                result[key] = int(decrypted)

            elif value_type == "float":
                result[key] = float(decrypted)

            elif value_type == "bool":
                result[key] = decrypted.lower() == "true"

            else:
                result[key] = decrypted

        else:
            result[key] = value

    return result


def delete_tokens() -> None:
    """
    Удаляет сохранённые TikTok-токены.
    """

    try:
        TOKEN_FILE.unlink(
            missing_ok=True
        )
    except OSError as exc:
        raise RuntimeError(
            "Не удалось удалить TikTok-токены."
        ) from exc


def has_tokens() -> bool:
    """
    Проверяет наличие сохранённых токенов.
    """

    return load_tokens() is not None


def get_access_token() -> str | None:
    """
    Возвращает access_token.
    """

    tokens = load_tokens()

    if not tokens:
        return None

    token = tokens.get(
        "access_token"
    )

    if token is None:
        return None

    return str(token)


def get_refresh_token() -> str | None:
    """
    Возвращает refresh_token.
    """

    tokens = load_tokens()

    if not tokens:
        return None

    token = tokens.get(
        "refresh_token"
    )

    if token is None:
        return None

    return str(token)