"""
image_effect_processor.py
Blur gaussiano + ajuste de opacidad para fondos de plantillas.
"""
from io import BytesIO
from PIL import Image, ImageFilter

class ImageEffectProcessor:
    def __init__(self, output_format="PNG"):
        self.output_format = output_format.upper()

    def apply_blur(self, image_buffer: BytesIO, radius: int = 5) -> BytesIO:
        image_buffer.seek(0)
        img = Image.open(image_buffer).filter(ImageFilter.GaussianBlur(radius))
        out = BytesIO()
        img.save(out, format=self.output_format)
        out.seek(0)
        return out

    def adjust_opacity(self, image_buffer: BytesIO, opacity: float = 0.5) -> BytesIO:
        image_buffer.seek(0)
        img  = Image.open(image_buffer).convert("RGBA")
        r, g, b, a = img.split()
        a    = a.point(lambda x: int(x * opacity))
        img  = Image.merge("RGBA", (r, g, b, a))
        out  = BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out
