from pathlib import Path

def read_file(path: str) -> dict:
    # optics_mcp/resources/filesystem.py -> parents[3] is project root
    base = Path(__file__).resolve().parents[3]
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
