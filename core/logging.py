import pathlib
import json
import time
import uuid

APP_DIR = pathlib.Path(__file__).parent.parent.resolve()

def create_run_dir(prefix: str = "run") -> pathlib.Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = APP_DIR / "tmp_runs" / f"{prefix}-{ts}-{uuid.uuid4()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

def write_log(run_dir: pathlib.Path, sections: list[tuple[str, str]]):
    """Append titled sections to interaction.txt for auditability."""
    try:
        p = run_dir / "interaction.txt"
        with open(p, "a", encoding="utf-8") as f:
            for title, body in sections:
                f.write(f"=== {title} ===\n")
                f.write(body + "\n\n")
    except Exception as e:
        print(f"Logging error: {e}")

def save_file(run_dir: pathlib.Path, filename: str, content: str):
    try:
        p = run_dir / filename
        pathlib.Path(p).write_text(content or "", encoding="utf-8")
    except Exception:
        pass

class SessionLogger:
    def __init__(self, session_id: str):
        self.session_id = session_id
        # Format: tmp_runs/session-{timestamp}-{uuid}
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.log_dir = APP_DIR / "tmp_runs" / f"session-{ts}-{session_id}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def _get_prefix(self):
        self.counter += 1
        return f"{self.counter:03d}"

    def log_json(self, name: str, data: dict | list):
        try:
            filename = f"{self._get_prefix()}_{name}.json"
            (self.log_dir / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Log error {name}: {e}")

    def log_text(self, name: str, text: str):
        try:
            filename = f"{self._get_prefix()}_{name}.txt"
            (self.log_dir / filename).write_text(str(text), encoding="utf-8")
        except Exception as e:
            print(f"Log error {name}: {e}")
