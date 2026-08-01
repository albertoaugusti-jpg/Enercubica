# -*- coding: utf-8 -*-
"""Sito Enercubica — Flask app.

Serve le pagine pubbliche (template Jinja2 preesistenti), il modulo di
contatto (salva i lead in SQLite) e un'area riservata protetta da password
per consultare ed esportare i lead raccolti.

Invio email via Postmark: opzionale. Se la variabile d'ambiente
POSTMARK_TOKEN non è impostata, il sito funziona comunque: i lead vengono
salvati regolarmente, semplicemente non parte la mail di notifica.
"""

import csv
import io
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from data import AZIENDA, PARTNER, SERVIZI, altri_servizi, trova_servizio

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-questa-chiave-in-produzione")

AREA_PASSWORD = os.environ.get("AREA_PASSWORD", "enercubica")
POSTMARK_TOKEN = os.environ.get("POSTMARK_TOKEN")


# ---------------------------------------------------------------------------
# Database dei lead
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lead (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            nome TEXT NOT NULL,
            azienda TEXT,
            email TEXT NOT NULL,
            telefono TEXT,
            servizio TEXT,
            messaggio TEXT,
            origine TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# Contesto comune a tutti i template
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        "servizi": SERVIZI,
        "partner": PARTNER,
        "azienda": AZIENDA,
        "anno": datetime.now().year,
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("autenticato"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Pagine pubbliche
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chi-siamo")
def chi_siamo():
    return render_template("chi-siamo.html")


@app.route("/servizi")
def servizi_index():
    return render_template("servizi.html")


@app.route("/servizi/<slug>")
def servizio(slug):
    s = trova_servizio(slug)
    if s is None:
        abort(404)
    return render_template("servizio.html", s=s, altri=altri_servizi(slug))


@app.route("/rete")
def rete():
    return render_template("rete.html")


@app.route("/contatti")
def contatti():
    return render_template("contatti.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/cookie")
def cookie():
    return render_template("cookie.html")


# ---------------------------------------------------------------------------
# Modulo di contatto (chiamato via fetch da static/js/main.js)
# ---------------------------------------------------------------------------

@app.route("/api/contatto", methods=["POST"])
def api_contatto():
    dati = request.get_json(silent=True) or {}

    # Honeypot anti-spam: se il campo nascosto è compilato, fingiamo successo.
    if dati.get("website"):
        return jsonify(ok=True)

    nome = (dati.get("nome") or "").strip()
    email = (dati.get("email") or "").strip()
    if not nome or not email:
        return jsonify(ok=False, errore="Servono almeno il nome e un indirizzo email."), 400

    db = get_db()
    db.execute(
        "INSERT INTO lead (data, nome, azienda, email, telefono, servizio, messaggio, origine) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.utcnow().isoformat(),
            nome,
            (dati.get("azienda") or "").strip(),
            email,
            (dati.get("telefono") or "").strip(),
            (dati.get("servizio") or "").strip(),
            (dati.get("messaggio") or "").strip(),
            (dati.get("origine") or "").strip(),
        ),
    )
    db.commit()

    if POSTMARK_TOKEN:
        invia_email_lead(nome, email, dati)

    return jsonify(ok=True)


def invia_email_lead(nome, email, dati):
    """Invio best-effort della notifica via Postmark. Non blocca il salvataggio del lead."""
    try:
        import urllib.request
        import json as _json

        corpo = (
            f"Nuova richiesta dal sito Enercubica\n\n"
            f"Nome: {nome}\nAzienda: {dati.get('azienda', '')}\nEmail: {email}\n"
            f"Telefono: {dati.get('telefono', '')}\nServizio: {dati.get('servizio', '')}\n"
            f"Messaggio: {dati.get('messaggio', '')}\n"
        )
        payload = _json.dumps(
            {
                "From": AZIENDA["email"],
                "To": "a.augusti@energelia.it,a.castagnaro@energelia.it",
                "Subject": f"Nuova richiesta da {nome} — sito Enercubica",
                "TextBody": corpo,
                "ReplyTo": email,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.postmarkapp.com/email",
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": POSTMARK_TOKEN,
            },
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass  # l'email è un extra: se fallisce, il lead resta comunque salvato


# ---------------------------------------------------------------------------
# Area riservata
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    errore = None
    if request.method == "POST":
        if request.form.get("password") == AREA_PASSWORD:
            session["autenticato"] = True
            return redirect(url_for("area_riservata"))
        errore = "Password errata."
    return render_template("login.html", errore=errore)


@app.route("/logout")
def logout():
    session.pop("autenticato", None)
    return redirect(url_for("login"))


@app.route("/area-riservata")
@login_required
def area_riservata():
    db = get_db()
    righe = db.execute("SELECT * FROM lead ORDER BY id DESC").fetchall()
    esito = session.pop("esito", None)
    return render_template(
        "area-riservata.html",
        lead=righe,
        esito=esito,
        postmark_ok=bool(POSTMARK_TOKEN),
    )


@app.route("/area-riservata/test-mail", methods=["POST"])
@login_required
def test_mail():
    if not POSTMARK_TOKEN:
        session["esito"] = {
            "ok": False,
            "testo": "POSTMARK_TOKEN non configurato: impossibile inviare la mail di prova.",
        }
    else:
        try:
            invia_email_lead(
                "Prova",
                AZIENDA["email"],
                {"azienda": "—", "telefono": "—", "servizio": "—", "messaggio": "Mail di prova dall'area riservata."},
            )
            session["esito"] = {"ok": True, "testo": "Mail di prova inviata."}
        except Exception as exc:  # pragma: no cover
            session["esito"] = {"ok": False, "testo": f"Invio non riuscito: {exc}"}
    return redirect(url_for("area_riservata"))


@app.route("/area-riservata/export.csv")
@login_required
def esporta_lead():
    db = get_db()
    righe = db.execute("SELECT * FROM lead ORDER BY id DESC").fetchall()

    buffer = io.StringIO()
    scrittore = csv.writer(buffer)
    scrittore.writerow(["Data", "Nome", "Azienda", "Email", "Telefono", "Servizio", "Messaggio"])
    for r in righe:
        scrittore.writerow(
            [r["data"], r["nome"], r["azienda"], r["email"], r["telefono"], r["servizio"], r["messaggio"]]
        )

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=lead-enercubica.csv"},
    )


# ---------------------------------------------------------------------------
# Errori
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def pagina_non_trovata(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
