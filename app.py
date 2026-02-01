from flask import Flask, render_template, request
import json
import os
from datetime import datetime

app = Flask(__name__)

# Archivo JSON para persistencia
JSON_FILE = "asin_data.json"

# Función para cargar ASINs desde el JSON
def cargar_asins():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

# Función para guardar ASINs en el JSON
def guardar_asins(asins):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(asins, f, indent=4)

# Cargar ASINs al iniciar la app
asin_list = cargar_asins()

@app.route("/")
def home():
    return render_template("index.html", asin_list=asin_list)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        asin = request.form.get("asin")
        if asin and not any(a["asin"] == asin for a in asin_list):
            registro = {
                "asin": asin,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            asin_list.append(registro)
            guardar_asins(asin_list)  # Guardar inmediatamente
    return render_template("register.html", asin_list=asin_list)

if __name__ == "__main__":
    app.run(debug=True)
