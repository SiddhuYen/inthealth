from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
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
requests_log = {}
DATABASE_URL = os.environ.get("DATABASE_URL")


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


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def insert_email(email):
    conn = psycopg2.connect(DATABASE_URL)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (email) VALUES (%s)", (email,))
        conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        return False
    except Exception as e:
        logging.error(f"DB error: {e}")
        return False
    finally:
        conn.close()


@app.route("/join", methods=["POST"])
def join():
    ip = request.remote_addr

    if is_rate_limited(ip):
        return jsonify({"error": "Too many requests. Try again in a minute."}), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    email = (data.get("email") or "").strip().lower()

    if not re.match(EMAIL_REGEX, email):
        return jsonify({"error": "Invalid email address"}), 400

    success = insert_email(email)

    if not success:
        return jsonify({"error": "That email is already on the waitlist"}), 409

    return jsonify({"success": True}), 201


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))