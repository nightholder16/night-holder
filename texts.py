"""Тексты офферов на 4 языках: ru (по умолчанию), en, ar, kit (китайский).

Вёрстка повторяет нативный блок подарка Telegram:

    Telegram                     <- шапка блока
    Vintage Cigar #23849         <- название подарка
    ──────────────               <- разделитель
    ПОКАЗАТЬ ПОДАРОК             <- ссылка на подарок
                                 <- пустая строка
    Пользователь предлагает Вам
    100 GRAM за подарок Vintage Cigar #23849.
    Предложение действует ещё 6 ч. 0 мин.. · 22:35
    [ Отклонить ][ Принять ]

Ключи:
  gift_card    — карточка-превью подарка: источник + точное название
  show_gift    — текст закрашенной плашки «ПОКАЗАТЬ ПОДАРОК»
  offer_text   — текст предложения (название подарка — гиперссылка)
  offer_timer  — служебная строка с таймером и временем отправки
  instruction  — текст «Заказ #... / Покупатель зарезервировал ...»
"""

# Разделитель внутри блока подарка
DIVIDER = "────────────────"

TEXTS: dict[str, dict[str, str]] = {
    # ======================= Русский (по умолчанию) ========================
    "ru": {
        "currency_gram": "GRAM",
        "currency_stars": "STARS",
        "currency_plain_gram": "GRAM",
        "currency_plain_stars": "STARS",

        # карточка-превью: источник + точное название предмета
        "gift_card": "<b>Telegram</b>\n<b>{gift_name}</b>",
        # закрашенная плашка-ссылка под карточкой
        "show_gift": "ПОКАЗАТЬ ПОДАРОК",

        "offer_text": (
            "Пользователь предлагает Вам <b>{amount} {currency}</b> за подарок "
            "<a href=\"{gift_link}\">{gift_name}</a>."
        ),
        "offer_timer": "<b>Предложение действует ещё {remaining}.</b> {time}",
        "decline": "⊗ Отклонить",
        "accept": "✓ Принять",

        "instruction": (
            "<b>Сделка с NFT</b>\n\n"
            "Заказ #{order_id}\n\n"
            "<b>Покупатель зарезервировал {amount} {currency} через</b> гарантийную "
            "систему Telegram. Средства находятся на специальном счёте удержания и "
            "будут автоматически начислены на ваш баланс {currency_plain} в Telegram "
            "сразу после передачи подарка.\n\n"
            "<b>Инструкция для завершения сделки:</b>\n"
            "1. Передайте пользователю: <a href=\"tg://user?id={seller_id}\">@{seller}</a>\n"
            "2. Нажмите «Передать подарок» и выберите <a href=\"{gift_link}\">{gift_name}</a>\n"
            "3. Подтвердите передачу подарка.\n\n"
            "Система Telegram зафиксирует транзакцию и моментально зачислит "
            "<b>{amount} {currency}</b> на ваш баланс. Резерв действует {reserve} часа."
        ),
        "btn_send_gift": "Передать подарок",
        "btn_confirm": "✓ Подтвердить передачу",

        "buy_created": "Оффер #{order_id} создан.",
        "sent_to_target": "Оффер #{order_id} отправлен получателю {target}.",
        "target_no_access": (
            "Не смог отправить оффер получателю {target}: Telegram не даёт боту писать "
            "ему первым. Пусть покупатель один раз нажмёт Start в чате с ботом "
            "(@lgjdakgjads_bot) или подключит аккаунт как бизнес-бота: "
            "Настройки → Устройства → Подключить бота."
        ),
        "target_not_found": (
            "Не нашёл получателя {target}. Telegram ищет по @username только группы "
            "и каналы. Пусть покупатель напишет боту /start — потом он появится "
            "в .buylist, либо укажи числовой id."
        ),
        "buy_usage": (
            "<b>Формат:</b> <code>.buy @покупатель &lt;ссылка на подарок&gt; "
            "&lt;цена&gt; &lt;gram|stars&gt; &lt;en|ar|кit&gt;</code>\n"
            "<b>Пример:</b> <code>.buy @buyer https://t.me/nftchannel/21490 100 gram en</code>\n"
            "Команда пишется в личку с ботом — покупатель её не видит, оффер приходит "
            "ему от Telegram. Без @покупателя оффер уйдёт в тот же чат."
        ),
        "buy_error": "Не удалось разобрать команду. Формат: <code>.buy @покупатель ссылка цена валюта язык</code>",

        "expired": "⏳ Срок действия оффера истёк.",
        "declined": "Оффер отклонён.",
        "declined_toast": "Вы отклонили оффер.",
        "warning": (
            "Внимание!\n\nСледуйте инструкции, чтобы не потерять подарок и получить "
            "оплату.\n\nНажмите «ОК», если вы прочитали это сообщение."
        ),
        "accepted_toast": "Оффер принят ✅",
        "already_used": "Этот оффер уже обработан.",
        "not_found": "Оффер не найден.",
    },
    # ============================ English ===================================
    "en": {
        "currency_gram": "GRAM",
        "currency_stars": "STARS",
        "currency_plain_gram": "GRAM",
        "currency_plain_stars": "STARS",

        "gift_card": "<b>Telegram</b>\n<b>{gift_name}</b>",
        "show_gift": "VIEW GIFT",

        "offer_text": (
            "User offers you <b>{amount} {currency}</b> in exchange for the gift "
            "<a href=\"{gift_link}\">{gift_name}</a>."
        ),
        "offer_timer": "<b>Offer expires in {remaining}.</b> {time}",
        "decline": "⊗ Decline",
        "accept": "✓ Accept",

        "instruction": (
            "<b>NFT Deal</b>\n\n"
            "Order #{order_id}\n\n"
            "<b>The buyer has reserved {amount} {currency} through</b> the Telegram "
            "guarantee system. The funds are held in a dedicated escrow account and "
            "will be credited to your {currency_plain} balance in Telegram right after "
            "the gift is transferred.\n\n"
            "<b>Completion steps:</b>\n"
            "1. Transfer it to: <a href=\"tg://user?id={seller_id}\">@{seller}</a>\n"
            "2. Tap «Transfer gift» and select <a href=\"{gift_link}\">{gift_name}</a>\n"
            "3. Confirm the gift transfer.\n\n"
            "Telegram will record the transaction and instantly credit "
            "<b>{amount} {currency}</b> to your balance. The reservation is valid for "
            "{reserve} hours."
        ),
        "btn_send_gift": "Transfer gift",
        "btn_confirm": "✓ Confirm transfer",

        "buy_created": "Offer #{order_id} created.",
        "sent_to_target": "Offer #{order_id} sent to {target}.",
        "target_not_found": "Could not find {target}. Check the @username.",
        "buy_usage": (
            "<b>Format:</b> <code>.buy &lt;gift link&gt; &lt;price&gt; "
            "&lt;gram|stars&gt; &lt;en|ar|kit&gt;</code>\n"
            "<b>Example:</b> <code>.buy @buyer https://t.me/nftchannel/21490 100 gram</code>\n"
            "If the language is omitted — Russian. To set an exact gift name, add it at "
            "the end: <code>.buy link 100 gram en Vintage Cigar #23849</code>."
        ),
        "buy_error": "Could not parse the command. Format: <code>.buy link price currency language</code>",

        "expired": "⏳ This offer has expired.",
        "declined": "Offer declined.",
        "declined_toast": "You declined the offer.",
        "warning": (
            "Warning!\n\nFollow the instructions to avoid losing your gift and get "
            "paid.\n\nTap OK once you have read this message."
        ),
        "accepted_toast": "Offer accepted ✅",
        "already_used": "This offer has already been processed.",
        "not_found": "Offer not found.",
    },
    # ============================= العربية ===================================
    "ar": {
        "currency_gram": "GRAM",
        "currency_stars": "STARS",
        "currency_plain_gram": "GRAM",
        "currency_plain_stars": "STARS",

        "gift_card": "<b>Telegram</b>\n<b>{gift_name}</b>",
        "show_gift": "عرض الهدية",

        "offer_text": (
            "يعرض عليك مستخدم <b>{amount} {currency}</b> مقابل هدية "
            "<a href=\"{gift_link}\">{gift_name}</a>."
        ),
        "offer_timer": "<b>العرض صالح لمدة {remaining}.</b> {time}",
        "decline": "⊗ رفض",
        "accept": "✓ قبول",

        "instruction": (
            "<b>صفقة NFT</b>\n\n"
            "الطلب #{order_id}\n\n"
            "<b>قام المشتري بحجز {amount} {currency} عبر</b> نظام الضمان في تيليجرام. "
            "توجد الأموال في حساب ضمان مخصص وسيتم إيداعها تلقائيًا في رصيدك "
            "{currency_plain} في تيليجرام بعد تحويل الهدية مباشرة.\n\n"
            "<b>خطوات إتمام الصفقة:</b>\n"
            "1. حوّل الهدية إلى: <a href=\"tg://user?id={seller_id}\">@{seller}</a>\n"
            "2. اضغط «تحويل الهدية» واختر <a href=\"{gift_link}\">{gift_name}</a>\n"
            "3. أكّد تحويل الهدية.\n\n"
            "سيسجّل تيليجرام العملية ويودع <b>{amount} {currency}</b> في رصيدك فورًا. "
            "الحجز ساري لمدة {reserve} ساعة."
        ),
        "btn_send_gift": "تحويل الهدية",
        "btn_confirm": "✓ تأكيد التحويل",

        "buy_created": "تم إنشاء العرض #{order_id}.",
        "sent_to_target": "تم إرسال العرض #{order_id} إلى {target}.",
        "target_not_found": "لم يتم العثور على {target}. تحقق من @username.",
        "buy_usage": (
            "<b>الصيغة:</b> <code>.buy &lt;رابط الهدية&gt; &lt;السعر&gt; "
            "&lt;gram|stars&gt; &lt;en|ar|кit&gt;</code>\n"
            "<b>مثال:</b> <code>.buy @buyer https://t.me/nftchannel/21490 100 gram ar</code>\n"
            "إذا لم تحدد اللغة فسيتم استخدام العربية."
        ),
        "buy_error": "تعذر تحليل الأمر. الصيغة: <code>.buy رابط سعر عملة لغة</code>",

        "expired": "⏳ انتهت صلاحية العرض.",
        "declined": "تم رفض العرض.",
        "declined_toast": "لقد رفضت العرض.",
        "warning": (
            "تنبيه!\n\nاتبع التعليمات حتى لا تفقد هديتك وتحصل على الدفع.\n\nاضغط «موافق» بعد قراءتك هذه الرسالة."
        ),
        "accepted_toast": "تم قبول العرض ✅",
        "already_used": "تمت معالجة هذا العرض مسبقًا.",
        "not_found": "العرض غير موجود.",
    },
    # ============================ 简体中文 ===================================
    "kit": {
        "currency_gram": "GRAM",
        "currency_stars": "STARS",
        "currency_plain_gram": "GRAM",
        "currency_plain_stars": "STARS",

        "gift_card": "<b>Telegram</b>\n<b>{gift_name}</b>",
        "show_gift": "查看礼物",

        "offer_text": (
            "用户愿意用 <b>{amount} {currency}</b> 交换礼物 "
            "<a href=\"{gift_link}\">{gift_name}</a>。"
        ),
        "offer_timer": "<b>报价剩余时间 {remaining}。</b> {time}",
        "decline": "⊗ 拒绝",
        "accept": "✓ 接受",

        "instruction": (
            "<b>NFT 交易</b>\n\n"
            "订单 #{order_id}\n\n"
            "<b>买家已通过 Telegram 担保系统锁定 {amount} {currency}。</b>"
            "资金存放在专用担保账户中，礼物转出后将自动充值到您的 {currency_plain} 余额。\n\n"
            "<b>完成步骤：</b>\n"
            "1. 转交给：<a href=\"tg://user?id={seller_id}\">@{seller}</a>\n"
            "2. 点击「转赠礼物」并选择 <a href=\"{gift_link}\">{gift_name}</a>\n"
            "3. 确认礼物转赠。\n\n"
            "Telegram 会记录该交易并立即将 <b>{amount} {currency}</b> 充值到您的余额，"
            "锁定有效期 {reserve} 小时。"
        ),
        "btn_send_gift": "转赠礼物",
        "btn_confirm": "✓ 确认转赠",

        "buy_created": "报价 #{order_id} 已创建。",
        "sent_to_target": "报价 #{order_id} 已发送给 {target}。",
        "target_not_found": "找不到 {target}，请检查 @username。",
        "buy_usage": (
            "<b>格式：</b> <code>.buy &lt;礼物链接&gt; &lt;价格&gt; "
            "&lt;gram|stars&gt; &lt;en|ar|кit&gt;</code>\n"
            "<b>示例：</b> <code>.buy @buyer https://t.me/nftchannel/21490 100 gram kit</code>\n"
            "未指定语言时使用中文。"
        ),
        "buy_error": "无法解析命令。格式：<code>.buy 链接 价格 币种 语言</code>",

        "expired": "⏳ 报价已过期。",
        "declined": "报价已拒绝。",
        "declined_toast": "您已拒绝该报价。",
        "warning": (
            "注意！\n\n请按照说明操作，以免丢失礼物并完成收款。\n\n阅读后请点击「确定」。"
        ),
        "accepted_toast": "报价已接受 ✅",
        "already_used": "该报价已处理过。",
        "not_found": "未找到报价。",
    },
}

DEFAULT_LANGUAGE = "ru"

# Синонимы языков, которые принимаются в команде .buy
LANGUAGE_ALIASES: dict[str, str] = {
    "ru": "ru", "rus": "ru", "рус": "ru", "русский": "ru", "р": "ru",
    "en": "en", "eng": "en", "англ": "en", "английский": "en", "e": "en",
    "ar": "ar", "ара": "ar", "арабский": "ar", "arabic": "ar", "a": "ar",
    "kit": "kit", "cn": "kit", "zh": "kit", "zh-cn": "kit", "кит": "kit",
    "китайский": "kit", "中文": "kit",
}

# Синонимы валют
CURRENCY_ALIASES: dict[str, str] = {
    "gram": "gram", "grm": "gram", "g": "gram", "грам": "gram", "гр": "gram",
    "stars": "stars", "star": "stars", "s": "stars", "звезда": "stars",
    "звёзд": "stars", "звезд": "stars", "старс": "stars",
}


def normalize_language(raw: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    """'Кит' -> 'kit', 'en' -> 'en', '' -> язык по умолчанию."""
    if not raw:
        return default
    key = raw.strip().lower()
    if not key:
        return default
    return LANGUAGE_ALIASES.get(key, default)


def normalize_currency(raw: str | None) -> str | None:
    """'gram' -> 'gram', 'stars' -> 'stars', неизвестное -> None."""
    if not raw:
        return None
    return CURRENCY_ALIASES.get(raw.strip().lower())


def t(language: str, key: str, **kwargs) -> str:
    """Возвращает текст на нужном языке с подстановками {плейсхолдеров}."""
    lang = normalize_language(language)
    bundle = TEXTS.get(lang, TEXTS[DEFAULT_LANGUAGE])
    template = bundle.get(key) or TEXTS[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs)


def is_language_token(token: str) -> bool:
    """Понимает ли бот этот аргумент как язык (.buy ... en «Название»)."""
    return bool(token) and token.strip().lower() in LANGUAGE_ALIASES
