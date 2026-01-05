from .base import BaseAgent

class DrafterAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("drafter", client, logger)

    def run(self, task: str, plan: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Plan: {plan}\nTask: {task}\n\nWrite the Python code to perform this analysis. IMPORTANT: The code MUST print the final results to stdout so they can be captured."}
        ]
        
        response = self.call_llm(messages)
        return response if isinstance(response, str) else str(response)
