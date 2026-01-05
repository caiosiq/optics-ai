from .base import BaseAgent
import json

class ConstructorAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("constructor", client, logger) 

    def run(self, goal: str, params: list, inventory: str) -> dict:
        # Convert params objects to dicts for JSON serialization
        params_status = json.dumps([p.model_dump() for p in params], indent=2)
        
        user_content = (
            f"Goal: {goal}\n"
            f"Inventory: {inventory}\n"
            f"Final Design Parameters:\n{params_status}\n\n"
            "TASK: Generate the Lab Plan JSON with absolute coordinates."
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        output_schema = {
            "type": "object",
            "properties": {
                "thought_process": {"type": "string"},
                "lab_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string"},
                            "position": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                },
                                "required": ["x", "y"]
                            },
                            "orientation": {"type": "number"}
                        },
                        "required": ["id", "type", "position", "orientation"]
                    }
                }
            },
            "required": ["thought_process", "lab_plan"]
        }

        return self.call_llm(messages, json_schema=output_schema)
