import json
from core.llm import call_openrouter
from core.logging import write_log
from core.config import load_config, APP_DIR
from optics_mcp.tools.execution import exec_python_sandbox

def run_physics_pipeline(task: str, context: str, state: dict, logger=None) -> dict:
    """
    Executes the Thinker -> Drafter -> Executor -> Reviewer pipeline.
    The goal is to derive parameter values for the DesignState by RUNNING code.
    Returns a dict with code, text, and updates.
    """
    cfg = load_config()
    
    if logger:
        logger.log_text("physics_request", f"Task: {task}\nContext: {context}")

    # 1. THINKER
    # We add the state context so the thinker knows what variables to solve for.
    state_desc = json.dumps(state.get("params", []), indent=2)
    
    thinker_sys = cfg["thinker"]["system"]
    thinker_msg = [
        {"role": "system", "content": thinker_sys},
        {"role": "user", "content": f"Context: {context}\nTask: {task}\nCurrent Design Parameters:\n{state_desc}\n\nGoal: Create a plan to calculate/simulate the missing parameters using Python."}
    ]
    
    if logger:
        logger.log_text("physics_thinker_input", json.dumps(thinker_msg, indent=2))

    plan, tm, raw_t = call_openrouter(
        thinker_msg, 
        model=cfg["models"]["thinker_model"],
        max_tokens=cfg["llm"]["max_tokens_thinker"]
    )
    
    if logger:
        logger.log_text("physics_thinker_output", plan)

    # 2. DRAFTER
    drafter_sys = cfg["drafter"]["system"]
    drafter_msg = [
        {"role": "system", "content": drafter_sys},
        {"role": "user", "content": f"Plan: {plan}\nTask: {task}\n\nWrite the Python code to perform this analysis. IMPORTANT: The code MUST print the final results to stdout so they can be captured."}
    ]
    
    if logger:
        logger.log_text("physics_drafter_input", json.dumps(drafter_msg, indent=2))

    code, dm, raw_d = call_openrouter(
        drafter_msg,
        model=cfg["models"]["drafter_model"],
        max_tokens=cfg["llm"]["max_tokens_drafter"]
    )
    
    if logger:
        logger.log_text("physics_drafter_output", code)

    # 3. EXECUTOR (New Step)
    # Actually run the code to get real values.
    if logger:
        logger.log_text("physics_execution_start", "Running sandbox...")
        
    exec_result = exec_python_sandbox(code, timeout_s=60)
    exec_output = exec_result.get("output", "")
    exec_images = exec_result.get("images", [])
    
    if logger:
        logger.log_json("physics_execution_result", exec_result)

    # 4. REVIEWER
    # The reviewer must extract the values into the JSON format.
    reviewer_sys = cfg["reviewer"]["system"]
    
    # We enforce a schema on the reviewer to get the updates back to the Architect/Server
    output_schema = {
        "type": "object",
        "properties": {
            "message_back": {
                "type": "string", 
                "description": "A polite message to the Architect/User summarizing the result found in the EXECUTION OUTPUT and what the code does."
            },
            "code_analysis": {
                "type": "string",
                "description": "Critique the code. Does it actually calculate what was asked? Are there physics errors? If the code failed, explain why."
            },
            "final_code": {
                "type": "string",
                "description": "The FINAL, corrected Python code. If the draft code ran successfully, this can be the same. If it failed, fix it."
            }
        },
        "required": ["message_back", "code_analysis", "final_code"]
    }

    review_packet = f"""Task: {task}
Plan: {plan}

Draft Code:
```python
{code}
```

Execution Output:
```
{exec_output}
```

INSTRUCTIONS:
1. Review the Execution Output and the Draft Code.
2. In 'code_analysis', critique the code. Did it solve the task? Are the physics correct? Does it carry any bugs?
3. In 'message_back', provide a polite summary for the user. Explain what the code does and what the results mean (if any).
4. If the code failed or had errors, FIX it in 'final_code'. If it was good, keep it.
5. ENSURE variable names in 'final_code' match the parameter names in the Design State (e.g. use 'Cavity_Length' instead of 'L').
6. DO NOT extract parameter updates automatically. The user will manually update the state based on the code output.
"""
    
    reviewer_msg = [
        {"role": "system", "content": reviewer_sys},
        {"role": "user", "content": review_packet}
    ]
    
    if logger:
        logger.log_text("physics_reviewer_input", json.dumps(reviewer_msg, indent=2))

    resp, rm, raw_r = call_openrouter(
        reviewer_msg,
        model=cfg["models"]["reviewer_model"],
        max_tokens=cfg["llm"]["max_tokens_reviewer"],
        json_schema=output_schema
    )
    
    if logger:
        logger.log_json("physics_reviewer_output", resp)

    return {
        "plan": plan,
        "code": resp.get("final_code", code), # Use the reviewer's corrected code
        "review": resp, # Contains 'message_back' and 'parameter_updates'
        "exec_output": exec_output, # Return execution log if needed
        "exec_images": exec_images
    }
