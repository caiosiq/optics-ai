import json
import pathlib
from typing import Any, Dict, Optional

APP_DIR = pathlib.Path(__file__).parent.parent.resolve()
CONFIG_DIR = APP_DIR / "config"
API_KEY_PATH = APP_DIR / "openrouter_api.txt"

def get_api_key() -> str:
    if not API_KEY_PATH.exists():
        return ""
    return API_KEY_PATH.read_text().strip()

def load_json_config(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error loading config {path}: {e}")
        return {}

def load_agent_config(agent_name: str) -> Dict[str, Any]:
    """Loads specific agent config."""
    agent_path = CONFIG_DIR / "agents" / f"{agent_name}.json"
    agent_cfg = load_json_config(agent_path)
    return agent_cfg

def load_legacy_config() -> Dict[str, Any]:
    """
    Reconstructs the old pipeline_context.json structure for backward compatibility.
    NOTE: RAG is now distributed in agent configs.
    """
    cfg = {}
    # cfg["rag"] = ... # Removed
    
    # Load agents
    for agent in ["thinker", "drafter", "reviewer"]:
        cfg[agent] = load_json_config(CONFIG_DIR / "agents" / f"{agent}.json")
    
    # Models key for server.py config_models()
    cfg["models"] = {}
    cfg["models"]["drafter_model"] = cfg["drafter"].get("model")
    # For reviewer, try default model
    reviewer_cfg = cfg["reviewer"]
    if "models" in reviewer_cfg:
        cfg["models"]["reviewer_model"] = reviewer_cfg["models"].get("default")
    else:
        cfg["models"]["reviewer_model"] = reviewer_cfg.get("model")

    return cfg

# For backward compatibility with existing server.py until fully updated
load_config = load_legacy_config
