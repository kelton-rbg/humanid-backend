# =============================================================================
# HumanID Backend — app.py
# Compatível com Render + Gunicorn
# Todas as credenciais via variáveis de ambiente — nunca hardcoded
# =============================================================================

# --- Imports ---
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import requests
import jwt
import datetime
import os
import stripe
import time
import urllib.request
import json
import logging

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

app = Flask(__name__)
CORS(app)

# Segurança — obrigatório definir SECRET_KEY no Render
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY environment variable is not set. Set it in Render before deploying.")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Sightengine
SIGHTENGINE_USER   = os.getenv("SIGHTENGINE_USER")
SIGHTENGINE_SECRET = os.getenv("SIGHTENGINE_SECRET")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Extensões permitidas
ALLOWED_EXTENSIONS_PHOTO = {"png", "jpg", "jpeg", "webp"}
ALLOWED_EXTENSIONS_VIDEO = {"mp4", "mov", "avi", "mkv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Stripe price IDs
PRICE_IDS = {
    "starter":  "price_1TVoTBRyx4mChIbOb3R037Mi",
    "basic":    "price_1TVoUpRyx4mChIbOuJvWg0YO",
    "pro":      "price_1TVoXJRyx4mChIbOeH9xeRAO",
    "ultimate": "price_1TVoZ7Ryx4mChIbO3Z30mUQJ",
}

# Créditos por pack
CREDITS = {
    "starter":  20,
    "basic":    50,
    "pro":      150,
    "ultimate": 500,
}

# Base de dados em memória — TEMPORÁRIA.
# ATENÇÃO: os dados perdem-se quando o servidor reinicia.
# Migrar para Supabase assim que possível.
users        = {}  # { email: { password, credits } }
user_credits = {}  # { user_id: credits }  (usado pelo webhook Stripe)

# =============================================================================
# UTILITÁRIOS
# =============================================================================

def allowed_file(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


def verify_token():
    """Valida o JWT enviado no header Authorization. Devolve o email ou None."""
    token = request.headers.get("Authorization")
    if not token:
        return None
    try:
        data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return data["email"]
    except Exception:
        return None

# =============================================================================
# MIDDLEWARE — Redirecionar WWW e forçar HTTPS
# =============================================================================

@app.before_request
def force_domain_redirect():
    host = request.host
    url  = request.url
    if host.startswith("www."):
        return redirect(url.replace("www.", "", 1), code=301)
    if request.headers.get("X-Forwarded-Proto") == "http":
        return redirect(url.replace("http://", "https://", 1), code=301)

# =============================================================================
# ROTAS BASE
# =============================================================================

@app.route("/")
def home():
    return "HumanID backend running 🚀"

# =============================================================================
# AUTENTICAÇÃO
# =============================================================================

@app.route("/register", methods=["POST"])
def register():
    data     = request.json or {}
    email    = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    if email in users:
        return jsonify({"error": "User already exists"}), 400

    users[email] = {"password": password, "credits": 150}
    logger.info(f"New user registered: {email}")
    return jsonify({"message": "User created"}), 201


@app.route("/login", methods=["POST"])
def login():
    data     = request.json or {}
    email    = data.get("email")
    password = data.get("password")
    user     = users.get(email)

    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    token = jwt.encode(
        {
            "email": email,
            "exp":   datetime.datetime.utcnow() + datetime.timedelta(days=1),
        },
        app.config["SECRET_KEY"],
        algorithm="HS256",
    )
    return jsonify({"token": token})


@app.route("/credits", methods=["GET"])
def get_credits():
    email = verify_token()
    if not email:
        return jsonify({"error": "Unauthorized"}), 401
    if email not in users:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"credits": users[email]["credits"]})

# =============================================================================
# ANÁLISE DE TEXTO
# =============================================================================

@app.route("/analyze", methods=["POST"])
def analyze():
    email = verify_token()
    if not email:
        return jsonify({"error": "Unauthorized"}), 401

    if email not in users:
        return jsonify({"error": "User not found"}), 404

    if users[email]["credits"] <= 0:
        return jsonify({"error": "No credits remaining"}), 403

    data = request.json or {}
    text = data.get("text", "")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Verificar credenciais antes de chamar API externa
    if not SIGHTENGINE_USER or not SIGHTENGINE_SECRET:
        logger.warning("Sightengine credentials not configured — returning service unavailable")
        return jsonify({"error": "Analysis service not configured"}), 503

    users[email]["credits"] -= 1

    try:
        response = requests.post(
            "https://api.sightengine.com/1.0/text/check.json",
            data={
                "text":       text,
                "lang":       "en",
                "mode":       "standard",
                "api_user":   SIGHTENGINE_USER,
                "api_secret": SIGHTENGINE_SECRET,
            },
            timeout=5,
        )
        result = response.json()
        return jsonify({
            "result":       result,
            "credits_left": users[email]["credits"],
        })

    except requests.exceptions.Timeout:
        logger.error("Sightengine timeout")
        return jsonify({"error": "Analysis service timed out. Please try again."}), 504

    except Exception as e:
        logger.error(f"Sightengine error: {e}")
        return jsonify({"error": "Analysis service unavailable. Please try again."}), 503

# =============================================================================
# ANÁLISE DE FICHEIROS (FOTO / VÍDEO)
# =============================================================================

@app.route("/api/v1/scan", methods=["POST"])
def scan_media():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file     = request.files["file"]
    category = request.form.get("category", "photo")

    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    allowed_set = ALLOWED_EXTENSIONS_PHOTO if category == "photo" else ALLOWED_EXTENSIONS_VIDEO
    if not allowed_file(file.filename, allowed_set):
        return jsonify({"error": "Invalid file format for this category"}), 400

    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify({"error": "File exceeds 50 MB limit"}), 413
    file.seek(0)

    # Sem análise real configurada — devolve erro claro em vez de resultado simulado
    if not SIGHTENGINE_USER or not SIGHTENGINE_SECRET:
        return jsonify({
            "error":  "File analysis not available",
            "detail": "Sightengine credentials are not configured. Set SIGHTENGINE_USER and SIGHTENGINE_SECRET in Render."
        }), 503

    # Quando as credenciais estiverem configuradas, implementar chamada real aqui.
    # Por agora, devolve 503 em vez de resultado inventado.
    return jsonify({
        "error":  "File analysis not yet implemented",
        "detail": "This endpoint requires a real analysis integration. Do not use simulated results."
    }), 501

# =============================================================================
# CONTACTO ENTERPRISE
# =============================================================================

@app.route("/api/v1/enterprise-contact", methods=["POST"])
def enterprise_contact():
    data  = request.json or {}
    email = data.get("email", "")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    public_domains = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com"]
    if any(domain in email for domain in public_domains):
        return jsonify({"error": "Please use a corporate email address"}), 400

    logger.info(f"Enterprise contact request from: {email}")
    return jsonify({
        "success": True,
        "message": "Request received. Our team will contact you shortly.",
    })

# =============================================================================
# THREAT MAP
# =============================================================================

@app.route("/api/v1/threat-map", methods=["GET"])
def get_live_threats():
    """
    Devolve dados reais de abuse.ch se disponíveis.
    Se a chamada falhar, devolve dados vazios — nunca dados inventados.
    """
    try:
        req = urllib.request.Request(
            "https://abuse.ch/api/",
            headers={"User-Agent": "HumanID-ThreatMap/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            data  = json.loads(response.read().decode())
            items = data.get("urls", [])[:5]
            live_threats = [
                {
                    "timestamp":   item.get("dateadded", "Unknown"),
                    "reporter":    item.get("reporter", "Anonymous"),
                    "threat_type": item.get("threat", "Unknown"),
                    "url":         item.get("url", ""),
                }
                for item in items
            ]
            return jsonify({"status": "online", "live_data": live_threats})

    except Exception as e:
        logger.warning(f"Threat map unavailable: {e}")
        return jsonify({
            "status":    "unavailable",
            "live_data": [],
            "message":   "Live threat data is currently unavailable.",
        })

# =============================================================================
# WASM MODEL CONFIG
# =============================================================================

@app.route("/api/v1/wasm-model", methods=["GET"])
def get_wasm_config():
    return jsonify({
        "wasm_engine":        "ONNX_Runtime_Web_Native",
        "acceleration":       "WebGL_Enabled",
        "model_architecture": "Polymorphic_Pixel_Analysis_v3",
        "status":             "Ready",
        "config": {
            "allow_local_inference":    True,
            "zero_data_retention_policy": "Strict_Enforced",
            "local_tensor_shape":       [1, 3, 224, 224],
        },
    })

# =============================================================================
# STRIPE — CHECKOUT + WEBHOOK
# =============================================================================

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data    = request.json or {}
    pack    = data.get("pack")
    user_id = data.get("user_id")

    if pack not in PRICE_IDS:
        return jsonify({"error": "Invalid pack"}), 400

    if not stripe.api_key:
        return jsonify({"error": "Payment service not configured"}), 503

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{"price": PRICE_IDS[pack], "quantity": 1}],
            metadata={"user_id": user_id, "pack": pack},
            success_url="https://humanid.online/success",
            cancel_url="https://humanid.online/cancel",
        )
        return jsonify({"checkout_url": session.url})

    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        return jsonify({"error": "Could not create checkout session"}), 500


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload         = request.data
    sig_header      = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not endpoint_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({"error": "Webhook not configured"}), 503

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session         = event["data"]["object"]
        user_id         = session["metadata"].get("user_id")
        pack            = session["metadata"].get("pack")
        credits_to_add  = CREDITS.get(pack, 0)

        if user_id:
            user_credits[user_id] = user_credits.get(user_id, 0) + credits_to_add
            logger.info(f"Added {credits_to_add} credits to user {user_id}")

    return jsonify({"status": "success"})

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
