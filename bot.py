"""Бот офферов подарков Telegram (подключается как бизнес-аккаунт).

Команда:
    .buy <ссылка на подарок> <цена> <gram|stars> <en|ar|кit>

Оффер уходит в тот же чат, откуда пришла команда (скрин 1).
После нажатия «Принять» покупателю в личку приходит инструкция «Сделка с NFT»
со скрином 3 и двумя кнопками:
    🎁 Передать NFT      -> tg://send_gift?to=<username продавца>
    ✅ Подтвердить передачу -> кнопка-заглушка (ничего не делает)
"""
import asyncio
import html
import io
import logging
import os
import re
import time
import types
import urllib.parse
from html.parser import HTMLParser
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    BusinessConnectionHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import gifts
import storage
from texts import (
    DEFAULT_LANGUAGE,
    is_language_token,
    normalize_currency,
    normalize_language,
    t,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("offers.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("offers")

# Версия кода — меняется при каждом обновлении, чтобы видеть, запущен ли свежий бот
BUILD = "2026-10-04 23:20"

# Типы апдейтов, которые нужны боту (в т.ч. бизнес-сообщения)
UPDATE_TYPES = [
    "message",
    "edited_message",
    "channel_post",
    "business_message",
    "edited_business_message",
    "business_connection",
    "callback_query",
]

# connection_id по чату бизнес-аккаунта и по его владельцу
CHAT_CONNECTION: dict[int, str] = {}
OWNER_CONNECTION: dict[int, str] = {}

# фоновые задачи (удаление команды), чтобы сборщик мусора их не убил
_BACKGROUND_TASKS: set[asyncio.Task] = set()

# Бот запоминает всех, от кого получал сообщения: Telegram не умеет искать
# обычного пользователя по @username (только группы и каналы), поэтому ведём
# свою память username -> user_id.
USERNAME_TO_ID: dict[str, int] = {}
ID_TO_USERNAME: dict[int, str] = {}


def remember_user(user) -> None:
    """Запоминает пользователя, чтобы его можно было указать в .buy по @username."""
    if user is None:
        return
    user_id = getattr(user, "id", None)
    username = getattr(user, "username", None)
    if not user_id:
        return
    if username:
        USERNAME_TO_ID["@" + username.lower()] = user_id
        ID_TO_USERNAME[user_id] = username
        logger.debug("Запомнил пользователя @%s (id=%s)", username, user_id)

CONFIRM_DELETE_AFTER = 6  # резерв: служебные сообщения больше не отправляются


# --- Вспомогательные функции ------------------------------------------------

def business_connection_id(message) -> Optional[str]:
    """Достаёт business_connection_id из сообщения/апдейта."""
    if not config.USE_BUSINESS_CONNECTION or message is None:
        return None
    direct = getattr(message, "business_connection_id", None)
    if direct:
        return direct
    chat = getattr(message, "chat", None)
    if chat is not None:
        return CHAT_CONNECTION.get(chat.id)
    return None


def format_remaining(seconds: int, language: str) -> str:
    """«6 ч. 0 мин.» / «6h 0m» — по языку оффера."""
    hours, minutes = divmod(max(0, seconds) // 60, 60)
    if language == "en":
        return f"{hours}h {minutes}m"
    if language == "ar":
        return f"{hours} س {minutes} د"
    if language == "kit":
        return f"{hours} 小时 {minutes} 分"
    return f"{hours} ч. {minutes} мин."


def format_clock(moment: Optional[float] = None) -> str:
    """Время отправки оффера — «22:38»."""
    return time.strftime("%H:%M", time.localtime(moment if moment is not None else time.time()))


def is_link(token: str) -> bool:
    return bool(token) and ("." in token or token.startswith("tg://")) and len(token) > 4


def parse_target(token: Optional[str]) -> Optional[str]:
    """Достаёт получателя оффера: @username или ссылка на профиль t.me/<username>.

    Ссылка на подарок (t.me/nft/..., t.me/канал/123) получателем НЕ считается.
    Числовые значения не принимаются — иначе цену можно спутать с id.
    None — отправляем в тот же чат, откуда пришла команда.
    """
    if not token:
        return None
    value = token.strip()
    if value.startswith("@") and len(value) > 1 and not value[1:].isdigit():
        return value
    if value.lower().startswith(("t.me/", "https://t.me/", "http://t.me/")):
        normalized = value if "://" in value else "https://" + value
        parts = [p for p in urllib.parse.urlsplit(normalized).path.split("/") if p]
        if len(parts) != 1:
            return None  # это ссылка на подарок/пост, а не на профиль
        first = parts[0]
        if first.isdigit() or first.lower() in gifts._ITEM_PATH_PREFIXES:
            return None
        return "@" + first
    return None


async def resolve_target_chat(context: ContextTypes.DEFAULT_TYPE, target: str):
    """Находит чат получателя.

    Порядок:
      1) числовой user id — работает всегда;
      2) @username из нашей памяти (бот запоминает всех, от кого получал сообщения);
      3) @username напрямую — Telegram это поддерживает только для групп и каналов,
         для обычного пользователя всегда отвечает «Chat not found».
    """
    value = target.strip()

    if value.lstrip("-").isdigit():
        try:
            chat = await context.bot.get_chat(int(value))
            logger.info("Получатель %s найден: chat_id=%s (%s)", value, chat.id, chat.type)
            return chat
        except TelegramError as exc:
            logger.warning("Не удалось найти получателя по id %s: %s", value, exc)
            return None

    username = value if value.startswith("@") else "@" + value
    key = username.lower()

    if key in USERNAME_TO_ID:
        user_id = USERNAME_TO_ID[key]
        logger.info("Получатель %s найден в памяти: chat_id=%s", username, user_id)
        try:
            return await context.bot.get_chat(user_id)
        except TelegramError:
            return types.SimpleNamespace(id=user_id, type="private", username=username[1:])

    try:
        chat = await context.bot.get_chat(username)
        logger.info("Получатель %s найден через Telegram: chat_id=%s (%s)", username, chat.id, chat.type)
        return chat
    except TelegramError as exc:
        logger.warning("Не удалось найти получателя %s: %s", username, exc)
        return None


def parse_buy_args(
    args: list[str],
) -> tuple[Optional[str], ...]:
    """Разбирает аргументы .buy.

    .buy [@кому] <ссылка> <цена> <gram|stars> [язык] [название] [ссылка на картинку]

    Если получатель указан — оффер уходит ему (команда остаётся в личке с ботом,
    покупатель её не видит). Если не указан — оффер уходит в текущий чат.
    """
    empty: tuple = (None, None, None, None, None, None, None)
    if not args:
        return empty

    # 1) получатель оффера ищем первым, иначе ссылка на профиль будет принята
    #    за ссылку на подарок. Принимаем @username, t.me/username и числовой id.
    target = next((item for item in args if parse_target(item)), None)
    rest = [item for item in args if item is not target]

    # числовой id получателя отличаем от цены: если чисел два, первое — получатель
    if target is None:
        numbers = [item for item in rest if item.lstrip("-").isdigit()]
        if len(numbers) >= 2:
            target = numbers[0]
            rest = [item for item in rest if item is not target]

    # 2) ссылка на подарок
    link_token = next((item for item in rest if is_link(item)), None)
    if not link_token:
        return empty
    rest = [item for item in rest if item is not link_token]

    amount = next((item for item in rest if item.replace(".", "", 1).isdigit()), None)
    if not amount:
        return empty
    rest = [item for item in rest if item is not amount]

    currency = normalize_currency(rest[0]) if rest else None
    if not currency:
        return empty

    if len(rest) > 1 and is_language_token(rest[1]):
        language = normalize_language(rest[1], config.DEFAULT_LANGUAGE or DEFAULT_LANGUAGE)
        tail = rest[2:]
    else:
        language = normalize_language(None, config.DEFAULT_LANGUAGE or DEFAULT_LANGUAGE)
        tail = rest[1:]

    # необязательная отдельная ссылка на картинку подарка
    image_hint = next((item for item in tail if gifts.is_direct_image(item)), None)
    if image_hint:
        tail = [item for item in tail if item is not image_hint]

    custom_name = " ".join(tail).strip() or None

    return (target, link_token, amount, currency, language, custom_name, image_hint)


class _TagBalanceChecker(HTMLParser):
    """Проверяет, что HTML-разметка закрыта (иначе Telegram ломает подчёркивание)."""

    VOID_TAGS = {"br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.broken = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.broken = True
        else:
            self.stack.pop()


def html_is_balanced(text: str) -> bool:
    checker = _TagBalanceChecker()
    try:
        checker.feed(text or "")
        checker.close()
    except Exception:  # noqa: BLE001
        return False
    return not checker.broken and not checker.stack


def strip_html(text: str) -> str:
    """Убирает теги — запасной вариант, если разметка не прошла проверку."""
    return re.sub(r"<[^>]+>", "", text or "")


async def send_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    business_id: Optional[str],
    *,
    text: Optional[str] = None,
    photo: Optional[bytes] = None,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    preview: bool = False,
    preview_above: bool = True,
) -> Optional[object]:
    """Отправляет сообщение в чат (с учётом бизнес-подключения).

    preview=True — не отключаем превью ссылок, чтобы Telegram сам нарисовал
    нативную карточку подарка (картинка + «ПОКАЗАТЬ ПОДАРОК»).
    preview_above=True — карточка подарка идёт СВЕРХУ, текст оффера под ней.
    """
    use_html = html_is_balanced(text)
    if not use_html:
        logger.warning("Разметка не сбалансирована, отправляю без HTML: %s", text)

    body = text if use_html else strip_html(text)
    common = {
        "parse_mode": ParseMode.HTML if use_html else None,
        "reply_markup": keyboard,
        "business_connection_id": business_id,
    }
    if preview:
        common["link_preview_options"] = LinkPreviewOptions(
            is_disabled=False,
            show_above_text=preview_above,
            prefer_large_media=True,
        )
    else:
        common["disable_web_page_preview"] = True

    try:
        if photo:
            # у send_photo нет параметра disable_web_page_preview
            return await context.bot.send_photo(
                chat_id=chat_id, photo=io.BytesIO(photo), caption=body, **common
            )
        return await context.bot.send_message(chat_id=chat_id, text=body, **common)
    except (Forbidden, BadRequest) as exc:
        logger.warning("Не удалось отправить в %s: %s", chat_id, exc)
        return None
    except TypeError as exc:
        # на всякий случай — повтор без необязательных параметров
        logger.warning("Ошибка параметров отправки (%s), повторяю упрощённо", exc)
        try:
            if photo:
                return await context.bot.send_photo(
                    chat_id=chat_id, photo=io.BytesIO(photo), caption=body,
                    reply_markup=keyboard, business_connection_id=business_id,
                )
            return await context.bot.send_message(
                chat_id=chat_id, text=body, reply_markup=keyboard,
                business_connection_id=business_id,
            )
        except TelegramError as retry_exc:
            logger.warning("Не удалось отправить даже упрощённо: %s", retry_exc)
            return None
    except TelegramError as exc:
        # последний шанс — отправить вообще без разметки
        logger.warning("Повторная отправка без HTML в %s: %s", chat_id, exc)
        try:
            plain = strip_html(text)
            if photo:
                return await context.bot.send_photo(
                    chat_id=chat_id, photo=io.BytesIO(photo), caption=plain,
                    reply_markup=keyboard, business_connection_id=business_id,
                )
            return await context.bot.send_message(
                chat_id=chat_id, text=plain, reply_markup=keyboard,
                business_connection_id=business_id,
            )
        except TelegramError as retry_exc:
            logger.warning("Не удалось отправить даже без разметки: %s", retry_exc)
            return None


# --- Подключение бизнес-аккаунта -------------------------------------------

async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запоминаем business_connection_id, когда бота подключили к бизнес-аккаунту."""
    connection = update.business_connection
    if connection is None:
        return
    CHAT_CONNECTION[connection.user_chat_id] = connection.id
    OWNER_CONNECTION[connection.user.id] = connection.id
    remember_user(connection.user)

    rights = getattr(connection, "rights", None)
    rights_text = "не заданы"
    if rights is not None:
        parts = []
        for field, label in (
            ("can_reply", "отвечать"),
            ("can_read_messages", "читать"),
            ("can_delete_sent_messages", "удалять свои (исходящие)"),
            ("can_delete_all_messages", "удалять все (входящие+исходящие)"),
            ("can_edit_name", "менять имя"),
        ):
            if getattr(rights, field, None):
                parts.append(label)
        rights_text = ", ".join(parts) if parts else "нет прав"
        if not getattr(rights, "can_delete_all_messages", None):
            rights_text += "  ← НЕТ права удалять входящие, команда .buy не удалится"

    logger.info(
        "Бизнес-подключение: id=%s, аккаунт=@%s, чат=%s, активно=%s, права: %s",
        connection.id,
        connection.user.username,
        connection.user_chat_id,
        connection.is_enabled,
        rights_text,
    )


# --- Команда .buy -----------------------------------------------------------

async def command_buy(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    link_token: str,
    amount: str,
    currency: str,
    language: str,
    custom_name: Optional[str] = None,
    image_hint: Optional[str] = None,
    target: Optional[str] = None,
) -> None:
    message = update.effective_message
    seller_chat = message.chat
    seller = message.from_user
    seller_connection = business_connection_id(message)

    # Если указан получатель (@username) — оффер уходит ему, а команда остаётся
    # в личке с ботом: покупатель её вообще не видит.
    chat_id = seller_chat.id
    business_id = seller_connection
    if target:
        resolved = await resolve_target_chat(context, target)
        if resolved is None:
            await send_to_chat(
                context,
                chat_id=seller_chat.id,
                business_id=seller_connection,
                text=t("ru", "target_not_found", target=html.escape(str(target))),
            )
            return
        chat_id = resolved.id
        business_id = CHAT_CONNECTION.get(chat_id)
    chat = types.SimpleNamespace(id=chat_id)

    # ленивая чистка просроченных офферов (фоновые задачи не нужны)
    try:
        await storage.expire_stale_offers()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Не удалось проверить сроки офферов: %s", exc)

    preview = await gifts.get_gift_preview(link_token, image_hint)
    link = html.escape(preview.link, quote=True)
    gift_name = html.escape(custom_name or preview.name)

    # В нативном режиме картинку не грузим — её нарисует сам Telegram по ссылке
    photo_bytes = None
    if not config.USE_NATIVE_PREVIEW and preview.image_url:
        photo_bytes = await gifts.download_photo(preview.image_url)

    photo_path = None
    if photo_bytes:
        photo_path = os.path.join(storage.PHOTO_DIR, f"{time.time_ns()}.jpg")
        try:
            with open(photo_path, "wb") as file:
                file.write(photo_bytes)
        except OSError as exc:
            logger.warning("Не удалось сохранить фото подарка: %s", exc)
            photo_path = None

    currency_label = t(language, f"currency_{currency}")
    remaining = config.OFFER_TTL_HOURS * 3600

    # --- Текстовый блок оффера + служебная строка + кнопки ---------------
    # Пользователь предлагает Вам 100 GRAM за подарок Vintage Cigar #23849.
    # Предложение действует ещё 6 ч. 0 мин.. 22:38
    # [❌ Отклонить][✅ Принять]
    #
    # Ссылка внутри текста заставляет Telegram нарисовать нативную карточку
    # подарка (изображение + «Telegram / название» + плашка ПОКАЗАТЬ ПОДАРОК).
    offer_text = t(
        language,
        "offer_text",
        amount=html.escape(amount),
        currency=currency_label,
        gift_link=link,
        gift_name=gift_name,
    )
    timer_text = t(
        language,
        "offer_timer",
        remaining=format_remaining(remaining, language),
        time=format_clock(),
    )
    offer_caption = offer_text + "\n\n" + timer_text

    offer = await storage.create_offer(
        chat_id=chat.id,
        connection_id=business_id,
        seller_id=seller.id,
        seller_name=seller.full_name,
        seller_username=seller.username,
        gift_link=preview.link,
        gift_name=gift_name,
        photo_path=photo_path,
        amount=amount,
        currency=currency,
        language=language,
    )

    # Кнопки ответа на оффер. Отдельной кнопки «ПОКАЗАТЬ ПОДАРОК» нет —
    # её рисует сама нативная карточка Telegram, а в тексте название подарка
    # уже является ссылкой на подарок.
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(language, "decline"), callback_data=f"ofc:decline:{offer.id}"),
            InlineKeyboardButton(t(language, "accept"), callback_data=f"ofc:accept:{offer.id}"),
        ],
    ])

    # Одно сообщение: текст оффера + таймер + нативная карточка подарка + кнопки
    sent = await send_to_chat(
        context,
        chat_id=chat.id,
        business_id=business_id,
        text=offer_caption,
        photo=photo_bytes,
        keyboard=keyboard,
        preview=config.USE_NATIVE_PREVIEW,
    )

    if sent is not None and getattr(sent, "message_id", None):
        await storage.update_offer(offer.id, message_id=sent.message_id)

    logger.info(
        "Оффер %s создан: чат=%s, продавец=@%s, %s %s, подарок=%s, язык=%s",
        offer.order_id,
        chat.id,
        seller.username or seller.id,
        amount,
        currency_label,
        gift_name,
        language,
    )

    # Подтверждение продавцу — приходит в его личку с ботом, покупатель его не видит
    if target:
        if sent is None:
            await send_to_chat(
                context,
                chat_id=seller_chat.id,
                business_id=seller_connection,
                text=t("ru", "target_no_access", target=html.escape(str(target))),
            )
        else:
            await send_to_chat(
                context,
                chat_id=seller_chat.id,
                business_id=seller_connection,
                text=t("ru", "sent_to_target", order_id=offer.order_id, target=html.escape(str(target))),
            )


# --- Реакция на кнопки -----------------------------------------------------

async def on_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    offer_id = query.data.split(":")[-1]
    language = "ru"

    offer, reason = await storage.try_claim_offer(offer_id, query.from_user.id)
    if offer is not None:
        language = offer.language

    if reason == "not_found":
        await query.answer(t(language, "not_found"), show_alert=True)
        return
    if reason == "already_used":
        await query.answer(t(language, "already_used"), show_alert=True)
        return
    if reason == "expired":
        await query.answer(t(language, "expired"), show_alert=True)
        await _clear_offer_keyboard(context, query, offer, language)
        return

    # Telegram показывает своё предупреждение «Внимание! Следуйте инструкциям…»
    # как всплывающее окно с кнопкой ОК — закрывается кнопкой ОК или нажатием
    # вне окна. show_alert=True — именно такой вид, а не всплывашка «тост».
    await query.answer(t(language, "warning"), show_alert=True)
    logger.info(
        "Нажата кнопка ПРИНЯТЬ: оффер=%s, чат=%s, покупатель=@%s (id=%s)",
        offer.order_id,
        offer.chat_id,
        query.from_user.username or "-",
        query.from_user.id,
    )

    instruction_text, card_text, keyboard = build_instruction(offer)
    connection_id = getattr(query.message, "business_connection_id", None) or offer.connection_id
    chat_id = offer.chat_id or getattr(
        getattr(query.message, "chat", None), "id", None
    )

    # Сообщение с оффером превращается в сделку: карточка подарка сверху,
    # текст с инструкцией снизу, кнопки «Передать подарок» / «Подтвердить передачу»
    edited = await _replace_offer_with_instruction(
        context, query, instruction_text, keyboard, connection_id
    )
    logger.info("Оффер переписан на сделку: %s", edited)

    if not edited and chat_id is not None:
        # не смогли переписать сообщение — отправляем инструкцию отдельным сообщением
        await send_to_chat(
            context,
            chat_id=chat_id,
            business_id=connection_id,
            text=instruction_text,
            keyboard=keyboard,
            preview=config.USE_NATIVE_PREVIEW,
        )

    await _log_deal(context, offer, query.from_user, instruction_text)

    logger.info(
        "Оффер %s принят покупателем @%s (id=%s)",
        offer.order_id,
        query.from_user.username or "-",
        query.from_user.id,
    )


async def _replace_offer_with_instruction(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup],
    connection_id,
) -> bool:
    """Меняет сообщение с оффером на сделку (в том же чате): текст + карточка + кнопки."""
    message = getattr(query, "message", None)
    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        logger.warning("Нет данных для редактирования сообщения оффера")
        return False

    # у Bot API параметр подписи называется caption, а не text
    preview = LinkPreviewOptions(
        is_disabled=False, show_above_text=True, prefer_large_media=True
    ) if config.USE_NATIVE_PREVIEW else None

    try:
        # у edit_message_caption параметра превью нет
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            business_connection_id=connection_id,
        )
        return True
    except (TelegramError, TypeError) as caption_error:
        logger.info("Подпись не переписалась (%s), пробую текст", caption_error)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options=preview,
            business_connection_id=connection_id,
        )
        return True
    except (TelegramError, TypeError) as exc:
        logger.warning("Не удалось заменить оффер на инструкцию: %s", exc)
        return False


async def on_decline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    offer_id = query.data.split(":")[-1]

    offer = await storage.get_offer(offer_id)
    language = offer.language if offer else "ru"
    if offer and offer.status == "pending":
        await storage.update_offer(offer_id, status="declined")

    await query.answer(t(language, "declined_toast"))
    if offer:
        await _clear_offer_keyboard(context, query, offer, language)
    logger.info("Оффер %s отклонён", offer.order_id if offer else offer_id)


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Подтвердить передачу» — заглушка, намеренно ничего не делает."""
    return


async def _clear_offer_keyboard(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    offer,
    language: str,
) -> None:
    """Убирает кнопки с сообщения оффера, чтобы его нельзя было принять повторно."""
    message = getattr(query, "message", None)
    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
            business_connection_id=getattr(message, "business_connection_id", None),
        )
    except (TelegramError, TypeError) as exc:
        logger.debug("Не удалось убрать кнопки: %s", exc)


def build_instruction(offer: storage.Offer) -> tuple[str, str, InlineKeyboardMarkup]:
    """Собирает сообщение после «Принять» (скрин 3).

    Возвращает:
      instruction_text — «Заказ #... / Покупатель зарезервировал ... / инструкция»
      card_text        — карточка подарка (Telegram + точное название)
      keyboard         — «ПОКАЗАТЬ ПОДАРОК», «Передать NFT ↗», «Подтвердить передачу»
    """
    language = offer.language
    seller_target = offer.seller_username or str(offer.seller_id)

    instruction_text = t(
        language,
        "instruction",
        order_id=offer.order_id,
        amount=html.escape(offer.amount),
        currency=t(language, f"currency_{offer.currency}"),
        currency_plain=t(language, f"currency_plain_{offer.currency}"),
        seller=html.escape(offer.seller_username or offer.seller_name or str(offer.seller_id)),
        seller_id=offer.seller_id,
        gift_link=offer.gift_link,
        gift_name=offer.gift_name,
        reserve=config.RESERVE_HOURS,
    )

    card_text = t(language, "gift_card", gift_name=offer.gift_name)

    # Только кнопки передачи: нативная карточка сама содержит «ПОКАЗАТЬ ПОДАРОК»
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                t(language, "btn_send_gift"),
                url=config.SEND_GIFT_LINK_TEMPLATE.format(target=seller_target),
            )
        ],
        [InlineKeyboardButton(t(language, "btn_confirm"), callback_data=f"noop:{offer.id}")],
    ])
    return instruction_text, card_text, keyboard


async def _load_photo(photo_path: Optional[str]) -> Optional[bytes]:
    if not photo_path:
        return None
    try:
        with open(photo_path, "rb") as file:
            return file.read()
    except OSError:
        return None


async def _log_deal(context, offer: storage.Offer, buyer, instruction_text: str) -> None:
    """Дублирует сделку в канал лога, если он задан в .env."""
    if not config.LOG_CHAT_ID:
        return
    text = (
        f"Сделка #{offer.order_id}\n"
        f"Продавец: @{html.escape(offer.seller_username or offer.seller_id)} | "
        f"Покупатель: @{html.escape(buyer.username or buyer.id)}\n\n"
        f"{instruction_text}"
    )
    try:
        await context.bot.send_message(
            chat_id=config.LOG_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=config.LOG_TOPIC_ID or None,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.warning("Не удалось записать сделку в лог: %s", exc)


# --- Прочие команды ---------------------------------------------------------

async def command_offers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    await storage.expire_stale_offers()
    offers = await storage.list_offers(
        chat_id=message.chat.id, seller_id=message.from_user.id, status="pending", limit=20
    )
    if not offers:
        await send_to_chat(
            context,
            chat_id=message.chat.id,
            business_id=business_connection_id(message),
            text=t("ru", "buy_usage"),
        )
        return

    lines = ["Активные офферы:"]
    for offer in offers:
        lines.append(
            f"• <code>{offer.order_id}</code> — {html.escape(offer.amount)} "
            f"{t(offer.language, f'currency_{offer.currency}')} — "
            f"{html.escape(offer.gift_name)} "
            f"({format_remaining(offer.remaining_seconds(), offer.language)})"
        )

    await send_to_chat(
        context,
        chat_id=message.chat.id,
        business_id=business_connection_id(message),
        text="\n".join(lines),
    )


async def command_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    await send_to_chat(
        context,
        chat_id=message.chat.id,
        business_id=business_connection_id(message),
        text=t("ru", "buy_usage"),
    )


async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единая точка входа для .buy, .offers, .help, .version и т.п.

    Команда .buy пишется в личку с ботом:
        .buy @покупатель <ссылка> <цена> <gram|stars> [язык] [название]
    Оффер уходит получателю, поэтому покупатель не видит ни команды, ни её текста.
    Без @покупателя оффер отправляется в тот же чат, где написана команда.
    """
    message = update.effective_message
    raw = (message.text or message.caption or "").strip()
    if not raw:
        return

    remember_user(message.from_user)

    head, _, tail = raw.partition(" ")
    command = head.lstrip("./").split("@")[0].lower()
    args = tail.split()

    # Сообщение с командой удаляем сразу и НЕ дожидаясь отправки оффера:
    # удаление идёт параллельно, поэтому сообщение исчезает мгновенно.
    connection_for_command = business_connection_id(message)
    if command in {"buy", "offers", "myoffers", "help", "start", "version", "dtest"}:
        task = asyncio.create_task(
            try_delete_command(context, message, connection_for_command)
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    if command == "buy":
        chat = getattr(message, "chat", None)
        logger.info(
            "Команда .buy: чат=%s, тип=%s, название=%r, подключение=%s, от=%s",
            getattr(chat, "id", None),
            getattr(chat, "type", None),
            getattr(chat, "title", None),
            business_connection_id(message) or "нет",
            getattr(message.from_user, "username", None),
        )
        target, link, amount, currency, language, custom_name, image_hint = parse_buy_args(args)
        if not link:
            await send_to_chat(
                context,
                chat_id=message.chat.id,
                business_id=business_connection_id(message),
                text=t("ru", "buy_error") + "\n\n" + t("ru", "buy_usage"),
            )
            return
        await command_buy(
            update, context, link, amount, currency, language,
            custom_name, image_hint, target=target,
        )
    elif command in {"offers", "myoffers"}:
        await command_offers(update, context)
    elif command in {"help", "start"}:
        await command_help(update, context)
    elif command == "buylist":
        if not ID_TO_USERNAME:
            text = (
                "Пока никого не знаю. Напишите боту /start — и получатель появится здесь."
            )
        else:
            lines = ["Известные получатели:"]
            for user_id, username in ID_TO_USERNAME.items():
                lines.append(f"• @{username} — <code>{user_id}</code>")
            text = "\n".join(lines)
        await send_to_chat(
            context,
            chat_id=message.chat.id,
            business_id=business_connection_id(message),
            text=text,
        )
    elif command == "dtest":
        await command_diag(update, context)
    elif command == "version":
        await send_to_chat(
            context,
            chat_id=message.chat.id,
            business_id=business_connection_id(message),
            text=f"Версия бота: <code>{BUILD}</code>",
        )


async def try_delete_command(
    context: ContextTypes.DEFAULT_TYPE, message, connection_id: Optional[str]
) -> bool:
    """Удаляет сообщение с командой .buy.

    Работает там, где у бота есть права: группы, супергруппы и чаты для двоих
    (администратор). В обычных личных чатах Telegram удалять чужие сообщения боту
    запрещает — тогда пишем об этом в лог.
    """
    if message is None:
        return False
    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return False

    chat_type = getattr(getattr(message, "chat", None), "type", "?")

    # 1) Бизнес-метод Telegram: deleteBusinessMessages — работает в бизнес-чатах
    if connection_id:
        try:
            await context.bot.delete_business_messages(
                business_connection_id=connection_id,
                message_ids=[message_id],
            )
            logger.info(
                "Команда удалена через deleteBusinessMessages (conn=%s, чат=%s, тип=%s, id=%s)",
                connection_id, chat_id, chat_type, message_id,
            )
            return True
        except (TelegramError, TypeError, AttributeError) as exc:
            logger.info("deleteBusinessMessages не сработал: %s", exc)

    attempts = [("deleteMessage", "one", None)]

    for label, kind, conn in attempts:
        api_kwargs = {"business_connection_id": conn} if conn else None
        try:
            if kind == "one":
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=message_id, api_kwargs=api_kwargs
                )
            else:
                await context.bot.delete_messages(
                    chat_id=chat_id, message_ids=[message_id], api_kwargs=api_kwargs
                )
            logger.info(
                "Команда удалена через %s (чат %s, тип %s, id %s)",
                label, chat_id, chat_type, message_id,
            )
            return True
        except TelegramError as exc:
            logger.info("Не удалось удалить команду через %s: %s", label, exc)

    logger.warning(
        "Команда осталась в чате %s (тип %s): бот не может удалять сообщения в этом чате. "
        "Нужен чат для двоих или группа, где бот администратор.",
        chat_id, chat_type,
    )
    return False


async def remember_any_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запоминает отправителя, чтобы его можно было указать получателем в .buy."""
    message = update.effective_message
    if message is not None:
        remember_user(message.from_user)


async def command_diag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Диагностика удаления по запросу: .dtest — пытается удалить сообщение с командой."""
    message = update.effective_message
    ok = await try_delete_command(context, message, business_connection_id(message))
    await send_to_chat(
        context,
        chat_id=message.chat.id,
        business_id=business_connection_id(message),
        text=f"Удаление команды: {'получилось' if ok else 'не вышло'} (детали в offers.log)",
    )


async def post_init(application: Application) -> None:
    await storage.init_db()
    me = await application.bot.get_me()
    logger.info("=" * 60)
    logger.info("БОТ ЗАПУЩЕН: @%s (%s), версия %s", me.username, me.full_name, BUILD)
    logger.info("=" * 60)


def build_application() -> Application:
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    command_filter = filters.TEXT & filters.Regex(r"^[./]")

    application.add_handler(BusinessConnectionHandler(on_business_connection))
    application.add_handler(
        MessageHandler(command_filter & ~filters.UpdateType.EDITED_MESSAGE, on_command)
    )
    # запоминаем всех, от кого приходят сообщения (чтобы искать по @username)
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.UpdateType.EDITED_MESSAGE, remember_any_user),
        group=1,
    )
    application.add_handler(
        CallbackQueryHandler(on_accept, pattern=r"^ofc:accept:")
    )
    application.add_handler(
        CallbackQueryHandler(on_decline, pattern=r"^ofc:decline:")
    )
    application.add_handler(
        CallbackQueryHandler(on_noop, pattern=r"^noop:")
    )

    return application


def main() -> None:
    application = build_application()
    logger.info("Запуск polling (бизнес-режим поддерживается)")
    application.run_polling(allowed_updates=UPDATE_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
