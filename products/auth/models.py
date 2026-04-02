"""
products/auth/models.py
=======================
Modelos del sistema de autenticación AUREON.

Optimizado para:
- Producción (PostgreSQL)
- Performance (índices + lazy loading)
- Seguridad (sesiones robustas)
- Escalabilidad
"""

import uuid
from datetime import datetime, timezone

from shared.db import db
from shared.models_base import TimestampMixin


def _uuid():
    return str(uuid.uuid4())


# ══════════════════════════════════════════════════════════
# USER — cuenta central
# ══════════════════════════════════════════════════════════

class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id          = db.Column(db.String(36), primary_key=True, default=_uuid)
    email       = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name        = db.Column(db.String(255), nullable=False)
    avatar_url  = db.Column(db.String(500), nullable=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active   = db.Column(db.Boolean, default=True, nullable=False)
    role        = db.Column(db.String(20), default="user", nullable=False)

    identities = db.relationship(
        "UserIdentity", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )
    devices = db.relationship(
        "UserDevice", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )
    sessions = db.relationship(
        "UserSession", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )
    passkeys = db.relationship(
        "UserPasskey", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )
    products = db.relationship(
        "UserProduct", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )
    activities = db.relationship(
        "UserActivity", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "is_verified": self.is_verified,
            "role": self.role,
            "created_at": self.created_at.isoformat(),
        }

    def is_admin(self):
        return self.role in ("admin", "superadmin")


# ══════════════════════════════════════════════════════════
# USER IDENTITY
# ══════════════════════════════════════════════════════════

class UserIdentity(TimestampMixin, db.Model):
    __tablename__ = "user_identities"

    id            = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id       = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)

    provider      = db.Column(db.String(50), nullable=False)
    provider_id   = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("provider", "provider_id", name="uq_identity_provider"),
    )

    user = db.relationship("User", back_populates="identities")


# ══════════════════════════════════════════════════════════
# USER DEVICE
# ══════════════════════════════════════════════════════════

class UserDevice(TimestampMixin, db.Model):
    __tablename__ = "user_devices"

    id           = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id      = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)

    fingerprint  = db.Column(db.String(255), nullable=True)
    ip           = db.Column(db.String(45), nullable=False)
    country      = db.Column(db.String(100), nullable=True)
    city         = db.Column(db.String(100), nullable=True)
    device_name  = db.Column(db.String(255), nullable=True)
    browser      = db.Column(db.String(100), nullable=True)
    os           = db.Column(db.String(100), nullable=True)
    is_trusted   = db.Column(db.Boolean, default=False, nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)

    user     = db.relationship("User", back_populates="devices")
    sessions = db.relationship(
        "UserSession", back_populates="device",
        cascade="all, delete-orphan", lazy="selectin"
    )
    passkeys = db.relationship(
        "UserPasskey", back_populates="device",
        cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "device_name": self.device_name,
            "browser": self.browser,
            "os": self.os,
            "ip": self.ip,
            "country": self.country,
            "city": self.city,
            "is_trusted": self.is_trusted,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════
# USER SESSION
# ══════════════════════════════════════════════════════════

class UserSession(TimestampMixin, db.Model):
    __tablename__ = "user_sessions"

    id             = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id        = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    device_id      = db.Column(db.String(36), db.ForeignKey("user_devices.id"), nullable=True)

    token_hash     = db.Column(db.String(255), nullable=False, unique=True, index=True)
    refresh_hash   = db.Column(db.String(255), nullable=True, unique=True, index=True)
    ip             = db.Column(db.String(45), nullable=False)

    last_active_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    revoked_at     = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index("ix_session_token_active", "token_hash", "revoked_at"),
    )

    user   = db.relationship("User", back_populates="sessions")
    device = db.relationship("UserDevice", back_populates="sessions")

    @property
    def is_active(self):
        return self.revoked_at is None

    def revoke(self):
        self.revoked_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "id": self.id,
            "device": self.device.to_dict() if self.device else None,
            "ip": self.ip,
            "last_active_at": self.last_active_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "is_active": self.is_active,
        }


# ══════════════════════════════════════════════════════════
# USER PASSKEY
# ══════════════════════════════════════════════════════════

class UserPasskey(TimestampMixin, db.Model):
    __tablename__ = "user_passkeys"

    id            = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id       = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    device_id     = db.Column(db.String(36), db.ForeignKey("user_devices.id"), nullable=True)

    credential_id = db.Column(db.Text, nullable=False, unique=True)
    public_key    = db.Column(db.Text, nullable=False)
    sign_count    = db.Column(db.Integer, default=0, nullable=False)
    device_type   = db.Column(db.String(50), nullable=True)
    last_used_at  = db.Column(db.DateTime, nullable=True)

    user   = db.relationship("User", back_populates="passkeys")
    device = db.relationship("UserDevice", back_populates="passkeys")

    def to_dict(self):
        return {
            "id": self.id,
            "device": self.device.to_dict() if self.device else None,
            "device_type": self.device_type,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════
# USER PRODUCT
# ══════════════════════════════════════════════════════════

class UserProduct(TimestampMixin, db.Model):
    __tablename__ = "user_products"

    id         = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id    = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.String(100), nullable=False)
    granted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", name="uq_user_product"),
    )

    user = db.relationship("User", back_populates="products")

    def to_dict(self):
        return {
            "product_id": self.product_id,
            "granted_at": self.granted_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════
# USER ACTIVITY
# ══════════════════════════════════════════════════════════

ACTIVITY_TYPES = {
    "login_success":   "Login exitoso",
    "login_failed":    "Intento fallido",
    "logout":          "Cierre de sesión",
    "register":        "Cuenta creada",
    "password_change": "Contraseña cambiada",
    "profile_update":  "Perfil actualizado",
    "session_revoked": "Sesión revocada",
    "product_access":  "Acceso a producto",
    "oauth_linked":    "Proveedor vinculado",
    "oauth_unlinked":  "Proveedor desvinculado",
}


class UserActivity(TimestampMixin, db.Model):
    __tablename__ = "user_activity"

    id          = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id     = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    event_type  = db.Column(db.String(50), nullable=False)

    ip          = db.Column(db.String(45), nullable=True)
    device_name = db.Column(db.String(255), nullable=True)
    product_id  = db.Column(db.String(100), nullable=True)
    extra_data  = db.Column("metadata", db.Text, nullable=True)

    __table_args__ = (
        db.Index("ix_activity_user_time", "user_id", "created_at"),
    )

    user = db.relationship("User", back_populates="activities")

    def to_dict(self):
        return {
            "id": self.id,
            "event_type": self.event_type,
            "label": ACTIVITY_TYPES.get(self.event_type, self.event_type),
            "ip": self.ip,
            "device_name": self.device_name,
            "product_id": self.product_id,
            "created_at": self.created_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════
# LOG ACTIVITY
# ══════════════════════════════════════════════════════════

def log_activity(
    user_id: str,
    event_type: str,
    ip: str = None,
    device_name: str = None,
    product_id: str = None,
    metadata: str = None,
    auto_commit: bool = True,
):
    activity = UserActivity(
        user_id=user_id,
        event_type=event_type,
        ip=ip,
        device_name=device_name,
        product_id=product_id,
        extra_data=metadata,
    )

    db.session.add(activity)

    if auto_commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise