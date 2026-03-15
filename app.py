"""
app.py — AUREON Principal
Sala de recepción de todos los productos AUREON.
Registra cada producto como Blueprint independiente.
"""

import os
import sys
import logging
from flask import Flask, render_template, jsonify

# ══════════════════════════════════════════════════════════
# SYS.PATH — permite que routes.py de cada producto importe
# sus sub-módulos (modules/, api/, services/) directamente.
# ══════════════════════════════════════════════════════════

_LIFEBOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "products", "lifebound")
if _LIFEBOUND_DIR not in sys.path:
    sys.path.insert(0, _LIFEBOUND_DIR)

# ── App ───────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aureon")

# ══════════════════════════════════════════════════════════
# BLUEPRINTS — un producto = un blueprint
# ══════════════════════════════════════════════════════════

# Lifebound (AlbumUS)
try:
    from products.lifebound.routes import lifebound_bp
    app.register_blueprint(lifebound_bp)
    log.info("Blueprint registered: /lifebound")
except Exception as e:
    log.error(f"Lifebound blueprint failed to load: {e}")

# Aquí se agregan futuros productos:
# from products.otro_producto import otro_bp
# app.register_blueprint(otro_bp)

# ══════════════════════════════════════════════════════════
# RUTAS AUREON
# ══════════════════════════════════════════════════════════

announcements = [
    {
        "title": "Lifebound — USCIS Evidence Builder",
        "description": "Genera tu álbum de evidencia para USCIS en minutos.",
        "link": "/lifebound"
    },
    {
        "title": "Nueva API Amazon disponible",
        "description": "Extracción avanzada de datos optimizada.",
        "link": "/hud"
    },
    {
        "title": "Automatización AliExpress mejorada",
        "description": "Scripts más rápidos y eficientes.",
        "link": "/hud"
    },
]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/hud")
def hud():
    return render_template("hud.html")

@app.route("/api/announcements")
def get_announcements():
    return jsonify(announcements)

# ══════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info(f"{'=' * 50}")
    log.info(f"  AUREON — http://localhost:{port}")
    log.info(f"  Products: /lifebound")
    log.info(f"{'=' * 50}")
    app.run(host="0.0.0.0", port=port, debug=False)