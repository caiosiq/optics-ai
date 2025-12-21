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
