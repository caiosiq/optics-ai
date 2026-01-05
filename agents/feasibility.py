from .base import BaseAgent
import json

class FeasibilityAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("feasibility", client, logger)

    def run(self, goal: str, inventory: str) -> dict:
        user_prompt = f"Goal: {goal}\nInventory: {inventory}"
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        output_schema = {
            "type": "object",
            "properties": {
                "feasible": {"type": "boolean"},
                "reason": {"type": "string"},
                "component_properties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "unit": {"type": "string"},
                            "value": {"type": ["number", "string", "null"]}
                        },
                        "required": ["name", "description"]
                    }
                },
                "design_parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "unit": {"type": "string"},
                            "value": {"type": ["number", "string", "null"]}
                        },
                        "required": ["name", "description"]
                    }
                },
                "design_scheme": {"type": "string"}
            },
            "required": ["feasible", "reason", "component_properties", "design_parameters", "design_scheme"]
        }
        
        return self.call_llm(messages, json_schema=output_schema)
