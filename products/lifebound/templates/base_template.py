from abc import ABC, abstractmethod
from typing import Dict


class BaseTemplate(ABC):
    id: str
    name: str
    description: str
    fields: Dict

    @abstractmethod
    def generate(self, data: Dict) -> bytes:
        pass
