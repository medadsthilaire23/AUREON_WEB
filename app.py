# app.py
"""
Aplicación principal de AUREON.

Este archivo:
- Inicializa el servidor Flask
- Define rutas principales
- Sirve la landing SaaS
- Sirve el hub de aplicaciones
- Prepara estructura para futuras APIs dinámicas

No contiene aún base de datos ni autenticación.
Es base limpia para evolución posterior.
"""

from flask import Flask, render_template, jsonify
from datetime import datetime

app = Flask(__name__)

# Simulación de anuncios dinámicos
announcements = [
    {
        "title": "Nueva API Amazon disponible",
        "description": "Extracción avanzada de datos optimizada.",
        "link": "/hud"
    },
    {
        "title": "Automatización AliExpress mejorada",
        "description": "Scripts más rápidos y eficientes.",
        "link": "/hud"
    }
]

@app.route("/")
def index():
    """Landing principal."""
    return render_template("index.html")

@app.route("/hud")
def hub():
    """Página de aplicaciones."""
    return render_template("hud.html")

@app.route("/api/announcements")
def get_announcements():
    """
    Endpoint que devuelve anuncios dinámicos.
    Se puede conectar más adelante a base de datos.
    """
    return jsonify(announcements)

if __name__ == "__main__":
    app.run(debug=True)
