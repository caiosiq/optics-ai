import json
import pathlib
import time
from typing import Any, Dict

from flask import Flask, request, send_from_directory, jsonify
import requests
import subprocess
import sys
from fastmcp import Client

APP_DIR = pathlib.Path(__file__).parent.resolve()
STATIC_DIR = APP_DIR / "static"
CONFIG_PATH = APP_DIR / "agent_config.json"
API_KEY_PATH = APP_DIR / "openrouter_api.txt"

app = Flask(__name__, static_folder=str(STATIC_DIR))
CONVERSATIONS: dict[str, list[dict]] = {}

# Start MCP client early so it's available when chat handler runs
MCP_CLIENT = None

def start_mcp_server():
    global MCP_CLIENT
    if MCP_CLIENT is None:
        script_path = str((APP_DIR / "optics_mcp" / "optics_server.py").resolve())
        MCP_CLIENT = Client(script_path)

class LLMJSONError(Exception):
    def __init__(self, message: str, raw_out: dict | None = None, raw_content: str | dict | None = None):
        super().__init__(message)
        self.raw_out = raw_out
        self.raw_content = raw_content


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_system_prompt(cfg: Dict[str, Any]) -> str:
    role = cfg.get("agent_role", "Optics Chat Agent")
    ctx_lines = cfg.get("agent_context", [])
    base = (
        f"You are the {role}. Answer optics questions and propose Python code and JSON files when useful.\n"
        "Your responses MUST follow the UI output format in the 'resource://ui-output-format' resource.\n"
        "You MUST obey the rules in the 'resource://optics-guardrails' resource.\n"
        "Always return a single JSON object with keys: text, code, code_meta, json_file (null allowed), no extra keys.\n"
        "After drafting a response, the system may validate it; if errors are reported, correct them."
    )
    base += "\nFiles may be provided via the MCP resource 'file://{path}'; request reading only if needed."
    if ctx_lines:
        base += "\nAgent Context:\n" + "\n".join(ctx_lines)
    return base


def _response_json_schema() -> Dict[str, Any]:
    try:
        # Use the same Pydantic model as the MCP server for consistency
        from optics_mcp.optics_server import OpticsAgentResponse
        return OpticsAgentResponse.model_json_schema()
    except Exception:
        # Fallback: minimal valid JSON Schema when import fails
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": ["string", "null"]},
                "code": {"type": ["string", "null"]},
                "code_meta": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "files_expected": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "json_file": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "system": {"type": "string"},
                        "elements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "type": {"type": "string"},
                                    "material": {"type": "string"},
                                    "radius_front_mm": {"type": "number"},
                                    "radius_back_mm": {"type": "number"},
                                    "thickness_mm": {"type": "number"}
                                },
                                "required": [
                                    "type",
                                    "material",
                                    "radius_front_mm",
                                    "radius_back_mm",
                                    "thickness_mm"
                                ]
                            }
                        },
                        "spacing_mm": {"type": "array", "items": {"type": "number"}},
                        "wavelength_nm": {"type": "number"}
                    },
                    "required": ["system", "elements", "spacing_mm", "wavelength_nm"]
                }
            },
            "required": ["text", "code", "code_meta", "json_file"]
        }


def call_openrouter(messages: list[dict], model: str, max_tokens: int = 2000, retries: int = 1, reasoning_effort: str = "low", temperature: float = 0.2) -> tuple[Dict[str, Any], Dict[str, Any]]:
    api_key = API_KEY_PATH.read_text().strip()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    schema = _response_json_schema()
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "OpticsAgentResponse", "schema": schema, "strict": False}
        },
        "reasoning": {"effort": reasoning_effort},
        "temperature": temperature,
    }
    # No tools included; rely on response_format + local Pydantic validation for speed
    last_out = None
    last_content = None
    finish_reason = None
    attempts = 0
    llm_start = time.perf_counter()
    for attempt in range(max(1, retries)):
        r = requests.post(url, headers=headers, json=payload, timeout=600)
        out = r.json()
        last_out = out
        if "choices" not in out or not out["choices"]:
            raise RuntimeError(f"Invalid LLM response: {json.dumps(out)[:500]}")
        choice = out["choices"][0]
        message = choice["message"]
        finish_reason = out["choices"][0].get("finish_reason")
        content = message.get("content")
        # No tool call handling in this fast path
        last_content = content
        if isinstance(content, dict):
            try:
                from optics_mcp.optics_server import OpticsAgentResponse
                OpticsAgentResponse.model_validate(content)
                llm_ms = int((time.perf_counter() - llm_start) * 1000)
                metrics = {"llm_ms": llm_ms, "retries": attempts + 1, "finish_reason": finish_reason, "usage": out.get("usage")}
                return content, metrics
            except Exception as ve:
                messages = messages + [{"role": "system", "content": f"Validation error: {str(ve)}. Return a corrected JSON per schema only."}]
                payload["messages"] = messages
                attempts += 1
                continue
        if isinstance(content, str):
            s = content.strip()
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    try:
                        from optics_mcp.optics_server import OpticsAgentResponse
                        OpticsAgentResponse.model_validate(obj)
                        llm_ms = int((time.perf_counter() - llm_start) * 1000)
                        metrics = {"llm_ms": llm_ms, "retries": attempts + 1, "finish_reason": finish_reason, "usage": out.get("usage")}
                        return obj, metrics
                    except Exception as ve:
                        messages = messages + [{"role": "system", "content": f"Validation error: {str(ve)}. Return a corrected JSON per schema only."}]
                        payload["messages"] = messages
                        attempts += 1
                        continue
            except Exception:
                pass
        # On failure or truncation, compress context and nudge the model
        if messages:
            compressed = [messages[0], messages[-1]] if len(messages) >= 2 else messages
        else:
            compressed = messages
        messages = compressed + [{"role": "system", "content": "Return a valid JSON object per schema only. No extra text. Fill unused keys with null."}]
        payload["messages"] = messages
        if finish_reason == "length":
            payload["max_tokens"] = min(4000, max_tokens + 1000)
        attempts += 1
    raise LLMJSONError("Model did not return valid JSON per schema", raw_out=last_out, raw_content=last_content)


def _clip(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit]


def _append_history(conv_id: str, role: str, content: str):
    CONVERSATIONS.setdefault(conv_id, []).append({"role": role, "content": content})


def _get_history(conv_id: str, limit_msgs: int, clip_chars: int) -> list[dict]:
    hist = CONVERSATIONS.get(conv_id, [])
    if not hist:
        return []
    if limit_msgs > 0:
        hist = hist[-limit_msgs:]
    return [{"role": m["role"], "content": _clip(str(m["content"]), clip_chars)} for m in hist]


def _extract_constraints_text(conv_id: str, limit_msgs: int, clip_chars: int, max_constraints: int) -> str:
    hist = CONVERSATIONS.get(conv_id, [])
    if not hist:
        return ""
    users = [m for m in hist if m.get("role") == "user"]
    if limit_msgs > 0:
        users = users[-limit_msgs:]
    out = []
    for m in users:
        t = str(m.get("content", ""))[:clip_chars]
        for line in t.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(k in s.lower() for k in ["wavelength", "power", "radius", "length", "reflect", "roc", "material", "lens", "spacing"]):
                if len(s) <= 160:
                    out.append(s)
            if len(out) >= max_constraints:
                break
        if len(out) >= max_constraints:
            break
    return "\n".join(out)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/download")
def download():
    path = request.args.get("path", "")
    p = pathlib.Path(path)
    base_allowed = [APP_DIR / "tmp_runs", APP_DIR / "saved_json"]
    try:
        abs_p = p.resolve()
        if not any(str(abs_p).startswith(str(b.resolve())) for b in base_allowed):
            return jsonify({"ok": False, "error": "invalid path"}), 400
        return send_from_directory(abs_p.parent, abs_p.name, as_attachment=False)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/chat", methods=["POST"])
def chat():
    cfg = load_config()
    start_mcp_server()
    data = request.get_json(force=True)
    user_text = (data or {}).get("message", "")
    model = (data or {}).get("model") or cfg.get("default_model", "openai/gpt-4.1-mini")
    conv_id = (data or {}).get("conversation_id") or "default"
    limit_msgs = int(cfg.get("context_window_messages", 5) or 0)
    clip_chars = int(cfg.get("max_message_chars", 800) or 800)
    add_clip = int(cfg.get("max_context_addition_chars", 1500) or 1500)
    system_prompt = build_system_prompt(cfg)
    history = _get_history(conv_id, limit_msgs, clip_chars)
    if cfg.get("session_constraints_enabled"):
        constraints = _extract_constraints_text(conv_id, limit_msgs, clip_chars, int(cfg.get("max_constraints", 10)))
        if constraints:
            system_prompt = system_prompt + "\nSession Constraints:\n" + constraints
    extra_ctx = (data or {}).get("extra_context") or []
    ctx_lines: list[str] = []
    for item in extra_ctx:
        kind = str(item.get("type",""))
        name = str(item.get("name",""))
        text = str(item.get("text",""))[:add_clip]
        if kind == "output" and text:
            ctx_lines.append(f"Output snippet:\n{text}")
        elif kind == "file":
            line = f"File: {name}\n{text}" if text else f"File: {name}"
            ctx_lines.append(line)
    ctx_block = "\n".join(ctx_lines)
    ctx_message = [{"role": "system", "content": ("Previous run context:\n" + ctx_block)}] if ctx_block else []
    messages = [{"role": "system", "content": system_prompt}] + history + ctx_message + [{"role": "user", "content": user_text}]
    try:
        t0 = time.perf_counter()
        _append_history(conv_id, "user", user_text)
        # Build prep time
        prep_ms = int((time.perf_counter() - t0) * 1000)
        resp, call_metrics = call_openrouter(
            messages,
            model,
            max_tokens=min(int(cfg.get("max_tokens", 2000) or 2000), 50000),
            retries=2,
            reasoning_effort=str(cfg.get("reasoning_effort", "low")),
            temperature=float(cfg.get("temperature", 0.2) or 0.2),
        )
        assistant_text = resp.get("text") or "Provided structured output"
        _append_history(conv_id, "assistant", assistant_text)
        post_ms = int((time.perf_counter() - t0) * 1000) - prep_ms - call_metrics.get("llm_ms", 0)
        metrics = {"prep_ms": prep_ms, **call_metrics, "post_ms": max(post_ms, 0), "timestamp": int(time.time()*1000)}
        return jsonify({"ok": True, "response": resp, "metrics": metrics})
    except Exception as e:
        if isinstance(e, LLMJSONError):
            return jsonify({"ok": False, "error": str(e), "raw_response": e.raw_out, "raw_message": e.raw_content}), 400
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.get_json(force=True)
    code = (data or {}).get("code", "")
    code_meta = (data or {}).get("code_meta")
    import subprocess, uuid, os, base64, io
    import re
    run_dir = APP_DIR / "tmp_runs" / str(uuid.uuid4())
    run_dir.mkdir(parents=True, exist_ok=True)
    instrument = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import sys, io, base64\n"
        "def _print_figs():\n"
        "    for num in plt.get_fignums():\n"
        "        buf = io.BytesIO()\n"
        "        plt.figure(num)\n"
        "        plt.savefig(buf, format='png', bbox_inches='tight')\n"
        "        buf.seek(0)\n"
        "        b64 = base64.b64encode(buf.read()).decode('ascii')\n"
        "        print('[[IMAGE]]'+b64)\n"
        "plt.show = _print_figs\n"
    )
    program = instrument + "\n" + code
    try:
        r = subprocess.run(
            ["python", "-c", program],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        out = r.stdout or ""
        err = r.stderr or ""
        images = []
        text_out = []
        for line in out.splitlines():
            if line.startswith("[[IMAGE]]"):
                images.append(line[len("[[IMAGE]]"):])
            else:
                text_out.append(line)
        files = []
        for p in run_dir.iterdir():
            if p.is_file():
                files.append(str(p))
        error_line = None
        error_user_line = None
        error_type = None
        error_msg = None
        if err:
            m = re.search(r"File \"<string>\", line (\d+)", err)
            if m:
                try:
                    error_line = int(m.group(1))
                except Exception:
                    error_line = None
            last = ""
            for ln in err.splitlines()[::-1]:
                ln = ln.strip()
                if ln:
                    last = ln
                    break
            if last:
                # e.g., IndentationError: unexpected indent
                parts = last.split(":", 1)
                error_type = parts[0].strip()
                error_msg = parts[1].strip() if len(parts) > 1 else ""
            inst_lines = instrument.count("\n") + 1
            if error_line and error_line > inst_lines:
                error_user_line = error_line - inst_lines
        resp = {
            "ok": r.returncode == 0,
            "output": "\n".join(text_out) + ("\n" + err if err else ""),
            "images": images,
            "files": files,
            "error": (error_type + (": " + error_msg if error_msg else "")) if r.returncode != 0 else None,
            "error_line": error_line,
            "error_user_line": error_user_line,
            "error_type": error_type,
        }
        return jsonify(resp)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/save_json", methods=["POST"])
def save_json():
    data = request.get_json(force=True)
    obj = (data or {}).get("json_file")
    if obj is None:
        return jsonify({"ok": False, "error": "json_file missing"}), 400
    out_dir = APP_DIR / "saved_json"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"agent-output-{ts}.json"
    pathlib.Path(out_path).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "path": str(out_path)})


@app.route("/test_response", methods=["GET"])
def test_response():
    sample = {
        "text": "Proposed two-lens system using BK7. See code for ray trace.",
        "code": "import matplotlib.pyplot as plt\nprint('Ray trace setup complete')\nplt.plot([0,1,2],[0,1,0])\nplt.title('Sample Ray Trace')\nplt.show()\nopen('report.txt','w').write('OK')\nprint('Wrote report.txt')",
        "code_meta": {"files_expected": ["report.txt"]},
        "json_file": {
            "system": "two_lens",
            "elements": [
                {"type": "lens", "material": "BK7", "radius_front_mm": 50, "radius_back_mm": -50, "thickness_mm": 5},
                {"type": "lens", "material": "BK7", "radius_front_mm": 30, "radius_back_mm": -30, "thickness_mm": 3}
            ],
            "spacing_mm": [20],
            "wavelength_nm": 532
        }
    }
    metrics = {"prep_ms": 5, "llm_ms": 42, "post_ms": 3, "retries": 1, "timestamp": int(time.time()*1000)}
    return jsonify({"ok": True, "response": sample, "metrics": metrics})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
