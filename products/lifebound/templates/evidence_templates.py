"""
evidence_templates.py
Plantillas de evidencia para casos migratorios USCIS.
"""
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from textwrap import wrap

from templates.photo_album_template import PhotoAlbumTemplate
from domain.value_objects.image_focus import ImageFocus


# ══════════════════════════════════════════════════════════
# HELPER — dibuja pie de página con fecha/lugar/descripción
# ══════════════════════════════════════════════════════════

def _draw_caption(c, cs, center_x, y, date_str, location_str, description_str, width):
    """Dibuja bloque de texto informativo al pie de la página."""
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(cs['text_secondary'])
    if date_str or location_str:
        meta = " · ".join(filter(None, [date_str, location_str]))
        tw = c.stringWidth(meta, "Helvetica-Bold", 9)
        c.drawString(center_x - tw / 2, y, meta)
        y -= 13

    if description_str:
        c.setFont("Helvetica", 9)
        c.setFillColor(cs['text_secondary'])
        for line in wrap(description_str, 80)[:3]:
            tw = c.stringWidth(line, "Helvetica", 9)
            c.drawString(center_x - tw / 2, y, line)
            y -= 11
    return y


def _fields_base(extra=None):
    base = {
        'date':        {'label': 'Date',        'type': 'text',     'required': False, 'default': ''},
        'location':    {'label': 'Location',    'type': 'text',     'required': False, 'default': ''},
        'description': {'label': 'Description', 'type': 'textarea', 'required': True,  'default': ''},
        'background_color': {'label': 'Color', 'type': 'select',
                             'options': ['white','cream','blush','sage','sky','lavender'],
                             'required': False, 'default': 'white'},
    }
    if extra:
        base.update(extra)
    return base


# ══════════════════════════════════════════════════════════
# SINGLE MOMENT V1 — 1 foto centrada grande
# ══════════════════════════════════════════════════════════

class EvidenceSingleMomentV1(PhotoAlbumTemplate):
    id          = "evidence_single_moment_v1"
    name        = "Single Moment"
    description = "1 foto centrada, marco profesional"
    fields      = {**_fields_base(), 'photo_1': {'label':'Photo','type':'image','required':False,'default':'','default_focus':'center'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {'photo_1': data['photo_1']} if data.get('photo_1') else {}
        focus = ImageFocus.from_string(data.get('photo_1_focus','center'))

        self.draw_background(c, bg)
        c.setStrokeColor(cs['accent']); c.setLineWidth(2)
        c.line(1*inch, self.height-0.5*inch, self.width-1*inch, self.height-0.5*inch)
        c.line(1*inch, 0.5*inch, self.width-1*inch, 0.5*inch)

        pw, ph = 5*inch, 6*inch
        px = (self.width-pw)/2; py = (self.height-ph)/2 + 0.3*inch
        self.draw_image_placeholder(c, px, py, pw, ph, "Photo", True, 'photo_1', user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, py - 0.3*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# SINGLE MOMENT V2 — 1 foto + título prominente
# ══════════════════════════════════════════════════════════

class EvidenceSingleMomentV2(PhotoAlbumTemplate):
    id          = "evidence_single_moment_v2"
    name        = "Single Moment V2"
    description = "1 foto con título prominente"
    fields      = {**_fields_base({'title': {'label':'Title','type':'text','required':False,'default':'A Special Moment'}}),
                   'photo_1': {'label':'Photo','type':'image','required':False,'default':'','default_focus':'center'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {'photo_1': data['photo_1']} if data.get('photo_1') else {}
        focus = ImageFocus.from_string(data.get('photo_1_focus','center'))

        self.draw_background(c, bg)
        cx = self.width/2

        title = data.get('title','A Special Moment')
        self.draw_text_with_style(c, title, cx, self.height-1.2*inch,
                                   font_name="Times-Italic", font_size=28,
                                   color_type='primary', color_name=bg, align='center')
        self.draw_decorative_line(c, 1.5*inch, self.height-1.5*inch, self.width-1.5*inch, self.height-1.5*inch, bg, 1)

        pw, ph = 5.5*inch, 6*inch
        px = (self.width-pw)/2; py = self.height-8*inch
        self.draw_image_placeholder(c, px, py, pw, ph, "Photo", True, 'photo_1', user_images, focus)

        _draw_caption(c, cs, cx, py - 0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# COMPARISON V1 — 2 fotos lado a lado
# ══════════════════════════════════════════════════════════

class EvidenceComparisonV1(PhotoAlbumTemplate):
    id          = "evidence_comparison_v1"
    name        = "Comparison"
    description = "2 fotos lado a lado"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Photo Left', 'type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_2': {'label':'Photo Right','type':'image','required':False,'default':'','default_focus':'top'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2') if data.get(k)}

        self.draw_background(c, bg)
        c.setFont("Helvetica", 10); c.setFillColor(cs['text_secondary'])
        c.drawCentredString(self.width/2, self.height-0.6*inch, "PHOTOGRAPHIC EVIDENCE")
        c.setStrokeColor(cs['accent']); c.setLineWidth(1)
        c.line(2*inch, self.height-0.75*inch, self.width-2*inch, self.height-0.75*inch)

        pw, ph = 3.4*inch, 5.5*inch
        gap = 0.4*inch
        total = pw*2+gap; sx = (self.width-total)/2
        py = (self.height-ph)/2 - 0.1*inch

        for i, (sid, label) in enumerate([('photo_1','LEFT'),('photo_2','RIGHT')]):
            x = sx + i*(pw+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','top'))
            self.draw_image_placeholder(c, x, py, pw, ph, label, True, sid, user_images, focus)
            c.setFont("Helvetica", 8); c.setFillColor(cs['text_secondary'])
            c.drawCentredString(x+pw/2, py-0.18*inch, label)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.35*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# COMPARISON V2 — 2 fotos apiladas verticalmente
# ══════════════════════════════════════════════════════════

class EvidenceComparisonV2(PhotoAlbumTemplate):
    id          = "evidence_comparison_v2"
    name        = "Comparison V2"
    description = "2 fotos apiladas verticamente"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Photo Top',   'type':'image','required':False,'default':'','default_focus':'center'},
                   'photo_2': {'label':'Photo Bottom','type':'image','required':False,'default':'','default_focus':'center'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2') if data.get(k)}

        self.draw_background(c, bg)
        pw, ph = 5*inch, 3.3*inch; gap = 0.3*inch
        px = (self.width-pw)/2
        py1 = self.height - 1.2*inch - ph
        py2 = py1 - gap - ph

        for sid, py, lbl in [('photo_1',py1,'TOP'),('photo_2',py2,'BOTTOM')]:
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','center'))
            self.draw_image_placeholder(c, px, py, pw, ph, lbl, True, sid, user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, py2-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# MILESTONE V1 — 1 foto con franja de título
# ══════════════════════════════════════════════════════════

class EvidenceMilestoneV1(PhotoAlbumTemplate):
    id          = "evidence_milestone_v1"
    name        = "Milestone"
    description = "1 foto con franja de título destacado"
    fields      = {**_fields_base({'title': {'label':'Milestone Title','type':'text','required':True,'default':'A New Beginning'}}),
                   'photo_1': {'label':'Photo','type':'image','required':False,'default':'','default_focus':'center'}}

    def generate(self, data: dict) -> bytes:
        from reportlab.lib.colors import black, white
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','cream')
        cs = self.get_color_scheme(bg)
        user_images = {'photo_1': data['photo_1']} if data.get('photo_1') else {}
        focus = ImageFocus.from_string(data.get('photo_1_focus','center'))

        self.draw_background(c, bg)
        pw, ph = 5.5*inch, 6*inch
        px = (self.width-pw)/2; py = self.height-7.5*inch

        self.draw_image_placeholder(c, px, py, pw, ph, "Photo", True, 'photo_1', user_images, focus)

        # Banner sobre la foto
        bh = 0.75*inch
        c.setFillColor(black)
        c.rect(px, py+ph-bh, pw, bh, fill=1, stroke=0)
        title = data.get('title','A New Beginning')
        c.setFillColor(white); c.setFont("Helvetica-Bold", 16)
        tw = c.stringWidth(title,"Helvetica-Bold",16)
        c.drawString(px+(pw-tw)/2, py+ph-bh+0.22*inch, title)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# BEFORE/AFTER V1 — 2 fotos con etiquetas BEFORE/AFTER
# ══════════════════════════════════════════════════════════

class EvidenceBeforeAfterV1(PhotoAlbumTemplate):
    id          = "evidence_before_after_v1"
    name        = "Before / After"
    description = "2 fotos con etiquetas BEFORE y AFTER"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Before Photo','type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_2': {'label':'After Photo', 'type':'image','required':False,'default':'','default_focus':'top'}}

    def generate(self, data: dict) -> bytes:
        from reportlab.lib.colors import white
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2') if data.get(k)}

        self.draw_background(c, bg)
        pw, ph = 3.2*inch, 5.2*inch; gap = 0.5*inch
        sx = (self.width - pw*2 - gap)/2
        py = (self.height-ph)/2

        for i, (sid, lbl, color_hex) in enumerate([
            ('photo_1','BEFORE','#64748b'),
            ('photo_2','AFTER', '#22c55e')
        ]):
            x = sx + i*(pw+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','top'))
            self.draw_image_placeholder(c, x, py, pw, ph, lbl, True, sid, user_images, focus)
            # Label pill
            pill_w, pill_h = 1.1*inch, 0.28*inch
            c.setFillColor(HexColor(color_hex))
            c.roundRect(x+(pw-pill_w)/2, py+ph-pill_h-0.1*inch, pill_w, pill_h, 4, fill=1, stroke=0)
            c.setFillColor(white); c.setFont("Helvetica-Bold", 9)
            tw = c.stringWidth(lbl,"Helvetica-Bold",9)
            c.drawString(x+(pw-tw)/2, py+ph-0.3*inch, lbl)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# SEQUENCE V1 — 3 fotos en fila
# ══════════════════════════════════════════════════════════

class EvidenceSequenceV1(PhotoAlbumTemplate):
    id          = "evidence_sequence_v1"
    name        = "Sequence"
    description = "3 fotos en secuencia horizontal"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Photo 1','type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_2': {'label':'Photo 2','type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_3': {'label':'Photo 3','type':'image','required':False,'default':'','default_focus':'top'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2','photo_3') if data.get(k)}

        self.draw_background(c, bg)
        pw, ph = 2.1*inch, 5.5*inch; gap = 0.2*inch
        total = pw*3 + gap*2; sx = (self.width-total)/2
        py = (self.height-ph)/2

        for i, sid in enumerate(['photo_1','photo_2','photo_3']):
            x = sx + i*(pw+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','top'))
            self.draw_image_placeholder(c, x, py, pw, ph, f"Photo {i+1}", True, sid, user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# SEQUENCE V2 — 3 fotos (1 grande + 2 pequeñas)
# ══════════════════════════════════════════════════════════

class EvidenceSequenceV2(PhotoAlbumTemplate):
    id          = "evidence_sequence_v2"
    name        = "Sequence V2"
    description = "1 foto grande + 2 fotos pequeñas"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Main Photo', 'type':'image','required':False,'default':'','default_focus':'center'},
                   'photo_2': {'label':'Photo 2',    'type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_3': {'label':'Photo 3',    'type':'image','required':False,'default':'','default_focus':'top'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2','photo_3') if data.get(k)}

        self.draw_background(c, bg)
        lw, lh = 3.8*inch, 5.5*inch
        sw, sh = 2.4*inch, 2.6*inch
        gap = 0.3*inch
        total_w = lw + gap + sw; sx = (self.width-total_w)/2
        large_y = (self.height-lh)/2
        s2_y = large_y + lh - sh
        s3_y = large_y

        focus1 = ImageFocus.from_string(data.get('photo_1_focus','center'))
        focus2 = ImageFocus.from_string(data.get('photo_2_focus','top'))
        focus3 = ImageFocus.from_string(data.get('photo_3_focus','top'))

        self.draw_image_placeholder(c, sx, large_y, lw, lh, "Main Photo", True, 'photo_1', user_images, focus1)
        self.draw_image_placeholder(c, sx+lw+gap, s2_y, sw, sh, "Photo 2", True, 'photo_2', user_images, focus2)
        self.draw_image_placeholder(c, sx+lw+gap, s3_y, sw, sh, "Photo 3", True, 'photo_3', user_images, focus3)

        cx = self.width/2
        _draw_caption(c, cs, cx, large_y-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# TIMELINE V1 — 3 fotos con línea de tiempo
# ══════════════════════════════════════════════════════════

class EvidenceEventTimelineV1(PhotoAlbumTemplate):
    id          = "evidence_event_timeline_v1"
    name        = "Timeline"
    description = "3 fotos con línea de tiempo visual"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Early Photo',  'type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_2': {'label':'Middle Photo', 'type':'image','required':False,'default':'','default_focus':'top'},
                   'photo_3': {'label':'Recent Photo', 'type':'image','required':False,'default':'','default_focus':'top'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2','photo_3') if data.get(k)}

        self.draw_background(c, bg)
        c.setFont("Helvetica-Bold", 12); c.setFillColor(cs['text_primary'])
        c.drawCentredString(self.width/2, self.height-0.8*inch, "EVIDENCE TIMELINE")
        self.draw_decorative_line(c, 1*inch, self.height-1*inch, self.width-1*inch, self.height-1*inch, bg, 1)

        pw, ph = 2.1*inch, 4.8*inch; gap = 0.25*inch
        total = pw*3+gap*2; sx = (self.width-total)/2
        py = self.height-6.5*inch

        # Timeline line
        cx_line = sx + pw/2
        c.setStrokeColor(cs['accent']); c.setLineWidth(2)
        c.line(cx_line, py+ph+0.2*inch, cx_line + (pw+gap)*2, py+ph+0.2*inch)

        labels = ['EARLY', 'MIDDLE', 'RECENT']
        for i, (sid, lbl) in enumerate(zip(['photo_1','photo_2','photo_3'], labels)):
            x = sx + i*(pw+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','top'))
            self.draw_image_placeholder(c, x, py, pw, ph, lbl, True, sid, user_images, focus)
            # Timeline dot
            dot_x = x + pw/2
            c.setFillColor(cs['accent']); c.circle(dot_x, py+ph+0.2*inch, 5, fill=1, stroke=0)
            c.setFont("Helvetica", 7); c.setFillColor(cs['text_secondary'])
            tw = c.stringWidth(lbl,"Helvetica",7)
            c.drawString(dot_x-tw/2, py+ph+0.4*inch, lbl)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# GRID V1 — 4 fotos en grid 2×2
# ══════════════════════════════════════════════════════════

class EvidenceGridV1(PhotoAlbumTemplate):
    id          = "evidence_grid_v1"
    name        = "Photo Grid"
    description = "4 fotos en grid 2×2"
    fields      = {**_fields_base(),
                   **{f'photo_{i}': {'label':f'Photo {i}','type':'image','required':False,'default':'','default_focus':'center'} for i in range(1,5)}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {f'photo_{i}': data[f'photo_{i}'] for i in range(1,5) if data.get(f'photo_{i}')}

        self.draw_background(c, bg)
        pw = ph = 2.8*inch; gap = 0.3*inch
        total_w = pw*2+gap; total_h = ph*2+gap
        sx = (self.width-total_w)/2; sy = (self.height-total_h)/2

        positions = [(sx,sy+ph+gap),(sx+pw+gap,sy+ph+gap),(sx,sy),(sx+pw+gap,sy)]
        for i, (x,y) in enumerate(positions):
            sid = f'photo_{i+1}'
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','center'))
            self.draw_image_placeholder(c, x, y, pw, ph, f"Photo {i+1}", True, sid, user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, sy-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# GRID V2 — 4 fotos en fila horizontal
# ══════════════════════════════════════════════════════════

class EvidenceGridV2(PhotoAlbumTemplate):
    id          = "evidence_grid_v2"
    name        = "Grid V2"
    description = "4 fotos en fila horizontal"
    fields      = {**_fields_base(),
                   **{f'photo_{i}': {'label':f'Photo {i}','type':'image','required':False,'default':'','default_focus':'center'} for i in range(1,5)}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {f'photo_{i}': data[f'photo_{i}'] for i in range(1,5) if data.get(f'photo_{i}')}

        self.draw_background(c, bg)
        pw, ph = 1.6*inch, 5.5*inch; gap = 0.2*inch
        total = pw*4+gap*3; sx = (self.width-total)/2
        py = (self.height-ph)/2

        for i in range(4):
            sid = f'photo_{i+1}'
            x = sx + i*(pw+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','center'))
            self.draw_image_placeholder(c, x, py, pw, ph, f"{i+1}", True, sid, user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, py-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()


# ══════════════════════════════════════════════════════════
# DAILY LIFE V1 — 4 fotos en layout magazine
# ══════════════════════════════════════════════════════════

class EvidenceDailyLifeV1(PhotoAlbumTemplate):
    id          = "evidence_daily_life_v1"
    name        = "Daily Life"
    description = "4 fotos en layout tipo revista"
    fields      = {**_fields_base(),
                   'photo_1': {'label':'Main Photo (large)',  'type':'image','required':False,'default':'','default_focus':'center'},
                   'photo_2': {'label':'Photo 2',             'type':'image','required':False,'default':'','default_focus':'center'},
                   'photo_3': {'label':'Photo 3',             'type':'image','required':False,'default':'','default_focus':'center'},
                   'photo_4': {'label':'Photo 4',             'type':'image','required':False,'default':'','default_focus':'center'}}

    def generate(self, data: dict) -> bytes:
        self._init_pdf()
        c, buf = self.create_canvas()
        bg = data.get('background_color','white')
        cs = self.get_color_scheme(bg)
        user_images = {k: data[k] for k in ('photo_1','photo_2','photo_3','photo_4') if data.get(k)}

        self.draw_background(c, bg)

        gap = 0.2*inch
        # Large left photo
        lw, lh = 3.5*inch, 5.5*inch
        lx, ly = 1*inch, self.height-6.8*inch
        # Small right column: 3 stacked
        sw = self.width - lx - lw - gap - 1*inch
        sh = (lh - gap*2) / 3

        f1 = ImageFocus.from_string(data.get('photo_1_focus','center'))
        self.draw_image_placeholder(c, lx, ly, lw, lh, "Main", True, 'photo_1', user_images, f1)

        rx = lx + lw + gap
        for i, sid in enumerate(['photo_2','photo_3','photo_4']):
            ry = ly + (2-i)*(sh+gap)
            focus = ImageFocus.from_string(data.get(f'{sid}_focus','center'))
            self.draw_image_placeholder(c, rx, ry, sw, sh, f"Photo {i+2}", True, sid, user_images, focus)

        cx = self.width/2
        _draw_caption(c, cs, cx, ly-0.25*inch,
                      data.get('date',''), data.get('location',''), data.get('description',''), self.width)
        c.showPage(); c.save(); buf.seek(0)
        return buf.getvalue()
