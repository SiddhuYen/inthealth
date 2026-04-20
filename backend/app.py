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
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logging.info("Database initialized successfully")
    finally:
        c.close()
        conn.close()


def insert_user(email, first_name, last_name):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO users (email, first_name, last_name)
            VALUES (%s, %s, %s)
            """,
            (email, first_name, last_name)
        )
        conn.commit()
        return "created"
    except errors.UniqueViolation:
        conn.rollback()
        return "duplicate"
    except Exception as e:
        conn.rollback()
        logging.exception(f"DB error while inserting user: {e}")
        return "error"
    finally:
        c.close()
        conn.close()


@app.route("/debug/db", methods=["GET"])
def debug_db():
    try:
        conn = get_connection()
        c = conn.cursor()

        c.execute("SELECT current_database(), current_user;")
        db_info = c.fetchone()

        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'users'
            );
        """)
        users_table_exists = c.fetchone()[0]

        c.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position;
        """)
        columns = c.fetchall()

        c.close()
        conn.close()

        return jsonify({
            "database_url_present": bool(DATABASE_URL),
            "connected": True,
            "database_name": db_info[0],
            "database_user": db_info[1],
            "users_table_exists": users_table_exists,
            "users_columns": columns
        }), 200
    except Exception as e:
        logging.exception(f"debug_db failed: {e}")
        return jsonify({
            "database_url_present": bool(DATABASE_URL),
            "connected": False,
            "error": str(e)
        }), 500


@app.route("/join", methods=["POST"])
def join():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.remote_addr

    if is_rate_limited(ip):
        return jsonify({"error": "Too many requests. Try again in a minute."}), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    email = (data.get("email") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    if not re.match(EMAIL_REGEX, email):
        return jsonify({"error": "Invalid email address"}), 400

    if not first_name or not last_name:
        return jsonify({"error": "First and last name are required"}), 400

    first_name = first_name.capitalize()
    last_name = last_name.capitalize()

    result = insert_user(email, first_name, last_name)

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
            SELECT first_name, last_name, email, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        rows = c.fetchall()

        return jsonify([
            {
                "first_name": row[0],
                "last_name": row[1],
                "email": row[2],
                "created_at": row[3].isoformat() if row[3] else None
            }
            for row in rows
        ])
    except Exception as e:
        logging.exception(f"DB error while fetching admin emails: {e}")
        return jsonify({"error": "Server error"}), 500
    finally:
        c.close()
        conn.close()


@app.route("/", methods=["GET"])
def home():
    return "Backend is running", 200


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))