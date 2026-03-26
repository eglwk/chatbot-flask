import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///local.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    sosci_serial = db.Column(db.String(128), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)

    def has_password(self) -> bool:
        return bool(self.password_hash)


@app.route("/")
def index():
    user_id = session.get("user_id")
    if user_id:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/resume")
def resume():
    """
    Aufruf z.B. /resume?s=ABC123
    - Falls User zu SERIAL existiert, aber noch kein Passwort hat: set_password
    - Falls Passwort existiert: login
    """
    serial = request.args.get("s", "").strip()

    if not serial:
        return "Fehlende SERIAL im Link.", 400

    user = User.query.filter_by(sosci_serial=serial).first()

    if not user:
        return (
            "Für diese SERIAL wurde noch kein Account vorbereitet. "
            "Bitte Studienleitung kontaktieren.",
            404,
        )

    session["pending_serial"] = serial

    if not user.has_password():
        return redirect(url_for("set_password"))

    return redirect(url_for("login"))


@app.route("/set-password", methods=["GET", "POST"])
def set_password():
    """
    Passwort wird nur einmal gesetzt.
    Voraussetzung: session['pending_serial'] ist vorhanden.
    """
    serial = session.get("pending_serial")

    if not serial:
        flash("Ungültiger Aufruf. Bitte nutzen Sie den Link aus der Studie.")
        return redirect(url_for("login"))

    user = User.query.filter_by(sosci_serial=serial).first()

    if not user:
        flash("Kein vorbereiteter Account gefunden.")
        return redirect(url_for("login"))

    if user.has_password():
        return redirect(url_for("login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_repeat = request.form.get("password_repeat", "")

        if not password:
            flash("Bitte ein Passwort eingeben.")
            return render_template("set_password.html", username=user.username)

        if len(password) < 8:
            flash("Das Passwort muss mindestens 8 Zeichen lang sein.")
            return render_template("set_password.html", username=user.username)

        if password != password_repeat:
            flash("Die Passwörter stimmen nicht überein.")
            return render_template("set_password.html", username=user.username)

        user.password_hash = generate_password_hash(password)
        db.session.commit()

        flash("Passwort erfolgreich gesetzt. Bitte jetzt einloggen.")
        return redirect(url_for("login"))

    return render_template("set_password.html", username=user.username)


@app.route("/login", methods=["GET", "POST"])
def login():
    prefill_username = ""

    pending_serial = session.get("pending_serial")
    if pending_serial:
        user_from_serial = User.query.filter_by(sosci_serial=pending_serial).first()
        if user_from_serial:
            prefill_username = user_from_serial.username

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if not user:
            flash("Unbekannter Benutzername.")
            return render_template("login.html", prefill_username=prefill_username)

        if not user.has_password():
            session["pending_serial"] = user.sosci_serial
            flash("Für diesen Account wurde noch kein Passwort gesetzt.")
            return redirect(url_for("set_password"))

        if not check_password_hash(user.password_hash, password):
            flash("Falsches Passwort.")
            return render_template("login.html", prefill_username=prefill_username)

        # Falls Resume-Link benutzt wurde: prüfen, ob Login zur SERIAL passt
        if pending_serial and user.sosci_serial != pending_serial:
            flash("Dieser Login gehört nicht zum aufgerufenen Studienlink.")
            return render_template("login.html", prefill_username=prefill_username)

        session["user_id"] = user.id
        return redirect(url_for("chat"))

    return render_template("login.html", prefill_username=prefill_username)


@app.route("/chat")
def chat():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("login"))

    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return redirect(url_for("login"))

    return render_template("chat.html", username=user.username, serial=user.sosci_serial)


@app.route("/logout")
def logout():
    session.clear()
    flash("Sie wurden ausgeloggt.")
    return redirect(url_for("login"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)