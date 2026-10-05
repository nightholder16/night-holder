"""Разбор ссылки на подарок и получение превью (фото + название) с t.me.

Логика:
  * из ссылки достаётся название подарка (текст поста / og:title / путь ссылки);
  * из той же ссылки достаётся картинка подарка (og:image, фон виджета, <img>);
  * если превью с сервера не получилось, пробуем несколько вариантов адреса
    (пост во вьюхе t.me/s/..., embed-версия, сама ссылка).

Никаких внешних библиотек — только стандартная urllib.
"""
import asyncio
import html
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger(__name__)

# Кэш превью, чтобы не дёргать t.me повторно
_PREVIEW_CACHE: dict[str, "GiftPreview"] = {}

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

_META_IMAGE_PATTERNS = [
    r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\'](.*?)["\']',
    r'<meta[^>]+property=["\']og:image:url["\'][^>]+content=["\'](.*?)["\']',
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](.*?)["\']',
]
_WIDGET_PHOTO_RE = re.compile(
    r'tgme_widget_message_photo[^>]*style="[^"]*background-image:url\(\'?([^\'")]+)', re.IGNORECASE
)
_BACKGROUND_RE = re.compile(r"background-image:url\(['\"]?([^)'\"]+)", re.IGNORECASE)
_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL
)
_WIDGET_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL
)

_TAG_RE = re.compile(r"<[^>]+>")

# Названия, которые бесполезны как название подарка
_GENERIC_TITLES = {
    "telegram", "post", "channel", "tg", "you", "message", "gift", "gifts",
    "telegram messenger", "welcome", "telegram widget", "widget", "telegram web",
    "telegram for desktop", "open telegram", "telegram contact", "telegram channel",
}

# Префиксы пути, после которых идёт не канал, а сам подарок:
#   t.me/nft/AstralShard-3137 -> AstralShard 3137
_ITEM_PATH_PREFIXES = {
    "nft", "gift", "gifts", "collect", "collectible", "item", "share", "unique",
}

# Части URL, которые не являются картинкой подарка (аватары, иконки)
_NOT_GIF_MARKERS = ("/avatar/", "/_tg/", "emoji", "favicon", "apple-touch", "og-image")


@dataclass
class GiftPreview:
    """Результат разбора ссылки на подарок."""

    link: str                 # каноническая ссылка (https://t.me/...)
    name: str                 # «Vintage Cigar #23849»
    image_url: Optional[str]  # прямая ссылка на картинку
    ok: bool                  # удалось ли получить превью


# --- Нормализация ссылки ----------------------------------------------------

def normalize_link(raw: str) -> str:
    """Приводит любую ссылку (t.me / telegram.me / tg://) к https://t.me/... ."""
    value = html.unescape((raw or "").strip().strip("<>"))
    if not value:
        return ""

    if not value.lower().startswith(("tg://", "http://", "https://")):
        value = "https://" + value.lstrip("/")

    if value.lower().startswith("tg://"):
        # tg://resolve?domain=channel&post=123 -> https://t.me/channel/123
        parsed = urllib.parse.urlsplit(value)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        domain = params.get("domain") or params.get("channel") or ""
        post = params.get("post") or params.get("id") or ""
        value = "https://t.me/" + "/".join(part for part in (domain, post) if part)

    parsed = urllib.parse.urlsplit(value)
    netloc = parsed.netloc.lower()
    if netloc in ("telegram.me", "telegram.dog", "www.telegram.me"):
        netloc = "t.me"
    elif netloc.startswith("www."):
        netloc = netloc[4:]

    query = urllib.parse.urlencode(
        {k: v for k, v in urllib.parse.parse_qsl(parsed.query) if k not in ("embed", "single")}
    )
    path = parsed.path
    if path.startswith("/s/"):  # /s/channel/id -> /channel/id
        path = path[2:]
    return urllib.parse.urlunsplit(("https", netloc, path, query, ""))


def is_direct_image(link: str) -> bool:
    """Ссылка ведёт сразу на картинку (.jpg/.png/...)."""
    path = urllib.parse.urlsplit(link).path.lower()
    return path.endswith(_IMAGE_EXTENSIONS)


def extract_name_from_link(link: str) -> str:
    """Достаёт название подарка из пути ссылки (…/Swiss%20Watch%20%2321490)."""
    parsed = urllib.parse.urlsplit(link)
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        decoded = urllib.parse.unquote(part).strip()
        if not decoded or decoded.lstrip("-").isdigit():
            continue
        if decoded.lower() in ("s", "add", "gift", "gifts", "nft", "collectible", "share"):
            continue
        return html.unescape(decoded).replace("-", " ").strip()
    return "Gift"


def name_from_item_path(link: str) -> Optional[str]:
    """Название подарка, если ссылка указывает на сам подарок, а не на канал.

    t.me/nft/AstralShard-3137 -> «AstralShard 3137»
    t.me/channel/21490        -> None (21490 это id поста, название — из текста поста)
    """
    parsed = urllib.parse.urlsplit(link)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    last = parts[-1]
    if last.lstrip("-").isdigit():
        return None  # обычный пост в канале — имя берём из текста поста

    previous = parts[-2].lower() if len(parts) > 1 else ""
    if previous in _ITEM_PATH_PREFIXES:
        candidate = html.unescape(urllib.parse.unquote(last)).replace("-", " ").strip()
        if candidate and candidate.lower() not in _GENERIC_TITLES:
            return candidate

    return None


def preview_urls(link: str) -> list[str]:
    """Варианты адресов, с которых пробуем взять превью (по убыванию приоритета)."""
    parsed = urllib.parse.urlsplit(link)
    parts = [p for p in parsed.path.split("/") if p]
    base = urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    urls: list[str] = []

    if len(parts) >= 2 and parts[-1].lstrip("-").isdigit():
        channel, post_id = parts[-2], parts[-1]
        # публичная вьюха поста — там всегда есть картинка, если она в посте
        urls.append(f"https://t.me/s/{channel}/{post_id}")
        urls.append(f"https://t.me/{channel}/{post_id}?embed=1")
        urls.append(base)
    elif parts:
        urls.append(f"{base}?embed=1")
        urls.append(base)

    urls.append(link)

    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


# --- HTTP -------------------------------------------------------------------

def _http_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=config.REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="ignore")


def _clean_html_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _absolute(url: str, base: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urllib.parse.urlunsplit((*urllib.parse.urlsplit(base)[:2], url, "", "", ""))
    return url


def _pick_name(page: str) -> str:
    """Название подарка: текст поста → og:title → <title>."""
    widget = _WIDGET_TEXT_RE.search(page)
    if widget:
        text = _clean_html_text(widget.group(1))
        if text:
            return text.split("\n")[0].strip()

    for pattern in (_OG_TITLE_RE, _TITLE_TAG_RE):
        match = pattern.search(page)
        if match:
            title = _clean_html_text(match.group(1))
            if title and title.lower() not in _GENERIC_TITLES:
                return title.split("\n")[0].strip()

    return ""


def _pick_image(page: str, base: str) -> Optional[str]:
    """Картинка подарка: og:image → фон виджета → любой <img> (без аватаров)."""
    candidates: list[str] = []

    for pattern in _META_IMAGE_PATTERNS:
        match = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if match:
            candidates.append(match.group(1))

    match = _WIDGET_PHOTO_RE.search(page)
    if match:
        candidates.append(match.group(1))

    candidates.extend(_BACKGROUND_RE.findall(page))

    # обычные <img>: пропускаем аватары/иконки
    for src in _IMG_RE.findall(page):
        if not any(marker in src.lower() for marker in _NOT_GIF_MARKERS):
            candidates.append(src)

    for candidate in candidates:
        url = _absolute(html.unescape(candidate).strip(), base)
        if url.lower().split("?")[0].endswith(_IMAGE_EXTENSIONS) or "cdn" in url:
            return url

    return None


def _fetch_preview(link: str) -> GiftPreview:
    fallback_name = extract_name_from_link(link)
    # для ссылок вида t.me/nft/<slug> название берём из самого slug —
    # заголовок такой страницы у Telegram бесполезен («Telegram Widget»)
    path_name = name_from_item_path(link)

    scraped_name = ""
    image_url: Optional[str] = None

    for url in preview_urls(link):
        try:
            page = _http_get(url)
        except Exception as exc:  # noqa: BLE001 — превью не критично
            logger.debug("preview %s failed: %s", url, exc)
            continue

        if not scraped_name:
            scraped_name = _pick_name(page)
        if not image_url:
            image_url = _pick_image(page, url)
        if image_url and (scraped_name or path_name):
            break

    name = path_name or scraped_name or fallback_name

    return GiftPreview(link=link, name=name, image_url=image_url, ok=bool(image_url or name != "Gift"))


async def get_gift_preview(raw_link: str, image_hint: Optional[str] = None) -> GiftPreview:
    """Превью подарка. Если ссылка ведёт на картинку — используем её напрямую."""
    link = normalize_link(raw_link)
    if not link:
        return GiftPreview(link=raw_link.strip(), name="Gift", image_url=None, ok=False)

    if image_hint:
        return GiftPreview(link=link, name="Gift", image_url=normalize_link(image_hint), ok=True)

    if is_direct_image(link):
        return GiftPreview(link=link, name=extract_name_from_link(link), image_url=link, ok=True)

    if link in _PREVIEW_CACHE:
        return _PREVIEW_CACHE[link]

    try:
        preview = await asyncio.to_thread(_fetch_preview, link)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gift preview error for %s: %s", link, exc)
        preview = GiftPreview(link=link, name=extract_name_from_link(link), image_url=None, ok=False)

    _PREVIEW_CACHE[link] = preview
    return preview


async def download_photo(image_url: str) -> Optional[bytes]:
    """Скачивает картинку подарка (с проверкой размера). None — если не вышло."""
    if not image_url:
        return None

    def _download() -> Optional[bytes]:
        try:
            request = urllib.request.Request(image_url, headers={"User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(request, timeout=config.REQUEST_TIMEOUT) as response:
                data = response.read(config.MAX_PHOTO_BYTES + 1)
            if len(data) > config.MAX_PHOTO_BYTES:
                logger.info("gift photo is too big, skipping: %s", image_url)
                return None
            return data
        except Exception as exc:  # noqa: BLE001
            logger.info("gift photo download failed (%s): %s", image_url, exc)
            return None

    return await asyncio.to_thread(_download)
