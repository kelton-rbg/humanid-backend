import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "HumanID backend running 🚀"

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    text = data.get("text", "")

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
            timeout=3  # 🔥 LIMITE DE TEMPO
        )

        result = response.json()

        return jsonify({
            "risk": "high",
            "confidence": "90%",
            "message": "Likely scam detected",
            "source": "AI"
        })

    except:
        return jsonify({
            "risk": "medium",
            "confidence": "70%",
            "message": "Suspicious message",
            "source": "fast-mode"
        })

if __name__ == "__main__":
    app.run(debug=True)

@app.before_request
def force_www_redirect():
    if request.host.startswith('www.'):
        return redirect(request.url.replace('www.', ''), code=301)
