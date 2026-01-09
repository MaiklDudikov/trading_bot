from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
import asyncio
from keyboards import main_kb, cancel_order_kb, stats_clear_kb
from bybit_api.detector import get_price, get_active_limit_sell_order
from bybit_api.balances import balance_strk, balance_usdt
from bybit_api.orders_up import buy_strk, sell_strk
from strategy import state as st
from strategy.up_cycle import strategy_cycle
from strategy.down_cycle import reset_down_vars
from strategy.stats_storage import save_stats_to_file, reset_stats
from config import DOWN_LEVELS_BASE
from bybit_api.price_cache import get_price_cached


router = Router()


# START КОМАНДА
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет 👋 я бот для торговли на Bybit 🤖\n\n"
        "Стратегия : BUY → TP → BUY → TP\n"
        "При развороте вниз включается откуп падения по уровням (DOWN).\n\n"
        "Выбери действие ⬇️",
        reply_markup=main_kb
    )


# КОМАНДА STOP: Полный стоп UP + DOWN
@router.message(Command("stop"))
async def cmd_stop(message: types.Message):
    st.strategy_running = False
    if st.strategy_task:
        st.strategy_task.cancel()
        st.strategy_task = None

    # Останавливаем DOWN
    if st.down_active:
        reset_down_vars()
        st.down_active = False
        st.trade_mode = "UP"

    await message.answer("⏹ Все стратегии остановлены.")


# 📈 Цена STRK
@router.message(F.text == "📈 цена STRK")
async def btn_price_strk(message: types.Message):
    price = get_price()
    await message.answer(f"📈 Цена STRK : *{price}*", parse_mode="Markdown")


# 💰 Баланс STRK
@router.message(F.text == "💰 баланс STRK")
async def btn_balance_strk(message: types.Message):
    bal = balance_strk()
    if isinstance(bal, (int, float)):
        bal = round(bal, 3)

    await message.answer(f"💰 Ваш баланс STRK : *{bal}*", parse_mode="Markdown")


# 💲 Баланс USDT
@router.message(F.text == "💲 баланс USDT")
async def btn_balance_usdt(message: types.Message):
    bal = balance_usdt()
    if isinstance(bal, (int, float)):
        bal = round(bal, 2)

    await message.answer(f"💲 Ваш баланс USDT : *{bal}*", parse_mode="Markdown")


# 📊 Активный ордер
@router.message(F.text == "📊 Активный ордер")
async def btn_active_order(message: types.Message):
    order = get_active_limit_sell_order()
    if not order:
        await message.answer("📭 Активных лимитных ордеров нет.")
        return

    price = order.get("price")
    qty = order.get("qty")
    status = order.get("orderStatus")
    order_id = order.get("orderId")

    await message.answer(
        "📊 *Активный лимитный ордер*\n\n"
        f"ID: `{order_id}`\n"
        f"Цена: *{price}*\n"
        f"Количество: *{qty}*\n"
        f"Статус: {status}",
        reply_markup=cancel_order_kb(order_id),
        parse_mode="Markdown"
    )


# 💷 Купить STRK
@router.message(F.text == "💷 Купить STRK")
async def btn_buy_strk(message: types.Message):
    # Блокируем BUY если включён DOWN
    if st.down_active:
        await message.answer(
            "⚠️ Сейчас активен DOWN-режим.\n"
            "Остановите его командой /stop перед запуском BUY.",
            parse_mode="Markdown"
        )
        return

    result = buy_strk()
    await message.answer(result, parse_mode="Markdown")

    # Запускаем стратегию, если покупка успешная
    if "Куплено STRK" in result and not st.strategy_running:
        st.strategy_running = True
        st.strategy_task = asyncio.create_task(
            strategy_cycle(message.chat.id, message.bot)
        )
        await message.answer("🚀 Стратегия BUY → TP запущена.\nОстановить → /stop")


# 💸 Продать STRK
@router.message(F.text == "💸 Продать STRK")
async def btn_sell_strk(message: types.Message):
    result = sell_strk()
    await message.answer(result, parse_mode="Markdown")


# 📊 Статистика
@router.message(Command("stats"))
async def stats_handler(message: types.Message):
    if st.total_trades == 0:
        winrate = 0
    else:
        winrate = round(st.profit_trades / st.total_trades * 100, 2)

    text = (
        "📊 *Статистика торговли*\n\n"
        f"Всего сделок : *{st.total_trades}*\n"
        f"Прибыльных : *{st.profit_trades}*\n"
        f"Убыточных : *{st.loss_trades}*\n"
        f"Win Rate : *{winrate} %*\n\n"
        f"Общий PnL : *{round(st.total_pnl, 4)} USDT*"
    )

    # перед показом — сохраним статистику в файл
    save_stats_to_file()

    await message.answer(text, parse_mode="Markdown", reply_markup=stats_clear_kb())


@router.callback_query(F.data == "stats_clear")
async def on_stats_clear(callback: types.CallbackQuery):
    reset_stats()
    await callback.message.answer("📊 Статистика торговли очищена")
    await callback.answer()


@router.message(Command("down"))
async def cmd_down(message: types.Message):

    if not st.down_active or st.down_base_price is None:
        await message.answer("DOWN-режим : ❌ не активен")
        return

    base = st.down_base_price
    current_price = get_price_cached()

    # ------------------------------
    # ATR для отображения
    # ------------------------------
    from strategy.down_cycle import calc_atr_percent
    atr_percent = calc_atr_percent()

    grid_step = 0.03                      # базовый шаг 3%
    hybrid_step = grid_step + atr_percent  # итоговый гибридный шаг

    levels_text = []

    # ------------------------------
    # РАСЧЁТ ВСЕХ УРОВНЕЙ 1–N
    # ------------------------------
    for lvl in range(1, DOWN_LEVELS_BASE + 1):

        # --- 1 уровень фиксированный ---
        if lvl == 1:
            level_price = round(base - 0.0060, 4)

        else:
            # оцениваем drawdown (как в down_cycle)
            try:
                price_now = get_price_cached()
            except:
                price_now = current_price

            if base > 0:
                drawdown = (base - price_now) / base
            else:
                drawdown = 0

            extra = 0
            if drawdown > 0.20:
                extra += 1
            if drawdown > 0.35:
                extra += 1
            if drawdown > 0.50:
                extra += 1

            effective_level = lvl + extra
            level_price = round(base * (1 - hybrid_step * effective_level), 4)

        levels_text.append(f"{lvl} уровень : ~*{level_price}*")

    # ------------------------------
    # Формируем ответ
    # ------------------------------
    text = (
        "*DOWN-режим активен* ✅\n\n"
        f"Базовая цена : *{base}*\n"
        f"Текущая цена : *{current_price}*\n\n"
        "Уровни :\n" +
        "\n".join(levels_text) +
        f"\n\nОткупов выполнено : *{st.down_levels_completed}/{DOWN_LEVELS_BASE}*\n"
        f"Ордера TP выставлены : *{len(st.down_sell_orders)}*"
    )

    await message.answer(text, parse_mode="Markdown")
