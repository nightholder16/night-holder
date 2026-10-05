"""Хранилище офферов (SQLite).

Оффер живёт 6 часов (OFFER_TTL_HOURS). Статусы:
  pending  — отправлен, ждёт ответа
  accepted — покупатель нажал «Принять»
  declined — покупатель нажал «Отклонить»
  expired  — время вышло
"""
import asyncio
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id           TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL,
    chat_id      INTEGER NOT NULL,
    connection_id TEXT,
    message_id   INTEGER,
    seller_id    INTEGER NOT NULL,
    seller_name  TEXT,
    seller_username TEXT,
    buyer_id     INTEGER,
    gift_link    TEXT NOT NULL,
    gift_name    TEXT NOT NULL,
    photo_path   TEXT,
    amount       TEXT NOT NULL,
    currency     TEXT NOT NULL,
    language     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   REAL NOT NULL,
    expires_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offers_chat ON offers (chat_id, status);
CREATE INDEX IF NOT EXISTS idx_offers_seller ON offers (seller_id, status);
"""

PHOTO_DIR = os.path.join(str(config.DATA_DIR), "photos")


@dataclass
class Offer:
    id: str
    order_id: str
    chat_id: int
    connection_id: Optional[str]
    message_id: Optional[int]
    seller_id: int
    seller_name: Optional[str]
    seller_username: Optional[str]
    buyer_id: Optional[int]
    gift_link: str
    gift_name: str
    photo_path: Optional[str]
    amount: str
    currency: str
    language: str
    status: str
    created_at: float
    expires_at: float

    def remaining_seconds(self) -> int:
        return max(0, int(self.expires_at - time.time()))


_connection: sqlite3.Connection | None = None
_lock = asyncio.Lock()


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        os.makedirs(PHOTO_DIR, exist_ok=True)
        _connection = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.executescript(_SCHEMA)
        _connection.commit()
    return _connection


def _init_sync() -> None:
    _get_connection()


async def init_db() -> None:
    await asyncio.to_thread(_init_sync)


def _row_to_offer(row: sqlite3.Row) -> Offer:
    return Offer(
        id=row["id"],
        order_id=row["order_id"],
        chat_id=row["chat_id"],
        connection_id=row["connection_id"],
        message_id=row["message_id"],
        seller_id=row["seller_id"],
        seller_name=row["seller_name"],
        seller_username=row["seller_username"],
        buyer_id=row["buyer_id"],
        gift_link=row["gift_link"],
        gift_name=row["gift_name"],
        photo_path=row["photo_path"],
        amount=row["amount"],
        currency=row["currency"],
        language=row["language"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def generate_order_id() -> str:
    """Идентификатор заказа вида TG-MI45UF42TG (как на скрине)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    tail = "".join(alphabet[uuid.uuid4().int % len(alphabet)] for _ in range(10))
    return f"TG-{tail}"


async def create_offer(**kwargs) -> Offer:
    def _insert() -> Offer:
        connection = _get_connection()
        now = time.time()
        offer = Offer(
            id=uuid.uuid4().hex[:12],
            order_id=kwargs.get("order_id") or generate_order_id(),
            chat_id=kwargs["chat_id"],
            connection_id=kwargs.get("connection_id"),
            message_id=kwargs.get("message_id"),
            seller_id=kwargs["seller_id"],
            seller_name=kwargs.get("seller_name"),
            seller_username=kwargs.get("seller_username"),
            buyer_id=None,
            gift_link=kwargs["gift_link"],
            gift_name=kwargs["gift_name"],
            photo_path=kwargs.get("photo_path"),
            amount=kwargs["amount"],
            currency=kwargs["currency"],
            language=kwargs.get("language") or config.DEFAULT_LANGUAGE,
            status="pending",
            created_at=now,
            expires_at=now + config.OFFER_TTL_HOURS * 3600,
        )
        connection.execute(
            """INSERT INTO offers (id, order_id, chat_id, connection_id, message_id, seller_id,
                                  seller_name, seller_username, buyer_id, gift_link, gift_name,
                                  photo_path, amount, currency, language, status, created_at,
                                  expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                offer.id, offer.order_id, offer.chat_id, offer.connection_id, offer.message_id,
                offer.seller_id, offer.seller_name, offer.seller_username, offer.buyer_id,
                offer.gift_link, offer.gift_name, offer.photo_path, offer.amount, offer.currency,
                offer.language, offer.status, offer.created_at, offer.expires_at,
            ),
        )
        connection.commit()
        return offer

    async with _lock:
        return await asyncio.to_thread(_insert)


async def get_offer(offer_id: str) -> Offer | None:
    def _select() -> Offer | None:
        row = _get_connection().execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        return _row_to_offer(row) if row else None

    async with _lock:
        return await asyncio.to_thread(_select)


async def update_offer(offer_id: str, **fields) -> Offer | None:
    def _update() -> Offer | None:
        connection = _get_connection()
        if not fields:
            row = connection.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
            return _row_to_offer(row) if row else None
        assignments = ", ".join(f"{key} = ?" for key in fields)
        connection.execute(
            f"UPDATE offers SET {assignments} WHERE id = ?",
            (*fields.values(), offer_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        return _row_to_offer(row) if row else None

    async with _lock:
        return await asyncio.to_thread(_update)


async def try_claim_offer(offer_id: str, buyer_id: int) -> tuple[Offer | None, str]:
    """Атомарно резервирует оффер за покупателем.

    Возвращает (offer, reason), где reason:
      'ok' | 'not_found' | 'already_used' | 'expired'
    """
    def _claim() -> tuple[Offer | None, str]:
        connection = _get_connection()
        row = connection.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if not row:
            return None, "not_found"

        offer = _row_to_offer(row)
        if offer.status != "pending":
            return offer, "already_used"
        if offer.expires_at <= time.time():
            connection.execute("UPDATE offers SET status = 'expired' WHERE id = ?", (offer_id,))
            connection.commit()
            return offer, "expired"

        connection.execute(
            "UPDATE offers SET status = 'accepted', buyer_id = ? WHERE id = ? AND status = 'pending'",
            (buyer_id, offer_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        return _row_to_offer(updated), "ok"

    async with _lock:
        return await asyncio.to_thread(_claim)


async def expire_stale_offers() -> int:
    """Помечает просроченные офферы (вызывается лениво, без фоновых задач)."""
    def _expire() -> int:
        connection = _get_connection()
        now = time.time()
        cursor = connection.execute(
            "UPDATE offers SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?",
            (now,),
        )
        connection.commit()
        return cursor.rowcount or 0

    async with _lock:
        return await asyncio.to_thread(_expire)


async def list_offers(chat_id: int | None = None, seller_id: int | None = None,
                      status: str | None = "pending", limit: int = 20) -> list[Offer]:
    def _list() -> list[Offer]:
        query = "SELECT * FROM offers WHERE 1=1"
        params: list = []
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(chat_id)
        if seller_id is not None:
            query += " AND seller_id = ?"
            params.append(seller_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = _get_connection().execute(query, params).fetchall()
        return [_row_to_offer(row) for row in rows]

    async with _lock:
        return await asyncio.to_thread(_list)
