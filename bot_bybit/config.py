import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# === API KEYS ===
API_KEY = os.getenv("BYBIT_API_KEY")
SECRET_KEY = os.getenv("BYBIT_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN_TRADE")

# Проверка — если ключи не загрузились, выводим предупреждение
if not API_KEY or not SECRET_KEY:
    print("⚠ WARNING: BYBIT API KEYS NOT LOADED FROM .env")

if not BOT_TOKEN:
    print("⚠ WARNING: BOT_TOKEN_TRADE NOT LOADED FROM .env")

# === Торговые настройки ===
SYMBOL = "STRKUSDT"

# Порог разворота вниз от avg_price (например, 0.0050)
TP_STEP = 0.0003
DRAWDOWN_TRIGGER = 0.0005
DOWN_FIRST_LEVEL = 0.0006

# Настройки Market BUY стратегии, команда /rebound
REBOUND_TP_PCT = 0.25        # +25%
REBOUND_BUYBACK_PCT = 0.12   # -12%

# Настройки DOWN-стратегии
DOWN_LEVELS_BASE = 5          # базовое деление депозита_BASE
DOWN_STEP = 0.0005       # Шаг падения на каждом уровне 0.0090, 0.0050
DOWN_TP_STEP = 0.0005    # TP для каждого уровня 0.0050
MAX_DOWN_LEVELS = 10        # максимум уровней в сетке

# --- Авто-возврат в UP после DOWN ---
AUTORESTART_UP = True
