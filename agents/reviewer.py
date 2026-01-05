from .base import BaseAgent

class ReviewerAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("reviewer", client, logger)

    def run(self, task: str, plan: str, draft_code: str, exec_output: str) -> dict:
        review_packet = f"""Task: {task}
Plan: {plan}

Draft Code:
```python
{draft_code}
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
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": review_packet}
        ]
        
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
        
        response = self.call_llm(messages, json_schema=output_schema)
        # Response should be a dict because json_schema was provided
        return response
