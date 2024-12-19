from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Route für die Startseite
@app.route('/')
def home():
    return render_template("index1.html")  # Lädt die HTML-Datei aus dem templates-Ordner

# API-Route für den Chatbot
@app.route('/send', methods=['POST'])
def send():
    data = request.get_json()
    user_message = data.get('message', '')

    # Bot-Logik
    if "Studien" in user_message:
        reply = "Es gibt viele Studien, die zeigen, dass Migration oft wirtschaftliche Gründe hat."
    elif "rechtlichen Vorgaben" in user_message:
        reply = "Es gibt strenge rechtliche Vorgaben, wer Sozialleistungen beziehen darf."
    elif "..." in user_message:
        reply = "Bitte stelle eine spezifischere Frage, damit ich besser antworten kann."
    else:
        reply = "Ich verstehe deine Frage nicht ganz. Kannst du sie bitte genauer formulieren?"

    return jsonify({'reply': reply})

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))  # Port für Render konfigurieren
    app.run(host="0.0.0.0", port=port, debug=True)
