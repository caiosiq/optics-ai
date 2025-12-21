try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    from fastmcp import FastMCP

import time
import sys
from pathlib import Path

# Ensure project root is in sys.path so we can import optics_mcp package
sys.path.append(str(Path(__file__).parents[1]))

# Import tools and resources from the structured package
from optics_mcp.tools.validation import validate_ui_output
from optics_mcp.tools.execution import exec_python_sandbox
from optics_mcp.resources.definitions import (
    ui_output_format, 
    optics_guardrails, 
    coding_standards,
    geometric_optics,
    laser_physics,
    physical_optics
)
from optics_mcp.resources.filesystem import read_file

def make_app():
    app = FastMCP("Optics MCP Server")

    # --- Resources ---
    @app.resource("resource://ui-output-format")
    def _ui_output_format():
        return ui_output_format()

    @app.resource("resource://optics-guardrails")
    def _optics_guardrails():
        return optics_guardrails()

    @app.resource("resource://coding-standards")
    def _coding_standards():
        return coding_standards()

    @app.resource("resource://geometric-optics")
    def _geometric_optics():
        return geometric_optics()

    @app.resource("resource://laser-physics")
    def _laser_physics():
        return laser_physics()

    @app.resource("resource://physical-optics")
    def _physical_optics():
        return physical_optics()

    @app.resource("file://{path}")
    def _read_file(path: str) -> dict:
        return read_file(path)

    # --- Tools ---
    @app.tool("validate_ui_output")
    def _validate_ui_output(candidate: dict) -> dict:
        return validate_ui_output(candidate)

    @app.tool("ping")
    def ping() -> dict:
        return {"ok": True, "ts": int(time.time() * 1000)}

    @app.tool("exec_python_sandbox")
    def _exec_python_sandbox(code: str, timeout_s: int = 120) -> dict:
        return exec_python_sandbox(code, timeout_s)

    @app.tool("caps")
    def caps() -> dict:
        return {
            "ok": True,
            "tools": [
                "validate_ui_output",
                "exec_python_sandbox",
                "ping",
            ],
            "resources": [
                "resource://ui-output-format",
                "resource://optics-guardrails",
                "resource://coding-standards",
                "resource://geometric-optics",
                "resource://laser-physics",
                "resource://physical-optics",
                "file://{path}",
            ],
        }

    return app

def main():
    app = make_app()
    app.run()

if __name__ == "__main__":
    main()
