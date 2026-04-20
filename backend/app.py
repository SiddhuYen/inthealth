from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2 import errors
import re
from time import time
import os
import logging

app = Flask(__name__)

CORS(app, origins=[
    "https://inthealth-1.onrender.com",
    "http://localhost:3000",
    "http://127.0.0.1:5500"
])

logging.basicConfig(level=logging.INFO)

EMAIL_REGEX = r"^[^@]+@[^@]+\.[^@]+$"
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_KEY = os.environ.get("ADMIN_KEY")

requests_log = {}


def is_rate_limited(ip):
    now = time()
    window = 60
    limit = 5

    if ip not in requests_log:
        requests_log[ip] = []

    requests_log[ip] = [t for t in requests_log[ip] if now - t < window]

    if len(requests_log[ip]) >= limit:
        return True

    requests_log[ip].append(now)
    return False


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        c.close()
        conn.close()


def insert_email(email):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (email) VALUES (%s)", (email,))
        conn.commit()
        return "created"
    except errors.UniqueViolation:
        conn.rollback()
        return "duplicate"
    except Exception as e:
        conn.rollback()
        logging.exception("DB error while inserting email")
        return "error"
    finally:
        c.close()
        conn.close()


@app.route("/join", methods=["POST"])
def join():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    if is_rate_limited(ip):
        return jsonify({"error": "Too many requests. Try again in a minute."}), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    email = (data.get("email") or "").strip().lower()

    if not re.match(EMAIL_REGEX, email):
        return jsonify({"error": "Invalid email address"}), 400

    result = insert_email(email)

    if result == "duplicate":
        return jsonify({"error": "That email is already on the waitlist"}), 409
    if result == "error":
        return jsonify({"error": "Server error"}), 500

    return jsonify({"success": True}), 201


@app.route("/admin/emails", methods=["GET"])
def admin_emails():
    secret = request.args.get("key")

    if not ADMIN_KEY or secret != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT email, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        rows = c.fetchall()

        return jsonify([
            {
                "email": row[0],
                "created_at": row[1].isoformat() if row[1] else None
            }
            for row in rows
        ])
    except Exception:
        logging.exception("DB error while fetching admin emails")
        return jsonify({"error": "Server error"}), 500
    finally:
        c.close()
        conn.close()


@app.route("/", methods=["GET"])
def home():
    return "Backend is running", 200


if __name__ == "__main__":
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))