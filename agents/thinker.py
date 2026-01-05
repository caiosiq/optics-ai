import json
from .base import BaseAgent

class ThinkerAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("thinker", client, logger)

    def run(self, task: str, context: str, state_params: list) -> str:
        state_desc = json.dumps(state_params, indent=2)
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Context: {context}\nTask: {task}\nCurrent Design Parameters:\n{state_desc}\n\nGoal: Create a plan to calculate/simulate the missing parameters using Python."}
        ]
        
        response = self.call_llm(messages)
        # If response is a tuple/dict, handle it. call_llm usually returns the content directly if no schema/tools.
        # But wait, BaseAgent.call_llm calls call_openrouter which returns (parsed, metrics, raw).
        # Ah, I need to check BaseAgent.call_llm implementation. 
        # In my implementation of BaseAgent.call_llm, it returns 'response' which is the first element of call_openrouter return.
        
        # call_openrouter returns:
        # 1. tool_calls (list) OR parsed_json (dict/list) OR content (str)
        # 2. metrics
        # 3. raw_text
        
        # So 'response' here should be the string content since we didn't use schema/tools.
        return response if isinstance(response, str) else str(response)
