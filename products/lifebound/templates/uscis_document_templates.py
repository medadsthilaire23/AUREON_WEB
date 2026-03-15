"""
templates/uscis_document_templates.py

Portada y carta de presentación para entrevista USCIS.

Cambios vs versión anterior
----------------------------
- Eliminados los `fields` dict duplicados en cada clase.
- Cada clase declara `shared_fields` (keys de CASE_SHARED_FIELDS)
  y `own_fields` (campos exclusivos).
- La propiedad `fields` en BaseTemplate los une automáticamente.
- Los métodos generate() no cambian — reciben data ya mergeado.
- receipts_N y receipts_I reemplazan los campos fijos n400_receipt / i751_receipt.
  El backend itera dinámicamente los forms que el usuario activó.
"""
from templates.base_template import BaseTemplate
from templates.pdf_template_mixin import PdfTemplateMixin
from reportlab.lib.units import inch


class CoverPageTemplate(BaseTemplate, PdfTemplateMixin):
    id          = "cover_page"
    name        = "Cover Page"
    description = "Portada para documentos de entrevista N-400 / I-751"

    shared_fields = [
        "field_office_name",
        "field_office_address",
        "attention",
        "applicant_name",
        "spouse_name",
        "address",
        "receipts_N",       # dict  { "N-400": "IOE...", "N-600": "IOE..." }
        "receipts_I",       # dict  { "I-751": "IOE...", "I-130": "IOE..." }
        "interview_date",
        "interview_time",
        "applicant_number",
    ]

    own_fields = {}  # todos sus campos son compartidos

    def generate(self, data):
        self._init_pdf()
        c, buffer = self.create_canvas()
        self.draw_header(c, data.get('field_office_name',''), data.get('field_office_address',''), data.get('attention',''))

        y = self.height - 2.5*inch

        # Datos del solicitante
        for lbl, key in [("Applicant:",'applicant_name'),("USC Spouse:",'spouse_name'),("Address:",'address')]:
            c.setFont("Helvetica-Bold",11); c.drawString(self.margin, y, lbl)
            c.setFont("Helvetica",11);      c.drawString(self.margin+1.5*inch, y, data.get(key,''))
            y -= 20
        y -= 20

        # Receipts dinámicos — primero serie N, luego serie I
        for series in ['receipts_N', 'receipts_I']:
            for form_name, receipt_num in data.get(series, {}).items():
                c.setFont("Helvetica-Bold", 11)
                c.drawString(self.margin, y, f"{form_name} Receipt #")
                c.setFont("Helvetica", 11)
                c.drawString(self.margin + 2*inch, y, receipt_num)
                y -= 20

        y -= 60

        # Título del combo dinámico según los forms activos
        all_forms = list(data.get('receipts_N', {}).keys()) + list(data.get('receipts_I', {}).keys())
        combo_title = " and ".join(all_forms) if all_forms else "COMBO"
        for title in [combo_title, "COMBO INTERVIEW", "DOCUMENTS"]:
            self.draw_centered_title(c, title, y); y -= 60

        y -= 30
        c.setFont("Helvetica-Bold",14)
        for txt in [f"Date of Interview: {data.get('interview_date','')}",
                    f"Time of Interview: {data.get('interview_time','')}"]:
            tw = c.stringWidth(txt,"Helvetica-Bold",14)
            c.drawString((self.width-tw)/2, y, txt); y -= 30

        self.draw_footer(c, data.get('applicant_number',''), data.get('applicant_name',''))
        c.showPage(); c.save(); buffer.seek(0)
        return buffer.getvalue()


class CoverLetterTemplate(BaseTemplate, PdfTemplateMixin):
    id          = "cover_letter"
    name        = "Cover Letter"
    description = "Carta de presentación para entrevista USCIS"

    shared_fields = [
        "field_office_name",
        "field_office_address",
        "attention",
        "applicant_name",
        "spouse_name",
        "address",
        "receipts_N",       # dict  { "N-400": "IOE...", ... }
        "receipts_I",       # dict  { "I-751": "IOE...", "I-130": "IOE..." }
        "applicant_number",
    ]

    own_fields = {
        "include_tax_years": {
            "label":    "Tax Years",
            "type":     "text",
            "required": False,
            "default":  "20XX - 20XX",
        },
    }

    def generate(self, data):
        self._init_pdf()
        c, buffer = self.create_canvas()
        y = self.height - self.margin
        c.setFont("Helvetica-Bold",10); c.drawString(self.margin, y, data.get('field_office_name',''))
        y -= 12; c.setFont("Helvetica",9); c.drawString(self.margin, y, data.get('field_office_address',''))
        y -= 15; c.setFont("Helvetica-Bold",10); c.drawString(self.margin, y, data.get('attention',''))

        # Header derecho — receipts dinámicos en una sola línea
        receipts_N = data.get('receipts_N', {})
        receipts_I = data.get('receipts_I', {})
        all_receipts = {**receipts_N, **receipts_I}
        receipt_line = "  |  ".join(f"{form}: {num}" for form, num in all_receipts.items())

        yp = self.height - 1.5*inch
        c.setFont("Helvetica",8)
        for txt in [
            f"Applicant: {data.get('applicant_name','')}",
            f"US Citizen Spouse: {data.get('spouse_name','')}",
            f"Address: {data.get('address','')}",
            receipt_line,
        ]:
            c.drawRightString(self.width-self.margin, yp, txt); yp -= 10

        yp -= 25
        c.setFont("Helvetica-Bold",12)
        title = "Interview Cover Letter"
        tw = c.stringWidth(title,"Helvetica-Bold",12)
        xc = (self.width-tw)/2
        c.drawString(xc, yp, title); c.line(xc, yp-2, xc+tw, yp-2); yp -= 30
        c.setFont("Helvetica",10); c.drawString(self.margin, yp, "Dear USCIS Officer,"); yp -= 25
        c.drawString(self.margin, yp, "Below you will find a list of evidence presented at the interview:"); yp -= 25

        c.setFont("Helvetica-Bold",10); c.drawString(self.margin, yp, "1.   Identification Documents"); yp -= 18
        c.setFont("Helvetica",9)
        for doc in ["Permanent Resident Card","EAD & I-512 ID Card","Driver License","Foreign Passport","Birth Certificate","Social Security Card"]:
            c.drawString(self.margin+25, yp, f"○  {doc}"); yp -= 11
        yp -= 8
        c.setFont("Helvetica-Bold",10); c.drawString(self.margin, yp, "2.   Joint Financials & Cohabitation"); yp -= 18
        c.setFont("Helvetica",9)
        for doc in [f"Joint Tax Returns ({data.get('include_tax_years','20XX - 20XX')})",
                    "Joint Bank Account Statements","Health & Life Insurance","Car Insurance","Joint Mortgage / Rent Receipts"]:
            c.drawString(self.margin+25, yp, f"○  {doc}"); yp -= 11
        yp -= 8
        c.setFont("Helvetica-Bold",10); c.drawString(self.margin, yp, "3.   Photographic Evidence"); yp -= 25
        c.setFont("Helvetica",9); c.drawString(self.margin, yp, "Thank you for reviewing these applications and supporting documents.")
        yp -= 25; c.drawString(self.margin, yp, "Sincerely,"); yp -= 15
        c.setFont("Helvetica-Bold",9)
        c.drawString(self.margin, yp, f"{data.get('applicant_name','')} and {data.get('spouse_name','')}")

        self.draw_footer(c, data.get('applicant_number',''), data.get('applicant_name',''))
        c.showPage(); c.save(); buffer.seek(0)
        return buffer.getvalue()


class IdentificationPageTemplate(BaseTemplate, PdfTemplateMixin):
    id          = "identification_page"
    name        = "Identification Page"
    description = "Página de documentos de identificación"

    shared_fields = [
        "field_office_name",
        "field_office_address",
        "attention",
        "applicant_name",
        "spouse_name",
        "applicant_number",
    ]

    own_fields = {}  # todos sus campos son compartidos

    def generate(self, data):
        self._init_pdf()
        c, buffer = self.create_canvas()
        self.draw_header(c, data.get('field_office_name',''), data.get('field_office_address',''), data.get('attention',''))
        y = self.height-2.5*inch
        self.draw_section_title(c, "IDENTIFICATION", y); y -= 60
        c.setFont("Helvetica-Bold",14); c.drawString(self.margin, y, f"{data.get('applicant_name','JANE SMITH')} – Applicant"); y -= 25
        c.setFont("Helvetica",12)
        for doc in ["Permanent Resident Card","EAD & I-512 ID Card","Driver License","Foreign Passport","Birth Certificate","Social Security Card"]:
            c.circle(self.margin+10, y+4, 3, fill=1); c.drawString(self.margin+30, y, doc); y -= 20
        y -= 20
        c.setFont("Helvetica-Bold",14); c.drawString(self.margin, y, f"{data.get('spouse_name','JOHN SMITH')} – USC Spouse"); y -= 25
        c.setFont("Helvetica",12)
        for doc in ["Driver License","Birth Certificate","US Passport","Social Security Card"]:
            c.circle(self.margin+10, y+4, 3, fill=1); c.drawString(self.margin+30, y, doc); y -= 20
        y -= 30
        c.setFont("Helvetica-Bold",13); c.drawString(self.margin, y, "4. MARRIAGE CERTIFICATE")
        self.draw_footer(c, data.get('applicant_number',''), data.get('applicant_name',''))
        c.showPage(); c.save(); buffer.seek(0)
        return buffer.getvalue()