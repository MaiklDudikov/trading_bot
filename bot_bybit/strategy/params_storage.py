import json
from pathlib import Path
import config

FILE = Path("strategy_params.json")


def save_params_to_file() -> None:
    data = {
        "TP_STEP": config.TP_STEP,
        "DRAWDOWN_TRIGGER": config.DRAWDOWN_TRIGGER,
        "DOWN_FIRST_LEVEL": config.DOWN_FIRST_LEVEL,
    }

    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_params_from_file() -> None:
    if not FILE.exists():
        save_params_to_file()
        return

    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        config.TP_STEP = float(data.get("TP_STEP", config.TP_STEP))
        config.DRAWDOWN_TRIGGER = float(data.get("DRAWDOWN_TRIGGER", config.DRAWDOWN_TRIGGER))
        config.DOWN_FIRST_LEVEL = float(data.get("DOWN_FIRST_LEVEL", config.DOWN_FIRST_LEVEL))

    except Exception as e:
        print(f"load_params_from_file error: {e}")
