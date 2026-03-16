import asyncio
import time
from aiogram import Bot

from bybit_api.client import client
from bybit_api.balances import balance_usdt
from bybit_api.detector import get_active_limit_sell_order
from bybit_api.price_cache import get_price_cached

from config import SYMBOL, REBOUND_TP_PCT, REBOUND_BUYBACK_PCT
from strategy import state as st


def market_buy_all_usdt_with_tp() -> str:
    """
    Покупает STRK на весь USDT и ставит TP +25%.
    Сохраняет новую точку входа в st.entry_price_up (можно переиспользовать).
    """
    usdt = balance_usdt()
    if not isinstance(usdt, (int, float)):
        return f"❌ Ошибка получения USDT:\n{usdt}"

    usdt_int = int(usdt)
    if usdt_int <= 0:
        return "❌ Недостаточно USDT"

    try:
        order = client.place_order(
            category="spot",
            symbol=SYMBOL,
            side="BUY",
            orderType="Market",
            qty=usdt_int,
            marketUnit="quoteCoin"
        )
    except Exception as e:
        return f"⚠ Ошибка BUY: {e}"

    order_id = order["result"]["orderId"]

    avg_price = None
    qty_base = None
    fee_strk = 0.0

    for _ in range(5):
        history = client.get_order_history(
            category="spot",
            orderId=order_id,
            symbol=SYMBOL
        )
        order_list = history.get("result", {}).get("list", [])
        if order_list:
            row = order_list[0]
            avg_price = row.get("avgPrice")
            qty_base = row.get("cumExecQty")

            fee_detail = row.get("cumFeeDetail", {})
            if isinstance(fee_detail, dict):
                try:
                    fee_strk = float(fee_detail.get("STRK", 0) or 0)
                except Exception:
                    fee_strk = 0.0

        if avg_price not in (None, "", "0") and qty_base not in (None, "", "0"):
            break

        time.sleep(0.6)

    if not avg_price or not qty_base:
        return "❌ Не удалось получить avgPrice / qty после BUY"

    avg_price = float(avg_price)
    qty_base = float(qty_base)

    st.trade_mode = "REBOUND"
    st.entry_price_up = avg_price

    qty_net = max(qty_base - fee_strk, 0.0)
    qty_to_sell = int(qty_net * 10) / 10
    if qty_to_sell <= 0:
        return "❌ Количество STRK для TP получилось 0"

    tp_price = round(avg_price * (1 + REBOUND_TP_PCT), 4)

    try:
        sell_order = client.place_order(
            category="spot",
            symbol=SYMBOL,
            side="SELL",
            orderType="Limit",
            qty=qty_to_sell,
            price=tp_price,
            timeInForce="GTC"
        )
    except Exception as e:
        return f"⚠ Ошибка установки TP: {e}"

    tp_order_id = sell_order["result"]["orderId"]
    st.rebound_last_tp_order_id = tp_order_id

    rebuy_price = round(tp_price * (1 - REBOUND_BUYBACK_PCT), 4)

    return (
        f"✅ REBOUND BUY выполнен\n"
        f"Куплено на *{usdt_int}* USDT по цене *{avg_price}*\n\n"
        f"📌 TP +25%: *{tp_price}*\n"
        f"📌 Повторный BUY при падении на 12%: *{rebuy_price}*\n"
        f"📌 Количество: *{qty_to_sell}*"
    )


def read_last_filled_tp_price() -> float | None:
    """
    Берёт последний исполненный SELL LIMIT и возвращает его avgPrice.
    """
    try:
        history = client.get_order_history(category="spot", symbol=SYMBOL)
    except Exception as e:
        print("rebound get_order_history error:", e)
        return None

    lst = history.get("result", {}).get("list", []) if history else []
    if not lst:
        return None

    for o in lst:
        if (
            o.get("side") == "Sell"
            and o.get("orderType") == "Limit"
            and o.get("orderStatus") in (
                "Filled",
                "PartiallyFilled",
                "PartiallyFilledCanceled",
                "PartiallyFilledCanceledByUser",
            )
        ):
            try:
                return float(o.get("avgPrice", "0") or 0)
            except Exception:
                return None

    return None


async def rebound_cycle(chat_id: int, bot: Bot):
    """
    Цикл:
    BUY all → TP +25% → ждать -12% от цены TP → BUY all → TP +25% ...
    """
    await bot.send_message(
        chat_id,
        "🔁 REBOUND-стратегия запущена\n"
        "BUY на весь депозит → TP +25% → BUYBACK -12% → повтор",
        parse_mode="Markdown"
    )

    while st.strategy_running and st.rebound_active:
        active = get_active_limit_sell_order()

        # 1. Если лимитка ещё есть — ждём её исполнения
        if active:
            await asyncio.sleep(1.5)
            continue

        # 2. Если лимитка исчезла, значит TP исполнился
        if st.rebound_last_sell_price is None:
            sell_price = read_last_filled_tp_price()
            if sell_price is not None:
                st.rebound_last_sell_price = sell_price

                rebuy_price = round(sell_price * (1 - REBOUND_BUYBACK_PCT), 4)

                await bot.send_message(
                    chat_id,
                    f"✅ TP исполнен\n"
                    f"Цена продажи: *{sell_price}*\n"
                    f"Ждём повторный BUY на уровне: *{rebuy_price}*",
                    parse_mode="Markdown"
                )

        # 3. Ждём падение на 12% от последней цены TP
        if st.rebound_last_sell_price is not None:
            try:
                last_price = get_price_cached()
            except Exception:
                last_price = None

            if last_price is not None:
                rebuy_trigger = st.rebound_last_sell_price * (1 - REBOUND_BUYBACK_PCT)

                if last_price <= rebuy_trigger:
                    msg = market_buy_all_usdt_with_tp()
                    await bot.send_message(chat_id, msg, parse_mode="Markdown")

                    # Сбрасываем якорь, ждём новый TP
                    st.rebound_last_sell_price = None

        await asyncio.sleep(1.5)
