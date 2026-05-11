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

import os
import stripe
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Stripe Secret Key
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Stripe Price IDs
PRICE_IDS = {
    "starter": "price_1TVoTBRyx4mChIbOb3R037Mi",   # €4.99
    "basic": "price_1TVoUpRyx4mChIbOuJvWg0YO",     # €9.99
    "pro": "price_1TVoXJRyx4mChIbOeH9xeRAO",       # €19.99
    "ultimate": "price_1TVoZ7Ryx4mChIbO3Z30mUQJ"   # €49.99
}

# Credit amounts
CREDITS = {
    "starter": 20,
    "basic": 50,
    "pro": 150,
    "ultimate": 500
}

# Fake in-memory database (replace later with PostgreSQL)
user_credits = {}

@app.route("/")
def home():
    return "HumanID backend running 🚀"

# Create Stripe Checkout
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data = request.json

    pack = data.get("pack")
    user_id = data.get("user_id")

    if pack not in PRICE_IDS:
        return jsonify({"error": "Invalid pack"}), 400

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[{
            "price": PRICE_IDS[pack],
            "quantity": 1,
        }],
        metadata={
            "user_id": user_id,
            "pack": pack
        },
        success_url="https://humanid.online/success",
        cancel_url="https://humanid.online/cancel"
    )

    return jsonify({
        "checkout_url": session.url
    })

# Stripe Webhook
@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            endpoint_secret
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]

        user_id = session["metadata"]["user_id"]
        pack = session["metadata"]["pack"]

        credits_to_add = CREDITS.get(pack, 0)

        current = user_credits.get(user_id, 0)

        user_credits[user_id] = current + credits_to_add

        print(f"Added {credits_to_add} credits to {user_id}")

    return jsonify({"status": "success"})

# Check Credits
@app.route("/credits/<user_id>")
def get_credits(user_id):

    credits = user_credits.get(user_id, 0)

    return jsonify({
        "credits": credits
    })

# Analyze Endpoint
@app.route("/analyze", methods=["POST"])
def analyze():

    data = request.json

    user_id = data.get("user_id")

    current_credits = user_credits.get(user_id, 0)

    if current_credits <= 0:
        return jsonify({
            "error": "Not enough credits"
        }), 403

    # Deduct 1 credit
    user_credits[user_id] -= 1

    return jsonify({
        "result": "Analysis completed",
        "remaining_credits": user_credits[user_id]
    })

if __name__ == "__main__":
    app.run(debug=True)
