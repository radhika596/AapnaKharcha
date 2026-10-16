"""FinanceFlow - personal finance management (Flask + SQLAlchemy + MySQL)."""
import csv, io, os, secrets
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import extract, func
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

CATEGORIES = ["Salary", "Other Income", "Food", "Rent", "Transport", "Utilities",
              "Shopping", "Health", "Entertainment", "Education", "Other"]
KEYWORDS = {"Food": ["swiggy", "zomato", "grocery", "restaurant", "cafe"],
            "Transport": ["uber", "ola", "fuel", "metro", "petrol"],
            "Utilities": ["electricity", "wifi", "broadband", "recharge"],
            "Shopping": ["amazon", "flipkart", "myntra"],
            "Entertainment": ["netflix", "spotify", "movie"],
            "Rent": ["rent"], "Salary": ["salary", "payroll"],
            "Health": ["pharmacy", "doctor", "hospital"]}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(7), nullable=False)  # income | expense
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(255), default="")
    date = db.Column(db.Date, nullable=False)
    __table_args__ = (db.Index("ix_txn_user_date", "user_id", "date"),)


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    monthly_limit = db.Column(db.Numeric(12, 2), nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "category"),)


# ---------- validation & helpers ----------
def money(v):
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return d.quantize(Decimal("0.01")) if d.is_finite() and 0 < d < Decimal("1e9") else None


def auto_category(text):
    t = (text or "").lower()
    return next((c for c, ws in KEYWORDS.items() if any(w in t for w in ws)), "Other")


def clean(f):
    """Validate a transaction dict. Returns (data, error)."""
    kind, amt = f.get("kind", ""), money(f.get("amount", ""))
    cat = f.get("category") or auto_category(f.get("description"))
    try:
        d = date.fromisoformat(f.get("date") or "")
    except ValueError:
        d = None
    err = None
    if kind not in ("income", "expense"): err = "Type must be income or expense."
    elif amt is None: err = "Amount must be a positive number."
    elif cat not in CATEGORIES: err = "Unknown category."
    elif d is None: err = "Date must be in YYYY-MM-DD format."
    return dict(kind=kind, amount=amt, category=cat, date=d,
                description=(f.get("description") or "").strip()[:255]), err


def month_range(s):
    try:
        y, m = map(int, s.split("-")); start = date(y, m, 1)
    except Exception:
        start = date.today().replace(day=1)
    return start, date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def summary(uid, month):
    """SQL-based analytics: totals, category spend, budget status, 6-month trend."""
    T = Transaction
    start, end = month_range(month)
    in_month = [T.user_id == uid, T.date >= start, T.date < end]
    totals = {k: float(v) for k, v in db.session.query(T.kind, func.sum(T.amount))
              .filter(*in_month).group_by(T.kind)}
    spent = {c: float(v) for c, v in db.session.query(T.category, func.sum(T.amount))
             .filter(*in_month, T.kind == "expense").group_by(T.category)
             .order_by(func.sum(T.amount).desc())}
    budgets = []
    for b in Budget.query.filter_by(user_id=uid).order_by(Budget.category):
        s, lim = spent.get(b.category, 0.0), float(b.monthly_limit)
        pct = round(s / lim * 100, 1)
        budgets.append(dict(category=b.category, limit=lim, spent=s, pct=pct,
                            status="over" if pct >= 100 else "warn" if pct >= 80 else "ok"))
    y, m = start.year, start.month - 5
    if m < 1: y, m = y - 1, m + 12
    yy, mm = extract("year", T.date), extract("month", T.date)
    rows = db.session.query(yy, mm, T.kind, func.sum(T.amount)).filter(
        T.user_id == uid, T.date >= date(y, m, 1), T.date < end).group_by(yy, mm, T.kind)
    agg = {(int(a), int(b), k): float(v) for a, b, k, v in rows}
    trend = {"labels": [], "income": [], "expense": []}
    for _ in range(6):
        trend["labels"].append(f"{y}-{m:02d}")
        trend["income"].append(agg.get((y, m, "income"), 0))
        trend["expense"].append(agg.get((y, m, "expense"), 0))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    inc, exp = totals.get("income", 0), totals.get("expense", 0)
    return dict(month=start.strftime("%Y-%m"), income=inc, expense=exp, net=round(inc - exp, 2),
                savings_rate=round((inc - exp) / inc * 100, 1) if inc else 0,
                by_category=spent, budgets=budgets, trend=trend,
                alerts=[b for b in budgets if b["status"] != "ok"])


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if "uid" not in session:
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


# ---------- app factory ----------
def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "mysql+pymysql://root:password@localhost/financeflow"),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1024 * 1024, CSRF=True)
    app.config.update(config or {})
    db.init_app(app)

    @app.cli.command("init-db")
    def init_db():
        db.create_all(); print("Tables created.")

    def csrf():
        return session.setdefault("csrf", secrets.token_hex(16))
    app.jinja_env.globals.update(csrf=csrf, CATEGORIES=CATEGORIES, today=date.today)

    @app.before_request
    def check_csrf():
        if app.config["CSRF"] and request.method == "POST":
            if not secrets.compare_digest(request.form.get("csrf_token", ""), session.get("csrf", "x")):
                abort(400, "Invalid CSRF token")

    # --- auth ---
    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if "uid" in session else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email, pw = request.form.get("email", "").strip().lower(), request.form.get("password", "")
            if "@" not in email or len(email) > 120: flash("Enter a valid email address.")
            elif len(pw) < 8: flash("Password must be at least 8 characters.")
            elif User.query.filter_by(email=email).first(): flash("That email is already registered.")
            else:
                db.session.add(User(email=email, password_hash=generate_password_hash(pw)))
                db.session.commit()
                flash("Account created. Log in to continue.")
                return redirect(url_for("login"))
        return render_template("auth.html", mode="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
            if u and check_password_hash(u.password_hash, request.form.get("password", "")):
                session.clear(); session["uid"] = u.id; session["email"] = u.email
                return redirect(url_for("dashboard"))
            flash("Incorrect email or password.")
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    def logout():
        session.clear(); return redirect(url_for("login"))

    # --- pages ---
    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/transactions", methods=["GET", "POST"])
    @login_required
    def transactions():
        uid = session["uid"]
        if request.method == "POST":
            data, err = clean(request.form)
            if err: flash(err)
            else:
                db.session.add(Transaction(user_id=uid, **data)); db.session.commit()
                flash("Transaction added.")
            return redirect(url_for("transactions"))
        T = Transaction
        q = T.query.filter_by(user_id=uid)
        month = request.args.get("month")
        if month:
            s, e = month_range(month); q = q.filter(T.date >= s, T.date < e)
        if request.args.get("category") in CATEGORIES: q = q.filter_by(category=request.args["category"])
        if request.args.get("kind") in ("income", "expense"): q = q.filter_by(kind=request.args["kind"])
        if request.args.get("q"): q = q.filter(T.description.ilike(f"%{request.args['q'][:50]}%"))
        rows = q.order_by(T.date.desc(), T.id.desc()).limit(200).all()
        return render_template("transactions.html", rows=rows, f=request.args)

    @app.post("/transactions/<int:tid>/delete")
    @login_required
    def delete_txn(tid):
        t = Transaction.query.filter_by(id=tid, user_id=session["uid"]).first_or_404()
        db.session.delete(t); db.session.commit()
        flash("Transaction deleted.")
        return redirect(url_for("transactions"))

    @app.route("/budgets", methods=["GET", "POST"])
    @login_required
    def budgets():
        uid = session["uid"]
        if request.method == "POST":
            cat, lim = request.form.get("category"), money(request.form.get("monthly_limit", ""))
            if cat not in CATEGORIES or lim is None: flash("Choose a category and a positive limit.")
            else:
                b = Budget.query.filter_by(user_id=uid, category=cat).first() or Budget(user_id=uid, category=cat)
                b.monthly_limit = lim; db.session.add(b); db.session.commit()
                flash(f"Budget for {cat} saved.")
            return redirect(url_for("budgets"))
        return render_template("budgets.html", items=summary(uid, request.args.get("month"))["budgets"])

    @app.post("/budgets/<int:bid>/delete")
    @login_required
    def delete_budget(bid):
        b = Budget.query.filter_by(id=bid, user_id=session["uid"]).first_or_404()
        db.session.delete(b); db.session.commit()
        return redirect(url_for("budgets"))

    # --- API, CSV ---
    @app.get("/api/summary")
    @login_required
    def api_summary():
        return jsonify(summary(session["uid"], request.args.get("month")))

    @app.get("/export")
    @login_required
    def export_csv():
        out = io.StringIO(); w = csv.writer(out)
        w.writerow(["date", "type", "category", "amount", "description"])
        for t in Transaction.query.filter_by(user_id=session["uid"]).order_by(Transaction.date):
            desc = t.description or ""
            if desc[:1] in "=+-@": desc = "'" + desc  # block CSV formula injection
            w.writerow([t.date, t.kind, t.category, t.amount, desc])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=financeflow.csv"})

    @app.post("/import")
    @login_required
    def import_csv():
        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".csv"):
            flash("Upload a .csv file."); return redirect(url_for("transactions"))
        reader = csv.DictReader(io.StringIO(file.read().decode("utf-8-sig", "replace")))
        reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames or []]
        ok = bad = 0
        for row in reader:
            raw = (row.get("amount") or "").strip()
            data, err = clean({"kind": (row.get("type") or ("expense" if raw.startswith("-") else "income")).lower(),
                               "amount": raw.lstrip("-"), "category": (row.get("category") or "").strip(),
                               "description": row.get("description"), "date": (row.get("date") or "").strip()})
            if err: bad += 1
            else: db.session.add(Transaction(user_id=session["uid"], **data)); ok += 1
        db.session.commit()
        flash(f"Imported {ok} rows, skipped {bad} invalid rows.")
        return redirect(url_for("transactions"))

    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
