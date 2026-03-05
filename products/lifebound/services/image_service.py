"""
image_service.py
Orquesta el procesamiento de imágenes:
focus + efectos para el PDF maker.
"""
from io import BytesIO
from domain.value_objects.image_dimensions import ImageDimensions
from domain.value_objects.image_focus import ImageFocus
from infrastructure.image.processors.image_resizer import ImageResizer
from infrastructure.image.processors.image_effect_processor import ImageEffectProcessor

class ImageService:
    def __init__(self):
        self._resizer   = ImageResizer()
        self._effects   = ImageEffectProcessor()

    def prepare(self, image_bytes: bytes, width: int, height: int,
                focus: ImageFocus = ImageFocus.CENTER) -> BytesIO:
        buf  = BytesIO(image_bytes)
        dims = ImageDimensions(width, height)
        return self._resizer.resize(buf, dims, focus=focus)

    def blur_background(self, image_bytes: bytes, radius: int = 8) -> BytesIO:
        return self._effects.apply_blur(BytesIO(image_bytes), radius)
