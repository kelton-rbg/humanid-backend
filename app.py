from flask import Flask, request, jsonify, redirect
import requests
import jwt
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'

# 👇 banco simples (temporário)
users = {}

# 🔐 REGISTRO
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data["email"]
    password = data["password"]

    if email in users:
        return jsonify({"error": "User exists"}), 400

    users[email] = {
        "password": password,
        "credits": 150
    }

    return jsonify({"message": "User created"})

# 🔑 LOGIN
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data["email"]
    password = data["password"]

    user = users.get(email)

    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    token = jwt.encode({
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    return jsonify({"token": token})

# 🔐 VERIFICAR TOKEN
def verify_token():
    token = request.headers.get("Authorization")

    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        return data["email"]
    except:
        return None

# 💳 CRÉDITOS
@app.route("/credits", methods=["GET"])
def credits():
    email = verify_token()

    if not email:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify({"credits": users[email]["credits"]})

# 🧠 ANALYZE REAL
@app.route("/analyze", methods=["POST"])
def analyze():
    email = verify_token()

    if not email:
        return jsonify({"error": "Unauthorized"}), 401

    if users[email]["credits"] <= 0:
        return jsonify({"error": "Sem créditos"}), 403

    data = request.json
    text = data.get("text", "")

    users[email]["credits"] -= 1

    try:
        response = requests.post(
            "https://api.sightengine.com/1.0/text/check.json",
            data={
                'text': text,
                'lang': 'en',
                'mode': 'standard',
                'api_user': 'TEU_API_USER',
                'api_secret': 'TEU_API_SECRET'
            },
            timeout=3
        )

        result = response.json()

        return jsonify({
            "result": result,
            "credits_left": users[email]["credits"]
        })

    except:
        return jsonify({
            "risk": "medium",
            "message": "Fallback mode",
            "credits_left": users[email]["credits"]
        })

# 🌍 HOME
@app.route("/")
def home():
    return "HumanID backend running 🚀"

# 🔁 REDIRECT WWW
from flask import redirect, request

@app.before_request
def force_domain_redirect():
    host = request.host
    url = request.url

    # Remove www
    if host.startswith("www."):
        return redirect(url.replace("www.", ""), code=301)

    # Force HTTPS (Render já ajuda, mas garantimos)
   from flask import redirect, request

@app.before_request
def force_domain_redirect():
    host = request.host
    url = request.url

    # remover www
    if host.startswith("www."):
        return redirect(url.replace("www.", ""), code=301)

    # garantir https (forma segura)
    if request.scheme == "http":
        return redirect(url.replace("http://", "https://"), code=301)
if __name__ == "__main__":
    app.run(debug=True) 
