"""
pattern_service.py
Carga los JSONs pre-generados y selecciona un patrón aleatorio.
"""
import json, random, os, logging
from pathlib import Path

logger  = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"

class PatternService:
    def __init__(self):
        self._cache = {}

    def _load(self, range_type: str) -> list:
        if range_type not in self._cache:
            f = DATA_DIR / f"patterns_{range_type.lower()}.json"
            with open(f) as fp:
                self._cache[range_type] = json.load(fp)["patterns"]
            logger.info(f"Loaded {len(self._cache[range_type])} patterns [{range_type}]")
        return self._cache[range_type]

    def _range(self, photo_count: int) -> str:
        if photo_count <= 30: return "LOW"
        if photo_count <= 55: return "MEDIUM"
        return "HIGH"

    def select(self, photo_count: int) -> dict:
        rt       = self._range(photo_count)
        patterns = [p for p in self._load(rt) if p["photo_count"] == photo_count]
        if not patterns:
            raise ValueError(f"No patterns for photo_count={photo_count}")
        return random.choice(patterns)
