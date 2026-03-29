"""
products/auth/passkey.py
========================
WebAuthn — registro y autenticación de passkeys (Face ID, huella, PIN).

Flujo de registro (2 pasos):
    1. GET  /auth/passkey/register/begin    → opciones para el navegador
    2. POST /auth/passkey/register/complete → verificar y guardar credencial

Flujo de login (2 pasos):
    1. POST /auth/passkey/login/begin       → challenge para el navegador
    2. POST /auth/passkey/login/complete    → verificar firma y crear sesión

Dependencia:
    pip install webauthn==2.1.0
"""

import os
import json
import logging
from datetime import datetime, timezone

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    PublicKeyCredentialDescriptor,
)
from flask import Blueprint, jsonify, request, g, session

from shared.db import db
from shared.auth_middleware import require_auth
from products.auth.models import User, UserDevice, UserPasskey, UserSession
from products.auth.utils import (
    create_access_token, create_refresh_token,
    hash_token, parse_device,
)

log = logging.getLogger("aureon.passkey")

passkey_bp = Blueprint("passkey", __name__, url_prefix="/auth/passkey")

# ── Configuración WebAuthn ─────────────────────────────────
RP_ID  = os.environ.get("WEBAUTHN_RP_ID",   "localhost")
RP_NAME= os.environ.get("WEBAUTHN_RP_NAME", "Aureon")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN",  "http://localhost:10000")


# ══════════════════════════════════════════════════════════
# REGISTRO — paso 1: generar opciones
# ══════════════════════════════════════════════════════════

@passkey_bp.route("/register/begin", methods=["GET"])
@require_auth
def register_begin():
    user = User.query.get(g.user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    existing_credentials = [
        PublicKeyCredentialDescriptor(id=webauthn.helpers.base64url_to_bytes(pk.credential_id))
        for pk in user.passkeys
    ]

    options = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=user.id.encode(),
        user_name=user.email,
        user_display_name=user.name,
        exclude_credentials=existing_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )

    session["passkey_register_challenge"] = webauthn.helpers.bytes_to_base64url(
        options.challenge
    )

    return jsonify(json.loads(webauthn.options_to_json(options))), 200


# ══════════════════════════════════════════════════════════
# REGISTRO — paso 2: verificar y guardar
# ══════════════════════════════════════════════════════════

@passkey_bp.route("/register/complete", methods=["POST"])
@require_auth
def register_complete():
    user = User.query.get(g.user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    challenge_b64 = session.pop("passkey_register_challenge", None)
    if not challenge_b64:
        return jsonify({"error": "No hay challenge activo"}), 400

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Body JSON requerido"}), 400

    try:
        verification = webauthn.verify_registration_response(
            credential=body,
            expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_b64),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            require_user_verification=True,
        )
    except Exception as e:
        log.warning("Passkey register failed: user=%s error=%s", g.user_id, e)
        return jsonify({"error": f"Verificación fallida: {str(e)}"}), 400

    # Asociar dispositivo si existe
    device_info = parse_device(request)
    device = None
    if device_info.get("fingerprint"):
        device = UserDevice.query.filter_by(
            user_id=user.id,
            fingerprint=device_info["fingerprint"],
        ).first()

    passkey = UserPasskey(
        user_id=user.id,
        device_id=device.id if device else None,
        credential_id=webauthn.helpers.bytes_to_base64url(verification.credential_id),
        public_key=webauthn.helpers.bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
        device_type=str(getattr(verification, "credential_device_type", "platform")),
    )
    db.session.add(passkey)
    db.session.commit()

    log.info("Passkey registrada: user=%s", user.email)
    return jsonify({"message": "Passkey registrada", "passkey_id": passkey.id}), 201


# ══════════════════════════════════════════════════════════
# LOGIN — paso 1: generar challenge
# ══════════════════════════════════════════════════════════

@passkey_bp.route("/login/begin", methods=["POST"])
def login_begin():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    allow_credentials = []
    if email:
        user = User.query.filter_by(email=email, is_active=True).first()
        if user:
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    id=webauthn.helpers.base64url_to_bytes(pk.credential_id)
                )
                for pk in user.passkeys
            ]

    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    session["passkey_login_challenge"] = webauthn.helpers.bytes_to_base64url(options.challenge)
    if email:
        session["passkey_login_email"] = email

    return jsonify(json.loads(webauthn.options_to_json(options))), 200


# ══════════════════════════════════════════════════════════
# LOGIN — paso 2: verificar firma y crear sesión
# ══════════════════════════════════════════════════════════

@passkey_bp.route("/login/complete", methods=["POST"])
def login_complete():
    challenge_b64 = session.pop("passkey_login_challenge", None)
    session.pop("passkey_login_email", None)

    if not challenge_b64:
        return jsonify({"error": "No hay challenge activo"}), 400

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Body JSON requerido"}), 400

    credential_id = body.get("id", "")
    passkey = UserPasskey.query.filter_by(credential_id=credential_id).first()
    if not passkey:
        return jsonify({"error": "Passkey no reconocida"}), 401

    user = User.query.get(passkey.user_id)
    if not user or not user.is_active:
        return jsonify({"error": "Usuario inactivo"}), 401

    try:
        verification = webauthn.verify_authentication_response(
            credential=body,
            expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_b64),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=webauthn.helpers.base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as e:
        log.warning("Passkey login failed: user=%s error=%s", passkey.user_id, e)
        return jsonify({"error": f"Verificación fallida: {str(e)}"}), 401

    # Actualizar sign_count anti-replay
    passkey.sign_count   = verification.new_sign_count
    passkey.last_used_at = datetime.now(timezone.utc)

    # Crear sesión
    device_info = parse_device(request)
    device = None
    if device_info.get("fingerprint"):
        device = UserDevice.query.filter_by(
            user_id=user.id,
            fingerprint=device_info["fingerprint"],
        ).first()

    if not device:
        device = UserDevice(user_id=user.id, **device_info)
        db.session.add(device)
        db.session.flush()

    device.last_seen_at = datetime.now(timezone.utc)

    user_session = UserSession(
        user_id=user.id,
        device_id=device.id,
        ip=device_info["ip"],
    )
    db.session.add(user_session)
    db.session.flush()

    access_token  = create_access_token(user.id, user_session.id)
    refresh_token = create_refresh_token(user.id, user_session.id)

    user_session.token_hash   = hash_token(access_token)
    user_session.refresh_hash = hash_token(refresh_token)

    db.session.commit()

    log.info("Passkey login exitoso: user=%s", user.email)
    return jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "user":          user.to_dict(),
    }), 200


# ══════════════════════════════════════════════════════════
# ELIMINAR PASSKEY
# ══════════════════════════════════════════════════════════

@passkey_bp.route("/<passkey_id>", methods=["DELETE"])
@require_auth
def delete_passkey(passkey_id):
    passkey = UserPasskey.query.filter_by(
        id=passkey_id, user_id=g.user_id
    ).first()

    if not passkey:
        return jsonify({"error": "Passkey no encontrada"}), 404

    from products.auth.models import UserIdentity
    identity           = UserIdentity.query.filter_by(user_id=g.user_id, provider="aureon").first()
    remaining_passkeys = UserPasskey.query.filter_by(user_id=g.user_id).count()

    if remaining_passkeys <= 1 and not (identity and identity.password_hash):
        return jsonify({
            "error": "No puedes eliminar tu única passkey sin tener contraseña configurada"
        }), 400

    db.session.delete(passkey)
    db.session.commit()

    log.info("Passkey eliminada: user=%s passkey=%s", g.user_id, passkey_id)
    return jsonify({"message": "Passkey eliminada"}), 200