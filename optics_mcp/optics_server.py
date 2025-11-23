from typing import Optional, List
from pydantic import BaseModel, Field, ValidationError
from pathlib import Path
try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    from fastmcp import FastMCP



class Element(BaseModel):
    type: str
    material: str
    radius_front_mm: float
    radius_back_mm: float
    thickness_mm: float


class JsonFile(BaseModel):
    system: str
    elements: List[Element]
    spacing_mm: List[float]
    wavelength_nm: float


class CodeMeta(BaseModel):
    files_expected: List[str] = Field(default_factory=list)


class OpticsAgentResponse(BaseModel):
    text: Optional[str] = None
    code: Optional[str] = None
    code_meta: Optional[CodeMeta] = None
    json_file: Optional[JsonFile] = None


def make_app():
    app = FastMCP("Optics MCP Server")

    @app.resource("resource://ui-output-format")
    def ui_output_format():
        return OpticsAgentResponse.model_json_schema()

    @app.resource("resource://optics-guardrails")
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

    @app.resource("file://{path}")
    def read_file(path: str) -> dict:
        base = Path(__file__).resolve().parents[1]
        allowed = [base / "tmp_runs", base / "saved_json"]
        p = Path(path)
        try:
            rp = p.resolve()
            if not any(str(rp).startswith(str(a.resolve())) for a in allowed):
                return {"ok": False, "error": "invalid path"}
            if not rp.exists() or not rp.is_file():
                return {"ok": False, "error": "not found"}
            size = rp.stat().st_size
            if size > 2000000:
                return {"ok": False, "error": "too large"}
            text = rp.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "path": str(rp), "size": len(text), "content": text}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.tool("validate_ui_output")
    def validate_ui_output(candidate: dict) -> dict:
        try:
            OpticsAgentResponse.model_validate(candidate)
            return {"ok": True, "errors": []}
        except ValidationError as ve:
            return {"ok": False, "errors": [str(ve)]}

    return app


def main():
    app = make_app()
    app.run()


if __name__ == "__main__":
    main()
