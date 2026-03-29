"""
products/auth/utils.py
======================
Utilidades del sistema de autenticación AUREON.

    - JWT     : generar y verificar access token + refresh token
    - bcrypt  : hashear y verificar contraseñas
    - Device  : parsear user-agent, extraer IP y fingerprint
    - Tokens  : generar tokens seguros para verificación y reset
"""

import os
import hashlib
import secrets

import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from user_agents import parse as ua_parse


# ── Constantes ────────────────────────────────────────────
SECRET_KEY     = os.environ.get("SECRET_KEY", "dev_secret_cambia_esto")
JWT_ALGORITHM  = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", 15))
REFRESH_DAYS   = int(os.environ.get("JWT_REFRESH_DAYS", 30))


# ══════════════════════════════════════════════════════════
# JWT
# ══════════════════════════════════════════════════════════

def create_access_token(user_id: str, session_id: str) -> str:
    """JWT de corta duración (15 min por defecto)."""
    payload = {
        "sub":        user_id,
        "session_id": session_id,
        "type":       "access",
        "iat":        datetime.now(timezone.utc),
        "exp":        datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, session_id: str) -> str:
    """Refresh token de larga duración (30 días por defecto)."""
    payload = {
        "sub":        user_id,
        "session_id": session_id,
        "type":       "refresh",
        "iat":        datetime.now(timezone.utc),
        "exp":        datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un JWT.
    Lanza jwt.ExpiredSignatureError o jwt.InvalidTokenError si falla.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


def hash_token(token: str) -> str:
    """SHA-256 del token para guardarlo en BD sin exponer el valor real."""
    return hashlib.sha256(token.encode()).hexdigest()


# ══════════════════════════════════════════════════════════
# CONTRASEÑAS
# ══════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Genera un hash bcrypt seguro de la contraseña."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def validate_password_strength(password: str) -> list[str]:
    """
    Valida que la contraseña cumpla requisitos mínimos.
    Retorna una lista de errores — vacía si es válida.
    """
    errors = []
    if len(password) < 8:
        errors.append("Mínimo 8 caracteres")
    if not any(c.isupper() for c in password):
        errors.append("Al menos una mayúscula")
    if not any(c.isdigit() for c in password):
        errors.append("Al menos un número")
    return errors


# ══════════════════════════════════════════════════════════
# TOKENS DE VERIFICACIÓN
# ══════════════════════════════════════════════════════════

def generate_verification_token() -> str:
    """Token seguro de 32 bytes para verificación de email."""
    return secrets.token_urlsafe(32)


def generate_reset_token() -> str:
    """Token seguro de 32 bytes para reset de contraseña."""
    return secrets.token_urlsafe(32)


# ══════════════════════════════════════════════════════════
# DEVICE PARSER
# ══════════════════════════════════════════════════════════

def parse_device(request) -> dict:
    """
    Extrae información del dispositivo desde el request de Flask.

    Lee:
        - User-Agent  → browser, OS, device_name
        - X-Forwarded-For o remote_addr → IP real
        - X-Fingerprint → fingerprint del browser (enviado por auth.js)

    Retorna un dict listo para crear un UserDevice.
    """
    user_agent_str = request.headers.get("User-Agent", "")
    ua             = ua_parse(user_agent_str)

    browser     = ua.browser.family or "Unknown"
    os_name     = ua.os.family     or "Unknown"
    device_name = f"{browser} · {os_name}"

    # IP real detrás de proxy/Render
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "0.0.0.0"
    )

    # Fingerprint enviado por el frontend (FingerprintJS)
    fingerprint_raw = request.headers.get("X-Fingerprint", "")
    fingerprint = (
        hashlib.sha256(fingerprint_raw.encode()).hexdigest()
        if fingerprint_raw else None
    )

    return {
        "ip":          ip,
        "device_name": device_name,
        "browser":     browser,
        "os":          os_name,
        "fingerprint": fingerprint,
    }


def is_new_device(user, device_info: dict) -> bool:
    """
    Devuelve True si el fingerprint o IP no coincide con ningún
    dispositivo conocido del usuario — útil para enviar alerta de seguridad.
    """
    if not device_info.get("fingerprint"):
        return False
    known_fingerprints = {d.fingerprint for d in user.devices if d.fingerprint}
    return device_info["fingerprint"] not in known_fingerprints