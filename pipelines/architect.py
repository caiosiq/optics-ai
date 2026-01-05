from typing import Any, Generator
from .base import BasePipeline
from agents.architect import ArchitectAgent
from core.state import DesignState, Parameter
from pipelines.physics import PhysicsPipeline

class ArchitectPipeline(BasePipeline):
    def __init__(self, session_id: str, state: dict, client=None, logger=None):
        super().__init__(logger)
        self.session_id = session_id
        self.state = DesignState(**state) if state else None
        self.architect_agent = ArchitectAgent(client, logger)
        self.physics_pipeline = PhysicsPipeline(client, logger)

    def run(self, user_text: str) -> Generator[dict, None, None]:
        """
        Executes the Architect Pipeline logic.
        Yields events/status updates as dicts.
        """
        if not self.state:
            yield {"type": "error", "message": "State not initialized."}
            return

        yield {"type": "status", "message": "Architect is thinking..."}

        # 1. Run Architect Agent
        response = self.architect_agent.run(
            self.state.goal, 
            self.state.inventory, 
            self.state.component_properties, 
            self.state.design_parameters, 
            user_text
        )

        if self.logger:
            self.logger.log_json("architect_response", response)

        # 2. Process State Updates
        if "design_scheme_update" in response and response["design_scheme_update"]:
            self.state.design_scheme = response["design_scheme_update"]

        struct_updates = response.get("structure_updates", [])
        for s in struct_updates:
            action = s.get("action")
            name = s.get("name")
            desc = s.get("description", "")
            unit = s.get("unit")
            
            if action == "add_component_property":
                if not any(p.name == name for p in self.state.component_properties):
                    self.state.component_properties.append(Parameter(name=name, description=desc, unit=unit))
            elif action == "remove_component_property":
                self.state.component_properties = [p for p in self.state.component_properties if p.name != name]
            elif action == "add_design_parameter":
                if not any(p.name == name for p in self.state.design_parameters):
                    self.state.design_parameters.append(Parameter(name=name, description=desc, unit=unit))
            elif action == "remove_design_parameter":
                self.state.design_parameters = [p for p in self.state.design_parameters if p.name != name]

        updates = response.get("parameter_updates", [])
        for u in updates:
            self.state.update_param(u["name"], u["value"])

        # Yield state update
        yield {"type": "state_update", "state": self.state.model_dump()}

        # 3. Handle Commands (Orchestration)
        arch_response_text = response.get("response_message", "")
        physics_output_text = ""
        final_code_block = None

        commands = response.get("commands", [])
        for cmd in commands:
            c_type = cmd.get("command_type")
            
            if c_type == "call_physics_analyser":
                task = cmd.get("task_description")
                ctx = cmd.get("context_info", "")
                
                yield {"type": "status", "message": f"Running Physics Analysis: {task}..."}
                
                # Internal Call to Physics Pipeline
                phy_res = self.physics_pipeline.run(task, ctx, self.state.model_dump())
                
                review_data = phy_res.get("review", {})
                message_back = review_data.get("message_back", "Analysis complete.")
                # We DO NOT show code_analysis here anymore, as requested by user
                # code_analysis = review_data.get("code_analysis", "")
                final_code_block = phy_res.get("code")

                physics_output_text += f"\n\n**Physics Analysis ({task})**:\n"
                physics_output_text += message_back
                # Only message_back is appended. 
                
                # Yield state again in case physics changed anything (not currently, but good practice)
                yield {"type": "state_update", "state": self.state.model_dump()}

            elif c_type == "finalize_design":
                self.state.stage = "CONSTRUCTION"
                physics_output_text += "\n\n**Design Finalized**. Proceeding to Construction Phase."
                yield {"type": "state_update", "state": self.state.model_dump()}
        
        # 4. Final Result
        final_text = arch_response_text + physics_output_text
        
        yield {
            "type": "result",
            "text": final_text,
            "code": final_code_block,
            "metrics": {}
        }
