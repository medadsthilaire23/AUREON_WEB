"""
image_source_type.py — Value Object
Tipo de origen de una imagen.
"""
from enum import Enum

class ImageSourceType(Enum):
    USER        = "user"
    PLACEHOLDER = "placeholder"
    GENERATED   = "generated"
