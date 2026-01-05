from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import json
import pathlib
from core.llm import call_openrouter
from core.config import load_agent_config

APP_DIR = pathlib.Path(__file__).parent.parent.resolve()
CONFIG_DIR = APP_DIR / "config"

def load_common_knowledge_config() -> List[str]:
    path = CONFIG_DIR / "common" / "knowledge.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            return []
    return []

class BaseAgent(ABC):
    def __init__(self, name: str, client: Any = None, logger: Any = None):
        self.name = name
        self.client = client  # MCP Client
        self.logger = logger
        self.config = load_agent_config(name)
        self.system_prompt = self.config.get("system", "")
        
        # Load model(s)
        self.models = self.config.get("models", {})
        self.default_model = self.config.get("model")
        
        # If 'model' key is missing but 'models' exists, set default from there
        if not self.default_model and self.models:
            self.default_model = self.models.get("default")
        
        self.llm_config = self.config.get("llm_config", {})
        
        # Knowledge and Tools
        # Merge specific agent knowledge with common knowledge
        self.common_knowledge = load_common_knowledge_config()
        self.agent_knowledge = self.config.get("knowledge", [])
        
        # Deduplicate while preserving order (Common first, then Agent specific)
        self.knowledge_resources = []
        seen = set()
        for k in self.common_knowledge + self.agent_knowledge:
            if k not in seen:
                self.knowledge_resources.append(k)
                seen.add(k)
                
        self.allowed_tools = self.config.get("tools", [])

    def log(self, key: str, data: Any):
        if self.logger:
            if isinstance(data, (dict, list)):
                self.logger.log_json(f"{self.name}_{key}", data)
            else:
                self.logger.log_text(f"{self.name}_{key}", str(data))

    def get_model(self, variant: str = "default") -> str:
        if not variant or variant == "default":
            return self.default_model
        if variant in self.models:
            return self.models[variant]
        return self.default_model

    def _inject_knowledge(self, messages: List[Dict[str, str]]):
        """
        Injects the content of defined knowledge resources into the system prompt.
        """
        if not self.knowledge_resources:
            return

        knowledge_context = "\n\n# KNOWLEDGE BASE\n"
        
        for res in self.knowledge_resources:
            if res.startswith("resource://"):
                name = res.replace("resource://", "")
                filename = name.replace("-", "_") + ".txt"
                path = APP_DIR / "knowledge" / filename
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    knowledge_context += f"## {name}\n{content}\n\n"
            elif res.startswith("file://"):
                # Handle file paths if needed
                pass
        
        # Append to the system prompt in the messages
        if messages and messages[0]["role"] == "system":
            # Check if we already injected to avoid duplication on retries/history if not handled carefully
            # But usually messages are constructed fresh.
            if "# KNOWLEDGE BASE" not in messages[0]["content"]:
                messages[0]["content"] += knowledge_context

    def call_llm(
        self, 
        messages: List[Dict[str, str]], 
        json_schema: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        model_variant: str = "default"
    ) -> Any:
        
        # Inject Knowledge
        self._inject_knowledge(messages)
        
        model_id = self.get_model(model_variant)
        
        if self.logger:
            self.log("llm_input", messages)
            self.log("llm_model_selected", model_id)
        
        response, metrics, raw_text = call_openrouter(
            messages,
            model=model_id,
            max_tokens=self.llm_config.get("max_tokens", 2000),
            temperature=self.llm_config.get("temperature", 0.2),
            reasoning_effort=self.llm_config.get("reasoning_effort", "low"),
            json_schema=json_schema,
            tools=tools
        )

        if self.logger:
            self.log("llm_output", response)
            
        return response

    @abstractmethod
    def run(self, *args, **kwargs) -> Any:
        pass
