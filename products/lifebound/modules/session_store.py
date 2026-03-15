"""
modules/session_store.py
=========================
Almacena estado de sesiones activas en memoria.
Thread-safe. Cada sesión tiene session_id único.

Uso
---
Todos los módulos deben importar la instancia compartida, no crear
instancias propias:

    from modules.session_store import store   # ← correcto
    from modules.session_store import SessionStore; SessionStore()  # ← MAL

Usar instancias separadas hace que cada módulo tenga su propio
diccionario en memoria y las sesiones nunca se comparten.
"""
import threading
import time
import logging

logger  = logging.getLogger(__name__)
TTL_SEC = 3600  # 1 hora


class SessionStore:
    def __init__(self):
        self._sessions = {}
        self._lock     = threading.Lock()

    def create(self, sid: str):
        with self._lock:
            self._sessions[sid] = {
                "created_at": time.time(),
                "photos":     {},
                "status":     "waiting",
            }

    def exists(self, sid: str) -> bool:
        with self._lock:
            s = self._sessions.get(sid)
            if not s:
                return False
            if time.time() - s["created_at"] > TTL_SEC:
                del self._sessions[sid]
                return False
            return True

    def set_photos(self, sid: str, photo_map: dict):
        with self._lock:
            if sid in self._sessions:
                self._sessions[sid]["photos"] = photo_map
                self._sessions[sid]["status"] = "photos_ready"

    def get_photos(self, sid: str) -> dict:
        with self._lock:
            return self._sessions.get(sid, {}).get("photos", {})

    def get_status(self, sid: str) -> dict:
        with self._lock:
            s = self._sessions.get(sid, {})
            return {
                "status": s.get("status", "not_found"),
                "photos": len(s.get("photos", {})),
            }

    def delete(self, sid: str):
        with self._lock:
            self._sessions.pop(sid, None)


# ── Instancia singleton compartida por todo el proceso ────────────────────
# Importar esto en todos los módulos:
#   from modules.session_store import store
store = SessionStore()