from abc import ABC
from typing import Optional
from io import BytesIO

from templates.base_template import BaseTemplate
from templates.pdf_template_mixin import PdfTemplateMixin
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib import colors

from domain.value_objects.image_focus import ImageFocus

RENDER_DPI = 150


class PhotoAlbumTemplate(BaseTemplate, PdfTemplateMixin, ABC):

    COLOR_PALETTES = {
        'white':    {'background': colors.white,          'text_primary': colors.black,           'text_secondary': HexColor('#666666'), 'accent': HexColor('#D4AF37'), 'border': HexColor('#E0E0E0')},
        'cream':    {'background': HexColor('#FFF8E7'),    'text_primary': HexColor('#2C1810'),     'text_secondary': HexColor('#6B5D52'), 'accent': HexColor('#C4A572'), 'border': HexColor('#D4C5A0')},
        'blush':    {'background': HexColor('#FFF0F5'),    'text_primary': HexColor('#4A3843'),     'text_secondary': HexColor('#8B7382'), 'accent': HexColor('#D4A5A5'), 'border': HexColor('#E8C5D0')},
        'sage':     {'background': HexColor('#F0F4F0'),    'text_primary': HexColor('#2D3E2D'),     'text_secondary': HexColor('#6B7C6B'), 'accent': HexColor('#8FA88F'), 'border': HexColor('#B0C8B0')},
        'sky':      {'background': HexColor('#F0F8FF'),    'text_primary': HexColor('#1C3A52'),     'text_secondary': HexColor('#5B7C99'), 'accent': HexColor('#7BA5CC'), 'border': HexColor('#A0C0E0')},
        'lavender': {'background': HexColor('#F5F0FF'),    'text_primary': HexColor('#3D2E52'),     'text_secondary': HexColor('#7A6B8F'), 'accent': HexColor('#B8A5D4'), 'border': HexColor('#C8B8E8')},
    }

    def __init__(self, image_service=None):
        super().__init__()
        self._init_pdf()
        self._image_service = image_service

    def get_color_scheme(self, color_name: str = 'white') -> dict:
        return self.COLOR_PALETTES.get(color_name, self.COLOR_PALETTES['white'])

    def draw_background(self, c, color_name: str = 'white'):
        cs = self.get_color_scheme(color_name)
        c.setFillColor(cs['background'])
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)

    def draw_image_placeholder(self, c, x, y, width, height,
                                label: str = "",
                                show_border: bool = True,
                                slot_id: Optional[str] = None,
                                user_images: Optional[dict] = None,
                                focus: ImageFocus = ImageFocus.CENTER):
        """Draw user image or placeholder. Crops image to fit slot using focus point."""
        from reportlab.lib.utils import ImageReader

        img_reader    = None
        is_user_image = False

        if user_images and slot_id and slot_id in user_images:
            try:
                img_path = user_images[slot_id]
                img_reader, is_user_image = self._load_and_crop_image(
                    img_path, width, height, focus
                )
            except Exception:
                img_reader = None

        if img_reader:
            try:
                c.drawImage(img_reader, x, y, width=width, height=height,
                            preserveAspectRatio=False, mask='auto')
            except Exception:
                self._draw_simple_placeholder(c, x, y, width, height)
                is_user_image = False
        else:
            self._draw_simple_placeholder(c, x, y, width, height)

        if not is_user_image and label:
            c.setFillColorRGB(0.96, 0.96, 0.96, alpha=0.7)
            c.rect(x + width*0.15, y + height*0.4, width*0.7, height*0.2, fill=1, stroke=0)
            c.setFont("Helvetica", 9)
            c.setFillColor(HexColor('#999999'))
            tw = c.stringWidth(label, "Helvetica", 9)
            c.drawString(x + (width - tw) / 2, y + (height / 2) - 4, label)

        if show_border:
            c.setStrokeColor(HexColor('#E0E0E0'))
            c.setLineWidth(1)
            c.rect(x, y, width, height, fill=0, stroke=1)

    def _load_and_crop_image(self, img_path_or_bytes, width, height, focus):
        """Load image, crop to fill slot exactly using focus point."""
        from PIL import Image
        from reportlab.lib.utils import ImageReader

        if isinstance(img_path_or_bytes, (bytes, bytearray)):
            img = Image.open(BytesIO(img_path_or_bytes))
        elif isinstance(img_path_or_bytes, BytesIO):
            img_path_or_bytes.seek(0)
            img = Image.open(img_path_or_bytes)
        else:
            img = Image.open(img_path_or_bytes)

        img = img.convert("RGB")

        target_w = int(width  * RENDER_DPI / inch)
        target_h = int(height * RENDER_DPI / inch)

        img_w, img_h = img.size
        scale = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Focus-based crop
        if focus == ImageFocus.TOP:
            crop_x = (new_w - target_w) // 2
            crop_y = 0
        elif focus == ImageFocus.BOTTOM:
            crop_x = (new_w - target_w) // 2
            crop_y = new_h - target_h
        elif focus == ImageFocus.LEFT:
            crop_x = 0
            crop_y = (new_h - target_h) // 2
        elif focus == ImageFocus.RIGHT:
            crop_x = new_w - target_w
            crop_y = (new_h - target_h) // 2
        else:  # CENTER
            crop_x = (new_w - target_w) // 2
            crop_y = (new_h - target_h) // 2

        img = img.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return ImageReader(buf), True

    def _draw_simple_placeholder(self, c, x, y, width, height):
        c.setFillColor(HexColor('#F5F5F5'))
        c.rect(x, y, width, height, fill=1, stroke=0)

    def draw_decorative_line(self, c, x1, y1, x2, y2, color_name='white', thickness=1):
        cs = self.get_color_scheme(color_name)
        c.setStrokeColor(cs['accent'])
        c.setLineWidth(thickness)
        c.line(x1, y1, x2, y2)

    def draw_text_with_style(self, c, text, x, y,
                              font_name="Helvetica", font_size=12,
                              color_type='primary', color_name='white', align='left'):
        cs = self.get_color_scheme(color_name)
        color_map = {'primary': cs['text_primary'], 'secondary': cs['text_secondary'], 'accent': cs['accent']}
        c.setFillColor(color_map.get(color_type, cs['text_primary']))
        c.setFont(font_name, font_size)
        if align == 'center':
            x = x - (c.stringWidth(text, font_name, font_size) / 2)
        elif align == 'right':
            x = x - c.stringWidth(text, font_name, font_size)
        c.drawString(x, y, text)

    def apply_layout_inversion(self, positions: list, invert: bool = False) -> list:
        if not invert:
            return positions
        return [{**pos, 'x': self.width - (pos['x'] + pos['width'])} for pos in positions]
