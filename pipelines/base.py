from abc import ABC, abstractmethod
from typing import Any

class BasePipeline(ABC):
    def __init__(self, logger=None):
        self.logger = logger

    @abstractmethod
    def run(self, *args, **kwargs) -> Any:
        pass
