# 📘 Bybit Trading Bot (UP + DOWN Strategy)

## 🚀 Overview

This project is a fully automated Telegram bot for algorithmic trading on **Bybit Spot** (e.g., STRKUSDT).  
The bot runs 24/7 and combines two core strategies:

### 1) UP Strategy — Trend Following (BUY → TP → BUY → TP → …)

Classic “trend up” logic:

- Buy STRK **market** using the entire available USDT balance
- Place a **limit sell order** at `avg_price + 0.0030`
- Once TP is hit and the limit order is fully filled → open a new BUY
- Repeat indefinitely: **BUY → TP → BUY → TP** as long as the market goes up

### 2) DOWN Strategy — Buying the Dip in Levels

If price reverses down after a BUY:

- The bot detects a **drawdown from entry price**
- Cancels the active TP-limit
- Sells STRK **market** (locking in a small loss / unfilled profit)
- Switches to **DOWN mode**
- Splits your USDT into N equal parts (e.g. 5 levels)
- On each drop (e.g. −0.0090 from the base price) it:
  - Buys STRK with `1/N` of the USDT
  - Places a limit TP at `avg_price + 0.0050` for that portion
- When all TP orders from DOWN mode are fully filled:
  - Bot automatically exits DOWN mode
  - Returns to UP strategy (BUY → TP → BUY → TP)

---

## 🎯 Main Features

- ✅ Automatic trend-following trading on Bybit Spot
- ✅ Automatic detection of downward reversal
- ✅ Multi-level dip buying (DOWN mode, configurable levels/step)
- ✅ Automatic transition: **UP → DOWN → UP**
- ✅ Manual stop with `/stop`
- ✅ Balance & price info buttons
- ✅ Basic **PnL analytics** and **trading stats**
- ✅ **Stats are persisted to `stats.json`** and restored after restart
- ✅ Button to **clear statistics** from Telegram

---

## 🧩 Project Structure

Example layout:

```text
bot/
│── main.py
│── config.py
│── state.py
│── keyboards.py
│
├── handlers/
│   └── main_buttons.py
│
├── bybit_api/
│   ├── client.py
│   ├── detector.py
│   ├── balances.py
│   ├── orders_up.py
│   └── cancel_order.py
│
└── strategy/
    ├── up_cycle.py
    ├── down_cycle.py
    └── state.py
```
The architecture is modular — all Bybit logic, strategy cycles, handlers and keyboards are separated into their own modules.

🛠 Requirements

- Python 3.11+ (you use 3.12)
- aiogram 3.x
- pybit (unified_trading HTTP client)

Install: pip install aiogram pybit

🔐 Configuration

In config.py you should provide:

API_KEY = "YOUR_BYBIT_API_KEY"
SECRET_KEY = "YOUR_BYBIT_SECRET_KEY"
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

SYMBOL = "STRKUSDT"          # trading pair
DOWN_LEVELS = 5              # number of averaging levels
DOWN_STEP = 0.0090           # drop per level
DOWN_TP_STEP = 0.0050        # TP above each buy level
DRAWDOWN_TRIGGER = 0.0050    # fall from entry price to start DOWN mode

Make sure your Bybit API key has:

✅ Read balance

✅ Spot trading permissions

▶ Running the Bot

From the project root: python main.py

The bot will:

1. Load saved statistics from stats.json (if exists)

2. Start polling Telegram updates

3. Wait for /start or button interactions

🤖 Bot Commands & Buttons
Commands

/start — show main menu and strategy description

/stop — stop all running strategies (UP and DOWN)

/stats — show trading statistics (total trades, win rate, PnL, UP/DOWN breakdown)

/down —  information about what is happening in DOWN mode

Reply Keyboard Buttons

📊 Активный ордер — show current active limit SELL order on STRK (if any)

📈 цена STRK — show current last price

💰 баланс STRK — show STRK balance

💲 баланс USDT — show USDT balance

💷 Купить STRK — start UP strategy: buy STRK and place TP

💸 Продать STRK — sell all STRK at market manually

Inline Buttons

Under /stats message:

🧹 Очистить статистику — clear all stats (in memory and in stats.json)

Under active order message:

❌ Отменить лимитный ордер — cancel current active SELL limit on STRK

🔄 UP → DOWN → UP Logic (High-Level)

1. You press “💷 Купить STRK”

2. Bot:

Buys STRK with all available USDT (market)

Gets avgPrice from Bybit

Places SELL limit at avgPrice + 0.0030

Starts UP cycle loop

3. While TP-limit exists:

Bot monitors price

If price drops by more than DRAWDOWN_TRIGGER →
cancel TP, sell STRK, enter DOWN

4. In DOWN mode:

Split USDT on balance into DOWN_LEVELS

For each level (price falls by DOWN_STEP):

Buy STRK for 1 level of USDT

Place TP at avg + DOWN_TP_STEP

Once all DOWN TP orders are filled:

Exit DOWN

Auto-restart UP if enabled

5. At any time you can /stop to terminate all loops safely.

🧱 Future Plans

Advanced risk management (dynamic levels instead of fixed 5)

Multiple symbols support (not only STRKUSDT)

Daily/weekly report summary via Telegram

Docker image for easy deployment

Backtesting tools and visualization
