from abc import ABC, abstractmethod
from typing import Any, Dict, Generator

class BaseStage(ABC):
    def __init__(self, state: dict, client=None, logger=None):
        self.state = state
        self.client = client
        self.logger = logger

    @abstractmethod
    def run(self, input_data: Any) -> Any:
        """
        Main execution method for the stage.
        Can return a single result or a generator for streaming.
        """
        pass
