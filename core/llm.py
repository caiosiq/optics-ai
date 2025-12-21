import time
import json
import requests
from typing import Any, Dict, Optional, List
from .config import get_api_key

class LLMJSONError(Exception):
    def __init__(self, message: str, raw_out: dict | None = None, raw_content: str | dict | None = None):
        super().__init__(message)
        self.raw_out = raw_out
        self.raw_content = raw_content

def call_openrouter(
    messages: list[dict],
    model: str,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    reasoning_effort: str = "low",
    json_schema: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    retries: int = 1
) -> tuple[Any, Dict[str, Any], str]:
    
    api_key = get_api_key()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning": {"effort": reasoning_effort},
    }

    if json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "Response", "schema": json_schema, "strict": False}
        }
    
    if tools:
        payload["tools"] = tools

    t0 = time.perf_counter()
    
    for attempt in range(max(1, retries)):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=600)
            out = r.json()
            
            if "choices" not in out or not out["choices"]:
                raise RuntimeError(f"Invalid LLM response: {json.dumps(out)[:200]}")
            
            choice = out["choices"][0]
            message = choice["message"]
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            finish_reason = choice.get("finish_reason")
            
            dt = int((time.perf_counter() - t0) * 1000)
            metrics = {"llm_ms": dt, "usage": out.get("usage"), "finish_reason": finish_reason, "retries": attempt}
            
            # Case 1: Tool Calls
            if tool_calls:
                return tool_calls, metrics, json.dumps(tool_calls)
            
            # Case 2: JSON Schema
            if json_schema:
                if isinstance(content, str):
                    try:
                        parsed = json.loads(content)
                        return parsed, metrics, content
                    except json.JSONDecodeError:
                        # Retry logic
                        messages.append({"role": "system", "content": "Error: Invalid JSON. Return strictly valid JSON."})
                        continue
                elif isinstance(content, dict):
                    return content, metrics, json.dumps(content)
            
            # Case 3: Plain Text
            return content, metrics, str(content)

        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(1)
            
    raise RuntimeError("Max retries exceeded")
