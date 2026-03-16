from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
import asyncio
from keyboards import main_kb, cancel_order_kb, stats_clear_kb
from bybit_api.detector import get_price, get_active_limit_sell_order
from bybit_api.balances import balance_strk, balance_usdt
from bybit_api.orders_up import buy_strk, sell_strk
from strategy import state as st
from strategy.up_cycle import strategy_cycle
from strategy.down_cycle import reset_down_vars, calc_atr_percent
from strategy.stats_storage import save_stats_to_file, reset_stats
from config import DOWN_LEVELS_BASE, DOWN_FIRST_LEVEL
import config
from strategy.params_storage import save_params_to_file
from bybit_api.price_cache import get_price_cached
from strategy.rebound_cycle import rebound_cycle, market_buy_all_usdt_with_tp


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


# КОМАНДА STOP: Полный стоп UP + DOWN + REBOUND
@router.message(Command("stop"))
async def cmd_stop(message: types.Message):
    st.strategy_running = False
    if st.strategy_task:
        st.strategy_task.cancel()
        st.strategy_task = None
        st.rebound_active = False
        st.rebound_last_sell_price = None
        st.rebound_last_tp_order_id = None

    # Останавливаем DOWN
    if st.down_active:
        reset_down_vars()
        st.down_active = False
        st.trade_mode = "UP"

    await message.answer("⏹ Все стратегии остановлены.")


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📘 *Справка по командам бота*\n\n"

        "*Основные команды:*\n"
        "/start — запуск бота и главное меню\n"
        "/help — показать эту справку\n"
        "/stop — остановить все стратегии\n"
        "/stats — показать статистику торговли\n"
        "/down — показать состояние DOWN-режима\n"
        "/params — показать текущие параметры стратегии\n\n"

        "*Изменение параметров стратегии:*\n"
        "/set tp 0.0003 — изменить шаг TP в BUY → TP\n"
        "/set reversal 0.0005 — изменить точку разворота вниз\n"
        "/set down1 0.0006 — изменить первый уровень DOWN\n\n"

        "*Кнопки в меню:*\n"
        "💷 Купить STRK — купить STRK на весь USDT и запустить UP-стратегию\n"
        "💸 Продать STRK — продать весь STRK по рынку\n"
        "📈 цена STRK — показать текущую цену STRK\n"
        "💰 баланс STRK — показать баланс STRK\n"
        "💲 баланс USDT — показать баланс USDT\n"
        "📊 Активный ордер — показать текущий лимитный ордер\n"
        "Отменить лимитный ордер — отменить активную лимитку\n\n"

        "*Логика стратегий:*\n"
        "UP-режим: BUY → TP → BUY → TP по кругу\n"
        "При падении цены ниже точки разворота включается DOWN-режим\n"
        "DOWN-режим: откуп уровней по сетке с TP и возвратом в UP\n\n"

        "*Важно:*\n"
        "Все изменения параметров через /set сохраняются и применяются сразу."
    )

    await message.answer(text, parse_mode="Markdown")


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

    try:
        current_price = get_price_cached()
    except Exception:
        current_price = base

    # ATR и hybrid step
    atr_percent = calc_atr_percent()
    grid_step = 0.03
    hybrid_step = grid_step + atr_percent

    # drawdown как в down_cycle.py
    if base > 0:
        drawdown = (base - current_price) / base
    else:
        drawdown = 0.0

    extra = 0
    if drawdown > 0.20:
        extra += 1
    if drawdown > 0.35:
        extra += 1
    if drawdown > 0.50:
        extra += 1

    # сколько уровней в теории можем открыть по текущему размеру уровня
    if st.down_usdt_total and st.down_usdt_per_level and st.down_usdt_per_level > 0:
        max_levels = int(st.down_usdt_total // st.down_usdt_per_level)
    else:
        max_levels = DOWN_LEVELS_BASE

    # для красивого вывода покажем хотя бы 10 уровней,
    # но не меньше базовых 5 и не больше теоретически доступных
    levels_to_show = max(DOWN_LEVELS_BASE, min(max_levels, 10))

    levels_text = []

    for lvl in range(1, levels_to_show + 1):

        if lvl == 1:
            level_price = round(base - DOWN_FIRST_LEVEL, 4)
        else:
            effective_level = lvl + extra
            level_price = round(base * (1 - hybrid_step * effective_level), 4)

        marker = ""
        if lvl <= st.down_levels_completed:
            marker = " ✅"

        levels_text.append(f"{lvl} уровень : ~*{level_price}*{marker}")

    text = (
        "*DOWN-режим активен* ✅\n\n"
        f"Базовая цена : *{round(base, 4)}*\n"
        f"Текущая цена : *{round(current_price, 4)}*\n"
        f"Drawdown : *{round(drawdown * 100, 2)} %*\n\n"
        f"ATR : *{round(atr_percent * 100, 2)} %*\n"
        f"Hybrid step : *{round(hybrid_step * 100, 2)} %*\n"
        f"Первый уровень : *-{DOWN_FIRST_LEVEL}*\n"
        f"Размер уровня : *{st.down_usdt_per_level} USDT*\n"
        f"Макс. уровней по депозиту : *{max_levels}*\n\n"
        "Уровни :\n"
        + "\n".join(levels_text)
        + f"\n\nОткупов выполнено : *{st.down_levels_completed}*"
        + f"\nОрдера TP выставлены : *{len(st.down_sell_orders)}*"
    )

    await message.answer(text, parse_mode="Markdown")


# /params
# /set tp 0.0030
# /set reversal 0.0050
# /set down1 0.0060
@router.message(Command("params"))
async def cmd_params(message: types.Message):
    text = (
        "⚙ *Текущие параметры стратегии*\n\n"
        f"TP STEP : *{config.TP_STEP}*\n"
        f"REVERSAL : *{config.DRAWDOWN_TRIGGER}*\n"
        f"DOWN FIRST LEVEL : *{config.DOWN_FIRST_LEVEL}*"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("set"))
async def cmd_set_param(message: types.Message):
    parts = message.text.split()

    if len(parts) != 3:
        await message.answer(
            "Использование:\n"
            "/set tp 0.0003\n"
            "/set reversal 0.0005\n"
            "/set down1 0.0006"
        )
        return

    param = parts[1].lower()

    try:
        value = float(parts[2])
    except ValueError:
        await message.answer("❌ Значение должно быть числом")
        return

    if value <= 0:
        await message.answer("❌ Значение должно быть больше нуля")
        return

    if param == "tp":
        config.TP_STEP = value
        save_params_to_file()
        await message.answer(f"✅ TP STEP обновлён: *{config.TP_STEP}*", parse_mode="Markdown")

    elif param == "reversal":
        config.DRAWDOWN_TRIGGER = value
        save_params_to_file()
        await message.answer(
            f"✅ Точка разворота обновлена: *{config.DRAWDOWN_TRIGGER}*",
            parse_mode="Markdown"
        )

    elif param == "down1":
        config.DOWN_FIRST_LEVEL = value
        save_params_to_file()
        await message.answer(
            f"✅ Первый уровень DOWN обновлён: *{config.DOWN_FIRST_LEVEL}*",
            parse_mode="Markdown"
        )

    else:
        await message.answer(
            "❌ Неизвестный параметр.\n"
            "Доступно:\n"
            "tp\n"
            "reversal\n"
            "down1"
        )


@router.message(Command("rebound"))
async def cmd_rebound(message: types.Message):
    if st.down_active:
        await message.answer("⚠ Сначала останови DOWN-режим командой /stop")
        return

    if st.strategy_running:
        await message.answer("⚠ Какая-то стратегия уже запущена. Останови её через /stop")
        return

    first_msg = market_buy_all_usdt_with_tp()
    await message.answer(first_msg, parse_mode="Markdown")

    if "REBOUND BUY выполнен" in first_msg:
        st.strategy_running = True
        st.rebound_active = True
        st.strategy_task = asyncio.create_task(
            rebound_cycle(message.chat.id, message.bot)
        )
