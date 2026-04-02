# app.py — AUREON Principal
# ══════════════════════════════════════════════════════════════════════════════
# Director de la escalera de inicialización en dos fases.
#
# FASE 1 — Bootstrap:
#     1. Base de datos
#     2. Registro de blueprints (auth, lifebound, ...)
#
# FASE 2 — Wiring:
#     3. OAuth
#     4. Conductor + wire_auth()  ← subsistema de control integrado
#     5. db.create_all()
# ══════════════════════════════════════════════════════════════════════════════

import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
_LIFEBOUND_DIR = os.path.join(_BASE_DIR, "products", "lifebound")
_SHARED_DIR    = os.path.join(_BASE_DIR, "shared")

for _path in [_LIFEBOUND_DIR, _SHARED_DIR, _BASE_DIR]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aureon")


def create_app():
    from flask import Flask, render_template, jsonify

    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_cambia_esto")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    # ══════════════════════════════════════════════════════
    # FASE 1 — BOOTSTRAP
    # ══════════════════════════════════════════════════════

    log.info("── Fase 1: Bootstrap ─────────────────────────")

    try:
        from shared.db import init_db
        init_db(app)
        log.info("  [✓] Database initialized")
    except Exception as e:
        log.error("  [✗] Database init failed: %s", e)
        raise

    try:
        from products.auth import create_auth_blueprint
        for bp in create_auth_blueprint():
            app.register_blueprint(bp)
        log.info("  [✓] Auth blueprints registered: /auth + /auth/passkey + /auth/oauth + /auth/account")
    except Exception as e:
        log.error("  [✗] Auth blueprints failed: %s", e)
        raise

    try:
        from products.lifebound.routes import lifebound_bp
        app.register_blueprint(lifebound_bp)
        log.info("  [✓] Lifebound blueprint registered: /lifebound")
    except Exception as e:
        log.error("  [✗] Lifebound blueprint failed: %s", e)

    # ══════════════════════════════════════════════════════
    # FASE 2 — WIRING
    # ══════════════════════════════════════════════════════

    log.info("── Fase 2: Wiring ────────────────────────────")

    # 2a. OAuth
    try:
        from products.auth import configure_auth
        configure_auth(app)
        log.info("  [✓] OAuth configured")
    except Exception as e:
        log.error("  [✗] OAuth configuration failed: %s", e)

    # 2b. Conductor + wire_auth (subsistema de control + middleware + contexto)
    try:
        from shared.control.conductor import conductor
        from products.auth.wiring import wire_auth
        wire_auth(app, conductor)
        conductor.mark_ready()
        log.info("  [✓] Conductor ready")
    except Exception as e:
        log.error("  [✗] Wiring failed: %s", e)
        raise  # Crítico — sin wiring no hay auth

    # 2c. Crear / verificar tablas
    try:
        with app.app_context():
            from shared.db import db
            db.create_all()
            log.info("  [✓] Tables verified/created")
    except Exception as e:
        log.error("  [✗] db.create_all failed: %s", e)
        raise

    # 2d. Rutas registradas (solo en desarrollo)
    if os.environ.get("FLASK_ENV") != "production":
        with app.app_context():
            for rule in app.url_map.iter_rules():
                if any(x in rule.rule for x in ["oauth", "passkey", "auth"]):
                    log.info("  RUTA: %s", rule.rule)

    log.info("── Sistema listo ✓ ───────────────────────────")

    # ══════════════════════════════════════════════════════
    # RUTAS PRINCIPALES
    # ══════════════════════════════════════════════════════

    announcements = [
        {
            "title":       "Lifebound — USCIS Evidence Builder",
            "description": "Genera tu álbum de evidencia para USCIS en minutos.",
            "link":        "/lifebound",
        },
        {
            "title":       "Nueva API Amazon disponible",
            "description": "Extracción avanzada de datos optimizada.",
            "link":        "/hud",
        },
        {
            "title":       "Automatización AliExpress mejorada",
            "description": "Scripts más rápidos y eficientes.",
            "link":        "/hud",
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

    @app.route("/health")
    def health():
        from shared.control.conductor import conductor
        return jsonify({
            "status":    "ok",
            "conductor": conductor.all_snapshots(),
        }), 200

    return app


# ══════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info("=" * 50)
    log.info("  AUREON — http://localhost:%d", port)
    log.info("  /auth      SSO central")
    log.info("  /lifebound USCIS Evidence Builder")
    log.info("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)