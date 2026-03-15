"""
templates/base_template.py

Clase base abstracta para todas las plantillas PDF.

Sistema shared/own
------------------
- CASE_SHARED_FIELDS : dict global con los campos comunes a 2+ plantillas intro.
                       Se define UNA sola vez aquí.
- shared_fields      : lista de keys (de CASE_SHARED_FIELDS) que usa esta plantilla.
- own_fields         : dict de campos exclusivos de esta plantilla.
- fields             : propiedad calculada = shared_fields resueltos + own_fields.
                       Mantiene compatibilidad con TemplateManager sin cambios.

Flujo de datos
--------------
El payload llega con:
    { "shared": {...}, "own": {...}, "photos": {...} }

generate.py hace el merge antes de llamar a generate():
    data = {**shared, **own, **photos}

Las plantillas no necesitan saber si un campo es shared u own;
simplemente usan data.get('campo').
"""
from abc import ABC, abstractmethod
from typing import Dict, List


# ══════════════════════════════════════════════════════════════════════════
# Fuente única de verdad para campos compartidos entre plantillas intro
# ══════════════════════════════════════════════════════════════════════════

CASE_SHARED_FIELDS: Dict = {
    "field_office_name": {
        "label":    "Field Office Name",
        "type":     "text",
        "required": True,
        "default":  "Your Field Office Name",
        "shared":   True,
    },
    "field_office_address": {
        "label":    "Field Office Address",
        "type":     "text",
        "required": True,
        "default":  "Address of Your USCIS Field Office",
        "shared":   True,
    },
    "attention": {
        "label":    "Attention",
        "type":     "text",
        "required": True,
        "default":  "Attn: I-751/N-400 Interview",
        "shared":   True,
    },
    "applicant_name": {
        "label":    "Applicant Name",
        "type":     "text",
        "required": True,
        "default":  "Jane Smith",
        "shared":   True,
    },
    "spouse_name": {
        "label":    "USC Spouse Name",
        "type":     "text",
        "required": True,
        "default":  "John Smith",
        "shared":   True,
    },
    "applicant_number": {
        "label":    "Applicant A Number",
        "type":     "text",
        "required": False,
        "default":  "Your A Number",
        "shared":   True,
    },
    "n400_receipt": {
        "label":    "N-400 Receipt #",
        "type":     "text",
        "required": True,
        "default":  "IOE0000000000",
        "shared":   True,
    },
    "i751_receipt": {
        "label":    "I-751 Receipt #",
        "type":     "text",
        "required": True,
        "default":  "IOE0000000000",
        "shared":   True,
    },
    "address": {
        "label":    "Address",
        "type":     "text",
        "required": True,
        "default":  "Your address here",
        "shared":   True,
    },
    "interview_date": {
        "label":    "Interview Date",
        "type":     "text",
        "required": True,
        "default":  "January 01, 20XX",
        "shared":   True,
    },
    "interview_time": {
        "label":    "Interview Time",
        "type":     "text",
        "required": True,
        "default":  "9:30 AM",
        "shared":   True,
    },
}


# ══════════════════════════════════════════════════════════════════════════
# Clase base
# ══════════════════════════════════════════════════════════════════════════

class BaseTemplate(ABC):
    id:          str = ""
    name:        str = ""
    description: str = ""

    # Keys de CASE_SHARED_FIELDS que usa esta plantilla
    shared_fields: List[str] = []

    # Campos exclusivos de esta plantilla (no compartidos)
    own_fields: Dict = {}

    @property
    def fields(self) -> Dict:
        """
        Resuelve shared_fields + own_fields en un único dict.
        Mantiene compatibilidad con TemplateManager.get_template_fields()
        y con cualquier código que acceda a template.fields.
        El flag 'shared': True permite al frontend saber qué pre-rellenar.
        """
        resolved_shared = {
            key: CASE_SHARED_FIELDS[key]
            for key in self.shared_fields
            if key in CASE_SHARED_FIELDS
        }
        return {**resolved_shared, **self.own_fields}

    @abstractmethod
    def generate(self, data: Dict) -> bytes:
        pass