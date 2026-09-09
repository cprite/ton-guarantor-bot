"""User-facing strings.

Two languages ship in the box; add a third by copying the ``en`` block and
translating the values. Keys missing from a locale fall back to English, so a
partial translation degrades gracefully instead of showing a traceback.
"""

from __future__ import annotations

DEFAULT_LOCALE = "en"

EN: dict[str, str] = {
    "menu": "<b>Escrow bot</b>\nPick what you want to do.",
    "btn_create": "Create a deal",
    "btn_join": "Join a deal",
    "btn_deals": "My deals",
    "btn_help": "How it works",
    "btn_back": "Back",
    "btn_cancel": "Cancel",
    "btn_accept": "Accept",
    "btn_decline": "Decline",
    "btn_received": "I received it",
    "btn_dispute": "Open a dispute",
    "btn_refresh": "Refresh",
    "btn_lang": "Language",
    "cancelled_input": "Cancelled.",
    "unknown": "I did not understand that. Use the menu below.",

    "join_ask_code": "Send the deal code you were given.",
    "choose_give": "What are <b>you</b> giving?",
    "choose_want": "What do you want <b>in return</b>?",
    "asset_ton": "TON",
    "asset_jetton": "Jetton",
    "asset_nft": "NFT",
    "asset_offchain": "Something else",

    "ask_ton_amount": "How much TON? For example <code>2.5</code>",
    "ask_jetton_master": "Send the jetton <b>master</b> address.",
    "ask_jetton_amount": "How much {symbol}? The jetton has {decimals} decimals.",
    "ask_nft_address": "Send the NFT <b>item</b> address.",
    "ask_offchain": (
        "Describe the item in your own words.\n\n"
        "⚠️ The escrow cannot verify anything off-chain. This leg is settled by "
        "you confirming that you received it, and by the operator if you disagree."
    ),

    "deal_created": (
        "✅ <b>Deal {code} created.</b>\n\n"
        "You give: {give}\n"
        "You get: {want}\n\n"
        "Send this to your counterparty:\n{link}\n\n"
        "Or have them enter the code <code>{code}</code>.\n"
        "Nobody has to fund anything until they accept. Unclaimed after {ttl}."
    ),
    "deal_terms": (
        "<b>Deal {code}</b>\n\n"
        "You give: {give}\n"
        "You get: {want}\n"
        "Service fee: {fee}\n\n"
        "Accept to start the escrow."
    ),
    "joined_notice": "👤 {who} joined deal <b>{code}</b> and is reviewing the terms.",
    "declined_notice": "❌ {who} declined deal <b>{code}</b>.",

    "need_payout_address": (
        "Your side of deal <b>{code}</b> is off-chain, so the escrow has no wallet "
        "to send your payout to.\n\nSend your TON address with:\n"
        "<code>/address {code} EQ...</code>"
    ),
    "address_saved": "Payout address for deal <b>{code}</b> saved.",

    "deposit_header": (
        "<b>Deal {code} — waiting for both sides.</b>\n"
        "Deadline: {deadline}\n\n{instructions}"
    ),
    "instr_ton": (
        "Send <b>{amount}</b> to\n<code>{address}</code>\n"
        "with the comment <code>{memo}</code>\n\n"
        "<a href=\"{link}\">Open in your wallet</a>"
    ),
    "instr_jetton": (
        "Send <b>{amount}</b> to\n<code>{address}</code>\n"
        "with the comment <code>{memo}</code>\n\n"
        "Use your wallet's jetton transfer and paste the comment — without it "
        "the escrow cannot tell which deal your tokens belong to."
    ),
    "instr_nft": (
        "Transfer the NFT\n<code>{nft}</code>\nto\n<code>{address}</code>\n"
        "with the comment <code>{memo}</code>"
    ),
    "instr_offchain": (
        "Hand <b>{what}</b> to your counterparty directly. "
        "They confirm receipt in this chat."
    ),
    "instr_surcharge": (
        "Also send <b>{amount}</b> to the same address with the same comment "
        "(service fee)."
    ),
    "instr_waiting_peer": "Your counterparty is sending: {what}",

    "deposit_credited": "💰 Deal <b>{code}</b>: received {amount} from {who}.",
    "side_funded": "✅ Deal <b>{code}</b>: {who} side is fully funded.",
    "deal_funded": "🔒 Deal <b>{code}</b>: both sides funded. Settling now.",
    "settling": "⏳ Deal <b>{code}</b>: payout broadcast, waiting for the network.",
    "completed": "🎉 <b>Deal {code} completed.</b>\nYou received: {received}\n{explorer}",
    "cancelled": "🚫 Deal <b>{code}</b> cancelled. {reason}",
    "expired": "⌛ Deal <b>{code}</b> expired. Anything deposited is being returned.",
    "refunding": "↩️ Deal <b>{code}</b>: refund broadcast.",
    "refunded": "↩️ Deal <b>{code}</b>: everything you deposited has been returned.",
    "disputed": (
        "⚠️ Deal <b>{code}</b> is disputed and frozen. "
        "The operator will look at it and release or refund the funds."
    ),
    "failed": (
        "🛑 Deal <b>{code}</b> could not be paid out automatically. "
        "Your funds are still held by the escrow and the operator has been alerted."
    ),

    "my_deals_empty": "You have no deals yet.",
    "my_deals": "<b>Your deals</b>\n\n{rows}",
    "deal_row": "<code>{code}</code> — {status} — {give} → {want}",

    "help": (
        "<b>How this escrow works</b>\n\n"
        "1. One side creates a deal and shares the code.\n"
        "2. The other side joins and accepts the terms.\n"
        "3. Both send their assets to the escrow wallet, each with its own comment.\n"
        "4. The bot verifies both deposits on-chain and swaps them in a single "
        "transaction.\n"
        "5. If the deadline passes, everything already deposited goes back to the "
        "wallet it came from.\n\n"
        "Escrow wallet:\n<code>{escrow}</code>\n{explorer}\n\n"
        "Network: <b>{network}</b>\nService fee: {fee}\n\n"
        "Commands: /start /deals /deal &lt;code&gt; /address &lt;code&gt; &lt;wallet&gt; "
        "/dispute &lt;code&gt; /cancel &lt;code&gt; /lang"
    ),
    "lang_prompt": "Choose a language.",
    "lang_set": "Language set to English.",

    "err_generic": "⚠️ {error}",
    "err_not_found": "No deal with that code.",
    "err_rate": "Slow down a little.",
    "err_offchain_disabled": "This operator does not accept off-chain items.",

    "admin_only": "That command is for the operator.",
    "admin_stats": (
        "<b>Operator dashboard</b>\n\n"
        "Escrow: <code>{escrow}</code>\nBalance: {balance}\nNetwork: {network}\n\n"
        "{rows}"
    ),
    "admin_deal": "<b>Deal {code}</b>\n<pre>{dump}</pre>",
    "admin_usage": (
        "Operator commands:\n"
        "/stats — balance and deal counts\n"
        "/inspect &lt;code&gt; — full state of one deal\n"
        "/release &lt;code&gt; — settle a deal normally\n"
        "/award &lt;code&gt; &lt;A|B&gt; — give everything to one side\n"
        "/refundeal &lt;code&gt; — return every deposit\n"
        "/payout &lt;address&gt; &lt;amount&gt; — send TON out of escrow by hand"
    ),
    "admin_done": "Done: {result}",
    "admin_alert": "🚨 <b>Operator alert</b>\n{error}",
    "admin_unmatched": (
        "🚨 <b>Unmatched transfer</b>\n"
        "{amount} from <code>{sender}</code>\n"
        "Comment: {comment}\nTx: <code>{tx}</code>\n\n"
        "Return it with /payout if it was a mistake."
    ),
    "admin_dispute": "⚠️ <b>Deal {code} disputed</b> by {who}.\nReason: {reason}",
}

RU: dict[str, str] = {
    "menu": "<b>Бот-гарант</b>\nВыберите действие.",
    "btn_create": "Создать сделку",
    "btn_join": "Войти в сделку",
    "btn_deals": "Мои сделки",
    "btn_help": "Как это работает",
    "btn_back": "Назад",
    "btn_cancel": "Отмена",
    "btn_accept": "Принять",
    "btn_decline": "Отклонить",
    "btn_received": "Я получил",
    "btn_dispute": "Открыть спор",
    "btn_refresh": "Обновить",
    "btn_lang": "Язык",
    "cancelled_input": "Отменено.",
    "unknown": "Не понял. Воспользуйтесь меню ниже.",

    "join_ask_code": "Пришлите код сделки, который вам дали.",
    "choose_give": "Что отдаёте <b>вы</b>?",
    "choose_want": "Что хотите <b>взамен</b>?",
    "asset_ton": "TON",
    "asset_jetton": "Джеттон",
    "asset_nft": "NFT",
    "asset_offchain": "Другое",

    "ask_ton_amount": "Сколько TON? Например <code>2.5</code>",
    "ask_jetton_master": "Пришлите адрес <b>мастер-контракта</b> джеттона.",
    "ask_jetton_amount": "Сколько {symbol}? У джеттона {decimals} знаков после запятой.",
    "ask_nft_address": "Пришлите адрес <b>NFT-предмета</b>.",
    "ask_offchain": (
        "Опишите предмет своими словами.\n\n"
        "⚠️ Вне блокчейна гарант ничего проверить не может. Эта сторона "
        "закрывается вашим подтверждением получения, а при разногласиях — оператором."
    ),

    "deal_created": (
        "✅ <b>Сделка {code} создана.</b>\n\n"
        "Вы отдаёте: {give}\n"
        "Вы получаете: {want}\n\n"
        "Отправьте партнёру:\n{link}\n\n"
        "Или пусть введёт код <code>{code}</code>.\n"
        "Пока он не примет условия, переводить ничего не нужно. Без партнёра сделка живёт {ttl}."
    ),
    "deal_terms": (
        "<b>Сделка {code}</b>\n\n"
        "Вы отдаёте: {give}\n"
        "Вы получаете: {want}\n"
        "Комиссия сервиса: {fee}\n\n"
        "Примите условия, чтобы запустить гаранта."
    ),
    "joined_notice": "👤 {who} вошёл в сделку <b>{code}</b> и смотрит условия.",
    "declined_notice": "❌ {who} отклонил сделку <b>{code}</b>.",

    "need_payout_address": (
        "Ваша сторона сделки <b>{code}</b> вне блокчейна, поэтому гаранту некуда "
        "отправить выплату.\n\nПришлите адрес кошелька:\n"
        "<code>/address {code} EQ...</code>"
    ),
    "address_saved": "Адрес для выплаты по сделке <b>{code}</b> сохранён.",

    "deposit_header": (
        "<b>Сделка {code} — ждём обе стороны.</b>\n"
        "Крайний срок: {deadline}\n\n{instructions}"
    ),
    "instr_ton": (
        "Отправьте <b>{amount}</b> на\n<code>{address}</code>\n"
        "с комментарием <code>{memo}</code>\n\n"
        "<a href=\"{link}\">Открыть в кошельке</a>"
    ),
    "instr_jetton": (
        "Отправьте <b>{amount}</b> на\n<code>{address}</code>\n"
        "с комментарием <code>{memo}</code>\n\n"
        "Используйте перевод джеттонов в кошельке и обязательно впишите "
        "комментарий — без него гарант не поймёт, к какой сделке относятся токены."
    ),
    "instr_nft": (
        "Переведите NFT\n<code>{nft}</code>\nна\n<code>{address}</code>\n"
        "с комментарием <code>{memo}</code>"
    ),
    "instr_offchain": (
        "Передайте <b>{what}</b> партнёру напрямую. "
        "Он подтвердит получение здесь, в чате."
    ),
    "instr_surcharge": (
        "Дополнительно отправьте <b>{amount}</b> на тот же адрес "
        "с тем же комментарием (комиссия сервиса)."
    ),
    "instr_waiting_peer": "Партнёр отправляет: {what}",

    "deposit_credited": "💰 Сделка <b>{code}</b>: получено {amount} от {who}.",
    "side_funded": "✅ Сделка <b>{code}</b>: сторона {who} полностью внесла своё.",
    "deal_funded": "🔒 Сделка <b>{code}</b>: обе стороны внесли. Провожу обмен.",
    "settling": "⏳ Сделка <b>{code}</b>: выплата отправлена, ждём сеть.",
    "completed": "🎉 <b>Сделка {code} завершена.</b>\nВы получили: {received}\n{explorer}",
    "cancelled": "🚫 Сделка <b>{code}</b> отменена. {reason}",
    "expired": "⌛ Сделка <b>{code}</b> просрочена. Всё внесённое возвращается.",
    "refunding": "↩️ Сделка <b>{code}</b>: возврат отправлен.",
    "refunded": "↩️ Сделка <b>{code}</b>: всё внесённое вам возвращено.",
    "disputed": (
        "⚠️ Сделка <b>{code}</b> заморожена из-за спора. "
        "Оператор разберётся и либо проведёт обмен, либо вернёт средства."
    ),
    "failed": (
        "🛑 Сделку <b>{code}</b> не удалось выплатить автоматически. "
        "Средства остаются у гаранта, оператор уведомлён."
    ),

    "my_deals_empty": "Сделок пока нет.",
    "my_deals": "<b>Ваши сделки</b>\n\n{rows}",
    "deal_row": "<code>{code}</code> — {status} — {give} → {want}",

    "help": (
        "<b>Как работает гарант</b>\n\n"
        "1. Одна сторона создаёт сделку и делится кодом.\n"
        "2. Вторая входит и принимает условия.\n"
        "3. Обе отправляют своё на кошелёк гаранта, каждая — со своим комментарием.\n"
        "4. Бот проверяет оба поступления в блокчейне и меняет их местами одной "
        "транзакцией.\n"
        "5. Если срок вышел — всё внесённое уходит обратно на те же кошельки.\n\n"
        "Кошелёк гаранта:\n<code>{escrow}</code>\n{explorer}\n\n"
        "Сеть: <b>{network}</b>\nКомиссия сервиса: {fee}\n\n"
        "Команды: /start /deals /deal &lt;код&gt; /address &lt;код&gt; &lt;кошелёк&gt; "
        "/dispute &lt;код&gt; /cancel &lt;код&gt; /lang"
    ),
    "lang_prompt": "Выберите язык.",
    "lang_set": "Язык переключён на русский.",

    "err_generic": "⚠️ {error}",
    "err_not_found": "Сделки с таким кодом нет.",
    "err_rate": "Помедленнее.",
    "err_offchain_disabled": "Этот оператор не принимает предметы вне блокчейна.",

    "admin_only": "Эта команда только для оператора.",
    "admin_stats": (
        "<b>Панель оператора</b>\n\n"
        "Гарант: <code>{escrow}</code>\nБаланс: {balance}\nСеть: {network}\n\n"
        "{rows}"
    ),
    "admin_deal": "<b>Сделка {code}</b>\n<pre>{dump}</pre>",
    "admin_usage": (
        "Команды оператора:\n"
        "/stats — баланс и счётчики сделок\n"
        "/inspect &lt;код&gt; — полное состояние сделки\n"
        "/release &lt;код&gt; — провести обмен как обычно\n"
        "/award &lt;код&gt; &lt;A|B&gt; — отдать всё одной стороне\n"
        "/refundeal &lt;код&gt; — вернуть все поступления\n"
        "/payout &lt;адрес&gt; &lt;сумма&gt; — отправить TON из гаранта вручную"
    ),
    "admin_done": "Готово: {result}",
    "admin_alert": "🚨 <b>Тревога оператора</b>\n{error}",
    "admin_unmatched": (
        "🚨 <b>Нераспознанный перевод</b>\n"
        "{amount} от <code>{sender}</code>\n"
        "Комментарий: {comment}\nTx: <code>{tx}</code>\n\n"
        "Верните через /payout, если это ошибка."
    ),
    "admin_dispute": "⚠️ <b>Спор по сделке {code}</b> от {who}.\nПричина: {reason}",
}

LOCALES: dict[str, dict[str, str]] = {"en": EN, "ru": RU}


def t(locale: str | None, key: str, **kwargs: object) -> str:
    """Render a string in ``locale``, falling back to English."""
    table = LOCALES.get((locale or DEFAULT_LOCALE).lower(), EN)
    template = table.get(key) or EN.get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def supported(locale: str | None) -> str:
    """Normalise a Telegram ``language_code`` to a locale we actually have."""
    code = (locale or DEFAULT_LOCALE).lower().split("-")[0]
    return code if code in LOCALES else DEFAULT_LOCALE
