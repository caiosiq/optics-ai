"""AI Optics Agent UI server

Implements the Cyber-Physical System (CPS) architecture with distinct Stages.
"""
import json
import pathlib
import time
import uuid
from typing import Any, Dict

from flask import Flask, request, send_from_directory, jsonify, Response, stream_with_context
from fastmcp import Client

# Core Imports
from core.config import load_config, APP_DIR
from core.session import Session
from core.llm import call_openrouter

app = Flask(__name__, static_folder=str(APP_DIR / "static"))

# Global Stores
SESSIONS: Dict[str, Session] = {}

# Start MCP client early so it's available
MCP_CLIENT = None
PREWARM_DONE = False

def start_mcp_server():
    """Start local MCP server client (optics_mcp/optics_server.py)."""
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
            asyncio.run(_ping())
        except Exception:
            pass
        PREWARM_DONE = True

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

@app.route("/load_session", methods=["POST"])
def load_session():
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    state = data.get("state")
    
    if not conv_id or not state:
        return jsonify({"ok": False, "error": "Missing data"}), 400
        
    # Recreate Session
    session = Session(conv_id, state, client=MCP_CLIENT)
    SESSIONS[conv_id] = session
    
    return jsonify({"ok": True})

@app.route("/init_design", methods=["POST"])
def init_design():
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    goal = data.get("goal")
    inventory = data.get("inventory")
    model = data.get("model") 
    
    if not all([conv_id, goal, inventory]):
        return jsonify({"ok": False, "error": "Missing fields"}), 400

    session = Session(conv_id, client=MCP_CLIENT)
    SESSIONS[conv_id] = session
    
    try:
        result = session.run_init(goal, inventory)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/chat_flow", methods=["POST"])
def chat_flow():
    data = request.get_json(force=True)
    user_text = data.get("message", "")
    conv_id = data.get("conversation_id")
    
    if conv_id in SESSIONS:
        session = SESSIONS[conv_id]
        return Response(stream_with_context(session.run_chat(user_text)), mimetype="text/event-stream")

    return jsonify({"error": "No active design session."}), 400

@app.route("/generate_lab_plan", methods=["POST"])
def generate_lab_plan():
    """
    Endpoint for Construction Stage to generate the plan.
    """
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    
    if conv_id in SESSIONS:
        session = SESSIONS[conv_id]
        try:
            result = session.run_generation()
            if "error" in result:
                return jsonify({"ok": False, "error": result["error"]}), 400
            return jsonify({"ok": True, "result": result})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
            
    return jsonify({"error": "No active session."}), 400

@app.route("/generate_robot_code", methods=["POST"])
def generate_robot_code():
    """
    Endpoint for Robot Stage to generate the code.
    """
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    
    if conv_id in SESSIONS:
        session = SESSIONS[conv_id]
        try:
            result = session.run_assembly()
            if "error" in result:
                return jsonify({"ok": False, "error": result["error"]}), 400
            return jsonify({"ok": True, "result": result})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
            
    return jsonify({"error": "No active session."}), 400

@app.route("/transition_stage", methods=["POST"])
def transition_stage():
    """
    Manually transition to a target stage (e.g. ROBOT_ASSEMBLY).
    """
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    target_stage = data.get("stage")
    
    if conv_id in SESSIONS:
        session = SESSIONS[conv_id]
        if target_stage:
            session.state["stage"] = target_stage
            session.update_state(session.state)
            return jsonify({"ok": True, "state": session.state})
            
    return jsonify({"error": "No active session."}), 400

@app.route("/update_parameter", methods=["POST"])
def update_parameter():
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    name = data.get("name")
    value = data.get("value")
    
    if conv_id in SESSIONS:
        session = SESSIONS[conv_id]
        from core.state import DesignState
        ds = DesignState(**session.state)
        if ds.update_param(name, value):
            session.update_state(ds.model_dump())
            return jsonify({"ok": True, "state": session.state})
        else:
            return jsonify({"ok": False, "error": "Parameter not found"}), 404
    
    return jsonify({"ok": False, "error": "Session not found"}), 404

@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.get_json(force=True)
    code = data.get("code", "")
    timeout_s = int(data.get("timeout_s") or 40)
    
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = APP_DIR / "tmp_runs" / f"exec-{ts}-{uuid.uuid4()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    (run_dir / "run_code_input.py").write_text(code, encoding="utf-8")
    
    import subprocess
    import sys
    
    cmd = [sys.executable, str(run_dir / "run_code_input.py")]
    try:
        instrumented_code = (
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
        ) + "\n" + code
        
        (run_dir / "run_code_input_inst.py").write_text(instrumented_code, encoding="utf-8")
        
        r = subprocess.run(
            [sys.executable, str(run_dir / "run_code_input_inst.py")],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s
        )
        
        out = r.stdout or ""
        err = r.stderr or ""
        
        images = []
        clean_out = []
        for line in out.splitlines():
            if line.startswith("[[IMAGE]]"):
                images.append(line[9:])
            else:
                clean_out.append(line)
        
        return jsonify({
            "ok": r.returncode == 0,
            "output": "\n".join(clean_out) + ("\nError:\n" + err if err else ""),
            "images": images,
            "files": [], 
            "error": None if r.returncode == 0 else "Execution failed"
        })
        
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/save_json", methods=["POST"])
def save_json():
    data = request.get_json(force=True)
    obj = data.get("json_file")
    if not obj:
        return jsonify({"ok": False, "error": "No json_file provided"}), 400
    
    out_dir = APP_DIR / "saved_json"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    p = out_dir / f"output-{ts}.json"
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "path": str(p)})

@app.route("/config_models", methods=["GET"])
def config_models():
    cfg = load_config()
    return jsonify({
        "drafter_model": cfg.get("models", {}).get("drafter_model"),
        "reviewer_model": cfg.get("models", {}).get("reviewer_model"),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
