"""
shared/models_base.py
=====================
Base declarativa de SQLAlchemy compartida.
Todos los modelos de todos los productos heredan de aquí.
"""

from datetime import datetime, timezone
from shared.db import db


class TimestampMixin:
    """
    Agrega created_at y updated_at automáticamente a cualquier modelo.

    Uso:
        class User(TimestampMixin, db.Model):
            ...
    """
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )