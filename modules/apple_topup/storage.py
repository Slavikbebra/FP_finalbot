import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("modules.apple_topup.storage")

DATA_DIR = Path("bot_data")
DATA_DIR.mkdir(exist_ok=True)
FILE = DATA_DIR / "apple_topup_orders.json"
TEMP_FILE = DATA_DIR / "apple_topup_orders.json.tmp"

ACTIVE_STATES = (
    "WAITING_REGION",
    "WAITING_REGION_CHANGED",
    "PREPARING_CODES",
    "CODES_SENT",
    "WAITING_CONFIRMATION",
    "SELLER_REQUESTED",
    "ERROR",
)

def _norm_username(value):
    if value is None:
        return ""
    return str(value).strip().lstrip("@").casefold()

def load():
    if not FILE.exists():
        return {}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.critical("Apple TopUp storage: повреждён %s: %s. Заказы не перезаписываем.", FILE, exc)
        raise RuntimeError(f"Повреждён файл Apple TopUp storage: {FILE}") from exc
    except OSError as exc:
        logger.exception("Apple TopUp storage: не удалось прочитать %s", FILE)
        raise RuntimeError(f"Не удалось прочитать Apple TopUp storage: {FILE}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Некорректный формат Apple TopUp storage: {FILE}")
    return data

def save(data):
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(TEMP_FILE, FILE)
    except OSError as exc:
        try:
            if TEMP_FILE.exists():
                TEMP_FILE.unlink()
        except OSError:
            pass
        logger.exception("Apple TopUp storage: не удалось сохранить %s", FILE)
        raise RuntimeError(f"Не удалось сохранить Apple TopUp storage: {FILE}") from exc

def get_order(order_id):
    return load().get(str(order_id))

def create_order(order_id, buyer_username, chat_id, **product_data):
    data = load()
    order = {
        "order_id": str(order_id),
        "buyer_username": buyer_username,
        "chat_id": str(chat_id) if chat_id is not None else None,
        "state": "WAITING_REGION",
        "codes": [],
        "fazercards_order_id": None,
        "fazercards_order_ids": [],
        "purchase_started": False,
        "codes_sent_at": None,
        "created_at": datetime.now().isoformat(),
        "lot_id": product_data.get("lot_id"),
        "product_name": product_data.get("product_name"),
        "fazercards_category_id": product_data.get("fazercards_category_id"),
        "fazercards_card_id": product_data.get("fazercards_card_id"),
        "quantity": int(product_data.get("quantity", 0) or 0),
        "product_items": product_data.get("product_items", []),
        "after_input_message": product_data.get("after_input_message"),
    }
    data[str(order_id)] = order
    save(data)
    logger.info(
        "🍎 Apple TopUp storage: заказ сохранён: order=%s buyer=%r chat_id=%r state=%s file=%s",
        order_id, buyer_username, order["chat_id"], order["state"], FILE
    )
    return order

def update_order(order_id, **kwargs):
    data = load()
    order = data.get(str(order_id))
    if not order:
        return None
    order.update(kwargs)
    data[str(order_id)] = order
    save(data)
    return order

def find_active_order(buyer_username, chat_id=None):
    data = load()
    normalized_chat_id = str(chat_id) if chat_id is not None else None
    username_norm = _norm_username(buyer_username)
    orders = []

    # 1) Основной поиск: username + chat_id.
    for order in data.values():
        if _norm_username(order.get("buyer_username")) != username_norm:
            continue
        if order.get("state") not in ACTIVE_STATES:
            continue
        saved_chat_id = order.get("chat_id")
        if normalized_chat_id is not None and saved_chat_id not in (None, "", normalized_chat_id):
            continue
        orders.append(order)

    if orders:
        orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return orders[0]

    # 2) Надёжный fallback: тот же FunPay chat_id.
    # Username в разных типах сообщений иногда представляется иначе,
    # но chat_id остаётся идентификатором конкретного чата.
    if normalized_chat_id is not None:
        chat_orders = [
            order for order in data.values()
            if order.get("state") in ACTIVE_STATES
            and str(order.get("chat_id")) == normalized_chat_id
        ]
        if chat_orders:
            chat_orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            order = chat_orders[0]
            logger.warning(
                "🍎 Apple TopUp storage: заказ найден по chat_id fallback: "
                "order=%s saved_buyer=%r incoming_buyer=%r chat_id=%r state=%s",
                order.get("order_id"), order.get("buyer_username"), buyer_username,
                normalized_chat_id, order.get("state")
            )
            return order

    logger.info(
        "🍎 Apple TopUp storage: активный заказ не найден: buyer=%r chat_id=%r file=%s",
        buyer_username, chat_id, FILE
    )
    return None
