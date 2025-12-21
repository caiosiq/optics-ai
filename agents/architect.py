import json
from core.llm import call_openrouter
from core.logging import write_log, create_run_dir
from core.state import DesignState
from core.config import load_config
from agents.physics import run_physics_pipeline

class ArchitectAgent:
    def __init__(self, session_id: str, state: dict, logger=None):
        self.session_id = session_id
        self.state = DesignState(**state) if state else None
        self.cfg = load_config()
        self.logger = logger
        # self.run_dir = create_run_dir(f"arch-{session_id}")

    def process_message(self, user_text: str) -> dict:
        """
        Main entry point for the Architect.
        Decides whether to chat, update state, or call physics.
        """
        # write_log(self.run_dir, [("User Input", user_text)])
        
        if not self.state:
            return {"text": "State not initialized."}

        # 1. DEFINE SCHEMA FOR STRUCTURED OUTPUT
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
        # We explicitly list current values to prevent overwriting with NaN
        comp_status = json.dumps([p.model_dump() for p in self.state.component_properties], indent=2)
        design_status = json.dumps([p.model_dump() for p in self.state.design_parameters], indent=2)
        
        system_prompt = (
            "You are The Architect, a Senior Optical Systems Engineer.\n"
            "Your Goal: Guide the user to complete the design of: " + self.state.goal + "\n"
            "Current Inventory: " + self.state.inventory + "\n"
            "Current State:\n"
            f"COMPONENT PROPERTIES (Intrinsic):\n{comp_status}\n\n"
            f"DESIGN PARAMETERS (Geometric/Tunable):\n{design_status}\n\n"
            "PROTOCOL:\n"
            "1. Analyze user input. If the user provides a value for a parameter (e.g. 'length is 15cm'), put it in 'parameter_updates'.\n"
            "2. DO NOT overwrite existing values with NaN or null. Only update if the user provides a NEW value.\n"
            "3. BE SKEPTICAL about Component Properties. If the user lists a 'Lens' but hasn't specified focal length, diameter, or material, you must ask for it.\n"
            "   - If you realize the current list of properties is INCOMPLETE, use 'structure_updates' to ADD necessary fields (e.g. 'Lens 1 Focal Length').\n"
            "   - Do NOT hallucinate values. If you don't know it, keep it null.\n"
            "4. If the user asks for a complex calculation (e.g. 'calculate stability', 'find optimal ROC'), use the 'commands' field to 'call_physics_analyser'.\n"
            "5. If you can update the parameter yourself (simple extraction), DO NOT call the physics analyzer.\n"
            "6. If all parameters are set (no nulls), command 'finalize_design'.\n"
            "7. Your 'response_message' should be professional and guide the user to the next step.\n"
        )

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]

        if self.logger:
            self.logger.log_text("architect_input", f"System Prompt:\n{system_prompt}\n\nUser Message:\n{user_text}")

        # 3. CALL ARCHITECT LLM
        response, metrics, raw = call_openrouter(
            messages, 
            model=self.cfg["models"]["thinker_model"],
            json_schema=output_schema,
            temperature=0.1
        )
        
        if self.logger:
            self.logger.log_json("architect_response", response)

        # write_log(self.run_dir, [("Architect Response", json.dumps(response, indent=2))])

        # 4. PROCESS OUTPUT
        # The response is already a dict matching the schema
        
        # Apply Structure Updates
        from core.state import Parameter
        
        # Apply Design Scheme Update
        if "design_scheme_update" in response and response["design_scheme_update"]:
            self.state.design_scheme = response["design_scheme_update"]

        struct_updates = response.get("structure_updates", [])
        for s in struct_updates:
            action = s.get("action")
            name = s.get("name")
            desc = s.get("description", "")
            unit = s.get("unit")
            
            if action == "add_component_property":
                # Check if exists
                if not any(p.name == name for p in self.state.component_properties):
                    self.state.component_properties.append(Parameter(name=name, description=desc, unit=unit))
            elif action == "remove_component_property":
                self.state.component_properties = [p for p in self.state.component_properties if p.name != name]
            elif action == "add_design_parameter":
                if not any(p.name == name for p in self.state.design_parameters):
                    self.state.design_parameters.append(Parameter(name=name, description=desc, unit=unit))
            elif action == "remove_design_parameter":
                self.state.design_parameters = [p for p in self.state.design_parameters if p.name != name]

        # Apply Direct Updates
        updates = response.get("parameter_updates", [])
        update_count = 0
        for u in updates:
            if self.state.update_param(u["name"], u["value"]):
                update_count += 1
        
        # We return the whole structure to the server, which will handle the commands
        return {
            "text": response.get("response_message", ""),
            "state": self.state.model_dump(),
            "commands": response.get("commands", []),
            "metrics": metrics
        }

    def _process_construction(self, user_text: str) -> dict:
        """
        Handle messages during the Construction Phase.
        Focus on assembly instructions and code generation.
        """
        if self.logger:
            self.logger.log_text("construction_input", user_text)

        output_schema = {
            "type": "object",
            "properties": {
                "thought_process": {"type": "string", "description": "Reasoning about the user's request."},
                "response_message": {"type": "string", "description": "Response to the user. Use Markdown for lists/instructions."},
                "code_block": {
                    "type": "string", 
                    "description": "Python code for the assembly/control script. Return ONLY if requested or relevant."
                }
            },
            "required": ["thought_process", "response_message"]
        }

        params_status = json.dumps([p.model_dump() for p in self.state.params], indent=2)
        
        system_prompt = (
            "You are the Construction Manager for an Optical System.\n"
            "The design is FINALIZED. Do not change parameters.\n"
            f"Goal: {self.state.goal}\n"
            f"Parameters:\n{params_status}\n\n"
            "TASK:\n"
            "1. Guide the user through the physical assembly of the system.\n"
            "2. If the user asks to 'start construction' or similar, provide a detailed step-by-step assembly guide.\n"
            "3. If appropriate (e.g., automated stages, alignment), generate a Python script to control the hardware.\n"
            "   - Assume a hypothetical 'lab_controller' library exists with functions like 'move_stage(axis, pos)', 'set_laser(power)', 'read_detector()'.\n"
            "   - Write clean, commented code.\n"
        )

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]

        response, metrics, raw = call_openrouter(
            messages,
            model=self.cfg["models"]["thinker_model"],
            json_schema=output_schema,
            temperature=0.1
        )

        if self.logger:
            self.logger.log_json("construction_response", response)

        return {
            "text": response.get("response_message", ""),
            "state": self.state.model_dump(),
            "commands": [], # No commands in construction mode for now
            "code": response.get("code_block"),
            "metrics": metrics
        }
