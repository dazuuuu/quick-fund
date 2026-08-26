import os, sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

def create_app(test_config=None):
    app=Flask(__name__); app.config.from_mapping(SECRET_KEY=os.environ.get("SECRET_KEY","quickfund-demo-secret"),DATABASE=os.path.join(app.instance_path,"quickfund.sqlite"))
    if test_config: app.config.update(test_config)
    os.makedirs(app.instance_path,exist_ok=True)
    def db():
        if "db" not in g:
            g.db=sqlite3.connect(app.config["DATABASE"]); g.db.row_factory=sqlite3.Row
        return g.db
    @app.teardown_appcontext
    def close(_error=None):
        connection=g.pop("db",None)
        if connection: connection.close()
    def init_db():
        db().executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,phone TEXT NOT NULL UNIQUE,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,reference TEXT NOT NULL UNIQUE,guarantor_name TEXT NOT NULL,guarantor_phone TEXT NOT NULL,amount_cents INTEGER NOT NULL,deposit_cents INTEGER NOT NULL,term_months INTEGER NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'awaiting_deposit',created_at TEXT NOT NULL,deposit_at TEXT,maturity_at TEXT,withdrawn_at TEXT,due_at TEXT,repaid_cents INTEGER NOT NULL DEFAULT 0,principal_repaid_cents INTEGER NOT NULL DEFAULT 0,accrued_interest_cents INTEGER NOT NULL DEFAULT 0,interest_updated_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,loan_id INTEGER NOT NULL,kind TEXT NOT NULL,amount_cents INTEGER NOT NULL,mpesa_code TEXT NOT NULL,phone TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(loan_id) REFERENCES loans(id));
        """)
        columns={row[1] for row in db().execute("PRAGMA table_info(loans)")}
        migrations={"principal_repaid_cents":"INTEGER NOT NULL DEFAULT 0","accrued_interest_cents":"INTEGER NOT NULL DEFAULT 0","interest_updated_at":"TEXT"}
        for name,definition in migrations.items():
            if name not in columns: db().execute(f"ALTER TABLE loans ADD COLUMN {name} {definition}")
        db().commit()
    def now(): return datetime.now(timezone.utc).replace(microsecond=0)
    def to_cents(value):
        amount=Decimal(value.replace(",",""))
        if amount<=0: raise InvalidOperation
        return int((amount*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    def max_term(amount):
        if amount<=5_000_000: return 3
        if amount<=10_000_000: return 7
        if amount<=25_000_000: return 9
        return 12
    def accrue_interest(item):
        """Post simple daily interest on outstanding principal for complete days."""
        if not item or item["status"]!="active" or not item["interest_updated_at"]: return item
        last=datetime.fromisoformat(item["interest_updated_at"]); days=(now()-last).days
        if days<1: return item
        principal=item["amount_cents"]-item["principal_repaid_cents"]
        added=int((Decimal(principal)*Decimal("0.003")*days).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
        updated=last+timedelta(days=days)
        db().execute("UPDATE loans SET accrued_interest_cents=accrued_interest_cents+?,interest_updated_at=? WHERE id=?",(added,updated.isoformat(),item["id"])); db().commit()
        return db().execute("SELECT * FROM loans WHERE id=?",(item["id"],)).fetchone()
    def receipt(kind,loan_id):
        prefix={"deposit":"DP","withdrawal":"WD","repayment":"RP"}[kind]
        return f"QF{prefix}{now():%m%d%H%M}{loan_id:04d}"
    def protected(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            if not g.user: flash("Please log in to continue.","error"); return redirect(url_for("login"))
            return view(*args,**kwargs)
        return wrapped
    @app.before_request
    def load_user():
        uid=session.get("user_id"); g.user=db().execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone() if uid else None
    @app.template_filter("money")
    def money(value): return f"{value/100:,.2f}"
    @app.context_processor
    def context(): return {"today":now().year}
    @app.get("/")
    def index(): return render_template("index.html")
    @app.route("/signup",methods=("GET","POST"))
    def signup():
        if request.method=="POST":
            name=request.form.get("name","").strip(); phone=request.form.get("phone","").strip(); email=request.form.get("email","").strip().lower(); password=request.form.get("password","")
            if not name or not phone or "@" not in email or len(password)<6: flash("Enter valid details and a password of at least 6 characters.","error")
            else:
                try:
                    password_hash=generate_password_hash(password,method="pbkdf2:sha256")
                    cur=db().execute("INSERT INTO users(name,phone,email,password_hash,created_at) VALUES(?,?,?,?,?)",(name,phone,email,password_hash,now().isoformat())); db().commit(); session.clear(); session["user_id"]=cur.lastrowid
                    flash("Account created. Welcome to QuickFund!","success"); return redirect(url_for("dashboard"))
                except sqlite3.IntegrityError: flash("That email or phone is already registered.","error")
        return render_template("auth.html",mode="signup")
    @app.route("/login",methods=("GET","POST"))
    def login():
        if request.method=="POST":
            user=db().execute("SELECT * FROM users WHERE email=?",(request.form.get("email","").strip().lower(),)).fetchone()
            if user and check_password_hash(user["password_hash"],request.form.get("password","")): session.clear(); session["user_id"]=user["id"]; return redirect(url_for("dashboard"))
            flash("Incorrect email or password.","error")
        return render_template("auth.html",mode="login")
    @app.get("/logout")
    def logout(): session.clear(); return redirect(url_for("index"))
    def find_loan(ref): return db().execute("SELECT * FROM loans WHERE reference=? AND user_id=?",(ref.upper(),g.user["id"])).fetchone()
    @app.get("/dashboard")
    @protected
    def dashboard(): return render_template("dashboard.html",loans=db().execute("SELECT * FROM loans WHERE user_id=? ORDER BY id DESC",(g.user["id"],)).fetchall())
    @app.route("/apply",methods=("GET","POST"))
    @protected
    def apply():
        if request.method=="POST":
            try:
                amount=to_cents(request.form.get("loan_amount","")); term=int(request.form.get("term_months","0")); guarantor=request.form.get("guarantor_name","").strip(); phone=request.form.get("guarantor_phone","").strip(); purpose=request.form.get("purpose","").strip()
                if term<1 or term>max_term(amount) or not guarantor or not phone or not purpose: raise ValueError
            except (InvalidOperation,ValueError,TypeError): flash("Complete all fields with a valid amount and allowed repayment period.","error"); return render_template("apply.html",values=request.form),400
            timestamp=now(); deposit=(amount*30+50)//100
            cur=db().execute("INSERT INTO loans(user_id,reference,guarantor_name,guarantor_phone,amount_cents,deposit_cents,term_months,purpose,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(g.user["id"],f"TEMP-{timestamp.timestamp()}",guarantor,phone,amount,deposit,term,purpose,timestamp.isoformat()))
            ref=f"QF-{timestamp:%Y%m%d}-{cur.lastrowid:05d}"; db().execute("UPDATE loans SET reference=? WHERE id=?",(ref,cur.lastrowid)); db().commit(); return redirect(url_for("loan",reference=ref))
        return render_template("apply.html",values={})
    @app.get("/loan/<reference>")
    @protected
    def loan(reference):
        item=find_loan(reference)
        if not item: flash("Loan not found.","error"); return redirect(url_for("dashboard"))
        item=accrue_interest(item)
        maturity=datetime.fromisoformat(item["maturity_at"]) if item["maturity_at"] else None
        tx=db().execute("SELECT * FROM transactions WHERE loan_id=? ORDER BY id DESC",(item["id"],)).fetchall()
        principal_balance=item["amount_cents"]-item["principal_repaid_cents"]
        balance=principal_balance+item["accrued_interest_cents"]
        return render_template("loan.html",loan=item,maturity=maturity,matured=bool(maturity and now()>=maturity),balance=balance,principal_balance=principal_balance,transactions=tx)
    @app.post("/loan/<reference>/deposit")
    @protected
    def deposit(reference):
        item=find_loan(reference); phone=request.form.get("phone","").strip()
        if not item or item["status"]!="awaiting_deposit" or not phone: flash("Enter a valid guarantor M-Pesa number.","error"); return redirect(url_for("loan",reference=reference))
        timestamp=now(); code=receipt("deposit",item["id"]); maturity=timestamp+timedelta(days=14)
        db().execute("UPDATE loans SET status='maturing',deposit_at=?,maturity_at=? WHERE id=?",(timestamp.isoformat(),maturity.isoformat(),item["id"])); db().execute("INSERT INTO transactions(loan_id,kind,amount_cents,mpesa_code,phone,created_at) VALUES(?,?,?,?,?,?)",(item["id"],"deposit",item["deposit_cents"],code,phone,timestamp.isoformat())); db().commit(); flash(f"Simulated M-Pesa deposit successful. Receipt: {code}","success"); return redirect(url_for("loan",reference=reference))
    @app.post("/loan/<reference>/simulate-maturity")
    @protected
    def simulate_maturity(reference):
        item=find_loan(reference)
        if item and item["status"]=="maturing": db().execute("UPDATE loans SET maturity_at=? WHERE id=?",((now()-timedelta(seconds=1)).isoformat(),item["id"])); db().commit(); flash("Demo clock advanced. The loan is ready to withdraw.","success")
        return redirect(url_for("loan",reference=reference))
    @app.post("/loan/<reference>/withdraw")
    @protected
    def withdraw(reference):
        item=find_loan(reference); maturity=datetime.fromisoformat(item["maturity_at"]) if item and item["maturity_at"] else None; phone=request.form.get("phone","").strip()
        if not item or item["status"]!="maturing" or not maturity or now()<maturity or not phone: flash("The loan is not mature or the M-Pesa number is missing.","error"); return redirect(url_for("loan",reference=reference))
        timestamp=now(); due=timestamp+timedelta(days=item["term_months"]*30); code=receipt("withdrawal",item["id"])
        db().execute("UPDATE loans SET status='active',withdrawn_at=?,due_at=?,interest_updated_at=? WHERE id=?",(timestamp.isoformat(),due.isoformat(),timestamp.isoformat(),item["id"])); db().execute("INSERT INTO transactions(loan_id,kind,amount_cents,mpesa_code,phone,created_at) VALUES(?,?,?,?,?,?)",(item["id"],"withdrawal",item["amount_cents"],code,phone,timestamp.isoformat())); db().commit(); flash(f"KES {money(item['amount_cents'])} sent by simulated M-Pesa. Daily interest is now active. Receipt: {code}","success"); return redirect(url_for("loan",reference=reference))
    @app.post("/loan/<reference>/simulate-interest")
    @protected
    def simulate_interest(reference):
        item=find_loan(reference)
        if item and item["status"]=="active" and item["interest_updated_at"]:
            days=max(1,min(365,int(request.form.get("days","1"))))
            shifted=datetime.fromisoformat(item["interest_updated_at"])-timedelta(days=days)
            db().execute("UPDATE loans SET interest_updated_at=? WHERE id=?",(shifted.isoformat(),item["id"])); db().commit()
            flash(f"Demo clock advanced by {days} day(s). Interest has been added.","success")
        return redirect(url_for("loan",reference=reference))
    @app.post("/loan/<reference>/repay")
    @protected
    def repay(reference):
        item=accrue_interest(find_loan(reference))
        if not item or item["status"]!="active": flash("This loan is not open for repayment.","error"); return redirect(url_for("dashboard"))
        principal_balance=item["amount_cents"]-item["principal_repaid_cents"]
        balance=principal_balance+item["accrued_interest_cents"]
        try:
            amount=to_cents(request.form.get("amount",""))
            if amount>balance: raise ValueError
        except (InvalidOperation,ValueError): flash(f"Enter an amount up to KES {money(balance)}.","error"); return redirect(url_for("loan",reference=reference))
        interest_paid=min(amount,item["accrued_interest_cents"]); principal_paid=amount-interest_paid
        new_interest=item["accrued_interest_cents"]-interest_paid; new_principal_paid=item["principal_repaid_cents"]+principal_paid; paid=item["repaid_cents"]+amount
        status="repaid" if new_interest==0 and new_principal_paid==item["amount_cents"] else "active"; timestamp=now(); code=receipt("repayment",item["id"])
        db().execute("UPDATE loans SET repaid_cents=?,principal_repaid_cents=?,accrued_interest_cents=?,status=?,interest_updated_at=? WHERE id=?",(paid,new_principal_paid,new_interest,status,timestamp.isoformat(),item["id"])); db().execute("INSERT INTO transactions(loan_id,kind,amount_cents,mpesa_code,phone,created_at) VALUES(?,?,?,?,?,?)",(item["id"],"repayment",amount,code,request.form.get("phone",g.user["phone"]),timestamp.isoformat())); db().commit(); flash(f"Repayment received. M-Pesa receipt: {code}","success"); return redirect(url_for("loan",reference=reference))
    with app.app_context(): init_db()
    return app

app=create_app()
if __name__=="__main__": app.run(debug=True)
