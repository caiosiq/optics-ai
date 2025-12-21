"""AI Optics Agent UI server

Implements the Cyber-Physical System (CPS) architecture with an Architect Agent
managing the design state and Physics Analyzer agents for simulation.
"""
import json
import pathlib
import time
import uuid
import threading
import queue
from typing import Any, Dict

from flask import Flask, request, send_from_directory, jsonify, Response, stream_with_context
from fastmcp import Client

# Core Imports
from core.config import load_config, APP_DIR
from core.logging import write_log, create_run_dir, SessionLogger
from core.state import DesignState
from agents.architect import ArchitectAgent
from agents.physics import run_physics_pipeline
from core.llm import call_openrouter

app = Flask(__name__, static_folder=str(APP_DIR / "static"))

# Global Stores
AGENTS: Dict[str, ArchitectAgent] = {}
CONVERSATIONS: Dict[str, list[dict]] = {}

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

@app.route("/init_design", methods=["POST"])
def init_design():
    """
    Initialize the Design Phase.
    1. Check feasibility of Goal + Inventory.
    2. Define required parameters.
    3. Instantiate ArchitectAgent.
    """
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    goal = data.get("goal")
    inventory = data.get("inventory")
    model = data.get("model") or "google/gemini-3-pro-preview"
    
    if not all([conv_id, goal, inventory]):
        return jsonify({"ok": False, "error": "Missing fields"}), 400

    # Initialize Logger
    logger = SessionLogger(conv_id)
    logger.log_json("init_request", {"goal": goal, "inventory": inventory, "model": model})

    # 1. Feasibility Analysis (LLM)
    system_prompt = (
        "You are a Senior Optical Engineer. The user wants to build an optical system.\n"
        "TASK:\n"
        "1. Analyze if the Goal is feasible with the Inventory.\n"
        "2. Define the EXACT list of 'Component Properties' (intrinsic specs like Refractive Index, Curvature, Length of crystal).\n"
        "   - You must be EXHAUSTIVE and SKEPTICAL. If the user says 'Lens', you need 'Focal Length', 'Diameter', 'Material', 'AR Coating' if relevant.\n"
        "   - Do NOT assume standard values. If the user didn't say 'f=100mm', then 'Focal Length' value is null.\n"
        "   - Critically evaluate if the provided inventory description lacks specific details needed for physics simulation.\n"
        "3. Define the EXACT list of 'Design Parameters' (geometric/tunable specs like Distances, Angles, Positions).\n"
        "4. Create a 'Design Scheme' (text description) explaining the physical layout and how components are arranged. This will guide the physics simulation.\n"
        "5. Return a JSON object with this structure:\n"
        "{\n"
        "  \"feasible\": boolean,\n"
        "  \"reason\": \"explanation...\",\n"
        "  \"component_properties\": [\n"
        "    {\"name\": \"Crystal Length\", \"description\": \"Length of the gain medium\", \"unit\": \"mm\", \"value\": null}\n"
        "  ],\n"
        "  \"design_parameters\": [\n"
        "    {\"name\": \"Cavity Length\", \"description\": \"Distance between mirrors\", \"unit\": \"mm\", \"value\": null}\n"
        "  ],\n"
        "  \"design_scheme\": \"The crystal is placed at the center of the cavity...\"\n"
        "}\n"
        "IMPORTANT: 'value' must be null unless the user EXPLICITLY provided it in the inventory string.\n"
    )
    user_prompt = f"Goal: {goal}\nInventory: {inventory}"
    
    try:
        resp, metrics, raw = call_openrouter(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            model,
            json_schema={
                "type": "object",
                "properties": {
                    "feasible": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "component_properties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "unit": {"type": "string"},
                                "value": {"type": ["number", "string", "null"]}
                            },
                            "required": ["name", "description"]
                        }
                    },
                    "design_parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "unit": {"type": "string"},
                                "value": {"type": ["number", "string", "null"]}
                            },
                            "required": ["name", "description"]
                        }
                    },
                    "design_scheme": {"type": "string"}
                },
                "required": ["feasible", "reason", "component_properties", "design_parameters", "design_scheme"]
            }
        )
        
        # 2. Create Agent
        state_dict = {
            "stage": "DESIGN",
            "goal": goal,
            "inventory": inventory,
            "component_properties": resp.get("component_properties", []),
            "design_parameters": resp.get("design_parameters", []),
            "design_scheme": resp.get("design_scheme", ""),
            "feasibility": resp.get("feasible"),
            "reason": resp.get("reason")
        }
        
        agent = ArchitectAgent(conv_id, state_dict)
        AGENTS[conv_id] = agent
        
        # 3. Formulate Initial Message
        msg = f"**Feasibility Analysis**: {resp.get('reason')}\n\n"
        if resp.get('feasible'):
            msg += "I have initialized the design state. Please provide the missing parameters from the checklist."
        else:
            msg += "WARNING: This build might not be possible with your inventory."

        return jsonify({
            "ok": True,
            "state": state_dict,
            "message": msg
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/chat_flow", methods=["POST"])
def chat_flow():
    """
    Streaming chat endpoint.
    Routes to ArchitectAgent if in Design Mode.
    Handles 'commands' from Architect to Physics Agent.
    """
    data = request.get_json(force=True)
    user_text = data.get("message", "")
    conv_id = data.get("conversation_id")
    
    # Check if we have an active Architect for this session
    if conv_id in AGENTS:
        agent = AGENTS[conv_id]
        
        def _stream_architect():
            yield "event: status\ndata: {\"message\": \"Architect is thinking...\"}\n\n"
            try:
                # Architect processes the message (synchronously for now)
                result = agent.process_message(user_text)
                
                # Stream initial state update (Architect might have done direct updates)
                yield "event: state_update\ndata: " + json.dumps({"state": result["state"]}) + "\n\n"
                
                # Architect Response Text
                arch_response = result["text"]
                
                # Check for Commands
                commands = result.get("commands", [])
                
                physics_output_text = ""
                final_code_block = None
                
                for cmd in commands:
                    c_type = cmd.get("command_type")
                    if c_type == "call_physics_analyser":
                        yield "event: status\ndata: {\"message\": \"Running Physics Analysis...\"}\n\n"
                        task = cmd.get("task_description")
                        ctx = cmd.get("context_info", "")
                        
                        # Call Physics Pipeline
                        # We pass the current state (which might have been updated by Architect just now)
                        # And pass the logger from the agent
                        phy_res = run_physics_pipeline(task, ctx, agent.state.model_dump(), logger=agent.logger)
                        
                        # Apply Physics Updates - DISABLED per user request
                        # The user wants to manually verify/update based on the code output.
                        # updates = phy_res.get("review", {}).get("parameter_updates", [])
                        # count = 0
                        # for u in updates:
                        #     if agent.state.update_param(u["name"], u["value"]):
                        #         count += 1
                        
                        # Get formatted message and code
                        review_data = phy_res.get("review", {})
                        message_back = review_data.get("message_back", "Analysis complete.")
                        code_analysis = review_data.get("code_analysis", "")
                        final_code_block = phy_res.get("code")

                        # Append Physics Analysis to the response
                        physics_output_text += f"\n\n**Physics Analysis ({task})**:\n"
                        physics_output_text += message_back
                        if code_analysis:
                            physics_output_text += f"\n\n**Code Analysis**:\n{code_analysis}"
                        
                        # if count > 0:
                        #     physics_output_text += f"\n\n*Proposed update for {count} parameters based on simulation.*"
                            
                        # Stream updated state after physics
                        yield "event: state_update\ndata: " + json.dumps({"state": agent.state.model_dump()}) + "\n\n"
                        
                    elif c_type == "finalize_design":
                        agent.state.stage = "CONSTRUCTION"
                        physics_output_text += "\n\n**Design Finalized**. Proceeding to Construction Phase."
                        yield "event: state_update\ndata: " + json.dumps({"state": agent.state.model_dump()}) + "\n\n"

                # Combine texts
                final_text = arch_response + physics_output_text

                # Stream response text (as a 'review' event to render in bubble)
                response_payload = {
                    "response": {
                        "text": final_text,
                        "code": final_code_block # Send the code to the UI
                    },
                    "metrics": {} 
                }
                
                yield "event: review\ndata: " + json.dumps(response_payload) + "\n\n"
                
                yield "event: done\ndata: {}\n\n"
                
            except Exception as e:
                yield "event: error\ndata: " + json.dumps({"error": str(e)}) + "\n\n"

        return Response(_stream_architect(), mimetype="text/event-stream")

    # Fallback to simple chat if no agent (legacy/free chat)
    return jsonify({"error": "No active design session. Please start from the landing page."}), 400

@app.route("/update_parameter", methods=["POST"])
def update_parameter():
    """
    Endpoint for Manual UI Updates.
    User edits a value in the sidebar -> this updates the state.
    """
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    name = data.get("name")
    value = data.get("value")
    
    if conv_id in AGENTS:
        agent = AGENTS[conv_id]
        success = agent.state.update_param(name, value)
        if success:
            return jsonify({"ok": True, "state": agent.state.model_dump()})
        else:
            return jsonify({"ok": False, "error": "Parameter not found"}), 404
    
    return jsonify({"ok": False, "error": "Session not found"}), 404

@app.route("/run_code", methods=["POST"])
def run_code():
    # Legacy run_code for manual execution from UI
    # We need to reimplement _run_code_subprocess or import it
    # For now, let's just use a simplified version or copy the old one
    # Since I deleted the old one, I'll rewrite a simple one.
    data = request.get_json(force=True)
    code = data.get("code", "")
    timeout_s = int(data.get("timeout_s") or 40)
    
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = APP_DIR / "tmp_runs" / f"exec-{ts}-{uuid.uuid4()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Save input
    (run_dir / "run_code_input.py").write_text(code, encoding="utf-8")
    
    # Execute
    import subprocess
    import sys
    
    cmd = [sys.executable, str(run_dir / "run_code_input.py")]
    try:
        # We need the instrumentation for images (matplotlib)
        # Re-injecting instrumentation
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
            "files": [], # TODO: list files
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
    app.run(host="0.0.0.0", port=8000, debug=True)
