"""
services/pattern_generator.py
==============================
Generador de patrones de plantillas para álbumes Lifebound.

Puede ejecutarse de dos formas
--------------------------------
Offline (una sola vez, o cuando se quiera actualizar el catálogo):
    python products/lifebound/services/pattern_generator.py

Online (desde un endpoint admin en runtime):
    from products.lifebound.services.pattern_generator import PatternGenerator
    result = PatternGenerator().generate_all()

Qué genera
----------
Tres archivos JSON en data/ con patrones pregenerados listos para ser
consumidos por PatternService sin ningún cálculo adicional:

    patterns_low.json    → photo_count 15-30
    patterns_medium.json → photo_count 31-55
    patterns_high.json   → photo_count 56-80

Cada patrón incluye:
    - slot_sequence      : lista de tamaños de slot por página (1-4)
    - template_sequence  : plantilla asignada a cada página
    - color_scheme       : estrategia y colores por página
    - sequence           : páginas completas (intro + evidencia)
    - checksum           : hash SHA-256 para detectar duplicados
"""

import hashlib
import json
import logging
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_DATA_DIR    = Path(__file__).parent.parent / "data"
_CONFIG_FILE = _DATA_DIR / "pattern_config.json"

# Páginas de introducción fijas — siempre las primeras 3 de todo álbum
_INTRO_PAGES = [
    {"page": 1, "template": "cover_page",     "slots": 0, "color": None},
    {"page": 2, "template": "cover_letter",   "slots": 0, "color": None},
    {"page": 3, "template": "identification", "slots": 0, "color": None},
]


class PatternGenerator:
    """
    Genera y escribe los archivos de patrones pregenerados.

    Uso offline:
        PatternGenerator().generate_all()

    Uso online (desde endpoint admin):
        result = PatternGenerator().generate_all()
        # result es un dict con métricas de la generación

    La instancia es stateless — cada llamada a generate_all() lee
    el config fresco y escribe los JSONs desde cero.
    """

    # Rangos de photo_count por tipo
    RANGE_LIMITS = {
        "LOW":    (15, 30),
        "MEDIUM": (31, 55),
        "HIGH":   (56, 80),
    }

    def __init__(self) -> None:
        self._config: dict | None = None

    # ═══════════════════════════════════════════════════════════════════
    # Configuración
    # ═══════════════════════════════════════════════════════════════════

    def _load_config(self) -> dict:
        """
        Carga pattern_config.json una sola vez por instancia.

        Lanza FileNotFoundError si el archivo no existe — es el único
        archivo que no se puede regenerar automáticamente.
        """
        if self._config is not None:
            return self._config

        if not _CONFIG_FILE.exists():
            raise FileNotFoundError(
                f"Configuración de patrones no encontrada: {_CONFIG_FILE}"
            )

        with open(_CONFIG_FILE, encoding="utf-8") as f:
            self._config = json.load(f)

        logger.info("pattern_config.json cargado (v%s)", self._config.get("version", "?"))
        return self._config

    # ═══════════════════════════════════════════════════════════════════
    # Generación de secuencia de slots
    # ═══════════════════════════════════════════════════════════════════

    def _generate_slot_sequence(
        self, photo_count: int, range_type: str, config: dict
    ) -> List[int]:
        """
        Genera la secuencia de tamaños de slot respetando frecuencias
        y límites de página definidos en pattern_config.json.

        Reglas de composición visual aplicadas al final:
            - Primera página: slot 1 o 2 (nunca arrancar con grilla)
            - Sin dos páginas de 1 foto consecutivas
            - Sin pasar de 1 foto directamente a 4
        """
        lim    = config["page_limits"][range_type]
        freqs  = {int(k): v for k, v in config["frequencies"][range_type].items()}
        ideal  = int(photo_count / 2.7)
        target = max(lim["min"], min(ideal, lim["max"]))
        max_s4 = lim["max_slot4"]

        pool = []
        rem  = photo_count
        s4   = 0

        # Distribuir por frecuencia
        for sz, fr in sorted(freqs.items(), key=lambda x: x[1], reverse=True):
            n = int(target * fr)
            if sz == 4:
                n = min(n, max(0, max_s4 - s4))
            n = min(n, rem // sz)
            if n > 0:
                pool.extend([sz] * n)
                rem -= sz * n
                if sz == 4:
                    s4 += n

        # Distribuir fotos restantes
        while rem > 0:
            if rem >= 4 and s4 < max_s4:
                pool.append(4); s4 += 1; rem -= 4
            elif rem >= 3:
                pool.append(3); rem -= 3
            elif rem >= 2:
                pool.append(2); rem -= 2
            else:
                pool.append(1); rem -= 1

        # Agrupar y mezclar por tamaño
        groups = defaultdict(list)
        for s in pool:
            groups[s].append(s)
        for lst in groups.values():
            random.shuffle(lst)

        seq = []
        for k in sorted(groups):
            seq.extend(groups[k])

        return self._apply_composition_rules(seq)

    def _apply_composition_rules(self, seq: List[int]) -> List[int]:
        """Aplica las tres reglas de composición visual en orden."""
        seq = self._fix_start(seq)
        seq = self._fix_no_consecutive_1(seq)
        seq = self._fix_no_1_to_4(seq)
        return seq

    def _fix_start(self, seq: List[int]) -> List[int]:
        """Primera página debe ser slot 1 o 2."""
        if not seq or seq[0] in (1, 2):
            return seq
        for i in range(1, len(seq)):
            if seq[i] in (1, 2):
                seq[0], seq[i] = seq[i], seq[0]
                return seq
        seq[0] = 2
        return seq

    def _fix_no_consecutive_1(self, seq: List[int]) -> List[int]:
        """Evitar dos páginas de foto única seguidas."""
        seq = seq[:]
        for i in range(1, len(seq)):
            if seq[i] == 1 and seq[i - 1] == 1:
                for j in range(i + 1, len(seq)):
                    if seq[j] != 1:
                        seq[i], seq[j] = seq[j], seq[i]
                        break
                else:
                    seq[i] = 2
        return seq

    def _fix_no_1_to_4(self, seq: List[int]) -> List[int]:
        """Evitar pasar de 1 foto directamente a 4."""
        seq = seq[:]
        for i in range(1, len(seq)):
            if seq[i - 1] == 1 and seq[i] == 4:
                for j in range(i + 1, len(seq)):
                    if seq[j] not in (1, 4):
                        seq[i], seq[j] = seq[j], seq[i]
                        break
                else:
                    seq[i] = 3
        return seq

    # ═══════════════════════════════════════════════════════════════════
    # Asignación de plantillas y colores
    # ═══════════════════════════════════════════════════════════════════

    def _assign_templates(self, slot_seq: List[int], config: dict) -> List[str]:
        """
        Asigna plantillas a cada slot rotando entre las opciones disponibles
        para garantizar variedad sin repetir la misma plantilla seguida.
        """
        counters = {1: 0, 2: 0, 3: 0, 4: 0}
        result   = []
        for sz in slot_seq:
            opts = config["templates"][str(sz)]
            result.append(opts[counters[sz] % len(opts)])
            counters[sz] += 1
        return result

    def _generate_color_scheme(self, strategy: str, n: int, config: dict) -> dict:
        """
        Genera el esquema de colores para n páginas según la estrategia.

        Estrategias disponibles (definidas en pattern_config.json):
            monochrome → un color para todo el álbum
            dual       → alternancia entre dos colores
            gradient   → transición suave entre tres colores
            palette    → selección aleatoria de una paleta predefinida
            random     → color independiente por página
        """
        colors = config["colors"]

        if strategy == "monochrome":
            c = random.choice(colors)
            return {"strategy": "monochrome", "base_colors": [c], "page_colors": [c] * n}

        if strategy == "dual":
            c1, c2 = random.sample(colors, 2)
            return {
                "strategy":    "dual",
                "base_colors": [c1, c2],
                "page_colors": [c1 if i % 2 == 0 else c2 for i in range(n)],
            }

        if strategy == "gradient":
            g  = random.choice(config["gradients"])
            pc = [
                g[0] if (i / max(n - 1, 1)) < 0.33
                else g[1] if (i / max(n - 1, 1)) < 0.66
                else g[2]
                for i in range(n)
            ]
            return {"strategy": "gradient", "base_colors": g, "page_colors": pc}

        if strategy == "palette":
            p = random.choice(config["palettes"])
            return {
                "strategy":    "palette",
                "base_colors": p,
                "page_colors": [random.choice(p) for _ in range(n)],
            }

        # random (default y fallback para estrategia desconocida)
        return {
            "strategy":    "random",
            "base_colors": colors,
            "page_colors": [random.choice(colors) for _ in range(n)],
        }

    # ═══════════════════════════════════════════════════════════════════
    # Construcción de un patrón individual
    # ═══════════════════════════════════════════════════════════════════

    def _build_pattern(
        self, photo_count: int, range_type: str, strategy: str, config: dict
    ) -> dict:
        """
        Construye un patrón completo para el photo_count y estrategia dados.

        El checksum SHA-256 permite detectar duplicados durante la generación
        masiva — dos patrones con igual checksum son visualmente idénticos.

        Retorna
        -------
        dict — patrón con todos los campos esperados por PatternService
        """
        slots     = self._generate_slot_sequence(photo_count, range_type, config)
        templates = self._assign_templates(slots, config)
        scheme    = self._generate_color_scheme(strategy, len(slots), config)

        raw_data = json.dumps(
            {"s": slots, "t": templates, "c": scheme["page_colors"]},
            sort_keys=True
        )
        checksum = hashlib.sha256(raw_data.encode()).hexdigest()

        pages = [
            {
                "page":     i + 4,   # páginas 1-3 son siempre intro
                "template": tid,
                "slots":    sz,
                "color":    scheme["page_colors"][i],
            }
            for i, (sz, tid) in enumerate(zip(slots, templates))
        ]

        return {
            "pattern_id":        f"{range_type.lower()}_{photo_count}_{checksum[:8]}",
            "range_type":        range_type,
            "photo_count":       photo_count,
            "total_pages":       3 + len(pages),
            "photo_pages":       len(pages),
            "slot_sequence":     slots,
            "template_sequence": templates,
            "color_scheme":      scheme,
            "checksum":          checksum,
            "sequence":          _INTRO_PAGES + pages,
        }

    # ═══════════════════════════════════════════════════════════════════
    # Generación masiva
    # ═══════════════════════════════════════════════════════════════════

    def _generate_range(
        self, range_type: str, lo: int, hi: int, patterns_per_count: int, config: dict
    ) -> list[dict]:
        """
        Genera todos los patrones para un rango completo (LOW, MEDIUM o HIGH).

        Para cada photo_count intenta generar `patterns_per_count` patrones
        únicos (por checksum). Si tras 20× intentos no alcanza el objetivo,
        acepta los que tenga y registra un WARNING.

        Parámetros
        ----------
        range_type         : str  — "LOW", "MEDIUM" o "HIGH"
        lo, hi             : int  — límites inclusivos del rango de photo_count
        patterns_per_count : int  — patrones únicos objetivo por photo_count
        config             : dict — contenido de pattern_config.json

        Retorna
        -------
        list[dict] — todos los patrones generados para el rango
        """
        strategies   = config["color_strategies"]
        all_patterns = []

        for pc in range(lo, hi + 1):
            seen     = set()
            batch    = []
            attempts = 0
            max_attempts = patterns_per_count * 20

            while len(batch) < patterns_per_count and attempts < max_attempts:
                attempts += 1
                strategy = strategies[len(batch) % len(strategies)]
                pattern  = self._build_pattern(pc, range_type, strategy, config)

                if pattern["checksum"] not in seen:
                    seen.add(pattern["checksum"])
                    batch.append(pattern)

            if len(batch) < patterns_per_count:
                logger.warning(
                    "[%s] photo_count=%d: solo %d/%d patrones únicos generados "
                    "tras %d intentos",
                    range_type, pc, len(batch), patterns_per_count, attempts
                )
            else:
                logger.debug("[%s] photo_count=%d: %d patrones", range_type, pc, len(batch))

            all_patterns.extend(batch)

        return all_patterns

    def generate_all(self, patterns_per_count: int | None = None) -> dict:
        """
        Genera y escribe los tres archivos JSON de patrones pregenerados.

        Puede llamarse tanto offline (CLI) como online (endpoint admin).
        Sobreescribe los archivos existentes en data/.

        Parámetros
        ----------
        patterns_per_count : int | None
            Patrones únicos a generar por photo_count.
            Si es None, usa el valor definido en pattern_config.json.
            Pasar un número menor (ej. 5) es útil para tests rápidos.

        Retorna
        -------
        dict — métricas de la generación:
            {
                "generated_at"  : str (ISO 8601),
                "ranges"        : {
                    "LOW":    {"file": "...", "total_patterns": N},
                    "MEDIUM": {...},
                    "HIGH":   {...},
                },
                "total_patterns": N,
            }

        Lanza
        -----
        FileNotFoundError — si pattern_config.json no existe
        """
        config = self._load_config()
        ppc    = patterns_per_count or config.get("patterns_per_count", 30)

        logger.info(
            "Iniciando generación: %d patrones/count, rangos %s",
            ppc, list(self.RANGE_LIMITS.keys())
        )

        generated_at = datetime.now().isoformat()
        metrics      = {"generated_at": generated_at, "ranges": {}, "total_patterns": 0}

        for range_type, (lo, hi) in self.RANGE_LIMITS.items():
            logger.info("Generando rango %s (%d-%d fotos)...", range_type, lo, hi)
            patterns = self._generate_range(range_type, lo, hi, ppc, config)

            output = {
                "version":        config.get("version", "v2.0"),
                "generated_at":   generated_at,
                "range_type":     range_type,
                "total_patterns": len(patterns),
                "patterns":       patterns,
            }

            out_path = _DATA_DIR / f"patterns_{range_type.lower()}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            metrics["ranges"][range_type] = {
                "file":           out_path.name,
                "total_patterns": len(patterns),
            }
            metrics["total_patterns"] += len(patterns)
            logger.info(
                "Rango %s completado: %d patrones → %s",
                range_type, len(patterns), out_path.name
            )

        logger.info("Generación completada: %d patrones en total", metrics["total_patterns"])
        return metrics


# ══════════════════════════════════════════════════════════════════════════
# CLI — uso offline
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Argumento opcional: patterns_per_count (útil para tests rápidos)
    ppc = int(sys.argv[1]) if len(sys.argv) > 1 else None

    print("Generando patrones de álbum Lifebound...")
    if ppc:
        print(f"  Modo rápido: {ppc} patrones por photo_count")

    result = PatternGenerator().generate_all(patterns_per_count=ppc)

    print(f"\n✅ Completado: {result['total_patterns']:,} patrones generados")
    for range_type, info in result["ranges"].items():
        print(f"   {range_type:6} → {info['file']} ({info['total_patterns']:,} patrones)")