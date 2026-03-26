from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
import requests
import os
import json
import re

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
# Blacklists / Hilfslisten
# -----------------------------
COMMON_GERMAN_CITIES = [
    "Mainz", "Wiesbaden", "Frankfurt", "Köln", "Berlin", "Hamburg", "München",
    "Stuttgart", "Darmstadt", "Mannheim", "Heidelberg", "Bonn", "Leipzig",
    "Dresden", "Koblenz", "Trier", "Ingelheim", "Bad Kreuznach", "Ludwigshafen"
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

# Wörter, die großgeschrieben werden dürfen und nicht blind als Name maskiert werden sollen
SAFE_CAPITALIZED_WORDS = {
    "Ich", "Heute", "Gestern", "Morgen", "Montag", "Dienstag", "Mittwoch",
    "Donnerstag", "Freitag", "Samstag", "Sonntag", "Januar", "Februar",
    "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
    "November", "Dezember", "Deutsch", "Deutschland"
}


# -----------------------------
# Hilfsfunktionen
# -----------------------------
def seafile_headers():
    return {
        "Authorization": f"Token {SEAFILE_TOKEN}",
        "Accept": "application/json"
    }


def require_login():
    return "username" in session


def get_participant_id():
    username = session.get("username")
    return USER_PARTICIPANT_IDS.get(username, "unknown")


def get_chat_filename():
    participant_id = get_participant_id()
    return f"participant_{participant_id}_day{STUDY_DAY}.json"


def get_chat_path():
    return f"/{get_chat_filename()}"


def replace_listed_locations(text):
    for city in sorted(COMMON_GERMAN_CITIES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(city)}\b", "[ORT]", text, flags=re.IGNORECASE)
    return text


def replace_listed_institutions(text):
    for inst in sorted(INSTITUTIONS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(inst)}\b", "[INSTITUTION]", text, flags=re.IGNORECASE)
    return text


def mask_capitalized_name_phrase(phrase):
    """
    Maskiert 1-2 großgeschriebene Wörter als Namen.
    Beispiel: 'Lisa' oder 'Lisa Müller'
    """
    words = phrase.split()
    cleaned = []
    for w in words:
        if w in SAFE_CAPITALIZED_WORDS:
            cleaned.append(w)
        else:
            cleaned.append("[NAME]")
    return " ".join(cleaned)


def anonymize_text(text):
    """
    Strengere Regex-Anonymisierung.
    Ziel: möglichst viele personenbezogene Daten vor dem Speichern ersetzen.
    """
    if not text:
        return text

    # -----------------------------
    # Strukturierte Daten
    # -----------------------------
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL]', text)  # E-Mail
    text = re.sub(r'(\+?\d[\d\s\/\-\(\)]{6,}\d)', '[PHONE]', text)  # Telefon
    text = re.sub(r'https?://\S+|www\.\S+', '[URL]', text)  # URLs
    text = re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b', '[IBAN]', text)  # IBAN
    text = re.sub(r'\b\d{5}\b', '[PLZ]', text)  # Postleitzahl
    text = re.sub(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b', '[DATUM]', text)  # Datum
    text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '[DATUM]', text)  # Datum alt.
    text = re.sub(r'@[A-Za-z0-9_\.]+', '[USERNAME]', text)  # Social / Handles

    # Straßen + Hausnummer
    text = re.sub(
        r'\b[A-ZÄÖÜ][a-zäöüß\-]+(?:straße|str\.|weg|allee|platz|gasse|ring|ufer)\s+\d+[a-zA-Z]?\b',
        '[ADRESSE]',
        text,
        flags=re.IGNORECASE
    )

    # Geburtsangaben / Alter
    text = re.sub(r'\b(geboren am|mein geburtsdatum ist)\s+[^,.\n]+', r'\1 [DATUM]', text, flags=re.IGNORECASE)
    text = re.sub(r'\bich bin\s+\d{1,3}\s+jahre?\s+alt\b', 'ich bin [ALTER] jahre alt', text, flags=re.IGNORECASE)

    # -----------------------------
    # Explizite Namensangaben
    # -----------------------------
    text = re.sub(
        r'\b(Ich heiße|Mein Name ist|Ich bin)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})',
        r'\1 [NAME]',
        text
    )

    # Kontakte / Beziehungen
    text = re.sub(
        r'\b(mein Freund|meine Freundin|mein Mann|meine Frau|mein Bruder|meine Schwester|meine Mutter|mein Vater|mein Sohn|meine Tochter|mein Kollege|meine Kollegin)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})',
        r'\1 [NAME]',
        text,
        flags=re.IGNORECASE
    )

    # -----------------------------
    # Wohnort / Herkunft / Institution
    # -----------------------------
    text = re.sub(
        r'\b(Ich wohne in|Ich lebe in|Ich komme aus|Ich bin aus|Mein Wohnort ist)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+){0,3})',
        r'\1 [ORT]',
        text
    )

    text = re.sub(
        r'\b(Ich arbeite bei|Ich arbeite an|Ich studiere an|Ich studiere bei|Ich bin an der|Ich bin bei)\s+([^,.\n]+)',
        r'\1 [INSTITUTION]',
        text,
        flags=re.IGNORECASE
    )

    # feste Listen
    text = replace_listed_locations(text)
    text = replace_listed_institutions(text)

    # -----------------------------
    # Namen nach typischen Kontexten
    # -----------------------------
    # Beispiele:
    # "mit Lisa einkaufen"
    # "bei Max"
    # "von Anna"
    # "für Paul"
    # "zusammen mit Lisa Müller"
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

    # -----------------------------
    # Verben + Name
    # Beispiele:
    # "ich habe Lisa getroffen"
    # "ich schrieb Max"
    # "ich rief Anna an"
    # -----------------------------
    verb_name_patterns = [
        r'(\b(?:habe|hatte|treffe|traf|gesehen|sah|kenne|kannte|schrieb|schreibe|rief|rufe|telefonierte mit|sprach mit)\b)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)'
    ]

    for pattern in verb_name_patterns:
        def repl2(match):
            verb = match.group(1)
            name_phrase = match.group(2)
            return f"{verb} {mask_capitalized_name_phrase(name_phrase)}"
        text = re.sub(pattern, repl2, text, flags=re.IGNORECASE)

    # -----------------------------
    # Sehr aggressive Restregel:
    # Großgeschriebenes Wortpaar nach "mit/bei/von/für" etc. ist schon oben abgedeckt.
    # Hier maskieren wir zusätzlich "Herr X", "Frau Y", "Dr. Z"
    # -----------------------------
    text = re.sub(
        r'\b(Herr|Frau|Dr\.|Prof\.)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'\1 [NAME]',
        text
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
        # Bereits gespeicherte, anonymisierte Historie laden
        chat_history = load_chat_history_from_seafile()

        # Für das Modell die aktuelle echte Eingabe nutzen
        model_history = chat_history.copy()
        model_history.append({
            "role": "user",
            "content": user_message
        })

        reply = ask_mistral(model_history)

        # Für die Speicherung anonymisieren
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


@app.route("/test_anonymization")
def test_anonymization():
    sample = (
        "Ich heiße Lisa Müller, wohne in Mainz, "
        "ich war mit Paul einkaufen und habe Anna getroffen. "
        "Mein Freund Max war auch dabei. "
        "Meine E-Mail ist lisa@example.com, "
        "meine Telefonnummer ist 0171 1234567 "
        "und meine PLZ ist 55116."
    )

    return jsonify({
        "original": sample,
        "anonymized": anonymize_text(sample)
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)