from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import re
from time import time
import os

app = Flask(__name__)

# Restrict CORS later to your domain
CORS(app)

EMAIL_REGEX = r"^[^@]+@[^@]+\.[^@]+$"

# Simple in-memory rate limiter
requests_log = {}

def is_rate_limited(ip):
    now = time()
    window = 60  # seconds
    limit = 5    # requests per minute

    if ip not in requests_log:
        requests_log[ip] = []

    requests_log[ip] = [t for t in requests_log[ip] if now - t < window]

    if len(requests_log[ip]) >= limit:
        return True

    requests_log[ip].append(now)
    return False


def init_db():
    conn = sqlite3.connect("waitlist.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()


def insert_email(email):
    conn = sqlite3.connect("waitlist.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (email) VALUES (?)", (email,))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()


@app.route("/join", methods=["POST"])
def join():
    ip = request.remote_addr

    # Rate limit
    if is_rate_limited(ip):
        return jsonify({"error": "Too many requests"}), 429

    data = request.get_json()
    email = (data.get("email") or "").strip()

    # Validate email
    if not re.match(EMAIL_REGEX, email):
        return jsonify({"error": "Invalid email"}), 400

    success = insert_email(email)

    if not success:
        return jsonify({"error": "Email already exists"}), 400

    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))