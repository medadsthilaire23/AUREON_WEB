# app.py — AUREON Principal v4.0
# ══════════════════════════════════════════════════════════════════════════════
# Director de la escalera de inicialización en dos fases.
#
# FASE 1 — Bootstrap:
#     1. BootGate (antes de todo)
#     2. Base de datos
#     3. Registro de blueprints (auth, lifebound, ...)
#
# FASE 2 — Wiring:
#     4. OAuth
#     5. Timer — instanciado e inyectado en Conductor
#     6. Conductor + wire_auth() + wire_lifebound()
#     7. validate_boot() — validación cruzada JSON ↔ Python  [v4.0]
#     8. GateResolver.wire()                                 [v4.0]
#     9. Tracer + wire_http_gate()
#    10. scan_registry en after_request
#    11. Alembic migrations
#    12. db.create_all()
#    13. BootGate.mark_ready()
#
# v4.0:
#   - validate_boot() verifica que tabla_operacion.json y operation_gates.py
#     estén sincronizados antes de marcar el sistema como listo.
#   - GateResolver resuelve la jerarquía de gates recursivamente.
#     Si no está wired, el sistema funciona en modo v3.x (fail-open).
#   - wire_lifebound() registra Lifebound en el Conductor.
#   - g.op_id nunca es "OP001" por defecto — rutas desconocidas → "XX".
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

_SENSITIVE_KEYS = {
    "SENTRY_DSN", "SECRET_KEY", "DATABASE_URL",
    "GOOGLE_CLIENT_SECRET", "GITHUB_CLIENT_SECRET",
    "PAYPAL_SECRET", "SMTP_PASSWORD",
}


def _before_send_filter(event, hint):
    for ctx_key in ("runtime", "environment", "os"):
        ctx = event.get("contexts", {}).get(ctx_key, {})
        for key in _SENSITIVE_KEYS:
            ctx.pop(key, None)
    extra = event.get("extra", {})
    for key in _SENSITIVE_KEYS:
        extra.pop(key, None)
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
                level       = logging.WARNING,
                event_level = logging.ERROR,
            ),
        ],
        traces_sample_rate = 0.1,
        environment        = os.environ.get("FLASK_ENV", "development"),
        release            = os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        send_default_pii   = False,
        before_send        = _before_send_filter,
    )
    log.info("  [✓] Sentry initialized (env=%s)", os.environ.get("FLASK_ENV"))
else:
    log.info("  [−] Sentry disabled (SENTRY_DSN not set)")


def _sentry_capture(exc: Exception, step: str, phase: str = "wiring") -> None:
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
    from flask import Flask, render_template, jsonify, request

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

    # ── 1a. BootGate ──────────────────────────────────────
    from shared.control.gates.boot_gate import BootGate
    boot_gate = BootGate()

    # ── 1b. Base de datos ─────────────────────────────────
    try:
        with boot_gate.step("OP010_001", "db_init"):
            from shared.db import init_db
            init_db(app)
        log.info("  [✓] Database initialized")
    except Exception as e:
        log.error("  [✗] Database init failed: %s", e)
        _sentry_capture(e, step="db_init", phase="bootstrap")
        raise

    # ── 1c. Blueprints ────────────────────────────────────
    try:
        with boot_gate.step("OP010_002", "auth_blueprints"):
            from products.auth import create_auth_blueprint
            for bp in create_auth_blueprint():
                app.register_blueprint(bp)
        log.info("  [✓] Auth blueprints registered")
    except Exception as e:
        log.error("  [✗] Auth blueprints failed: %s", e)
        _sentry_capture(e, step="auth_blueprints", phase="bootstrap")
        raise

    try:
        with boot_gate.step("OP010_002", "lifebound_blueprint"):
            from products.lifebound.routes import lifebound_bp
            app.register_blueprint(lifebound_bp)
        log.info("  [✓] Lifebound blueprint registered")
    except Exception as e:
        log.error("  [✗] Lifebound blueprint failed: %s", e)
        _sentry_capture(e, step="lifebound_blueprint", phase="bootstrap")
        # No raise — Lifebound no es crítico

    # ══════════════════════════════════════════════════════
    # FASE 2 — WIRING
    # ══════════════════════════════════════════════════════

    log.info("── Fase 2: Wiring ────────────────────────────")

    # ── 2a. OAuth ─────────────────────────────────────────
    try:
        with boot_gate.step("OP010_003", "oauth"):
            from products.auth import configure_auth
            configure_auth(app)
        log.info("  [✓] OAuth configured")
    except Exception as e:
        log.error("  [✗] OAuth configuration failed: %s", e)
        _sentry_capture(e, step="oauth")

    # ── 2b. Timer ─────────────────────────────────────────
    try:
        with boot_gate.step("OP010_004", "timer"):
            from shared.control.timer import Timer
            from shared.control.registries.base import event_registry
            timer = Timer(registry=event_registry, poll_interval_ms=500)
            timer.start()
        log.info("  [✓] Timer started")
    except Exception as e:
        log.error("  [✗] Timer failed: %s", e)
        _sentry_capture(e, step="timer")
        raise

    # ── 2c. Conductor + wire_auth + wire_lifebound ────────
    try:
        with boot_gate.step("OP010_004", "conductor"):
            from shared.control.conductor import conductor
            from shared.control.registries.base import GateRegistry, BreakerRegistry

            conductor.wire_timer(timer)

            from products.auth.wiring import wire_auth
            wire_auth(app, conductor)

            for gate_name in ("HttpGate", "DbGate", "ModuleGate", "BootGate"):
                if gate_name in GateRegistry:
                    conductor._gates[gate_name] = GateRegistry.get(gate_name)

            conductor._gates["BootGate"] = boot_gate
            conductor.mark_ready()
        log.info("  [✓] Conductor ready")
    except Exception as e:
        log.error("  [✗] Wiring failed: %s", e)
        _sentry_capture(e, step="conductor")
        raise

    # ── 2c-bis. wire_lifebound ────────────────────────────
    # Separado del bloque anterior — Lifebound no es crítico.
    # Si falla, auth sigue funcionando.
    try:
        from products.lifebound.wiring import wire_lifebound
        wire_lifebound(app, conductor)
        log.info("  [✓] Lifebound wired")
    except Exception as e:
        log.warning("  [!] Lifebound wiring failed (no crítico): %s", e)
        _sentry_capture(e, step="lifebound_wiring")

    # ── 2d. wire_registry en BootGate ─────────────────────
    try:
        boot_gate.wire_registry(event_registry)
        log.info("  [✓] BootGate registry wired")
    except Exception as e:
        log.error("  [✗] BootGate wire_registry failed: %s", e)

    # ── 2e. validate_boot() — v4.0 ────────────────────────
    # Validación cruzada: tabla_operacion.json ↔ Python.
    # Si hay advertencias las loguea pero NO aborta el boot.
    # En producción el sistema arranca aunque el JSON tenga warnings.
    try:
        from shared.control.operation_gates import validate_boot
        boot_result = validate_boot()
        if boot_result["ok"]:
            log.info(
                "  [✓] OperationGates: %d operaciones validadas",
                boot_result["total"],
            )
        else:
            log.warning(
                "  [!] OperationGates: %d advertencias en tabla_operacion.json",
                len(boot_result["warnings"]),
            )
            for w in boot_result["warnings"]:
                log.warning("      ⚠ %s", w)
    except Exception as e:
        log.warning("  [!] validate_boot falló (no crítico): %s", e)

    # ── 2f. GateResolver — v4.0 ───────────────────────────
    # Orquestador de validación recursiva de jerarquía de gates.
    # Fail-open: si falla el wiring, el sistema funciona en modo v3.x.
    try:
        from shared.control.logic.gate_resolver import gate_resolver
        gate_resolver.wire(
            event_registry   = event_registry,
            gate_registry    = GateRegistry,
            breaker_registry = BreakerRegistry,
            conductor_gates  = conductor._gates,
        )
        log.info("  [✓] GateResolver wired")
    except Exception as e:
        log.warning("  [!] GateResolver wiring falló (fail-open, modo v3.x): %s", e)
        _sentry_capture(e, step="gate_resolver")

    # ── 2g. Tracer ────────────────────────────────────────
    try:
        with boot_gate.step("OP010_005", "tracer"):
            from shared.control.tracer import Tracer, register_tracer, TraceLoopError
            tracer = Tracer(conductor)
            register_tracer(tracer)
            app.before_request(tracer.begin)
            app.after_request(tracer.finish)
            app.register_error_handler(TraceLoopError, tracer.loop_error_handler)

            # Inyectar HttpGate en Tracer — cierra eventos CREATE→FINISH/ANOMALY
            if "HttpGate" in GateRegistry:
                http_gate = GateRegistry.get("HttpGate")
                tracer.wire_http_gate(http_gate)
                log.info("  [✓] Tracer ← HttpGate wired")
            else:
                log.warning("  [!] HttpGate no encontrado — eventos CREATE no se cerrarán")

        log.info("  [✓] Tracer wired")
    except Exception as e:
        log.error("  [✗] Tracer wiring failed: %s", e)
        _sentry_capture(e, step="tracer")
        raise

    # ── 2h. scan_registry en after_request ────────────────
    _SKIP_SCAN_PREFIXES = ("/static/", "/health", "/favicon")

    @app.after_request
    def _scan_control_registry(response):
        try:
            if not any(request.path.startswith(p) for p in _SKIP_SCAN_PREFIXES):
                conductor.scan_registry()
        except Exception as e:
            log.error("[app] scan_registry error: %s", e)
        return response

    log.info("  [✓] scan_registry registrado en after_request")

    # ── 2i. Alembic migrations ────────────────────────────
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

    # ── 2j. Crear / verificar tablas ──────────────────────
    try:
        with app.app_context():
            from shared.db import db
            db.create_all()
        log.info("  [✓] Tables verified/created")
    except Exception as e:
        log.error("  [✗] db.create_all failed: %s", e)
        _sentry_capture(e, step="db_create_all")
        raise

    # ── 2k. BootGate.mark_ready() ─────────────────────────
    boot_gate.mark_ready()
    if boot_gate.is_ready:
        log.info("  [✓] BootGate OPEN — sistema listo")
    else:
        log.error("  [✗] BootGate no pudo abrir — hay pasos fallidos")

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
        """Endpoint público mínimo para Render y UptimeRobot."""
        return jsonify({"status": "ok"}), 200

    @app.route("/health/full")
    def health_full():
        """Estado interno del sistema de control. Protegido en producción."""
        if _is_production:
            internal_token = os.environ.get("HEALTH_TOKEN", "")
            provided_token = request.headers.get("X-Health-Token", "")
            if not internal_token or provided_token != internal_token:
                return jsonify({"error": "Forbidden"}), 403

        import shared.control.tracer as _tracer_mod
        payload = {
            "status":       "ok",
            "boot_gate":    boot_gate.snapshot(),
            "conductor":    conductor.all_snapshots(),
            "timer":        timer.snapshot(),
            "gate_resolver": gate_resolver.snapshot() if gate_resolver._wired else None,
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