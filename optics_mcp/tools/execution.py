import time
import subprocess
import sys
import json
import uuid
from pathlib import Path
from optics_mcp.core.sandbox import SANDBOX_RUNNER_CODE

def exec_python_sandbox(code: str, timeout_s: int = 120) -> dict:
    import uuid
    
    # 1. Setup Run Directory
    # We need to find the root directory of the project relative to this file
    # This file is in optics_mcp/tools/execution.py
    # So parents[2] is optics_mcp/, parents[3] is agent-ui/
    base = Path(__file__).resolve().parents[3]
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
        
        # We pipe the user code into stdin
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
        if "__JSON_RESULT_START__" in stdout:
            parts = stdout.split("__JSON_RESULT_START__")
            # raw_output = parts[0] 
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
