from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
import requests
import os
import json

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "bitte-spaeter-sicher-ersetzen")
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_PARTITIONED"] = True


# -----------------------------
# Login-Daten
# -----------------------------
USERS = {
    "test": "12345"
}

USER_PARTICIPANT_IDS = {
    "test": "vp1"
}

# -----------------------------
# API / externe Dienste
# -----------------------------
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "ministral-3b-2512")
MISTRAL_API_URL = os.environ.get(
    "MISTRAL_API_URL",
    "https://api.mistral.ai/v1/chat/completions"
)

SEAFILE_BASE_URL = os.environ.get("SEAFILE_BASE_URL")
SEAFILE_TOKEN = os.environ.get("SEAFILE_TOKEN")
SEAFILE_REPO_ID = os.environ.get("SEAFILE_REPO_ID")
STUDY_DAY = os.environ.get("STUDY_DAY", "1")


# -----------------------------
# Hilfsfunktionen
# -----------------------------
def seafile_headers():
    return {
        "Authorization": f"Token {SEAFILE_TOKEN}",
        "Accept": "application/json"
    }


def require_login():
    if "username" not in session:
        return False
    return True


def get_participant_id():
    username = session.get("username")
    return USER_PARTICIPANT_IDS.get(username, "unknown")


def get_chat_filename():
    participant_id = get_participant_id()
    return f"participant_{participant_id}_day{STUDY_DAY}.json"


def get_chat_path():
    return f"/{get_chat_filename()}"


def get_upload_link():
    url = f"{SEAFILE_BASE_URL}/api2/repos/{SEAFILE_REPO_ID}/upload-link/"
    response = requests.get(url, headers=seafile_headers(), timeout=30)

    if response.status_code != 200:
        raise Exception(f"Upload-Link fehlgeschlagen: {response.status_code} {response.text}")

    return response.text.strip('"')


def get_update_link():
    url = f"{SEAFILE_BASE_URL}/api2/repos/{SEAFILE_REPO_ID}/update-link/"
    response = requests.get(url, headers=seafile_headers(), timeout=30)

    if response.status_code != 200:
        raise Exception(f"Update-Link fehlgeschlagen: {response.status_code} {response.text}")

    return response.text.strip('"')


def get_download_link():
    url = f"{SEAFILE_BASE_URL}/api2/repos/{SEAFILE_REPO_ID}/file/"
    params = {"p": get_chat_path()}

    response = requests.get(
        url,
        headers=seafile_headers(),
        params=params,
        timeout=30
    )

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        raise Exception(f"Download-Link fehlgeschlagen: {response.status_code} {response.text}")

    return response.text.strip('"')


def load_chat_history_from_seafile():
    try:
        download_link = get_download_link()
        if not download_link:
            return []

        file_response = requests.get(download_link, timeout=30)

        if file_response.status_code != 200:
            return []

        data = file_response.json()

        if isinstance(data, list):
            return data

        return []
    except Exception:
        return []


def upload_new_file_to_seafile(file_bytes):
    upload_link = get_upload_link()

    files = {
        "file": (get_chat_filename(), file_bytes, "application/json")
    }

    data = {
        "parent_dir": "/",
        "replace": "1"
    }

    response = requests.post(
        upload_link,
        headers={"Authorization": f"Token {SEAFILE_TOKEN}"},
        files=files,
        data=data,
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"Upload fehlgeschlagen: {response.status_code} {response.text}")


def update_file_in_seafile(file_bytes):
    update_link = get_update_link()

    files = {
        "file": (get_chat_filename(), file_bytes, "application/json")
    }

    data = {
        "target_file": get_chat_path()
    }

    response = requests.post(
        update_link,
        headers={"Authorization": f"Token {SEAFILE_TOKEN}"},
        files=files,
        data=data,
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"Update fehlgeschlagen: {response.status_code} {response.text}")


def save_chat_history_to_seafile(chat_history):
    file_bytes = json.dumps(chat_history, ensure_ascii=False, indent=2).encode("utf-8")

    existing = load_chat_history_from_seafile()

    if existing:
        update_file_in_seafile(file_bytes)
    else:
        upload_new_file_to_seafile(file_bytes)


def ask_mistral(chat_history):
    messages = [
        {
            "role": "system",
            "content": (
                "Du bist Chatti, ein freundlicher, zugewandter Chatbot. "
                "Antworte klar, warm und nicht zu lang. "
                "Wenn die Person etwas Persönliches schreibt, reagiere empathisch, aber nicht übertrieben. "
                "Schreibe auf Deutsch."
            )
        }
    ]

    for msg in chat_history[-10:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MISTRAL_MODEL,
        "messages": messages
    }

    response = requests.post(
        MISTRAL_API_URL,
        headers=headers,
        json=data,
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"Mistral-Fehler: {response.status_code} {response.text}")

    result = response.json()
    return result["choices"][0]["message"]["content"]


# -----------------------------
# Routen
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username in USERS and USERS[username] == password:
            session["username"] = username
            return redirect(url_for("home"))

        return render_template("login.html", error="Login fehlgeschlagen. Bitte Benutzername und Passwort prüfen.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    if not require_login():
        return redirect(url_for("login"))

    return render_template(
        "index1.html",
        username=session["username"],
        participant_id=get_participant_id()
    )


@app.route("/load_chat", methods=["GET"])
def load_chat():
    if not require_login():
        return jsonify({"error": "Nicht eingeloggt"}), 401

    try:
        chat_history = load_chat_history_from_seafile()
        return jsonify({"chat_history": chat_history})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden: {str(e)}"}), 500


@app.route("/send", methods=["POST"])
def send():
    if not require_login():
        return jsonify({"error": "Nicht eingeloggt"}), 401

    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Leere Nachricht"}), 400

    try:
        chat_history = load_chat_history_from_seafile()

        chat_history.append({
            "role": "user",
            "content": user_message
        })

        reply = ask_mistral(chat_history)

        chat_history.append({
            "role": "assistant",
            "content": reply
        })

        save_chat_history_to_seafile(chat_history)

        return jsonify({"reply": reply})
    except Exception as e:
        print("Fehler:", repr(e))
        return jsonify({"error": str(e)}), 500


@app.route("/test_seafile")
def test_seafile():
    if not require_login():
        return jsonify({"error": "Nicht eingeloggt"}), 401

    headers = {
        "Authorization": f"Token {SEAFILE_TOKEN}",
        "Accept": "application/json"
    }

    url = f"{SEAFILE_BASE_URL}/api2/repos/"
    response = requests.get(url, headers=headers, timeout=30)

    safe_prefix = ""
    if SEAFILE_TOKEN:
        safe_prefix = SEAFILE_TOKEN[:8]

    return jsonify({
        "status_code": response.status_code,
        "response_text": response.text,
        "token_exists": bool(SEAFILE_TOKEN),
        "token_prefix": safe_prefix,
        "token_length": len(SEAFILE_TOKEN) if SEAFILE_TOKEN else 0,
        "base_url": SEAFILE_BASE_URL,
        "repo_id": SEAFILE_REPO_ID,
        "username": session.get("username"),
        "participant_id": get_participant_id(),
        "current_chat_file": get_chat_filename()
    })


@app.route("/test_presidio")
def test_presidio():
    sample = "Ich heiße Lisa Müller, meine E-Mail ist lisa@example.com und meine Telefonnummer ist 0171 1234567."

    return jsonify({
        "presidio_available": PRESIDIO_AVAILABLE,
        "original": sample,
        "anonymized": anonymize_text(sample)
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)