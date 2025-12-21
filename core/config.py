import json
import pathlib
from typing import Any, Dict

APP_DIR = pathlib.Path(__file__).parent.parent.resolve()
CONFIG_PATH = APP_DIR / "pipeline_context.json"
API_KEY_PATH = APP_DIR / "openrouter_api.txt"

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def get_api_key() -> str:
    if not API_KEY_PATH.exists():
        return ""
    return API_KEY_PATH.read_text().strip()
