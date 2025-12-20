from typing import Optional, List
from pydantic import BaseModel, Field, ValidationError
from pathlib import Path
import time
import sys
import subprocess
import json
import os

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    from fastmcp import FastMCP

# --- Sandbox Runner Script Content ---
# We write this to a file and execute it via subprocess to ensure total isolation.
SANDBOX_RUNNER_CODE = """
import sys, io, os, base64, json, traceback
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def run_user_code(src):
    # Capture stdout/stderr
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    images = []
    
    # Mock plt.show to capture images
    def _print_figs():
        for num in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(num)
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            images.append(base64.b64encode(buf.read()).decode('ascii'))
            plt.close(num)
    plt.show = _print_figs

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_buf, err_buf
    
    ok = True
    try:
        # Execute the code
        exec(src, {'__name__': '__main__'})
    except Exception:
        traceback.print_exc(file=err_buf)
        ok = False
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        
    return {
        "ok": ok,
        "output": out_buf.getvalue() + "\\n" + err_buf.getvalue(),
        "images": images
    }

if __name__ == "__main__":
    try:
        # Read code from stdin
        code = sys.stdin.read()
        result = run_user_code(code)
        # Print result as JSON to stdout (separate from user output)
        print("__JSON_RESULT_START__")
        print(json.dumps(result))
        print("__JSON_RESULT_END__")
    except Exception as e:
        # Fallback error handling
        err = {"ok": False, "output": str(e), "images": []}
        print("__JSON_RESULT_START__")
        print(json.dumps(err))
        print("__JSON_RESULT_END__")
"""

# --- Pydantic Models ---
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

# --- App Definition ---
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

    @app.resource("resource://coding-standards")
    def coding_standards():
        try:
            base = Path(__file__).resolve().parents[1]
            p = base / "knowledge" / "coding_standards.txt"
            return (p.read_text(encoding="utf-8") if p.exists() else "")
        except Exception:
            return ""

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

    @app.tool("ping")
    def ping() -> dict:
        return {"ok": True, "ts": int(time.time() * 1000)}

    @app.tool("exec_python_sandbox")
    def exec_python_sandbox(code: str, timeout_s: int = 120) -> dict:
        import uuid
        
        # 1. Setup Run Directory
        base = Path(__file__).resolve().parents[1]
        run_root = base / "tmp_runs"
        run_root.mkdir(exist_ok=True)
        run_id = f"code-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4()}"
        run_dir = run_root / run_id
        run_dir.mkdir(exist_ok=True)

        # 2. Write files (User Code + Runner)
        runner_path = run_dir / "runner.py"
        runner_path.write_text(SANDBOX_RUNNER_CODE, encoding="utf-8")
        
        # 3. Execute via Subprocess (Isolated)
        try:
            print(f"[sandbox] launching {run_dir}")
            
            # We pipe the user code into stdin so we don't have to write it to a file the runner imports
            # (simplifies encoding/path issues)
            proc = subprocess.run(
                [sys.executable, str(runner_path)],
                input=code,
                text=True,
                capture_output=True,
                cwd=str(run_dir),
                timeout=timeout_s
            )
            
            stdout = proc.stdout
            
            # 4. Parse Results
            # The runner prints __JSON_RESULT_START__ ... JSON ... __JSON_RESULT_END__
            if "__JSON_RESULT_START__" in stdout:
                parts = stdout.split("__JSON_RESULT_START__")
                raw_output = parts[0] # Anything printed before the result block (should be empty usually)
                json_part = parts[1].split("__JSON_RESULT_END__")[0]
                
                try:
                    res = json.loads(json_part)
                    # List any generated files
                    files = []
                    for p in run_dir.glob("**/*"):
                        if p.is_file() and p.name != "runner.py":
                            files.append(str(p.resolve()))
                    
                    res["files"] = files
                    return res
                except json.JSONDecodeError:
                    return {"ok": False, "output": f"Runner JSON Error. Raw stdout: {stdout}", "images": [], "files": []}
            else:
                return {"ok": False, "output": f"Runner failed (No JSON). Stderr: {proc.stderr}\nStdout: {stdout}", "images": [], "files": []}

        except subprocess.TimeoutExpired:
            return {"ok": False, "output": f"Execution timed out after {timeout_s}s", "images": [], "files": []}
        except Exception as e:
            return {"ok": False, "output": f"System Error: {str(e)}", "images": [], "files": []}

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
                "file://{path}",
            ],
        }

    return app

def main():
    app = make_app()
    app.run()

if __name__ == "__main__":
    main()
