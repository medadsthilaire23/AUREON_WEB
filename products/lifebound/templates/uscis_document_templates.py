"""
uscis_document_templates.py
Portada y carta de presentación para entrevista USCIS.
"""
from templates.base_template import BaseTemplate
from templates.pdf_template_mixin import PdfTemplateMixin
from reportlab.lib.units import inch


class CoverPageTemplate(BaseTemplate, PdfTemplateMixin):
    id          = "cover_page"
    name        = "Cover Page"
    description = "Portada para documentos de entrevista N-400 / I-751"
    fields = {
        'field_office_name':    {'label':'Field Office Name',   'type':'text','required':True, 'default':'Your Field Office Name'},
        'field_office_address': {'label':'Field Office Address','type':'text','required':True, 'default':'Address of Your USCIS Field Office'},
        'attention':            {'label':'Attention',           'type':'text','required':True, 'default':'Attn: I-751/N-400 Interview'},
        'applicant_name':       {'label':'Applicant Name',      'type':'text','required':True, 'default':'Jane Smith'},
        'spouse_name':          {'label':'USC Spouse Name',     'type':'text','required':True, 'default':'John Smith'},
        'address':              {'label':'Address',             'type':'text','required':True, 'default':'Your address here'},
        'n400_receipt':         {'label':'N-400 Receipt #',     'type':'text','required':True, 'default':'IOE0000000000'},
        'i751_receipt':         {'label':'I-751 Receipt #',     'type':'text','required':True, 'default':'IOE0000000000'},
        'interview_date':       {'label':'Interview Date',      'type':'text','required':True, 'default':'January 01, 20XX'},
        'interview_time':       {'label':'Interview Time',      'type':'text','required':True, 'default':'9:30 AM'},
        'applicant_number':     {'label':'Applicant A Number',  'type':'text','required':False,'default':'Your A Number'},
    }

    def generate(self, data):
        self._init_pdf()
        c, buffer = self.create_canvas()
        self.draw_header(c, data.get('field_office_name',''), data.get('field_office_address',''), data.get('attention',''))

        y = self.height - 2.5*inch
        for lbl, key in [("Applicant:",'applicant_name'),("USC Spouse:",'spouse_name'),("Address:",'address')]:
            c.setFont("Helvetica-Bold",11); c.drawString(self.margin, y, lbl)
            c.setFont("Helvetica",11);      c.drawString(self.margin+1.5*inch, y, data.get(key,''))
            y -= 20
        y -= 20
        for lbl, key in [("N-400 Receipt #",'n400_receipt'),("I-751 Receipt #",'i751_receipt')]:
            c.setFont("Helvetica-Bold",11); c.drawString(self.margin, y, lbl)
            c.setFont("Helvetica",11);      c.drawString(self.margin+2*inch, y, data.get(key,''))
            y -= 20
        y -= 60
        for title in ["N-400 and I-751","COMBO INTERVIEW","DOCUMENTS"]:
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
    fields = {
        'field_office_name':    {'label':'Field Office Name',   'type':'text','required':True, 'default':'Your Field Office Name'},
        'field_office_address': {'label':'Field Office Address','type':'text','required':True, 'default':'Address of Your USCIS Field Office'},
        'attention':            {'label':'Attention',           'type':'text','required':True, 'default':'Attn: I-751/N-400 Interview'},
        'applicant_name':       {'label':'Applicant Name',      'type':'text','required':True, 'default':'Jane Smith'},
        'spouse_name':          {'label':'USC Spouse Name',     'type':'text','required':True, 'default':'John Smith'},
        'address':              {'label':'Address',             'type':'text','required':True, 'default':'Your address here'},
        'n400_receipt':         {'label':'N-400 Receipt #',     'type':'text','required':True, 'default':'IOE0000000000'},
        'i751_receipt':         {'label':'I-751 Receipt #',     'type':'text','required':True, 'default':'IOE0000000000'},
        'applicant_number':     {'label':'Applicant A Number',  'type':'text','required':False,'default':'Your A Number'},
        'include_tax_years':    {'label':'Tax Years',           'type':'text','required':False,'default':'20XX - 20XX'},
    }

    def generate(self, data):
        self._init_pdf()
        c, buffer = self.create_canvas()
        y = self.height - self.margin
        c.setFont("Helvetica-Bold",10); c.drawString(self.margin, y, data.get('field_office_name',''))
        y -= 12; c.setFont("Helvetica",9); c.drawString(self.margin, y, data.get('field_office_address',''))
        y -= 15; c.setFont("Helvetica-Bold",10); c.drawString(self.margin, y, data.get('attention',''))

        yp = self.height-1.5*inch
        c.setFont("Helvetica",8)
        for txt in [f"Applicant: {data.get('applicant_name','')}",
                    f"US Citizen Spouse: {data.get('spouse_name','')}",
                    f"Address: {data.get('address','')}",
                    f"I-751: {data.get('i751_receipt','')} | N-400: {data.get('n400_receipt','')}"]:
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
        for doc in [f"Joint Tax Returns ({data.get('include_tax_years','20XX-20XX')})",
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
    fields = {
        'field_office_name':    {'label':'Field Office Name',   'type':'text','required':True, 'default':'Your Field Office Name'},
        'field_office_address': {'label':'Field Office Address','type':'text','required':True, 'default':'Address of Your USCIS Field Office'},
        'attention':            {'label':'Attention',           'type':'text','required':True, 'default':'Attn: I-751/N-400 Interview'},
        'applicant_name':       {'label':'Applicant Name',      'type':'text','required':True, 'default':'JANE SMITH'},
        'spouse_name':          {'label':'USC Spouse Name',     'type':'text','required':True, 'default':'JOHN SMITH'},
        'applicant_number':     {'label':'Applicant A Number',  'type':'text','required':False,'default':'Your A Number'},
    }

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
