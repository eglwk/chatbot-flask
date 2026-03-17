from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

MISTRAL_API_KEY = "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"


def ask_mistral(messages):
    url = "https://api.mistral.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "mistral-small-latest",
        "messages": messages
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 200:
        return "Entschuldigung, gerade konnte ich keine Antwort erzeugen."

    result = response.json()
    return result["choices"][0]["message"]["content"]


def build_messages(chat_history):
    messages = [
        {
            "role": "system",
            "content": "Du bist ein freundlicher, zugewandter Chatbot. Antworte klar, warm und nicht zu lang."
        }
    ]

    for msg in chat_history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    return messages


@app.route('/')
def home():
    return render_template("index1.html")


@app.route('/send', methods=['POST'])
def send():
    data = request.get_json()
    chat_history = data.get('chat_history', [])

    messages = build_messages(chat_history)
    reply = ask_mistral(messages)

    return jsonify({'reply': reply})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)