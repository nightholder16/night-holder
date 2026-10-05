"""Конфигурация бота офферов подарков Telegram.

Все настройки читаются из .env (рядом с проектом).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_env_file(path: Path | str = BASE_DIR / ".env") -> None:
    """Загружает .env в os.environ (существующие переменные не перезаписывает)."""
    file_path = Path(path)
    if not file_path.exists():
        return
    with open(file_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default


def _normalize_chat_id(raw_value: str | None, default: str | None = None) -> int:
    """-1001234 -> -1001234; 1234 -> -1001234; @username -> 0."""
    value = (raw_value if raw_value is not None else default) or ""
    value = value.strip()
    if not value:
        return 0
    if value.lstrip("-").isdigit():
        return int(value) if value.startswith("-") else int(f"-100{value}")
    return 0


# --- Бот -------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(item.strip())
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if item.strip().lstrip("-").isdigit()
}

# --- Логика офферов --------------------------------------------------------
# Сколько часов действует оффер (скрин 1: «действует ещё 6 ч. 0 мин.»)
OFFER_TTL_HOURS = _int("OFFER_TTL_HOURS", 6)
# Сколько часов держится резерв сделки (текст инструкции)
RESERVE_HOURS = _int("RESERVE_HOURS", 24)
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "ru").strip().lower() or "ru"

# --- Ссылки ----------------------------------------------------------------
# tg://send_gift?to=<username> — кнопка «Передать NFT»
SEND_GIFT_LINK_TEMPLATE = os.getenv(
    "SEND_GIFT_LINK_TEMPLATE", "tg://send_gift?to={target}"
).strip()

# --- Логи ------------------------------------------------------------------
# Необязательно: дублировать сообщение о сделке в канал/чат
LOG_CHAT_ID = _normalize_chat_id(os.getenv("LOG_CHAT_ID"))
LOG_TOPIC_ID = _int("LOG_TOPIC_ID", 0)

# --- Карточка подарка ------------------------------------------------------
# 1 (по умолчанию) — бот просто отправляет ссылку на подарок, и Telegram сам
#     рисует нативную превью-карточку: картинка подарка + «ПОКАЗАТЬ ПОДАРОК».
# 0 — бот сам скачивает картинку со страницы и отправляет фото (запасной вариант).
USE_NATIVE_PREVIEW = _flag("USE_NATIVE_PREVIEW", "1")

# --- Бизнес-режим ----------------------------------------------------------
# 1 (по умолчанию) — отправка от имени бизнес-аккаунта: работает предупреждение Telegram
#     при нажатии «Принять», но клиент подписывает сообщения именем бота
#     («SafeMod, 22:48») — это подпись клиента, Bot API её отключить не умеет.
# 0 — бот пишет как обычный бот: подписи нет, предупреждения тоже нет.
USE_BUSINESS_CONNECTION = _flag("USE_BUSINESS_CONNECTION", "1")

# --- Прочее ----------------------------------------------------------------
DB_PATH = str(DATA_DIR / "offers.db")
MAX_PHOTO_BYTES = _int("MAX_PHOTO_BYTES", 8 * 1024 * 1024)
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 15)
USER_AGENT = os.getenv(
    "USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
).strip()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Добавь токен в файл .env")
