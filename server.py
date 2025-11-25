"""AI Optics Agent UI server

Implements a two-stage streaming pipeline (Drafter → Reviewer) and a single-pass
JSON-structured response path. Integrates MCP resources for schema/guardrails,
executes returned code in a sandbox, and persists readable interaction logs.
"""
import json
import pathlib
import time
from typing import Any, Dict

from flask import Flask, request, send_from_directory, jsonify, Response
from flask import stream_with_context
import requests
import subprocess
import sys
from fastmcp import Client
import threading
import queue
import uuid
import os

APP_DIR = pathlib.Path(__file__).parent.resolve()
STATIC_DIR = APP_DIR / "static"
CONFIG_PATH = APP_DIR / "pipeline_context.json"
API_KEY_PATH = APP_DIR / "openrouter_api.txt"

app = Flask(__name__, static_folder=str(STATIC_DIR))
CONVERSATIONS: dict[str, list[dict]] = {}

# Start MCP client early so it's available when chat handler runs
MCP_CLIENT = None

def start_mcp_server():
    """Start local MCP server client (optics_mcp/optics_server.py) once per process."""
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
    reviewer = cfg.get("reviewer", {})
    s = str(reviewer.get("system") or "")
    if s:
        return s
    base = (
        "You are the Optics Chat Agent. Return a single JSON object (text, code, code_meta, json_file).\n"
        "Validate and correct code: fix typos, syntax errors, unphysical assumptions, and bad practices; ensure code runs as-is.\n"
        "Use MCP resources 'resource://ui-output-format' and 'resource://optics-guardrails'."
    )
    return base


def _response_json_schema() -> Dict[str, Any]:
    """Return the OpticsAgentResponse JSON Schema; fallback to a minimal valid schema."""
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


def _extract_code_text(s: str) -> str:
    """Extract code from fenced blocks or return raw text."""
    t = s.strip()
    if "```" in t:
        parts = t.split("```")
        if len(parts) >= 3:
            body = parts[1]
            if "\n" in body:
                first = body.split("\n", 1)[1]
                return first
            return body
    return t

def _looks_like_json(s: str) -> bool:
    s = (s or "").strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))

def _normalize_response(obj: Dict[str, Any]) -> Dict[str, Any]:
    try:
        t = obj.get("text")
        if isinstance(t, str) and _looks_like_json(t):
            inner = json.loads(t)
            if isinstance(inner, dict):
                for k in ["text", "code", "code_meta", "json_file"]:
                    if k in inner:
                        obj[k] = inner[k]
    except Exception:
        pass
    return obj


# def call_openrouter_drafter(messages: list[dict], model: str, max_tokens: int = 8000, temperature: float = 0.1) -> tuple[str, Dict[str, Any], str]:
#     """Call a fast model to produce raw Python code; handles agentic tool-call outputs."""
#     api_key = API_KEY_PATH.read_text().strip()
#     url = "https://openrouter.ai/api/v1/chat/completions"
#     headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
#     payload = {
#         "model": model,
#         "messages": messages,
#         "max_tokens": max_tokens,
#         "temperature": temperature,
#     }
#     t0 = time.perf_counter()
#     r = requests.post(url, headers=headers, json=payload, timeout=600)
#     out = r.json()
#     if "choices" not in out or not out["choices"]:
#         raise RuntimeError(f"Invalid LLM response: {json.dumps(out)[:500]}")
#     choice = out["choices"][0]
#     message = choice.get("message", {})
#     content = message.get("content")
#     if not content:
#         if message.get("tool_calls"):
#             try:
#                 args = message["tool_calls"][0]["function"]["arguments"]
#                 print("DRAFTER tool_calls arguments detected")
#                 if isinstance(args, str) and args.strip().startswith("{"):
#                     try:
#                         arg_json = json.loads(args)
#                         content = arg_json.get("code") or arg_json.get("script") or args
#                     except Exception:
#                         content = args
#                 else:
#                     content = args
#             except Exception:
#                 content = ""
#         elif message.get("reasoning"):
#             print("DRAFTER reasoning field used")
#             content = message.get("reasoning")
#     if isinstance(content, dict):
#         code = str(content.get("code") or "")
#     else:
#         code = _extract_code_text(str(content or ""))
#     dt = int((time.perf_counter() - t0) * 1000)
#     conf = 0.4
#     L = len(code or "")
#     if L >= 200:
#         conf += 0.2
#     if "import" in (code or ""):
#         conf += 0.15
#     if any(k in (code or "") for k in ["plt.", "numpy", "np.", "ray", "lens"]):
#         conf += 0.15
#     if (choice.get("finish_reason") or "") == "length":
#         conf -= 0.1
#     conf = max(0.0, min(0.95, conf))
#     raw = content if isinstance(content, str) else json.dumps(content or {})
#     return code, {"llm_ms": dt, "usage": out.get("usage"), "finish_reason": choice.get("finish_reason"), "confidence": round(conf, 2)}, raw

def call_openrouter_drafter(messages: list[dict], model: str, max_tokens: int = 2000, temperature: float = 0.4) -> tuple[str, Dict[str, Any], str]:
    """Call a fast model to produce raw Python code; handles agentic tool-call outputs."""
    api_key = API_KEY_PATH.read_text().strip()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages_with_prefill = messages + [{"role": "assistant", "content": "```python\nimport numpy as np"}]

    payload = {
        "model": model,
        "messages": messages_with_prefill, # <--- We send the forced start
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    t0 = time.perf_counter()
    r = requests.post(url, headers=headers, json=payload, timeout=600)
    
    try:
        out = r.json()
    except:
        raise RuntimeError(f"Invalid JSON from LLM: {r.text[:200]}")

    if "choices" not in out or not out["choices"]:
        raise RuntimeError(f"Invalid LLM response structure: {json.dumps(out)[:200]}")
    
    choice = out["choices"][0]
    message = choice.get("message", {})
    content = message.get("content")
    
    # --- Extraction Logic ---
    if not content:
        if message.get("tool_calls"):
            try:
                args = message["tool_calls"][0]["function"]["arguments"]
                # Handle JSON arguments
                if isinstance(args, str) and args.strip().startswith("{"):
                    try:
                        arg_json = json.loads(args)
                        content = arg_json.get("code") or arg_json.get("script") or arg_json.get("body") or args
                    except:
                        content = args
                else:
                    content = args
            except:
                content = ""
        elif message.get("reasoning"):
            content = message.get("reasoning")
            
    if isinstance(content, dict):
        code = str(content.get("code") or "")
    else:
        code = _extract_code_text(str(content or ""))
    
    # Ensure imports are present when models omit them
    if code.strip() and ("import numpy" not in code):
        code = "import numpy as np\n" + code

    dt = int((time.perf_counter() - t0) * 1000)
    
    # Confidence metrics
    conf = 0.4
    L = len(code or "")
    if L >= 200: conf += 0.2
    if "np." in (code or ""): conf += 0.2 # Check for numpy specifically
    if (choice.get("finish_reason") or "") == "length": conf -= 0.1
    conf = max(0.0, min(0.95, conf))
    
    raw = content if isinstance(content, str) else json.dumps(content or {})
    return code, {"llm_ms": dt, "usage": out.get("usage"), "finish_reason": choice.get("finish_reason"), "confidence": round(conf, 2)}, raw

def call_openrouter_thinker(messages: list[dict], model: str, max_tokens: int = 600, temperature: float = 0.2) -> tuple[str, Dict[str, Any], str]:
    api_key = API_KEY_PATH.read_text().strip()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    t0 = time.perf_counter()
    r = requests.post(url, headers=headers, json=payload, timeout=600)
    try:
        out = r.json()
    except Exception:
        raise RuntimeError(f"Invalid JSON from LLM: {r.text[:200]}")
    if "choices" not in out or not out["choices"]:
        raise RuntimeError(f"Invalid LLM response: {json.dumps(out)[:500]}")
    choice = out["choices"][0]
    message = choice.get("message", {})
    content = message.get("content")
    plan_text = ""
    if isinstance(content, dict):
        plan_text = str(content.get("text") or content.get("plan") or "")
    else:
        plan_text = str(content or "")
    dt = int((time.perf_counter() - t0) * 1000)
    raw = content if isinstance(content, str) else json.dumps(content or {})
    metrics = {"llm_ms": dt, "finish_reason": choice.get("finish_reason"), "usage": out.get("usage")}
    return plan_text, metrics, raw

def call_openrouter_reviewer(messages: list[dict], model: str, max_tokens: int = 6000, reasoning_effort: str = "low", temperature: float = 0.4) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """Call the reviewer model to return strict JSON; normalize nested JSON-in-text.

    Uses provider-compatible `strict: false` and local validation, retrying once with
    a corrective nudge when the model violates the schema.
    """
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
    t0 = time.perf_counter()
    r = requests.post(url, headers=headers, json=payload, timeout=600)
    out = r.json()
    if "choices" not in out or not out["choices"]:
        raise RuntimeError(f"Invalid LLM response: {json.dumps(out)[:500]}")
    choice = out["choices"][0]
    content = choice["message"].get("content")
    if isinstance(content, dict):
        try:
            from optics_mcp.optics_server import OpticsAgentResponse
            OpticsAgentResponse.model_validate(content)
        except Exception as ve:
            # retry once with a corrective nudge
            messages = messages + [{"role": "system", "content": f"Validation error: {str(ve)}. Return corrected JSON per schema only."}]
            payload["messages"] = messages
            r = requests.post(url, headers=headers, json=payload, timeout=600)
            out = r.json()
            choice = out.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content") or content
        dt = int((time.perf_counter() - t0) * 1000)
        conf = 0.6
        try:
            has_code = bool(content.get("code"))
            has_json = bool(content.get("json_file"))
            if has_code:
                conf += 0.2
            if has_json:
                conf += 0.15
        except Exception:
            pass
        if (choice.get("finish_reason") or "") == "length":
            conf -= 0.1
        conf = max(0.0, min(0.98, conf))
        content = _normalize_response(content)
        raw = json.dumps(content or {})
        return content, {"llm_ms": dt, "usage": out.get("usage"), "finish_reason": choice.get("finish_reason"), "confidence": round(conf, 2)}, raw
    s = str(content or "").strip()
    try:
        obj = json.loads(s)
    except Exception:
        obj = {"text": s, "code": None, "code_meta": None, "json_file": None}
    dt = int((time.perf_counter() - t0) * 1000)
    conf = 0.5
    if isinstance(obj, dict):
        if obj.get("code"):
            conf += 0.2
        if obj.get("json_file"):
            conf += 0.2
    if (choice.get("finish_reason") or "") == "length":
        conf -= 0.1
    conf = max(0.0, min(0.95, conf))
    raw = s
    obj = _normalize_response(obj)
    return obj, {"llm_ms": dt, "usage": out.get("usage"), "finish_reason": choice.get("finish_reason"), "confidence": round(conf, 2)}, raw


def call_openrouter(messages: list[dict], model: str, max_tokens: int = 2000, retries: int = 1, reasoning_effort: str = "low", temperature: float = 0.2) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """Single-pass JSON path for non-streaming; normalize nested JSON.

    Retries once with a corrective nudge when local validation fails.
    """
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
                content = _normalize_response(content)
                raw = json.dumps(content or {})
                return content, metrics, raw
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
                        obj = _normalize_response(obj)
                        return obj, metrics, s
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

def _write_log(run_dir: pathlib.Path, sections: list[tuple[str, str]]):
    """Append titled sections to tmp_runs/<uuid>/interaction.txt for auditability."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        p = run_dir / "interaction.txt"
        with open(p, "a", encoding="utf-8") as f:
            for title, body in sections:
                f.write(title + "\n")
                f.write(body + "\n\n")
    except Exception:
        pass


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
    reviewer_model = (data or {}).get("model") or (cfg.get("models", {})).get("reviewer_model") or "openai/gpt-4.1-mini"
    conv_id = (data or {}).get("conversation_id") or "default"
    rconf = cfg.get("reviewer", {})
    limit_msgs = int(rconf.get("include_history_messages", 5) or 0)
    clip_chars = int(rconf.get("clip_user_chars", 800) or 800)
    add_clip = int(rconf.get("clip_extra_context_chars", 1500) or 1500)
    system_prompt = build_system_prompt(cfg)
    history = _get_history(conv_id, limit_msgs, clip_chars)
    if bool(rconf.get("include_session_constraints")):
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
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_dir = APP_DIR / "tmp_runs" / f"{ts}-{uuid.uuid4()}"
        resp, call_metrics, raw_text = call_openrouter(
            messages,
            reviewer_model,
            max_tokens=min(int((cfg.get("llm", {}) or {}).get("max_tokens_reviewer", 2000) or 2000), 50000),
            retries=2,
            reasoning_effort=str((cfg.get("llm", {}) or {}).get("reasoning_effort_reviewer", "low")),
            temperature=float((cfg.get("llm", {}) or {}).get("temperature_reviewer", 0.2) or 0.2),
        )
        _write_log(run_dir, [
            ("User said:", user_text),
            ("Reviewer was called and was given this context and prompt:", json.dumps(messages, indent=2)),
            ("Reviewer Raw Reply:", raw_text),
            ("Final Parsed reply:", json.dumps(resp, indent=2)),
        ])
        assistant_text = resp.get("text") or "Provided structured output"
        _append_history(conv_id, "assistant", assistant_text)
        post_ms = int((time.perf_counter() - t0) * 1000) - prep_ms - call_metrics.get("llm_ms", 0)
        metrics = {"prep_ms": prep_ms, **call_metrics, "post_ms": max(post_ms, 0), "timestamp": int(time.time()*1000)}
        return jsonify({"ok": True, "response": resp, "metrics": metrics})
    except Exception as e:
        if isinstance(e, LLMJSONError):
            return jsonify({"ok": False, "error": str(e), "raw_response": e.raw_out, "raw_message": e.raw_content}), 400
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/chat_flow", methods=["POST"])
def chat_flow():
    cfg = load_config()
    data = request.get_json(force=True)
    user_text = (data or {}).get("message", "")
    conv_id = (data or {}).get("conversation_id") or "default"
    dconf = cfg.get("drafter", {})
    rconf = cfg.get("reviewer", {})
    tconf = cfg.get("thinker", {})
    llmconf = cfg.get("llm", {})
    limit_msgs = int(dconf.get("include_history_messages", 0) or 0)
    clip_chars = int(dconf.get("clip_user_chars", 800) or 800)
    add_clip = int(dconf.get("clip_extra_context_chars", 1500) or 1500)
    drafter_model = str((cfg.get("models", {})).get("drafter_model") or "minimax/minimax-m2")
    reviewer_model = str((cfg.get("models", {})).get("reviewer_model") or "openai/gpt-4o")
    thinker_model = str((cfg.get("models", {})).get("thinker_model") or "google/gemini-2.0-flash-exp")
    system_prompt = str(dconf.get("system") or "Return only Python code for optics simulation; no JSON; ensure runnable without args.")
    history = _get_history(conv_id, limit_msgs, clip_chars)
    extra_ctx = (data or {}).get("extra_context") or []
    ctx_lines = []
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
    ctx_message = [{"role": "system", "content": ("Previous run context:\n" + ctx_block)}] if (ctx_block and bool(dconf.get("include_previous_run_context", True))) else []
    messages = [{"role": "system", "content": system_prompt}] + history + ctx_message + [{"role": "user", "content": user_text}]
    thinker_system = str(tconf.get("system") or "You are a Physics Planner. Output ONLY concise bullet points for physical constraints, formulas (e.g., ABCD matrices), parameter relations, and allowed Python libraries. Do NOT write code.")
    thinker_messages = [{"role": "system", "content": thinker_system}] + [{"role": "user", "content": user_text}]
    q = queue.Queue()
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = APP_DIR / "tmp_runs" / f"{ts}-{uuid.uuid4()}"
    _write_log(run_dir, [("User said:", user_text)])
   
    def _drafter():
        try:
            # Load specific configs
            llmconf = cfg.get("llm", {})
            dconf = cfg.get("drafter", {})
            # Fast gating: if not a code/simulation request, skip Thinker/Drafter
            t = (user_text or "").lower().strip()
            kws = list(dconf.get("keywords_trigger", [])) or [
                "simulate","plot","code","python","diffraction","optics",
                "design","beam","matrix","ray","lens","cavity","laser","run"
            ]
            should_draft = len(t) > 2 and any(k in t for k in kws)
            if not should_draft:
                rev_system = build_system_prompt(cfg)
                rev_messages = [{"role": "system", "content": rev_system}] + history + ctx_message + [{"role": "user", "content": user_text}]
                models_cfg = cfg.get("models", {})
                reviewer_fast = str(models_cfg.get("fast_reviewer_model") or reviewer_model)
                small_tokens = int(llmconf.get("max_tokens_reviewer_small", 400) or 400)
                small_temp = float(llmconf.get("temperature_reviewer_small", 0.2) or 0.2)
                small_effort = str(llmconf.get("reasoning_effort_reviewer_small", "none"))
                resp, rm, raw_r = call_openrouter_reviewer(
                    rev_messages,
                    reviewer_fast,
                    max_tokens=small_tokens,
                    reasoning_effort=small_effort,
                    temperature=small_temp,
                )
                _write_log(run_dir, [
                    ("Reviewer (Direct) Prompt:", json.dumps(rev_messages, indent=2)),
                    ("Reviewer Raw Reply:", raw_r),
                    ("Final Parsed reply:", json.dumps(resp, indent=2)),
                ])
                q.put(("review", {"response": resp, "metrics": rm}))
                return
            
            # 1. Check if we need to draft code or just chat
            t = (user_text or "").lower().strip()
            kws = list(dconf.get("keywords_trigger", [])) or ["simulate","plot","code","python","diffraction","optics","design","beam","matrix","ray","lens","cavity","laser","run"]
            should_draft = len(t) > 2 and any(k in t for k in kws)

            if not should_draft:
                # --- DIRECT PATH (Chat only) ---
                # Skip Thinker/Drafter, go straight to Reviewer (UserChat)
                rev_system = build_system_prompt(cfg)
                rev_messages = [{"role": "system", "content": rev_system}] + history + ctx_message + [{"role": "user", "content": user_text}]
                
                resp, rm, raw_r = call_openrouter_reviewer(
                    rev_messages, 
                    reviewer_model, 
                    max_tokens=min(int(llmconf.get("max_tokens_reviewer", 2000) or 2000), 50000), 
                    # reasoning_effort=str(llmconf.get("reasoning_effort_reviewer", "low")), 
                    reasoning_effort="low",
                    temperature=float(llmconf.get("temperature_reviewer", 0.2) or 0.2)
                )
                
                _write_log(run_dir, [
                    ("Reviewer (Direct) Prompt:", json.dumps(rev_messages, indent=2)),
                    ("Reviewer Raw Reply:", raw_r),
                    ("Final Parsed reply:", json.dumps(resp, indent=2)),
                ])
                q.put(("review", {"response": resp, "metrics": rm}))
                return

            # --- AGENTIC PATH (Think -> Draft -> Review) ---

            # STEP 1: THINKER (The Physicist)
            q.put(("status", {"message": "🤔 Physicist is planning..."}))
            
            thinker_messages = [{"role": "system", "content": cfg.get("thinker", {}).get("system")}] + history + [{"role": "user", "content": user_text}]
            plan_text, tm, raw_t = call_openrouter_thinker(
                thinker_messages,
                model=thinker_model,
                max_tokens=int(llmconf.get("max_tokens_thinker", 1200) or 1200),
                temperature=float(llmconf.get("temperature_thinker", 0.2) or 0.2),
            )
            if not str(plan_text or "").strip():
                need = int(llmconf.get("max_tokens_thinker", 1200) or 1200)
                msg = f"Thinker returned no plan. Increase 'max_tokens_thinker' (current {need}) and retry — e.g., double it."
                _write_log(run_dir, [
                    ("Thinker Prompt:", json.dumps(thinker_messages, indent=2)),
                    ("Thinker Raw Reply:", raw_t),
                    ("Notice:", msg),
                ])
                q.put(("error", {"error": msg}))
                return
            
            _write_log(run_dir, [
                ("Thinker Prompt:", json.dumps(thinker_messages, indent=2)),
                ("Physicist Plan:", plan_text)
            ])

            # STEP 2: DRAFTER (The Coder)
            q.put(("status", {"message": "💻 Drafting Code..."}))
            print("DRAFTER model:", drafter_model)
            
            # Construct Drafter Context: System + History + PLAN + User Request
            # We inject the plan as a "User" instruction to ensure it is followed.
            drafter_messages = [{"role": "system", "content": system_prompt}] + history + ctx_message
            drafter_messages.append({
                "role": "user", 
                "content": f"Here is the Physics Blueprint you must follow:\n{plan_text}\n\nUser Request: {user_text}"
            })

            d_tokens = int(llmconf.get("max_tokens_drafter", 4000) or 4000)
            d_temp = float(llmconf.get("temperature_drafter", 0.2) or 0.2)
            
            code, m, raw_d = call_openrouter_drafter(drafter_messages, drafter_model, max_tokens=d_tokens, temperature=d_temp)
            
            _write_log(run_dir, [
                ("Drafter Prompt (with plan):", json.dumps(drafter_messages, indent=2)),
                ("Drafter Output:", raw_d),
            ])
            
            # Stream the draft to UI immediately
            _append_history(conv_id, "assistant", code[:200])
            q.put(("draft", {"code": code, "metrics": m, "raw": raw_d}))

            # STEP 3: REVIEWER (The QA)
            q.put(("status", {"message": "🔍 Reviewing & Validating..."}))
            
            rev_system = build_system_prompt(cfg)
            
            # Construct a specific Review Packet
            # We explicitly show the Reviewer the Request and the Draft
            review_packet = (
                f"User Request: {user_text}\n\n"
                f"Physics Plan Used:\n{plan_text}\n\n"
                f"Draft Code Generated:\n{code}\n\n"
                "TASK: Validate this code. If it fails the physics check (e.g. wrong matrix order), FIX IT."
            )
            
            rev_messages = [{"role": "system", "content": rev_system}] + history + [{"role": "user", "content": review_packet}]
            models_cfg = cfg.get("models", {})
            reviewer_fast = str(models_cfg.get("fast_reviewer_model") or reviewer_model)
            resp, rm, raw_r = call_openrouter_reviewer(
                rev_messages,
                reviewer_fast,
                max_tokens=int(llmconf.get("max_tokens_reviewer", 3000) or 3000),
                reasoning_effort=str(llmconf.get("reasoning_effort_reviewer", "low")),
                temperature=float(llmconf.get("temperature_reviewer", 0.4) or 0.4),
            )
            
            _write_log(run_dir, [
                ("Reviewer Prompt:", json.dumps(rev_messages, indent=2)),
                ("Reviewer Raw Reply:", raw_r),
                ("Final Parsed reply:", json.dumps(resp, indent=2)),
            ])
            
            q.put(("review", {"response": resp, "metrics": rm}))

        except Exception as e:
            q.put(("error", {"error": str(e)}))
        finally:
            q.put(("done", {}))
    threading.Thread(target=_drafter, daemon=True).start()
    @stream_with_context
    def _stream():
        while True:
            kind, payload = q.get()
            if kind == "draft":
                yield "event: draft\n" + "data: " + json.dumps(payload) + "\n\n"
            elif kind == "review":
                yield "event: review\n" + "data: " + json.dumps(payload) + "\n\n"
            elif kind == "error":
                yield "event: error\n" + "data: " + json.dumps(payload) + "\n\n"
            elif kind == "done":
                yield "event: done\n" + "data: {}\n\n"
                break
    return Response(_stream(), mimetype="text/event-stream")


@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.get_json(force=True)
    code = (data or {}).get("code", "")
    code_meta = (data or {}).get("code_meta")
    try:
        if MCP_CLIENT is None:
            start_mcp_server()
        import asyncio
        async def _run():
            async with MCP_CLIENT:
                res = await MCP_CLIENT.call_tool("exec_python_sandbox", {"code": code})
                return res
        result = asyncio.run(_run())
        ok = bool(result.get("ok"))
        return jsonify({
            "ok": ok,
            "output": result.get("output") or "",
            "images": result.get("images") or [],
            "files": [],
            "error": None if ok else "execution failed",
            "error_line": None,
            "error_user_line": None,
            "error_type": None,
        })
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

@app.route("/config_models", methods=["GET"])
def config_models():
    cfg = load_config()
    models = cfg.get("models", {})
    return jsonify({
        "drafter_model": models.get("drafter_model"),
        "reviewer_model": models.get("reviewer_model"),
        "thinker_model": models.get("thinker_model"),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
