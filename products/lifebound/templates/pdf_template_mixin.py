from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch


class PdfTemplateMixin:

    def _init_pdf(self):
        self.width, self.height = letter
        self.margin = 1 * inch

    def create_canvas(self):
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        return c, buffer

    def draw_header(self, c, office_name, office_address, attention):
        y = self.height - self.margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.margin, y, office_name)
        y -= 15
        c.setFont("Helvetica", 11)
        c.drawString(self.margin, y, office_address)
        y -= 20
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.margin, y, attention)

    def draw_footer(self, c, applicant_number, applicant_name):
        y = 0.75 * inch
        c.setFont("Helvetica", 9)
        footer_text = f"{applicant_name} | A#: {applicant_number}"
        c.drawString(self.margin, y, footer_text)

    def draw_section_title(self, c, title, y_pos):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(self.margin, y_pos, title)
        c.line(self.margin, y_pos - 5, self.width - self.margin, y_pos - 5)

    def draw_centered_title(self, c, title, y_pos, font_name="Helvetica-Bold", font_size=18):
        c.setFont(font_name, font_size)
        text_width = c.stringWidth(title, font_name, font_size)
        x_centered = (self.width - text_width) / 2
        c.drawString(x_centered, y_pos, title)
