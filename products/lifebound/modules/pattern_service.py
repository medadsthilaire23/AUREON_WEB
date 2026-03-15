"""
modules/pattern_service.py
===========================
Servicio de selección de patrones pregenerados.

Responsabilidad única: leer los JSONs pregenerados y seleccionar
aleatoriamente un patrón que coincida con el photo_count solicitado.

Este módulo no genera patrones — esa responsabilidad pertenece a
services/pattern_generator.py. Si los JSONs no existen, el error
indica claramente qué hacer.

Archivos requeridos en data/
-----------------------------
- patterns_low.json    → photo_count 15-30
- patterns_medium.json → photo_count 31-55
- patterns_high.json   → photo_count 56-80

Si alguno falta, ejecutar:
    python products/lifebound/services/pattern_generator.py
"""

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"

_RANGE_FILES: dict[str, str] = {
    "LOW":    "patterns_low.json",
    "MEDIUM": "patterns_medium.json",
    "HIGH":   "patterns_high.json",
}


class PatternService:
    """
    Servicio stateless de selección de patrones pregenerados.

    Los JSONs se cargan una sola vez en memoria (lazy, por range_type)
    y se cachean para evitar I/O por request. Thread-safe en lectura
    dado que el cache solo crece y nunca muta entradas existentes.
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[dict]] = {}

    def _resolve_range(self, photo_count: int) -> str:
        """
        Determina el range_type según la cantidad de fotos.

        LOW    → 15-30 | MEDIUM → 31-55 | HIGH → 56-80
        """
        if photo_count <= 30:
            return "LOW"
        if photo_count <= 55:
            return "MEDIUM"
        return "HIGH"

    def _load(self, range_type: str) -> list[dict]:
        """
        Carga y cachea los patrones del JSON correspondiente al range_type.

        Parámetros
        ----------
        range_type : str — "LOW", "MEDIUM" o "HIGH"

        Retorna
        -------
        list[dict] — lista de patrones disponibles para ese rango

        Lanza
        -----
        FileNotFoundError — si el JSON no existe en data/
                            (solución: ejecutar pattern_generator.py)
        KeyError          — si el JSON no contiene la clave "patterns"
        """
        if range_type in self._cache:
            return self._cache[range_type]

        filename = _RANGE_FILES.get(range_type)
        if not filename:
            raise ValueError(f"range_type desconocido: {range_type!r}")

        filepath = _DATA_DIR / filename
        if not filepath.exists():
            raise FileNotFoundError(
                f"Archivo de patrones no encontrado: {filepath}. "
                "Ejecutar: python products/lifebound/services/pattern_generator.py"
            )

        with open(filepath, encoding="utf-8") as fp:
            raw = json.load(fp)

        if "patterns" not in raw:
            raise KeyError(
                f"{filename} no contiene la clave 'patterns'. "
                "El archivo puede estar corrupto — regenerar con pattern_generator.py"
            )

        patterns = raw["patterns"]
        self._cache[range_type] = patterns
        logger.info("Patrones cargados: %d entradas [%s]", len(patterns), range_type)
        return patterns

    def select(self, photo_count: int) -> dict:
        """
        Selecciona aleatoriamente un patrón para el photo_count dado.

        Parámetros
        ----------
        photo_count : int — cantidad de fotos del álbum (15-80)

        Retorna
        -------
        dict — patrón con template_sequence, slot_sequence, color_scheme, etc.

        Lanza
        -----
        ValueError        — si no hay patrones para ese photo_count exacto
        FileNotFoundError — si el JSON del rango no existe
        """
        range_type   = self._resolve_range(photo_count)
        all_patterns = self._load(range_type)

        matching = [p for p in all_patterns if p.get("photo_count") == photo_count]
        if not matching:
            raise ValueError(
                f"No hay patrones para photo_count={photo_count} en rango {range_type}. "
                "Regenerar con pattern_generator.py"
            )

        selected = random.choice(matching)
        logger.info(
            "Patrón seleccionado: %s (%d candidatos, photo_count=%d)",
            selected.get("pattern_id", "sin_id"), len(matching), photo_count
        )
        return selected