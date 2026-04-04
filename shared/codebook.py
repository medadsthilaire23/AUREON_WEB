# shared/codebook.py
# ══════════════════════════════════════════════════════════════════════════════
# AUREON — Codebook interno
#
# PROPÓSITO:
#   Tabla de traducción entre códigos opacos y significados legibles.
#   Los eventos se envían a Sentry como códigos — sin este archivo
#   los logs son ruido ininteligible para cualquier observador externo.
#
# REGLAS DE CÓDIGO:
#   - Sin vocales (A E I O U) → imposible formar palabras accidentalmente
#   - Sin separadores ni espacios
#   - Nunca reutilizar un código eliminado
#   - El significado real solo existe aquí
#
# ESTRUCTURA DE PREFIJOS (prefijo → capa → subsistema):
#
#   Capa Sistema / Infraestructura:
#     FACB1   → Fases de arranque (bootstrap / wiring)
#     BCB1    → Base de datos
#     GCB1    → Gates
#     CBS1    → Circuit Breakers
#     CCB1    → Conductor
#     TCB1    → Tracer
#     ERCB1   → Encoder
#     EMCB1   → Encoder Messager
#
#   Capa Autenticación:
#     RCB2    → Registro
#     ECB2    → Login email/password
#     GCB2    → OAuth Google
#     HCB2    → OAuth GitHub
#     CB2     → OAuth Complete / Sesiones / 2FA
#     CBP2    → Passkey
#     CBE2    → Email
#     CBD2    → Dispositivos
#     CBC2    → Cuenta
#     CBSS2   → Consent / SSO
#
#   Capa Producto:
#     CBS3    → Lifebound sesión
#     CB3     → Lifebound templates / imágenes / PDF
#     CBG3    → Lifebound generación + IA
#     CBLP3   → Lifebound patrones
#     CBLF3   → Lifebound formularios
#     CBLA3   → Lifebound acceso
#     AP3     → Acceso genérico al producto
#
#   Capa Tráfico / Seguridad:
#     CBR4    → Requests
#     PS4     → Patrones sospechosos
#     CAT4    → Anomalías
#     CBA4    → Ataques
#
#   Capa Construcción / Desarrollo:
#     CBD5    → Deploy
#     CBB5    → Blueprints
#     CBW5    → Wiring
#     CBM5    → Migraciones
#     CBE5    → Entorno
#
#   Capa Cliente (eventos frontend → longitud variable, sin vocales):
#     KLL1    → Cliente login / registro
#     CLO1    → Cliente OAuth
#     SN1     → Cliente sesión
#     MP1     → Cliente passkey
#     CLC1    → Cliente cuenta
#     CL1     → Cliente 2FA
#     KLF2    → Cliente Lifebound
#     CLT3    → Cliente tráfico / navegación
#
# VALIDADOR:
#   _validate() corre al importar este módulo y detecta códigos o
#   significados duplicados antes del arranque. El chequeo de formato
#   es por prefijo conocido — cualquier código con prefijo no registrado
#   se reporta como desconocido pero no bloquea el arranque.
#
# MANTENIMIENTO:
#   - Al agregar un nuevo subsistema → registrar su prefijo en la tabla
#     de arriba y extender el diccionario correspondiente
#   - Al agregar nuevos productos → extender CB3/AP3 y KLF2
#   - Al eliminar un código → marcarlo como DEPRECATED en comentario,
#     nunca borrar la entrada ni reutilizar el código
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations
import hashlib
import re


# ══════════════════════════════════════════════════════════
# CAPA SISTEMA / INFRAESTRUCTURA
# ══════════════════════════════════════════════════════════

SYSTEM = {
    # ── Fases de arranque ──────────────────────────────────
    "FACB1K7X": "phase_bootstrap_start",
    "FACB1M3Z": "phase_bootstrap_complete",
    "FACB1N9W": "phase_wiring_start",
    "FACB1P4V": "phase_wiring_complete",
    "FACB1Q2R": "phase_system_ready",
    "FACB1R8T": "phase_bootstrap_failed",
    "FACB1S5J": "phase_wiring_failed",

    # ── Base de datos ──────────────────────────────────────
    "BCB1T1B": "db_initialized",
    "BCB1V6D": "db_init_failed",
    "BCB1W3F": "db_migration_applied",
    "BCB1X9G": "db_migration_failed",
    "BCB1Y4H": "db_tables_verified",
    "BCB1Z7K": "db_connection_lost",
    "BCB1B2L": "db_connection_recovered",

    # ── Gates ──────────────────────────────────────────────
    "GCB1C5M": "gate_http_opened",
    "GCB1D8N": "gate_http_closed",
    "GCB1F1P": "gate_boot_opened",
    "GCB1G4Q": "gate_boot_closed",
    "GCB1H7R": "gate_module_opened",
    "GCB1J2S": "gate_module_closed",
    "GCB1K5T": "gate_db_opened",
    "GCB1L8V": "gate_db_closed",
    "GCB1M1W": "gate_oauth_google_opened",
    "GCB1N4X": "gate_oauth_google_closed",
    "GCB1P7Y": "gate_oauth_github_opened",
    "GCB1Q2Z": "gate_oauth_github_closed",
    "GCB1R5B": "gate_passkey_opened",
    "GCB1S8C": "gate_passkey_closed",
    "GCB1T1D": "gate_registration_opened",
    "GCB1V4F": "gate_registration_closed",

    # ── Circuit Breakers ───────────────────────────────────
    "CBS1W7G": "breaker_closed",
    "CBS1X2H": "breaker_open",
    "CBS1Y5J": "breaker_half_open",
    "CBS1Z8K": "breaker_tripped",
    "CBS1B1L": "breaker_recovered",
    "CBS1C4M": "breaker_google_oauth_tripped",
    "CBS1D7N": "breaker_github_oauth_tripped",
    "CBS1F2P": "breaker_passkey_tripped",
    "CBS1G5Q": "breaker_email_send_tripped",
    "CBS1H8R": "breaker_encoder_tripped",

    # ── Conductor ──────────────────────────────────────────
    "CCB1J1S": "conductor_ready",
    "CCB1K4T": "conductor_alert_received",
    "CCB1L7V": "conductor_action_log_and_pass",
    "CCB1M2W": "conductor_action_block_request",
    "CCB1N5X": "conductor_action_trip_module",
    "CCB1P8Y": "conductor_action_trip_global",
    "CCB1Q1Z": "conductor_action_shutdown",
    "CCB1R4B": "conductor_product_registered",

    # ── Tracer ─────────────────────────────────────────────
    "TCB1S7C": "tracer_begin",
    "TCB1T2D": "tracer_finish",
    "TCB1V5F": "tracer_checkpoint",
    "TCB1W8G": "tracer_loop_detected",
    "TCB1X1H": "tracer_wired",

    # ── Encoder ────────────────────────────────────────────
    "ERCB1Y4J": "encoder_success",
    "ERCB1Z3K": "encoder_failed",
    "ERCB1B6L": "encoder_breaker_opened",
    "ERCB1C9M": "encoder_data_sanitized",
    "ERCB1D2N": "encoder_codebook_miss",
    "ERCB1F5P": "encoder_sanitization_failed",
    "ERCB1G8Q": "encoder_forbidden_detected",

    # ── Encoder Messager ───────────────────────────────────
    "EMCB1H3R": "encoder_messager_success",
    "EMCB1J6S": "encoder_messager_failed",
}


# ══════════════════════════════════════════════════════════
# CAPA AUTENTICACIÓN
# ══════════════════════════════════════════════════════════

AUTH = {
    # ── Registro ───────────────────────────────────────────
    "RCB2K7X": "register_success",
    "RCB2M3Z": "register_failed_validation",
    "RCB2N9W": "register_failed_duplicate",
    "RCB2P4V": "register_failed_weak_password",
    "RCB2Q2R": "register_email_sent",

    # ── Login email/password ───────────────────────────────
    "ECB2R8T": "login_success",
    "ECB2S5J": "login_failed_credentials",
    "ECB2T1B": "login_failed_inactive",
    "ECB2V6D": "login_failed_unverified",
    "ECB2W3F": "login_blocked_gate",
    "ECB2X9G": "login_blocked_breaker",

    # ── OAuth Google ───────────────────────────────────────
    "GCB2Y4H": "oauth_google_initiated",
    "GCB2Z7K": "oauth_google_success",
    "GCB2B2L": "oauth_google_failed",
    "GCB2C5M": "oauth_google_no_email",
    "GCB2D8N": "oauth_google_state_mismatch",
    "GCB2F1P": "oauth_google_user_created",
    "GCB2G4Q": "oauth_google_user_linked",
    "GCB2H7R": "oauth_google_identity_already_linked",

    # ── OAuth GitHub ───────────────────────────────────────
    "HCB2J2S": "oauth_github_initiated",
    "HCB2K5T": "oauth_github_success",
    "HCB2L8V": "oauth_github_failed",
    "HCB2M1W": "oauth_github_no_email",
    "HCB2N4X": "oauth_github_state_mismatch",
    "HCB2P7Y": "oauth_github_user_created",
    "HCB2Q2Z": "oauth_github_user_linked",
    "HCB2R5B": "oauth_github_identity_already_linked",

    # ── OAuth Complete ─────────────────────────────────────
    "CB2S8C": "oauth_complete_redirect",
    "CB2T1D": "oauth_complete_failed",

    # ── Passkey ────────────────────────────────────────────
    "CBP2V4F": "passkey_register_begin",
    "CBP2W7G": "passkey_register_complete",
    "CBP2X2H": "passkey_register_failed",
    "CBP2Y5J": "passkey_login_begin",
    "CBP2Z8K": "passkey_login_success",
    "CBP2B1L": "passkey_login_failed",
    "CBP2C4M": "passkey_deleted",
    "CBP2D7N": "passkey_credential_updated",
    "CBP2F2P": "passkey_list_viewed",

    # ── Email ──────────────────────────────────────────────
    "CBE2G5Q": "email_verification_sent",
    "CBE2H8R": "email_verification_confirmed",
    "CBE2J1S": "email_verification_failed",
    "CBE2K4T": "email_resend_verification_requested",
    "CBE2L7V": "email_reset_sent",
    "CBE2M2W": "email_reset_confirmed",
    "CBE2N5X": "email_reset_failed",
    "CBE2P8Y": "email_new_device_alert_sent",
    "CBE2Q1Z": "email_sessions_revoked_sent",
    "CBE2R4B": "email_send_failed",

    # ── Sesiones ───────────────────────────────────────────
    "CB2S7C": "session_created",
    "CB2T2D": "session_refreshed",
    "CB2V5F": "session_revoked",
    "CB2W8G": "session_all_revoked",
    "CB2X1H": "session_expired",
    "CB2Y4J": "session_invalid_token",
    "CB2Z7L": "session_token_refresh_failed",
    "CB2B2M": "session_concurrent_detected",

    # ── Dispositivos ───────────────────────────────────────
    "CBD2C5N": "device_new_detected",
    "CBD2D8P": "device_trusted",
    "CBD2F1Q": "device_deleted",
    "CBD2G4R": "device_fingerprint_matched",
    "CBD2H7S": "device_invalid_fingerprint",

    # ── 2FA ────────────────────────────────────────────────
    "CB2J2T": "2fa_initiated",
    "CB2K5V": "2fa_success",
    "CB2L8W": "2fa_failed",
    "CB2M1X": "2fa_resent",
    "CB2N4Y": "2fa_expired",

    # ── Cuenta ─────────────────────────────────────────────
    "CBC2P7Z": "account_profile_updated",
    "CBC2Q2B": "account_password_changed",
    "CBC2R5C": "account_deleted",
    "CBC2S8D": "account_reactivated",
    "CBC2T1F": "account_deactivated",
    "CBC2V4G": "oauth_identity_linked",
    "CBC2W7H": "oauth_identity_unlinked",

    # ── Consent / SSO ──────────────────────────────────────
    "CBSS2X2J": "consent_granted",
    "CBSS2Y5K": "consent_denied",
    "CBSS2Z8L": "product_access_granted",
    "CBSS2B1M": "product_access_revoked",
}


# ══════════════════════════════════════════════════════════
# CAPA PRODUCTO
# ══════════════════════════════════════════════════════════

PRODUCT = {
    # ── Lifebound — Sesión ────────────────────────────────
    "CBS3K7X": "lifebound_session_started",
    "CBS3M3Z": "lifebound_session_restored",
    "CBS3N9W": "lifebound_session_expired",
    "CBS3P4V": "lifebound_session_cleared",

    # ── Lifebound — Plantillas ────────────────────────────
    "CB3Q2R": "lifebound_templates_loaded",
    "CB3R8T": "lifebound_template_selected",
    "CB3S5J": "lifebound_template_failed",

    # ── Lifebound — Imágenes ──────────────────────────────
    "CB3T1B": "lifebound_image_uploaded",
    "CB3V6D": "lifebound_image_upload_failed",
    "CB3W3F": "lifebound_image_processed",
    "CB3X9G": "lifebound_image_processing_failed",
    "CB3Y4H": "lifebound_image_slot_assigned",
    "CB3Z7K": "lifebound_slot_filled",
    "CB3B2L": "lifebound_slot_empty",

    # ── Lifebound — Generación ────────────────────────────
    "CBG3C5M": "lifebound_generation_started",
    "CBG3D8N": "lifebound_generation_success",
    "CBG3F1P": "lifebound_generation_failed",
    "CBG3G4Q": "lifebound_generation_partial",
    "CBG3H7R": "lifebound_ai_call_success",
    "CBG3J2S": "lifebound_ai_call_failed",
    "CBG3K5T": "lifebound_ai_breaker_open",

    # ── Lifebound — PDF ───────────────────────────────────
    "CB3L8V": "lifebound_pdf_created",
    "CB3M1W": "lifebound_pdf_failed",
    "CB3N4X": "lifebound_pdf_downloaded",

    # ── Lifebound — Patrones ──────────────────────────────
    "CBLP3P7Y": "lifebound_pattern_applied",
    "CBLP3Q2Z": "lifebound_pattern_failed",

    # ── Lifebound — Formularios ───────────────────────────
    "CBLF3R5B": "lifebound_questionnaire_saved",
    "CBLF3S8C": "lifebound_applicant_data_saved",
    "CBLF3T1D": "lifebound_grouping_applied",

    # ── Lifebound — Acceso ────────────────────────────────
    "CBLA3V4F": "lifebound_auth_guard_blocked",
    "CBLA3W7G": "lifebound_consent_required",

    # ── Acceso genérico al producto ───────────────────────
    "AP3X2H": "product_accessed",
    "AP3Y5J": "product_access_denied",
    "AP3Z8K": "product_auth_required",
}


# ══════════════════════════════════════════════════════════
# CAPA TRÁFICO / SEGURIDAD
# ══════════════════════════════════════════════════════════

TRAFFIC = {
    # ── Requests ──────────────────────────────────────────
    "CBR4K7X": "request_normal",
    "CBR4M3Z": "request_blocked",
    "CBR4N9W": "request_rate_limited",
    "CBR4P4V": "request_invalid_token",
    "CBR4Q2R": "request_unauthorized",
    "CBR4R8T": "request_forbidden",

    # ── Patrones sospechosos ──────────────────────────────
    "PS4S5J": "traffic_brute_force_detected",
    "PS4T1B": "traffic_credential_stuffing",
    "PS4V6D": "traffic_suspicious_ip",
    "PS4W3F": "traffic_multiple_failures",
    "PS4X9G": "traffic_unusual_location",
    "PS4Y4H": "traffic_bot_detected",
    "PS4Z7K": "traffic_token_reuse_detected",
    "PS4B2L": "traffic_expired_token_used",
    "PS4C5M": "traffic_invalid_fingerprint",
    "PS4D8N": "traffic_cors_violation",

    # ── Anomalías ─────────────────────────────────────────
    "CAT4F1P": "anomaly_loop_detected",
    "CAT4G4Q": "anomaly_cascade_failure",
    "CAT4H7R": "anomaly_high_latency",
    "CAT4J2S": "anomaly_memory_pressure",

    # ── Ataques ───────────────────────────────────────────
    "CBA4K5T": "attack_csrf_attempt",
    "CBA4L8V": "attack_injection_attempt",
    "CBA4M1W": "attack_replay_token",
    "CBA4N4X": "attack_state_mismatch",
}


# ══════════════════════════════════════════════════════════
# CAPA CONSTRUCCIÓN / DESARROLLO
# ══════════════════════════════════════════════════════════

BUILD = {
    # ── Deploy ────────────────────────────────────────────
    "CBD5K7X": "deploy_started",
    "CBD5M3Z": "deploy_success",
    "CBD5N9W": "deploy_failed",
    "CBD5P4V": "deploy_rolled_back",

    # ── Blueprints ────────────────────────────────────────
    "CBB5Q2R": "blueprint_auth_registered",
    "CBB5R8T": "blueprint_lifebound_registered",
    "CBB5S5J": "blueprint_passkey_registered",
    "CBB5T1B": "blueprint_oauth_registered",
    "CBB5V6D": "blueprint_account_registered",
    "CBB5W3F": "blueprint_registration_failed",

    # ── Wiring ────────────────────────────────────────────
    "CBW5X9G": "wiring_oauth_configured",
    "CBW5Y4H": "wiring_conductor_ready",
    "CBW5Z7K": "wiring_tracer_ready",
    "CBW5B2L": "wiring_auth_complete",
    "CBW5C5M": "wiring_failed",

    # ── Migraciones ───────────────────────────────────────
    "CBM5D8N": "migration_applied",
    "CBM5F1P": "migration_skipped",
    "CBM5G4Q": "migration_failed",
    "CBM5H7R": "migration_rolled_back",

    # ── Entorno ───────────────────────────────────────────
    "CBE5J2S": "env_production",
    "CBE5K5T": "env_development",
    "CBE5L8V": "env_missing_secret_key",
    "CBE5M1W": "env_missing_database_url",
    "CBE5N4X": "env_sentry_active",
    "CBE5P7Y": "env_sentry_inactive",
    "CBE5Q2Z": "env_sentry_dsn_missing",
    "CBE5R5B": "env_render_git_commit",
}


# ══════════════════════════════════════════════════════════
# CAPA CLIENTE
# Eventos emitidos desde el frontend (JS) hacia Sentry o
# hacia el endpoint interno de telemetría.
# Longitud variable según subsistema — ver tabla de prefijos.
# ══════════════════════════════════════════════════════════

CLIENT_AUTH = {
    # ── Login / Registro ──────────────────────────────────
    "KLL1K7XM3ZN": "client_login_page_viewed",
    "KLL1P4VQ2RB": "client_login_attempted",
    "KLL1R8TS5JC": "client_login_success",
    "KLL1T1BV6DD": "client_login_failed",
    "KLL1W3FX9GF": "client_register_page_viewed",
    "KLL1Y4HZ7KG": "client_register_attempted",
    "KLL1B2LM3ZH": "client_register_success",
    "KLL1D8NP4VJ": "client_register_failed",

    # ── OAuth ─────────────────────────────────────────────
    "CLO1F1PQ2RK": "client_oauth_google_clicked",
    "CLO1G4RR8TL": "client_oauth_github_clicked",
    "CLO1H7SS5JM": "client_oauth_complete_received",

    # ── Sesión ────────────────────────────────────────────
    "SN1J2TT1BN": "client_logout_clicked",
    "SN1K5VV6DP": "client_token_stored_localStorage",
    "SN1L8WW3FQ": "client_token_cleared",
    "SN1M1XX9GR": "client_session_list_viewed",
    "SN1N4YY4HS": "client_session_revoked",

    # ── Passkey ───────────────────────────────────────────
    "MP1P7ZZ7KT": "client_passkey_register_clicked",
    "MP1Q2BB2LV": "client_passkey_login_clicked",
    "MP1R5CC5MW": "client_passkey_deleted",

    # ── Cuenta ────────────────────────────────────────────
    "CLC1S8DD8NX": "client_account_page_viewed",
    "CLC1T1FF1PY": "client_identity_unlinked",
    "CLC1V4GG4QZ": "client_password_reset_requested",
    "CLC1W7HH7RB": "client_password_reset_completed",
    "CLC1X2JJ2SC": "client_email_verification_clicked",
    "CLC1Y5KK5TD": "client_device_list_viewed",

    # ── 2FA ───────────────────────────────────────────────
    "CL1Z8LL8VF": "client_2fa_submitted",
}

CLIENT_PRODUCT = {
    # ── Lifebound ─────────────────────────────────────────
    "KLF2K7XM3ZN": "client_lifebound_opened",
    "KLF2P4VQ2RB": "client_lifebound_questionnaire_started",
    "KLF2R8TS5JC": "client_lifebound_questionnaire_completed",
    "KLF2T1BV6DD": "client_lifebound_applicant_form_filled",
    "KLF2W3FX9GF": "client_lifebound_image_uploaded",
    "KLF2Y4HZ7KG": "client_lifebound_generate_clicked",
    "KLF2B2LM3ZH": "client_lifebound_pdf_downloaded",
    "KLF2D8NP4VJ": "client_lifebound_preview_viewed",
    "KLF2F1PQ2RK": "client_lifebound_template_changed",
    "KLF2G4RR8TL": "client_lifebound_slot_clicked",
    "KLF2H7SS5JM": "client_lifebound_nav_step_changed",
    "KLF2J2TT1BN": "client_lifebound_session_restored",
    "KLF2K5VV6DP": "client_lifebound_error_displayed",
    "KLF2L8WW3FQ": "client_lifebound_debug_panel_opened",
    "KLF2M1XX9GR": "client_lifebound_grouping_applied",
}

CLIENT_TRAFFIC = {
    # ── Navegación ────────────────────────────────────────
    "CLT3K7XM3ZN": "client_page_not_found",
    "CLT3P4VQ2RB": "client_unauthorized_redirect",
    "CLT3R8TS5JC": "client_consent_page_viewed",
    "CLT3T1BV6DD": "client_consent_granted",
    "CLT3W3FX9GF": "client_consent_denied",
    "CLT3Y4HZ7KG": "client_consent_redirect",
    "CLT3B2LM3ZH": "client_token_expired_detected",
    "CLT3D8NP4VJ": "client_token_refreshed",
    "CLT3F1PQ2RK": "client_auth_guard_redirect",
    "CLT3G4RR8TL": "client_api_error_received",
    "CLT3H7SS5JM": "client_network_error",
    "CLT3J2TT1BN": "client_offline_detected",
    "CLT3K5VV6DP": "client_error_boundary_triggered",
}


# ══════════════════════════════════════════════════════════
# ÍNDICE MAESTRO Y REVERSO
# ══════════════════════════════════════════════════════════

MASTER: dict[str, str] = {
    **SYSTEM,
    **AUTH,
    **PRODUCT,
    **TRAFFIC,
    **BUILD,
    **CLIENT_AUTH,
    **CLIENT_PRODUCT,
    **CLIENT_TRAFFIC,
}

# Índice inverso — significado → código
# Uso: REVERSE["oauth_google_success"] → "GCB2Z7K"
REVERSE: dict[str, str] = {v: k for k, v in MASTER.items()}


# ══════════════════════════════════════════════════════════
# SUSTITUCIONES DE DATOS SENSIBLES
#
# Usado por el Encoder antes de enviar eventos a Sentry.
# Cada campo listado aquí es transformado antes de salir
# del sistema — nunca viajan en texto plano.
#
# SUBSTITUTIONS: campo → función de transformación
# FORBIDDEN_FIELDS: campos que bloquean el envío completo
#   si aparecen en el payload. El Encoder emite
#   "encoder_forbidden_detected" y descarta el evento.
# ══════════════════════════════════════════════════════════

def _hash(value: str, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


SUBSTITUTIONS: dict[str, callable] = {
    "email":       lambda v: _hash(v, 8),
    "ip":          lambda v: re.sub(r'\.\d+$', '.x', v) if v else "x.x.x.x",
    "user_id":     lambda v: _hash(v, 6),
    "session_id":  lambda v: _hash(v, 6),
    "device_id":   lambda v: _hash(v, 6),
    "name":        lambda v: "USR",
    "provider_id": lambda v: _hash(v, 8),
    "token":       lambda v: "[REDACTED]",
    "password":    lambda v: "[REDACTED]",
}

FORBIDDEN_FIELDS: set[str] = {
    "password", "password_hash", "token", "access_token",
    "refresh_token", "secret_key", "api_key", "private_key",
    "credit_card", "ssn", "webhook_url",
}


# ══════════════════════════════════════════════════════════
# VALIDADOR DE INTEGRIDAD
#
# Corre al importar este módulo — antes del arranque.
# Detecta códigos duplicados y significados duplicados.
# No valida formato de prefijo porque los prefijos son
# heterogéneos por diseño (ver tabla en el header).
# Si falla → RuntimeError detiene el arranque inmediatamente.
# ══════════════════════════════════════════════════════════

def _validate() -> None:
    seen_codes: set[str] = set()
    for code in MASTER:
        if code in seen_codes:
            raise RuntimeError(f"[Codebook] Código duplicado: {code}")
        seen_codes.add(code)

    seen_meanings: set[str] = set()
    for meaning in MASTER.values():
        if meaning in seen_meanings:
            raise RuntimeError(f"[Codebook] Significado duplicado: {meaning}")
        seen_meanings.add(meaning)


_validate()