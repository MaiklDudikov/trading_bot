import asyncio
import time
# import numpy as np
from aiogram import Bot

# from bybit_api.detector import get_price
from bybit_api.balances import balance_usdt
from bybit_api.client import client
from bybit_api.price_cache import get_price_cached

from config import SYMBOL, DOWN_LEVELS_BASE, DOWN_FIRST_LEVEL
from strategy import state as st
from strategy.trade_stats import register_trade


# ===================== ATR CALCULATION =====================
def calc_atr_percent() -> float:
    """
    ATR по минутным свечам Bybit.
    Возвращает ATR в долях от цены:
    0.005 = 0.5%
    """
    try:
        data = client.get_kline(
            category="spot",
            symbol=SYMBOL,
            interval="1",   # 1-минутные свечи
            limit=20
        )
    except Exception as e:
        print("ATR get_kline error:", e)
        return 0.02

    candles = data.get("result", {}).get("list", [])
    if not candles or len(candles) < 2:
        return 0.02

    # Bybit часто отдаёт свечи от новых к старым → разворачиваем
    candles = candles[::-1]

    highs = []
    lows = []
    closes = []

    for c in candles:
        try:
            high = float(c[2])
            low = float(c[3])
            close = float(c[4])
        except (ValueError, TypeError, IndexError):
            continue

        highs.append(high)
        lows.append(low)
        closes.append(close)

    if len(closes) < 2:
        return 0.02

    tr_values = []

    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_values.append(tr)

    if not tr_values:
        return 0.02

    atr = sum(tr_values) / len(tr_values)
    last_close = closes[-1]

    if last_close <= 0:
        return 0.02

    atr_percent = atr / last_close

    # Ограничение, чтобы сетка не сходила с ума
    return max(0.003, min(atr_percent, 0.03))


# ===================== RESET DOWN VARS =====================
def reset_down_vars():
    st.down_active = False
    st.down_base_price = None
    st.down_usdt_total = None
    st.down_usdt_per_level = None

    st.down_levels_completed = 0
    st.down_sell_orders = []
    st.down_tp_map = {}

    # очищаем массивы уровней (если нужны)
    st.down_entry_prices = []
    st.down_qty_list = []


# ===================== ENTER DOWN MODE =====================
async def enter_down_mode(chat_id: int, last_price: float, bot: Bot):

    st.trade_mode = "DOWN"
    st.down_active = True

    st.down_base_price = st.entry_price_up or last_price

    usdt = balance_usdt()
    if not isinstance(usdt, (int, float)) or usdt <= 0:
        await bot.send_message(chat_id, "❌ Нет USDT для DOWN-режима.")
        st.down_active = False
        st.trade_mode = "UP"
        return

    st.down_usdt_total = float(usdt)
    st.down_usdt_per_level = round(st.down_usdt_total / DOWN_LEVELS_BASE, 2)

    st.down_levels_completed = 0
    st.down_sell_orders = []
    st.down_tp_map = {}

    # для отображения — первый уровень (0.0060 заменил на DOWN_FIRST_LEVEL)
    first_level = round(st.down_base_price - DOWN_FIRST_LEVEL, 4)

    await bot.send_message(
        chat_id,
        f"📉 Переход в режим торговли вниз DOWN\n\n"
        f"Базовая цена : *{st.down_base_price}* (ждём ≈ *{first_level}*)\n"
        f"Текущая цена : *{last_price}*\n\n"
        f"Всего USDT для откупа : *{st.down_usdt_total}*\n"
        f"На уровень (~) : *{st.down_usdt_per_level}*\n"
        f"Уровней : *{DOWN_LEVELS_BASE}*\n"
        f"ATR-адаптация активна ⚡",
        parse_mode="Markdown"
    )

    asyncio.create_task(down_mode_cycle(chat_id, bot))


# ===================== MAIN DOWN CYCLE =====================
async def down_mode_cycle(chat_id: int, bot: Bot):
    await bot.send_message(chat_id, "✔ DOWN-режим запущен\nЖдём падение 🔍")

    while st.down_active:
        await asyncio.sleep(2)

        try:
            price = get_price_cached()
        except Exception:
            continue

        base = st.down_base_price

        atr_percent = calc_atr_percent()
        grid_step = 0.03
        hybrid_step = grid_step + atr_percent

        drawdown = (base - price) / base if base else 0
        extra = 0
        if drawdown > 0.20:
            extra += 1
        if drawdown > 0.35:
            extra += 1
        if drawdown > 0.50:
            extra += 1

        max_levels = int(st.down_usdt_total // st.down_usdt_per_level)
        next_level = st.down_levels_completed + 1

        if next_level > max_levels:
            continue

        # 0.0006 заменил на DOWN_FIRST_LEVEL
        if st.down_levels_completed == 0:
            target_price = base - DOWN_FIRST_LEVEL
        else:
            target_price = base * (1 - hybrid_step * (next_level + extra))

        # ===== BUY LEVEL =====
        if price <= target_price:
            try:
                buy = client.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="BUY",
                    orderType="Market",
                    qty=int(st.down_usdt_per_level),
                    marketUnit="quoteCoin"
                )
            except Exception:
                continue

            buy_id = buy["result"]["orderId"]

            lst = []  # предварительно объявляем переменную
            for _ in range(3):
                h = client.get_order_history(category="spot", orderId=buy_id, symbol=SYMBOL)
                lst = h.get("result", {}).get("list", [])
                if lst and lst[0].get("avgPrice"):
                    break
                await asyncio.sleep(0.8)

            if not lst:
                continue

            row = lst[0]
            entry = float(row["avgPrice"])
            qty = float(row["cumExecQty"])
            fee = float(row.get("cumFeeDetail", {}).get("STRK", 0))
            qty = int((qty - fee) * 10) / 10

            tp = round(entry * (1 + hybrid_step + 0.01), 4)

            try:
                sell = client.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="SELL",
                    orderType="Limit",
                    qty=qty,
                    price=tp,
                    timeInForce="GTC"
                )
            except Exception:
                continue

            oid = sell["result"]["orderId"]

            st.down_sell_orders.append(oid)
            st.down_tp_map[oid] = {"entry": entry, "qty": qty}
            st.down_levels_completed += 1

            await bot.send_message(
                chat_id,
                f"🟢 Уровень *{st.down_levels_completed}* откуплен\n"
                f"Цена : *{entry}*\n"
                f"TP : *{tp}*\n"
                f"ATR : *{round(atr_percent*100, 2)}%*",
                parse_mode="Markdown"
            )

        # ===== CHECK TP CLOSE =====
        if time.time() - st.last_open_check > 8 and st.down_sell_orders:
            st.last_open_check = time.time()

            try:
                open_data = client.get_open_orders(category="spot", symbol=SYMBOL)
                open_ids = {o["orderId"] for o in open_data["result"]["list"]}
            except Exception:
                continue

            closed = [oid for oid in st.down_sell_orders if oid not in open_ids]

            for oid in closed:
                h = client.get_order_history(category="spot", orderId=oid, symbol=SYMBOL)
                lst = h.get("result", {}).get("list", [])
                if not lst:
                    continue

                sell_price = float(lst[0]["avgPrice"])
                data = st.down_tp_map.pop(oid)
                pnl = (sell_price - data["entry"]) * data["qty"]

                register_trade(pnl)

                st.down_sell_orders.remove(oid)

            if not st.down_sell_orders:
                await bot.send_message(chat_id, "🎯 Все TP DOWN закрыты\nВозврат в UP ⬆️")
                reset_down_vars()
                from strategy.up_cycle import strategy_cycle
                st.strategy_running = True
                st.strategy_task = asyncio.create_task(strategy_cycle(chat_id, bot))
                return

        # ===== AUTO EXIT =====
        if price >= base:
            await bot.send_message(chat_id, "📈 Цена вернулась к базе\nВозврат в UP ⬆️")
            reset_down_vars()
            from strategy.up_cycle import strategy_cycle
            st.strategy_running = True
            st.strategy_task = asyncio.create_task(strategy_cycle(chat_id, bot))
            return
