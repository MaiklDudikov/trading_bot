import time
from pybit import exceptions
from .client import client
from .balances import balance_strk, balance_usdt
from config import SYMBOL
from strategy import state as st
from strategy.trade_stats import register_trade   # ← НОВОЕ


def buy_strk() -> str:
    """
    Покупка STRK по маркету на весь USDT + установка лимитного ордера +0.0030.
    Обновляет st.trade_mode и st.entry_price_up.
    Возвращает текст сообщения для пользователя.
    """
    usdt = balance_usdt()
    if not isinstance(usdt, (int, float)):
        return f"❌ Ошибка получения баланса USDT :\n{usdt}"

    usdt_int = int(usdt)
    if usdt_int <= 0:
        return "❌ Недостаточно USDT"

    # 1) Market BUY
    try:
        order = client.place_order(
            category="spot",
            symbol=SYMBOL,
            side="BUY",
            orderType="Market",
            qty=usdt_int,
            marketUnit="quoteCoin"
        )
    except (exceptions.InvalidRequestError, exceptions.FailedRequestError) as e:
        print("place_order BUY error:", e)
        return f"⚠ Ошибка при покупке STRK : {e}"

    print("place_order (BUY):", order)
    order_id = order["result"]["orderId"]

    # 2) Ждём avgPrice И cumExecQty из истории ордера
    avg_price = None
    qty_base = None
    fee_strk = 0.0

    for _ in range(3):
        history = client.get_order_history(
            category="spot",
            orderId=order_id,
            symbol=SYMBOL
        )
        order_list = history.get("result", {}).get("list", [])
        print("get_order_history (BUY):", history)

        if order_list:
            order_row = order_list[0]
            avg_price = order_row.get("avgPrice")
            qty_base = order_row.get("cumExecQty")

            fee_detail = order_row.get("cumFeeDetail", {})
            if isinstance(fee_detail, dict):
                fee_val = fee_detail.get("STRK") or fee_detail.get("Strk")
                if fee_val:
                    try:
                        fee_strk = float(fee_val)
                    except ValueError:
                        fee_strk = 0.0

        if avg_price not in [None, "", "0"] and qty_base not in [None, "", "0"]:
            break

        time.sleep(0.8)

    if not avg_price or not qty_base:
        return "❌ Не удалось получить данные сделки (avgPrice / qty) после 6 попыток"

    try:
        avg_price = float(avg_price)
        qty_base = float(qty_base)
    except ValueError:
        return "❌ Ошибка преобразования avgPrice/qty в числа"

    # 3) Сохраняем цену входа для детектора разворота
    st.trade_mode = "UP"
    st.entry_price_up = avg_price
    st.reversal_detected = False

    # 4) Чистое количество STRK после комиссии
    net_qty = max(qty_base - fee_strk, 0.0)
    qty_to_sell = int(net_qty * 10) / 10  # обрезаем до 1 знака

    if qty_to_sell <= 0:
        return (
            "❌ После покупки фактическое количество STRK получилось слишком маленьким :\n"
            f"Всего : {qty_base}, комиссия : {fee_strk}"
        )

    # 5) Цена лимитного ордера (+0.0030)
    sell_price = round(avg_price + 0.0003, 4)

    # 6) Размещаем лимитный ордер
    try:
        sell_order = client.place_order(
            category="spot",
            symbol=SYMBOL,
            side="SELL",
            orderType="Limit",
            qty=qty_to_sell,
            price=sell_price,
            timeInForce="GTC"
        )
    except (exceptions.InvalidRequestError, exceptions.FailedRequestError) as e:
        print("place_order SELL limit error:", e)
        return f"⚠ Ошибка при выставлении лимитного ордера : {e}"

    print("sell limit order:", sell_order)

    # Информативный текст для Telegram 0.0050
    down_trigger_price = round(avg_price - 0.0005, 4)

    return (
        f"✅ Куплено STRK на сумму *{usdt_int}* USDT по цене *{avg_price}* за шт, "
        f"ждём *{sell_price}* или *{down_trigger_price}*\n\n"
        f"📌 Выставлен лимитный ордер\n"
        f"Цена : *{sell_price}*\n"
        f"Количество : *{qty_to_sell}*"
    )


def sell_strk() -> str:
    """
    Продажа всего STRK по маркету.
    Используется как ручная кнопка и при развороте.
    Считает PnL, если известна цена входа st.entry_price_up.
    """
    bal = balance_strk()

    if not isinstance(bal, (int, float)):
        return str(bal)

    # Обрезаем до 1 знака после запятой (truncate)
    strk = int(bal * 10) / 10

    if strk <= 0:
        return "❌ Недостаточно STRK"

    try:
        order = client.place_order(
            category="spot",
            symbol=SYMBOL,
            side="SELL",
            orderType="Market",
            qty=strk
        )
    except (exceptions.InvalidRequestError, exceptions.FailedRequestError) as e:
        print("place_order SELL market error:", e)
        return f"⚠ Ошибка при продаже STRK : {e}"

    print("SELL market order:", order)

    # --- ПРОСЧЁТ PnL, если есть цена входа вверх ---
    pnl = None
    avg_sell_price = None

    try:
        order_id = order["result"]["orderId"]

        # иногда Bybit не сразу отдаёт avgPrice, делаем несколько попыток
        lst = []
        for _ in range(5):
            history = client.get_order_history(
                category="spot",
                orderId=order_id,
                symbol=SYMBOL
            )
            lst = history.get("result", {}).get("list", [])
            if lst and lst[0].get("avgPrice") not in ("0", None, ""):
                break
            time.sleep(0.3)

        if lst:
            row = lst[0]
            avg_sell_price = float(row.get("avgPrice", "0") or "0")
            qty_exec = float(row.get("cumExecQty", "0") or "0")

            # если знаем цену входа вверх — считаем PnL
            if st.entry_price_up is not None and qty_exec > 0 and avg_sell_price > 0:
                pnl = (avg_sell_price - st.entry_price_up) * qty_exec

                # единая статистика
                register_trade(pnl)

                print(
                    f"[UP SELL] qty={qty_exec}, "
                    f"buy={st.entry_price_up}, sell={avg_sell_price}, pnl={pnl}"
                )

    except Exception as e:
        # не ломаем бота, если статистику не получилось посчитать
        print("Error while calculating PnL for SELL:", e)

    # --- Формируем ответ для Telegram (ВСЕГДА строка) ---
    # 1) Полный успех → и продажа, и PnL рассчитан
    if pnl is not None and avg_sell_price is not None:
        return (
            f"✅ Продано STRK : *{strk}*\n"
            f"Цена продажи : *{avg_sell_price}*\n"
            f"PnL по сделке : *{round(pnl, 4)}* USDT"
        )

    # 2) Цена продажи есть, но нет entry_price_up или qty_exec
    if avg_sell_price is not None and pnl is None:
        return (
            f"✅ Продано STRK : *{strk}*\n"
            f"Цена продажи : *{avg_sell_price}*\n"
            f"PnL невозможно рассчитать (нет цены входа или объёма)"
        )

    # 3) Даже avgPrice не пришёл (редкий случай)
    return (
        f"✅ Продано STRK : *{strk}*\n"
        f"PnL невозможно рассчитать (данные Bybit не пришли)"
    )
