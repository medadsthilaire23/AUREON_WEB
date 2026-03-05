"""
image_resizer.py
Crop inteligente con focus. CENTER por defecto (modo automático).
"""
import logging
from io import BytesIO
from PIL import Image
from domain.value_objects.image_dimensions import ImageDimensions
from domain.value_objects.image_focus import ImageFocus

logger = logging.getLogger(__name__)

class ImageResizer:
    def __init__(self, output_format="JPEG", output_quality=90):
        self.output_format  = output_format.upper()
        self.output_quality = output_quality

    def resize(self, image_buffer: BytesIO, dimensions: ImageDimensions,
               focus: ImageFocus = ImageFocus.CENTER) -> BytesIO:
        image_buffer.seek(0)
        img = Image.open(image_buffer).convert("RGB")
        tw, th = dimensions.width, dimensions.height
        iw, ih = img.size
        scale  = max(tw / iw, th / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img    = img.resize((nw, nh), Image.LANCZOS)

        if focus == ImageFocus.TOP:
            box = (0, 0, tw, th)
        elif focus == ImageFocus.BOTTOM:
            box = (0, nh - th, tw, nh)
        elif focus == ImageFocus.LEFT:
            box = (0, (nh - th) // 2, tw, (nh - th) // 2 + th)
        elif focus == ImageFocus.RIGHT:
            box = (nw - tw, (nh - th) // 2, nw, (nh - th) // 2 + th)
        else:  # CENTER
            box = ((nw - tw) // 2, (nh - th) // 2,
                   (nw - tw) // 2 + tw, (nh - th) // 2 + th)

        img    = img.crop(box)
        out    = BytesIO()
        img.save(out, format=self.output_format, quality=self.output_quality)
        out.seek(0)
        return out
