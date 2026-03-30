from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "HumanID backend running 🚀"

if __name__ == "__main__":
    app.run(debug=True)