from .base import BaseAgent
import json

class ArchitectAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__("architect", client, logger)

    def run(self, goal: str, inventory: str, component_properties: list, design_parameters: list, user_text: str) -> dict:
        # 1. DEFINE SCHEMA
        output_schema = {
            "type": "object",
            "properties": {
                "thought_process": {
                    "type": "string", 
                    "description": "Your internal reasoning. Analyze if the user provided values for parameters, or if a complex simulation is needed."
                },
                "response_message": {
                    "type": "string", 
                    "description": "The response to show to the user. Ask for missing parameters or confirm updates."
                },
                "parameter_updates": {
                    "type": "array",
                    "description": "List of simple parameter updates extracted directly from user text.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Exact name of the parameter from the current state."},
                            "value": {"type": ["number", "string"], "description": "The value to set. Do NOT use NaN."}
                        },
                        "required": ["name", "value"]
                    }
                },
                "structure_updates": {
                    "type": "array",
                    "description": "Updates to the structure of properties/parameters (add/remove items).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add_component_property", "remove_component_property", "add_design_parameter", "remove_design_parameter"]},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "unit": {"type": "string"}
                        },
                        "required": ["action", "name"]
                    }
                },
                "design_scheme_update": {
                    "type": "string",
                    "description": "Updated text description of the design scheme if changed."
                },
                "commands": {
                    "type": "array",
                    "description": "List of commands to execute (e.g., run physics analysis).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "command_type": {
                                "type": "string", 
                                "enum": ["call_physics_analyser", "finalize_design"],
                                "description": "Use 'call_physics_analyser' ONLY for complex simulations/calculations. Use 'finalize_design' when ALL parameters are set."
                            },
                            "task_description": {"type": "string", "description": "Description of the task for the physics agent."},
                            "context_info": {"type": "string", "description": "Any extra context needed."}
                        },
                        "required": ["command_type", "task_description"]
                    }
                }
            },
            "required": ["thought_process", "response_message", "parameter_updates", "commands"]
        }

        # 2. CONSTRUCT PROMPT
        comp_status = json.dumps([p.model_dump() for p in component_properties], indent=2)
        design_status = json.dumps([p.model_dump() for p in design_parameters], indent=2)
        
        system_prompt = self.system_prompt + f"\n\nGoal: {goal}\nInventory: {inventory}"
        
        user_content = (
            f"Current State:\n"
            f"COMPONENT PROPERTIES (Intrinsic):\n{comp_status}\n\n"
            f"DESIGN PARAMETERS (Geometric/Tunable):\n{design_status}\n\n"
            f"User Input: {user_text}"
        )

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]

        # 3. CALL LLM
        return self.call_llm(messages, json_schema=output_schema)
