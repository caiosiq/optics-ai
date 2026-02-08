from .base import BaseAgent
from core.llm import call_openrouter
from core.config import load_config
import pathlib
import json

class RoboticsEngineerAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__(client, logger)
        self.role = "Senior Robotics Integration Engineer"
        self._load_config()
        
    def _load_config(self):
        """Loads agent configuration from JSON."""
        try:
            config_path = pathlib.Path("config/agents/robotics.json")
            self.config = json.loads(config_path.read_text(encoding="utf-8"))
                
            # Load API specs dynamically
            specs_path = pathlib.Path("knowledge/robot_api_specs.txt")
            self.api_specs = specs_path.read_text(encoding="utf-8") if specs_path.exists() else "API Specs not found."
            
        except Exception as e:
            print(f"[RoboticsEngineerAgent] Config Load Error: {e}")
            self.config = {}
            self.api_specs = "Error loading specs."

    def run(self, lab_plan: list) -> str:
        print(f"[RoboticsEngineerAgent] Generating code for {len(lab_plan)} components")
        
        # Hydrate the system prompt with actual API specs
        base_prompt = self.config.get("system", "")
        system_prompt = base_prompt.replace("{api_specs}", self.api_specs)
        
        user_message = f"Generate the robot assembly script for this lab plan:\n{lab_plan}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # Use model from config, fallback to global drafter, then default
        model = self.config.get("model") or load_config().get("models", {}).get("drafter_model", "google/gemini-2.0-flash-exp")
        
        try:
            response_tuple = call_openrouter(messages, model=model)
            content = response_tuple[0]
            
            if not content:
                return "# Error: No response from LLM."

            # Clean up response (remove markdown code fences if present)
            if isinstance(content, str):
                code = content.strip()
            else:
                code = str(content).strip()
                
            if code.startswith("```python"):
                code = code[9:]
            if code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]
                
            return code.strip()
        except Exception as e:
            print(f"[RoboticsEngineerAgent] Error: {e}")
            return f"# Error generating code: {e}"
