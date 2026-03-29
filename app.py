"""
app.py — AUREON Principal
Sala de recepción de todos los productos AUREON.
Registra cada producto como Blueprint independiente.
"""

import os
import sys
import logging
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
load_dotenv()
# ══════════════════════════════════════════════════════════
# SYS.PATH — permite que routes.py de cada producto importe
# sus sub-módulos (modules/, api/, services/) directamente.
# ══════════════════════════════════════════════════════════

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
_LIFEBOUND_DIR = os.path.join(_BASE_DIR, "products", "lifebound")
_SHARED_DIR    = os.path.join(_BASE_DIR, "shared")

for _path in [_LIFEBOUND_DIR, _SHARED_DIR, _BASE_DIR]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ── App ───────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_cambia_esto")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aureon")

# ══════════════════════════════════════════════════════════
# BASE DE DATOS
# ══════════════════════════════════════════════════════════

try:
    from shared.db import init_db
    init_db(app)
    log.info("Database initialized")
except Exception as e:
    log.error(f"Database init failed: {e}")

# ══════════════════════════════════════════════════════════
# BLUEPRINTS — un producto = un blueprint
# ══════════════════════════════════════════════════════════

# Auth (SSO central — init_auth registra auth_bp, passkey_bp y oauth_bp)
try:
    from products.auth import init_auth
    init_auth(app)
    log.info("Blueprint registered: /auth + /auth/passkey + /auth/oauth")
except Exception as e:
    log.error(f"Auth blueprint failed to load: {e}")

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
# CREAR TABLAS
# Solo en desarrollo — en producción usar: alembic upgrade head
# ══════════════════════════════════════════════════════════

try:
    with app.app_context():
        from shared.db import db
        db.create_all()
        log.info("Tables verified/created")
except Exception as e:
    log.error(f"db.create_all failed: {e}")

# ══════════════════════════════════════════════════════════
# DEBUG — rutas registradas (borrar en producción)
# ══════════════════════════════════════════════════════════

with app.app_context():
    for rule in app.url_map.iter_rules():
        if any(x in rule.rule for x in ['oauth', 'passkey', 'auth']):
            log.info(f"RUTA: {rule.rule}")

# ══════════════════════════════════════════════════════════
# RUTAS AUREON
# ══════════════════════════════════════════════════════════

announcements = [
    {
        "title":       "Lifebound — USCIS Evidence Builder",
        "description": "Genera tu álbum de evidencia para USCIS en minutos.",
        "link":        "/lifebound"
    },
    {
        "title":       "Nueva API Amazon disponible",
        "description": "Extracción avanzada de datos optimizada.",
        "link":        "/hud"
    },
    {
        "title":       "Automatización AliExpress mejorada",
        "description": "Scripts más rápidos y eficientes.",
        "link":        "/hud"
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
    log.info(f"  /auth      SSO central")
    log.info(f"  /lifebound USCIS Evidence Builder")
    log.info(f"{'=' * 50}")
    app.run(host="0.0.0.0", port=port, debug=False)