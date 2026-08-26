import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Flask, abort, flash, g, redirect, render_template, request, url_for


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=os.path.join(app.instance_path, "quickfund.sqlite"),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE,
                borrower_name TEXT NOT NULL,
                borrower_phone TEXT NOT NULL,
                borrower_email TEXT NOT NULL,
                guarantor_name TEXT NOT NULL,
                guarantor_phone TEXT NOT NULL,
                loan_amount_cents INTEGER NOT NULL,
                deposit_amount_cents INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'awaiting_deposit',
                created_at TEXT NOT NULL,
                deposit_confirmed_at TEXT,
                contact_available_at TEXT
            )
            """
        )
        db.commit()

    def money(cents):
        return f"{cents / 100:,.2f}"

    app.jinja_env.filters["money"] = money

    @app.context_processor
    def inject_now():
        return {"today": datetime.now().year}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/apply", methods=("GET", "POST"))
    def apply():
        values = request.form
        if request.method == "POST":
            required = (
                "borrower_name", "borrower_phone", "borrower_email",
                "guarantor_name", "guarantor_phone", "loan_amount", "purpose",
            )
            if any(not values.get(field, "").strip() for field in required):
                flash("Please complete every field.", "error")
                return render_template("apply.html", values=values), 400
            try:
                amount = Decimal(values["loan_amount"].replace(",", ""))
                if amount <= 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                flash("Enter a valid loan amount greater than zero.", "error")
                return render_template("apply.html", values=values), 400

            amount_cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            deposit_cents = int((Decimal(amount_cents) * Decimal("0.30")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            now = datetime.now(timezone.utc).replace(microsecond=0)
            db = get_db()
            cursor = db.execute(
                """INSERT INTO applications
                (borrower_name, borrower_phone, borrower_email, guarantor_name,
                 guarantor_phone, loan_amount_cents, deposit_amount_cents, purpose, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["borrower_name"].strip(), values["borrower_phone"].strip(),
                    values["borrower_email"].strip(), values["guarantor_name"].strip(),
                    values["guarantor_phone"].strip(), amount_cents, deposit_cents,
                    values["purpose"].strip(), now.isoformat(),
                ),
            )
            application_id = cursor.lastrowid
            reference = f"QF-{now:%Y%m%d}-{application_id:05d}"
            db.execute("UPDATE applications SET reference = ? WHERE id = ?", (reference, application_id))
            db.commit()
            return redirect(url_for("application_status", reference=reference))
        return render_template("apply.html", values=values)

    def find_application(reference):
        row = get_db().execute(
            "SELECT * FROM applications WHERE reference = ?", (reference.upper(),)
        ).fetchone()
        if row is None:
            abort(404)
        return row

    @app.get("/application/<reference>")
    def application_status(reference):
        application = find_application(reference)
        available = None
        days_left = None
        if application["contact_available_at"]:
            available = datetime.fromisoformat(application["contact_available_at"])
            delta = available - datetime.now(timezone.utc)
            days_left = max(0, (delta.days + (1 if delta.seconds else 0)))
        return render_template(
            "status.html", application=application, available=available, days_left=days_left
        )

    @app.post("/application/<reference>/confirm-deposit")
    def confirm_deposit(reference):
        application = find_application(reference)
        if application["status"] == "awaiting_deposit":
            confirmed = datetime.now(timezone.utc).replace(microsecond=0)
            available = confirmed + timedelta(days=14)
            get_db().execute(
                """UPDATE applications SET status = 'waiting_period',
                deposit_confirmed_at = ?, contact_available_at = ? WHERE id = ?""",
                (confirmed.isoformat(), available.isoformat(), application["id"]),
            )
            get_db().commit()
            flash("Deposit confirmed. The 14-day waiting period has started.", "success")
        return redirect(url_for("application_status", reference=reference))

    @app.route("/track", methods=("GET", "POST"))
    def track():
        if request.method == "POST":
            reference = request.form.get("reference", "").strip().upper()
            if reference:
                exists = get_db().execute(
                    "SELECT 1 FROM applications WHERE reference = ?", (reference,)
                ).fetchone()
                if exists:
                    return redirect(url_for("application_status", reference=reference))
            flash("We could not find that application reference.", "error")
        return render_template("track.html")

    with app.app_context():
        init_db()
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
