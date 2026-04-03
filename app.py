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
#     4. Conductor + wire_auth()
#     5. Tracer
#     6. Alembic migrations
#     7. db.create_all()
#
# Sentry:
#     - Inicializado antes de create_app()
#     - _before_send_filter limpia variables sensibles
#     - capture_exception en todos los bloques críticos del wiring
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


# ══════════════════════════════════════════════════════════
# SENTRY — antes de create_app()
# ══════════════════════════════════════════════════════════

# Variables que nunca deben salir hacia Sentry
_SENSITIVE_KEYS = {
    "SENTRY_DSN",
    "SECRET_KEY",
    "DATABASE_URL",
    "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_SECRET",
    "PAYPAL_SECRET",
    "SMTP_PASSWORD",
}


def _before_send_filter(event, hint):
    """
    Intercepta cada evento antes de enviarlo a Sentry.
    Elimina variables de entorno sensibles del contexto
    y limpia cualquier extra que las contenga.
    """
    # Limpiar contexto de runtime/entorno
    for ctx_key in ("runtime", "environment", "os"):
        ctx = event.get("contexts", {}).get(ctx_key, {})
        for key in _SENSITIVE_KEYS:
            ctx.pop(key, None)

    # Limpiar extra
    extra = event.get("extra", {})
    for key in _SENSITIVE_KEYS:
        extra.pop(key, None)

    # Limpiar request data — nunca enviar headers de autorización
    request_data = event.get("request", {})
    headers = request_data.get("headers", {})
    headers.pop("Authorization", None)
    headers.pop("Cookie", None)

    return event


_sentry_dsn = os.environ.get("SENTRY_DSN", "")

if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask      import FlaskIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.logging    import LoggingIntegration

    sentry_sdk.init(
        dsn                = _sentry_dsn,
        integrations       = [
            FlaskIntegration(),
            SqlalchemyIntegration(),
            LoggingIntegration(
                level       = logging.WARNING,   # captura WARNING+ en breadcrumbs
                event_level = logging.ERROR,     # crea evento solo en ERROR+
            ),
        ],
        traces_sample_rate = 0.1,                # 10% de requests trackeadas
        environment        = os.environ.get("FLASK_ENV", "development"),
        release            = os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        send_default_pii   = False,              # nunca enviar datos personales
        before_send        = _before_send_filter,
    )
    log.info("  [✓] Sentry initialized (env=%s)", os.environ.get("FLASK_ENV"))
else:
    log.info("  [−] Sentry disabled (SENTRY_DSN not set)")


# ── Helper interno — captura a Sentry con contexto de fase ────────────────
def _sentry_capture(exc: Exception, step: str, phase: str = "wiring") -> None:
    """
    Captura una excepción en Sentry con tags de fase y paso.
    No lanza — si Sentry falla, el sistema continúa su propio raise.
    Solo actúa si el SDK está disponible y el DSN está configurado.
    """
    if not _sentry_dsn:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("phase", phase)
            scope.set_tag("step",  step)
            scope.set_tag("env",   os.environ.get("FLASK_ENV", "development"))
            sentry_sdk.capture_exception(exc)
    except Exception as sentry_err:
        log.error("  [Sentry] capture failed: %s", sentry_err)


# ══════════════════════════════════════════════════════════
# APP FACTORY
# ══════════════════════════════════════════════════════════

def create_app():
    from flask import Flask, render_template, jsonify

    app = Flask(__name__)

    app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_cambia_esto")

    _is_production = os.environ.get("FLASK_ENV") == "production"
    app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
    app.config["SESSION_COOKIE_SECURE"]      = _is_production
    app.config["SESSION_COOKIE_HTTPONLY"]    = True
    app.config["SESSION_COOKIE_NAME"]        = "aureon_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = 3600
    app.config["MAX_CONTENT_LENGTH"]         = 100 * 1024 * 1024

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
        _sentry_capture(e, step="db_init", phase="bootstrap")
        raise

    try:
        from products.auth import create_auth_blueprint
        for bp in create_auth_blueprint():
            app.register_blueprint(bp)
        log.info("  [✓] Auth blueprints registered: /auth + /auth/passkey + /auth/oauth + /auth/account")
    except Exception as e:
        log.error("  [✗] Auth blueprints failed: %s", e)
        _sentry_capture(e, step="auth_blueprints", phase="bootstrap")
        raise

    try:
        from products.lifebound.routes import lifebound_bp
        app.register_blueprint(lifebound_bp)
        log.info("  [✓] Lifebound blueprint registered: /lifebound")
    except Exception as e:
        log.error("  [✗] Lifebound blueprint failed: %s", e)
        _sentry_capture(e, step="lifebound_blueprint", phase="bootstrap")
        # No raise — Lifebound no es crítico

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
        _sentry_capture(e, step="oauth")
        # No raise — OAuth puede fallar sin tumbar el sistema

    # 2b. Conductor + wire_auth
    try:
        from shared.control.conductor import conductor
        from products.auth.wiring import wire_auth
        wire_auth(app, conductor)
        conductor.mark_ready()
        log.info("  [✓] Conductor ready")
    except Exception as e:
        log.error("  [✗] Wiring failed: %s", e)
        _sentry_capture(e, step="conductor")
        raise  # Crítico

    # 2c. Tracer
    try:
        from shared.control.tracer import Tracer, register_tracer, TraceLoopError
        tracer = Tracer(conductor)
        register_tracer(tracer)
        app.before_request(tracer.begin)
        app.after_request(tracer.finish)
        app.register_error_handler(TraceLoopError, tracer.loop_error_handler)
        log.info("  [✓] Tracer wired (before_request / after_request / loop_error_handler)")
    except Exception as e:
        log.error("  [✗] Tracer wiring failed: %s", e)
        _sentry_capture(e, step="tracer")
        raise  # Crítico

    # 2d. Alembic migrations
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        alembic_cfg = AlembicConfig(os.path.join(_BASE_DIR, "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", os.path.join(_BASE_DIR, "migrations")
        )
        with app.app_context():
            alembic_command.upgrade(alembic_cfg, "head")
        log.info("  [✓] Alembic migrations applied (head)")
    except Exception as e:
        log.error("  [✗] Alembic migration failed: %s", e)
        _sentry_capture(e, step="alembic")
        # No raise — db.create_all actúa como fallback

    # 2e. Crear / verificar tablas
    try:
        with app.app_context():
            from shared.db import db
            db.create_all()
            log.info("  [✓] Tables verified/created")
    except Exception as e:
        log.error("  [✗] db.create_all failed: %s", e)
        _sentry_capture(e, step="db_create_all")
        raise  # Crítico

    # 2f. Rutas registradas (solo en desarrollo)
    if not _is_production:
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
        """
        Endpoint público mínimo para Render y UptimeRobot.
        Solo confirma que el sistema está vivo — sin datos internos.
        """
        return jsonify({"status": "ok"}), 200

    @app.route("/health/full")
    def health_full():
        """
        Endpoint completo con estado del conductor y tracer.
        Proteger con @require_admin antes de ir a producción.
        """
        from shared.control.conductor import conductor
        import shared.control.tracer as _tracer_mod

        payload = {
            "status":    "ok",
            "conductor": conductor.all_snapshots(),
        }
        if _tracer_mod._tracer_instance is not None:
            payload["tracer"] = _tracer_mod._tracer_instance.snapshot()

        return jsonify(payload), 200

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