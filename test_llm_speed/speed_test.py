import pathlib
import time
import json
import requests

MODEL = "openai/gpt-4.1-mini"
PROMPT = (
    "You are designing a stable laser cavity using a 1\% Nd:YAG crystal pumped at 250 mW. The goal is to propose a complete, unambiguous optical cavity design that maximizes mode stability and output power given the physical constraints below. System constraints: Pump power: 250 mW (maximum) Gain medium: Nd:YAG crystal, 1\% doping concentration Crystal thickness: 5 mm Pump beam radius (1/e²): 0.5 mm at input face Lens focal length: 0.1 m Input coupler reflectivity: 99\% Output coupler reflectivity: 99.74\% Output coupler radius of curvature (ROC): 15 cm Wavelength: 1064 nm (fundamental transition) Requirements for your output: A python script that, when ran, will provide all geometrical parameters of the cavity unambiguously in a .txt file: -mirror types (flat, concave, etc.) -distances between mirrors, lens, and crystal -beam waist location and size inside the crystal -stability margin -mode volume vs. pump volume overlap -expected diffraction losses You must avoid calculating these quantities directly but instead write a python code that, when ran, will give these proprieties.Make sure the code has no characthers that charmap cant output."
)

BASE = pathlib.Path(__file__).parent.resolve()
API_KEY = (BASE / "openrouter_api.txt").read_text().strip()
OUT_PATH = BASE / "response.txt"

def run():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "reasoning": {"effort": "high"}, "temperature": 0.2}
    t0 = time.perf_counter()
    t1 = time.perf_counter()
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    t2 = time.perf_counter()
    data = r.json()
    t3 = time.perf_counter()
    if "choices" not in data or not data["choices"]:
        print("error: invalid response")
        OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return
    content = data["choices"][0]["message"].get("content", "")
    OUT_PATH.write_text(str(content), encoding="utf-8")
    prep_ms = int((t1 - t0) * 1000)
    llm_ms = int((t2 - t1) * 1000)
    parse_ms = int((t3 - t2) * 1000)
    total_ms = int((t3 - t0) * 1000)
    usage = data.get("usage")
    print("prompt:")
    print(PROMPT)
    print("\nresponse:")
    print(content)
    print("\nmetrics:")
    print(json.dumps({"prep_ms": prep_ms, "llm_ms": llm_ms, "parse_ms": parse_ms, "total_ms": total_ms, "usage": usage}, indent=2))

if __name__ == "__main__":
    run()