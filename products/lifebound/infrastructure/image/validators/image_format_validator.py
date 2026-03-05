"""
image_format_validator.py
Validación de imágenes: formato, resolución mínima, tamaño máximo.
"""
from io import BytesIO
from PIL import Image

MIN_WIDTH  = 600
MIN_HEIGHT = 900
MAX_BYTES  = 15 * 1024 * 1024  # 15MB

CONVERTIBLE = {"image/heic","image/webp","image/bmp","image/tiff","image/gif"}
VALID_NATIVE = {"image/jpeg","image/png"}

class ImageFormatValidator:

    def validate(self, data: bytes, mime_type: str) -> dict:
        """
        Retorna:
          { "valid": True,  "data": bytes, "reason": None }
          { "valid": False, "data": None,  "reason": "mensaje" }
        """
        if len(data) > MAX_BYTES:
            return {"valid": False, "data": None,
                    "reason": f"File too large (max 15MB)"}

        if mime_type not in VALID_NATIVE and mime_type not in CONVERTIBLE:
            return {"valid": False, "data": None,
                    "reason": f"Unsupported format: {mime_type}"}

        try:
            img = Image.open(BytesIO(data)).convert("RGB")
            w, h = img.size
            if w < MIN_WIDTH or h < MIN_HEIGHT:
                return {"valid": False, "data": None,
                        "reason": f"Resolution too low ({w}x{h}, min {MIN_WIDTH}x{MIN_HEIGHT})"}
            # Convertir a JPEG si es necesario
            if mime_type not in VALID_NATIVE:
                out = BytesIO()
                img.save(out, format="JPEG", quality=90)
                data = out.getvalue()
            return {"valid": True, "data": data, "reason": None}
        except Exception as e:
            return {"valid": False, "data": None,
                    "reason": f"Corrupted or unreadable image"}
