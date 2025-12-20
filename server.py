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
PREWARM_DONE = False

def start_mcp_server():
    """Start local MCP server client (optics_mcp/optics_server.py) once per process and prewarm once."""
    global MCP_CLIENT, PREWARM_DONE
    if MCP_CLIENT is None:
        script_path = str((APP_DIR / "optics_mcp" / "optics_server.py").resolve())
        MCP_CLIENT = Client(script_path)
    if not PREWARM_DONE:
        try:
            import asyncio
            async def _ping():
                async with MCP_CLIENT:
                    try:
                        await MCP_CLIENT.call_tool("ping", {})
                    except Exception:
                        pass
                    try:
                        await MCP_CLIENT.call_tool("exec_python_sandbox", {"code": "print('warmup')", "timeout_s": 5})
                    except Exception:
                        pass
            asyncio.run(_ping())
        except Exception:
            pass
        PREWARM_DONE = True

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

def simple_rag_retrieve(user_query: str) -> str:
    query = (user_query or "").lower()
    # Only the four curated knowledge files
    knowledge_map = {
        # Geometric Optics (ray/ABCD)
        "geometric": "knowledge/geometric_optics.txt",
        "ray": "knowledge/geometric_optics.txt",
        "abcd": "knowledge/geometric_optics.txt",
        "matrix": "knowledge/geometric_optics.txt",
        # Laser Physics (gain/pump/resonator specifics)
        "laser": "knowledge/laser_physics.txt",
        "gain": "knowledge/laser_physics.txt",
        "pump": "knowledge/laser_physics.txt",
        "resonator": "knowledge/laser_physics.txt",
        # Physical Optics (wave/fourier/diffraction)
        "physical": "knowledge/physical_optics.txt",
        "wave": "knowledge/physical_optics.txt",
        "fourier": "knowledge/physical_optics.txt",
        "fresnel": "knowledge/physical_optics.txt",
        "diffraction": "knowledge/physical_optics.txt",
        # Coding Standards
        "code": "knowledge/coding_standards.txt",
        "standard": "knowledge/coding_standards.txt",
        "standards": "knowledge/coding_standards.txt",
        "practice": "knowledge/coding_standards.txt",
        "simulate": "knowledge/coding_standards.txt",
        "optimize": "knowledge/coding_standards.txt",
        "simulation": "knowledge/coding_standards.txt",
        "optimization": "knowledge/coding_standards.txt",
    }
    context: list[str] = []
    files_to_read = set()
    files_to_read.add("knowledge/coding_standards.txt")
    for kw, fp in knowledge_map.items():
        if kw in query:
            files_to_read.add(fp)
    for fp in files_to_read:
        try:
            full = APP_DIR / fp
            if full.exists():
                context.append(f"--- REFERENCE DOC: {fp} ---\n{full.read_text(encoding='utf-8')}")
        except Exception as e:
            print(f"RAG Error reading {fp}: {e}")
    if not context:
        return ""
    return "\n".join(context)

def _rag_all_context() -> str:
    try:
        files = [
            APP_DIR / "knowledge" / "geometric_optics.txt",
            APP_DIR / "knowledge" / "laser_physics.txt",
            APP_DIR / "knowledge" / "physical_optics.txt",
            APP_DIR / "knowledge" / "coding_standards.txt",
        ]
        out = []
        for fp in files:
            if fp.exists():
                out.append(f"--- REFERENCE DOC: {fp.name} ---\n{fp.read_text(encoding='utf-8')}")
        return "\n".join(out)
    except Exception:
        return ""
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

def call_openrouter_drafter(messages: list[dict], model: str, max_tokens: int = 2000, temperature: float = 0.4, reasoning_effort: str = "low") -> tuple[str, Dict[str, Any], str]:
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
        "reasoning": {"effort": reasoning_effort},
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

def call_openrouter_thinker(messages: list[dict], model: str, max_tokens: int = 600, temperature: float = 0.2, reasoning_effort: str = "high") -> tuple[str, Dict[str, Any], str]:
    api_key = API_KEY_PATH.read_text().strip()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning": {"effort": reasoning_effort},
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


def _save_code(run_dir: pathlib.Path, filename: str, code: str):
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        p = run_dir / filename
        pathlib.Path(p).write_text(code or "", encoding="utf-8")
    except Exception:
        pass

def _run_code_subprocess(run_dir: pathlib.Path, code: str, timeout_s: int) -> Dict[str, Any]:
    try:
        import subprocess, io, base64, re, os
        pre_files = set()
        try:
            for p in run_dir.iterdir():
                if p.is_file():
                    pre_files.add(p.name)
        except Exception:
            pass
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
        program = instrument + "\n" + (code or "")
        r = subprocess.run(["python", "-c", program], cwd=str(run_dir), capture_output=True, text=True, timeout=max(1, int(timeout_s)))
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
        try:
            ignore = {"run_code_input.py", "run_code_output.txt", "files.lst", "interaction.txt", "drafter.py", "reviewer.py"}
            for p in run_dir.iterdir():
                if p.is_file() and (p.name not in pre_files) and (p.name not in ignore):
                    files.append(str(p.resolve()))
        except Exception:
            pass
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
                parts = last.split(":", 1)
                error_type = parts[0].strip()
                error_msg = parts[1].strip() if len(parts) > 1 else ""
            inst_lines = instrument.count("\n") + 1
            if error_line and error_line > inst_lines:
                error_user_line = error_line - inst_lines
        return {
            "ok": r.returncode == 0,
            "output": "\n".join(text_out) + ("\n" + err if err else ""),
            "images": images,
            "files": files,
            "error": (error_type + (": " + error_msg if error_msg else "")) if r.returncode != 0 else None,
            "error_line": error_line,
            "error_user_line": error_user_line,
            "error_type": error_type,
        }
    except Exception as e:
        return {"ok": False, "output": "", "images": [], "files": [], "error": str(e), "error_line": None, "error_user_line": None, "error_type": None}


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
        c = str(resp.get("code") or "")
        if c.strip():
            _save_code(run_dir, "reviewer.py", c)
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
            t_all_start = time.perf_counter()
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
                rag_cfg = cfg.get("rag", {})
                if bool(rag_cfg.get("include_all_to_reviewer")):
                    all_ctx = _rag_all_context()
                    if all_ctx:
                        rev_messages.insert(0, {"role": "system", "content": all_ctx})
                models_cfg = cfg.get("models", {})
                reviewer_fast = str(models_cfg.get("fast_reviewer_model") or reviewer_model)
                small_tokens = int(llmconf.get("max_tokens_reviewer_small", 400) or 400)
                small_temp = float(llmconf.get("temperature_reviewer_small", 0.2) or 0.2)
                small_effort = str(llmconf.get("reasoning_effort_reviewer_small", "none"))
                t_rev_start = time.perf_counter()
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
                c = str(resp.get("code") or "")
                if c.strip():
                    _save_code(run_dir, "reviewer.py", c)
                total_ms = int((time.perf_counter() - t_all_start) * 1000)
                rev_llm = rm.get("llm_ms") if isinstance(rm, dict) else None
                metrics_combined = {"total_ms": total_ms, "reviewer_ms": int(rev_llm or ((time.perf_counter() - t_rev_start) * 1000)), "timestamp": int(time.time()*1000)}
                q.put(("review", {"response": resp, "metrics": metrics_combined}))
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
            q.put(("status", {"message": "📚 Retrieving Physics Knowledge..."}))
            rag_cfg = cfg.get("rag", {})
            if bool(rag_cfg.get("include_all_to_thinker")):
                retrieved_context = _rag_all_context()
            else:
                retrieved_context = simple_rag_retrieve(user_text)
            q.put(("status", {"message": "🤔 Physicist is planning..."}))

            thinker_messages = [{"role": "system", "content": cfg.get("thinker", {}).get("system")}] + history + [{"role": "user", "content": user_text}]
            if retrieved_context:
                rag_instruction = (
                    f"User Query: {user_text}\n\n"
                    f"CRITICAL PHYSICS REFERENCES (MUST FOLLOW):\n{retrieved_context}\n\n"
                    "TASK: Create a Physics Blueprint based on the reference above."
                )
                thinker_messages = list(thinker_messages)
                thinker_messages[-1] = {"role": "user", "content": rag_instruction}
                _write_log(run_dir, [("RAG Context (Thinker):", retrieved_context)])
            t_think_start = time.perf_counter()
            plan_text, tm, raw_t = call_openrouter_thinker(
                thinker_messages,
                model=thinker_model,
                max_tokens=int(llmconf.get("max_tokens_thinker", 1200) or 1200),
                temperature=float(llmconf.get("temperature_thinker", 0.2) or 0.2),
                reasoning_effort=str(llmconf.get("reasoning_effort_thinker", "high")),
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
            rag_cfg = cfg.get("rag", {})
            if bool(rag_cfg.get("include_all_to_drafter")):
                all_ctx = _rag_all_context()
                if all_ctx:
                    drafter_messages.append({"role": "system", "content": all_ctx})
                    _write_log(run_dir, [("RAG Context (Drafter):", all_ctx)])
            drafter_messages.append({
                "role": "user", 
                "content": f"Here is the Physics Blueprint you must follow:\n{plan_text}\n\nUser Request: {user_text}"
            })

            d_tokens = int(llmconf.get("max_tokens_drafter", 4000) or 4000)
            d_temp = float(llmconf.get("temperature_drafter", 0.2) or 0.2)
            if not bool(rag_cfg.get("include_all_to_drafter")):
                try:
                    cs_full = APP_DIR / "knowledge" / "coding_standards.txt"
                    if cs_full.exists():
                        cs_text = cs_full.read_text(encoding="utf-8")
                        drafter_messages.append({"role": "system", "content": f"CODING STANDARDS:\n{cs_text}"})
                        _write_log(run_dir, [("RAG Context (Drafter):", cs_text)])
                except Exception as e:
                    print(f"RAG Error reading coding standards: {e}")
            t_draft_start = time.perf_counter()
            code, m, raw_d = call_openrouter_drafter(drafter_messages, drafter_model, max_tokens=d_tokens, temperature=d_temp, reasoning_effort=str(llmconf.get("reasoning_effort_drafter", "low")))
            
            _write_log(run_dir, [
                ("Drafter Prompt (with plan):", json.dumps(drafter_messages, indent=2)),
                ("Drafter Output:", raw_d),
            ])
            if str(code or "").strip():
                _save_code(run_dir, "drafter.py", code)
            
            # Stream the draft to UI immediately
            _append_history(conv_id, "assistant", code[:200])
            q.put(("draft", {"code": code, "metrics": m, "raw": raw_d}))

            # STEP 3: REVIEWER (The QA)
            q.put(("status", {"message": "🔍 Reviewing & Validating..."}))
            
            rev_system = build_system_prompt(cfg)
            
            # Construct a specific Review Packet
            # We explicitly show the Reviewer the Request and the Draft
            
            cs_text_block = ""
            try:
                cs_full_for_rev = APP_DIR / "knowledge" / "coding_standards.txt"
                if cs_full_for_rev.exists():
                    cs_text_block = cs_full_for_rev.read_text(encoding="utf-8")
            except Exception:
                cs_text_block = ""
            review_packet = (
                f"User Request: {user_text}\n\n"
                f"Physics Plan Used:\n{plan_text}\n\n"
                f"Draft Code Generated:\n{code}\n\n"
                + (f"OUR CODING STANDARDS:\n{cs_text_block}\n\n" if cs_text_block else "")
                + "TASK: Validate this code. Make sure the geometry proposed makes sense, that the method of finding the parameters is valid, efficient and with reasonable physical bounds, and that the physics equations for this system were correctly proposed, FIX IT."
            )
            
            rev_messages = [{"role": "system", "content": rev_system}] + history + [{"role": "user", "content": review_packet}]
            rag_cfg = cfg.get("rag", {})
            if bool(rag_cfg.get("include_all_to_reviewer")):
                all_ctx = _rag_all_context()
                if all_ctx:
                    rev_messages.insert(0, {"role": "system", "content": all_ctx})
            models_cfg = cfg.get("models", {})
            reviewer_fast = str(models_cfg.get("fast_reviewer_model") or reviewer_model)
            t_rev_start = time.perf_counter()
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
            c = str(resp.get("code") or "")
            if c.strip():
                _save_code(run_dir, "reviewer.py", c)
            
            total_ms = int((time.perf_counter() - t_all_start) * 1000)
            metrics_combined = {
                "total_ms": total_ms,
                "thinker_ms": int((tm.get("llm_ms") if isinstance(tm, dict) else ((time.perf_counter() - t_think_start) * 1000))),
                "drafter_ms": int((m.get("llm_ms") if isinstance(m, dict) else ((time.perf_counter() - t_draft_start) * 1000))),
                "reviewer_ms": int((rm.get("llm_ms") if isinstance(rm, dict) else ((time.perf_counter() - t_rev_start) * 1000))),
                "timestamp": int(time.time()*1000)
            }
            q.put(("review", {"response": resp, "metrics": metrics_combined}))

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
    timeout_s = int((data or {}).get("timeout_s") or 40)
    try:
        print("/run_code: received request, code_len=", len(code or ""))
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_dir = APP_DIR / "tmp_runs" / f"exec-{ts}-{uuid.uuid4()}"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "run_code_input.py").write_text(code or "", encoding="utf-8")
            _write_log(run_dir, [("Run Code Input:", (code or "")[:1000])])
            print("/run_code: saved input at", str(run_dir))
        except Exception:
            pass
        fb = _run_code_subprocess(run_dir, code, timeout_s)
        ok = bool(fb.get("ok"))
        try:
            out_text = fb.get("output") or ""
            files_list = fb.get("files") or []
            (run_dir / "run_code_output.txt").write_text(out_text, encoding="utf-8")
            (run_dir / "files.lst").write_text("\n".join(map(str, files_list)), encoding="utf-8")
            _write_log(run_dir, [("Run Code Output:", out_text), ("Run Code Files:", "\n".join(map(str, files_list)))])
            print("/run_code: tool returned ok=", ok, " output_len=", len(out_text), " files_count=", len(files_list))
        except Exception:
            pass
        extra_files = []
        try:
            for name in ["run_code_input.py", "run_code_output.txt", "files.lst"]:
                p = run_dir / name
                if p.exists():
                    extra_files.append(str(p.resolve()))
        except Exception:
            pass
        print("/run_code: responding JSON, extra_files=", len(extra_files))
        return jsonify({
            "ok": ok,
            "output": fb.get("output") or "",
            "images": fb.get("images") or [],
            "files": fb.get("files") or [],
            "error": None if ok else "execution failed",
            "error_line": fb.get("error_line"),
            "error_user_line": fb.get("error_user_line"),
            "error_type": fb.get("error_type"),
        })
    except Exception as e:
        print("/run_code: exception:", str(e))
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
    try:
        code = sample["code"]
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_dir = APP_DIR / "tmp_runs" / f"selftest-{ts}-{uuid.uuid4()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_code_input.py").write_text(code or "", encoding="utf-8")
        fb = _run_code_subprocess(run_dir, code, 5)
        out_text = fb.get("output") or ""
        files_list = fb.get("files") or []
        (run_dir / "run_code_output.txt").write_text(out_text, encoding="utf-8")
        (run_dir / "files.lst").write_text("\n".join(map(str, files_list)), encoding="utf-8")
        return jsonify({"ok": True, "response": sample, "metrics": metrics, "run": {"output": out_text, "files": files_list}})
    except Exception:
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

@app.route("/status", methods=["GET"])
def status():
    report = {
        "flask_server": "ok",
        "mcp_server": "unknown",
        "mcp_tools": [],
        "mcp_resources": []
    }
    try:
        script_path = str((APP_DIR 
                           / "optics_mcp" 
                           / "optics_server.py").resolve())
        import asyncio
        from fastmcp import Client as FastClient
        client = FastClient(script_path)
        async def _check():
            async with client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                return tools, resources
        tools, resources = asyncio.run(_check())
        report["mcp_server"] = "connected"
        report["mcp_tools"] = [getattr(t, "name", str(t)) for t in (tools or [])]
        report["mcp_resources"] = [getattr(r, "name", str(r)) for r in (resources or [])]
    except Exception as e:
        report["mcp_server"] = f"error: {str(e)}"
    return jsonify(report)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
