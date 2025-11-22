import json
import pathlib

# Minimal MCP-like module: exposes resources and a validator tool.

BASE = pathlib.Path(__file__).parent.resolve()
SCHEMA_PATH = BASE / "ui_output_format.json"
EXAMPLES_PATH = BASE / "ui_output_examples.json"
GUARDRAILS_PATH = BASE / "optics_guardrails.md"

def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

def load_examples() -> list:
    return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))

def load_guardrails() -> str:
    return GUARDRAILS_PATH.read_text(encoding="utf-8")

def validate_ui_output(candidate: dict) -> dict:
    try:
        import jsonschema
        schema = load_schema()
        jsonschema.validate(candidate, schema)
        return {"ok": True, "errors": []}
    except ImportError:
        # Fallback: minimal top-level validation without dependency
        keys = {"text", "code", "code_meta", "json_file"}
        extra = [k for k in candidate.keys() if k not in keys]
        missing = [k for k in keys if k not in candidate]
        errs = []
        if extra:
            errs.append(f"extra keys: {extra}")
        if missing:
            errs.append(f"missing keys: {missing}")
        return {"ok": not errs, "errors": errs}
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}