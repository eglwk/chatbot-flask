from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import json
import re
import psycopg2
import psycopg2.extras

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "bitte-spaeter-sicher-ersetzen")
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_PARTITIONED"] = True

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
DATABASE_URL = os.environ.get("DATABASE_URL")

# -----------------------------
# Blacklists / Hilfslisten
# -----------------------------
COMMON_GERMAN_CITIES = [
    "Mainz", "Wiesbaden", "Frankfurt", "Köln", "Berlin", "Hamburg", "München",
    "Stuttgart", "Darmstadt", "Mannheim", "Heidelberg", "Bonn", "Leipzig",
    "Dresden", "Koblenz", "Trier", "Ingelheim", "Bad Kreuznach", "Ludwigshafen",
    "Bad Homburg", "Offenbach", "Kaiserslautern"
]

INSTITUTIONS = [
    "JGU",
    "Johannes Gutenberg-Universität",
    "Johannes Gutenberg Universität",
    "Universität Mainz",
    "Uni Mainz",
    "Universität",
    "Hochschule",
    "Schule",
    "Klinik",
    "Krankenhaus"
]

SAFE_CAPITALIZED_WORDS = {
    "Ich", "Heute", "Gestern", "Morgen", "Montag", "Dienstag", "Mittwoch",
    "Donnerstag", "Freitag", "Samstag", "Sonntag", "Januar", "Februar",
    "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
    "November", "Dezember", "Deutsch", "Deutschland", "Der", "Die", "Das"
}

# -----------------------------
# Datenbank
# -----------------------------
def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL ist nicht gesetzt.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            participant_id TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def create_user(participant_id, username, password):
    conn = get_db_connection()
    cur = conn.cursor()
    password_hash = generate_password_hash(password)

    cur.execute("""
        INSERT INTO users (participant_id, username, password_hash)
        VALUES (%s, %s, %s)
    """, (participant_id, username, password_hash))

    conn.commit()
    cur.close()
    conn.close()

def get_user_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, participant_id, username, password_hash
        FROM users
        WHERE username = %s
    """, (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def get_user_by_participant_id(participant_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, participant_id, username, password_hash
        FROM users
        WHERE participant_id = %s
    """, (participant_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

# -----------------------------
# Hilfsfunktionen
# -----------------------------
def seafile_headers():
    return {
        "Authorization": f"Token {SEAFILE_TOKEN}",
        "Accept": "application/json"
    }

def require_login():
    return "username" in session and "participant_id" in session

def get_participant_id():
    return session.get("participant_id", "unknown")

def get_chat_filename():
    participant_id = get_participant_id()
    return f"participant_{participant_id}_day{STUDY_DAY}.json"

def get_chat_path():
    return f"/{get_chat_filename()}"

def mask_capitalized_name_phrase(phrase):
    words = phrase.split()
    masked_words = []

    for w in words:
        cleaned = w.strip(",.!?:;")
        if cleaned in SAFE_CAPITALIZED_WORDS:
            masked_words.append(w)
        else:
            suffix = w[len(cleaned):] if len(w) > len(cleaned) else ""
            masked_words.append("[NAME]" + suffix)

    return " ".join(masked_words)

def anonymize_text(text):
    if not text:
        return text

    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL]', text)
    text = re.sub(r'(\+?\d[\d\s\/\-\(\)]{6,}\d)', '[PHONE]', text)
    text = re.sub(r'https?://\S+|www\.\S+', '[URL]', text)
    text = re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b', '[IBAN]', text)
    text = re.sub(r'\b\d{5}\b', '[PLZ]', text)
    text = re.sub(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b', '[DATUM]', text)
    text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '[DATUM]', text)
    text = re.sub(r'@[A-Za-z0-9_\.]+', '[USERNAME]', text)

    text = re.sub(
        r'\b[A-ZÄÖÜ][a-zäöüß\-]+(?:straße|str\.|weg|allee|platz|gasse|ring|ufer)\s+\d+[a-zA-Z]?\b',
        '[ADRESSE]',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(meine adresse ist|ich wohne in der|ich wohne in dem)\s+([^,.\n]+)',
        r'\1 [ADRESSE]',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(ich wohne in|ich lebe in|ich komme aus|ich bin aus|mein wohnort ist)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+){0,4})',
        r'\1 [ORT]',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(geboren am|mein geburtsdatum ist)\s+[^,.\n]+',
        r'\1 [DATUM]',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\bich bin\s+\d{1,3}\s+jahre?\s+alt\b',
        'ich bin [ALTER] jahre alt',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(Ich heiße|Mein Name ist|Ich bin)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})',
        r'\1 [NAME]',
        text
    )

    text = re.sub(
        r'\b(Herr|Frau|Dr\.|Prof\.)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})',
        r'\1 [NAME]',
        text
    )

    text = re.sub(
        r'\b(mein Freund|meine Freundin|mein Mann|meine Frau|mein Bruder|meine Schwester|meine Mutter|mein Vater|mein Sohn|meine Tochter|mein Kollege|meine Kollegin)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})',
        r'\1 [NAME]',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(Ich arbeite bei|Ich arbeite an|Ich studiere an|Ich studiere bei|Ich bin an der|Ich bin bei)\s+([^,.\n]+)',
        r'\1 [INSTITUTION]',
        text,
        flags=re.IGNORECASE
    )

    for city in sorted(COMMON_GERMAN_CITIES, key=len, reverse=True):
        text = re.sub(rf'\b{re.escape(city)}\b', '[ORT]', text, flags=re.IGNORECASE)

    for inst in sorted(INSTITUTIONS, key=len, reverse=True):
        text = re.sub(rf'\b{re.escape(inst)}\b', '[INSTITUTION]', text, flags=re.IGNORECASE)

    context_patterns = [
        r'(\bmit)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bbei)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bvon)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bfür)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bzusammen mit)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bneben)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(\bgegenüber von)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)'
    ]

    for pattern in context_patterns:
        def repl(match):
            prefix = match.group(1)
            name_phrase = match.group(2)
            return f"{prefix} {mask_capitalized_name_phrase(name_phrase)}"
        text = re.sub(pattern, repl, text)

    verb_patterns = [
        r'(\b(?:habe|hatte|treffe|traf|gesehen|sah|kenne|kannte|schrieb|schreibe|rief|rufe|kontaktierte|sprach mit|telefonierte mit|besuchte)\b)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)'
    ]

    for pattern in verb_patterns:
        def repl2(match):
            verb = match.group(1)
            name_phrase = match.group(2)
            return f"{verb} {mask_capitalized_name_phrase(name_phrase)}"
        text = re.sub(pattern, repl2, text, flags=re.IGNORECASE)

    text = re.sub(
        r'\b(war mit)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        lambda m: f"{m.group(1)} {mask_capitalized_name_phrase(m.group(2))}",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r'\b(habe mich mit)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        lambda m: f"{m.group(1)} {mask_capitalized_name_phrase(m.group(2))}",
        text,
        flags=re.IGNORECASE
    )

    return text

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
@app.route("/register", methods=["GET", "POST"])
def register():
    participant_id = request.args.get("pid", "").strip()

    if request.method == "POST":
        participant_id = request.form.get("participant_id", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not participant_id or not username or not password:
            return render_template(
                "register.html",
                error="Bitte alle Felder ausfüllen.",
                participant_id=participant_id
            )

        if get_user_by_participant_id(participant_id):
            return render_template(
                "register.html",
                error="Für diese Teilnehmer-ID wurde bereits ein Konto angelegt.",
                participant_id=participant_id
            )

        try:
            create_user(participant_id, username, password)
            return redirect(url_for("login"))
        except Exception as e:
            return render_template(
                "register.html",
                error=f"Registrierung fehlgeschlagen: {str(e)}",
                participant_id=participant_id
            )

    return render_template("register.html", participant_id=participant_id)

@app.route("/login", methods=["GET", "POST"])
def login():
    participant_id = request.args.get("pid", "").strip()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = get_user_by_username(username)

        if user and check_password_hash(user["password_hash"], password):
            session["username"] = user["username"]
            session["participant_id"] = user["participant_id"]
            return redirect(url_for("home"))

        return render_template("login.html", error="Login fehlgeschlagen.", participant_id=participant_id)

    return render_template("login.html", participant_id=participant_id)

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

        model_history = chat_history.copy()
        model_history.append({
            "role": "user",
            "content": user_message
        })

        reply = ask_mistral(model_history)

        chat_history.append({
            "role": "user",
            "content": anonymize_text(user_message)
        })

        chat_history.append({
            "role": "assistant",
            "content": anonymize_text(reply)
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

    return jsonify({
        "status_code": response.status_code,
        "response_text": response.text,
        "base_url": SEAFILE_BASE_URL,
        "repo_id": SEAFILE_REPO_ID,
        "username": session.get("username"),
        "participant_id": get_participant_id(),
        "current_chat_file": get_chat_filename()
    })

@app.route("/test_anonymization")
def test_anonymization():
    sample = (
        "Ich heiße Lisa Müller, wohne in Mainz, "
        "meine Adresse ist Musterstraße 12. "
        "Ich war mit Paul einkaufen und habe Anna getroffen. "
        "Mein Freund Max war auch dabei. "
        "Ich wohne in Bad Kreuznach. "
        "Meine E-Mail ist lisa@example.com, "
        "meine Telefonnummer ist 0171 1234567 "
        "und meine PLZ ist 55116."
    )

    return jsonify({
        "original": sample,
        "anonymized": anonymize_text(sample)
    })

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)