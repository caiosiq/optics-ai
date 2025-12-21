from pathlib import Path
from optics_mcp.models.types import OpticsAgentResponse

def ui_output_format():
    return OpticsAgentResponse.model_json_schema()

def optics_guardrails():
    return {
        "rules": [
            "JSON-only responses; single object with keys: text, code, code_meta, json_file",
            "No invented numeric values; compute inside code and print",
            "Code must run as-is; no argparse/sys.argv/input()",
            "Use SI units or state units explicitly",
            "Do not just guess values for important parameters, generate meaningful code to compute them"
        ]
    }

def _read_knowledge(filename: str) -> str:
    try:
        # optics_mcp/resources/definitions.py -> parents[3] is project root
        base = Path(__file__).resolve().parents[3]
        p = base / "knowledge" / filename
        return (p.read_text(encoding="utf-8") if p.exists() else "")
    except Exception:
        return ""

def coding_standards():
    return _read_knowledge("coding_standards.txt")

def geometric_optics():
    return _read_knowledge("geometric_optics.txt")

def laser_physics():
    return _read_knowledge("laser_physics.txt")

def physical_optics():
    return _read_knowledge("physical_optics.txt")
