import io, pytest
from app import create_app, db


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "CSRF": False, "SECRET_KEY": "test"})
    with app.app_context():
        db.create_all()
        yield app.test_client()


def signup(c, email="a@x.com"):
    c.post("/register", data={"email": email, "password": "password123"})
    return c.post("/login", data={"email": email, "password": "password123"})


def add(c, **kw):
    d = {"kind": "expense", "amount": "100", "category": "Food", "date": "2026-10-05", "description": "lunch"}
    d.update(kw)
    return c.post("/transactions", data=d, follow_redirects=True)


def test_auth_required(client):
    assert client.get("/dashboard").status_code == 302
    assert client.get("/api/summary").status_code == 302


def test_register_login_and_bad_password(client):
    assert signup(client).status_code == 302
    client.post("/logout")
    r = client.post("/login", data={"email": "a@x.com", "password": "wrong"})
    assert b"Incorrect email or password" in r.data


def test_short_password_rejected(client):
    r = client.post("/register", data={"email": "b@x.com", "password": "short"})
    assert b"at least 8" in r.data


@pytest.mark.parametrize("bad", [{"amount": "-5"}, {"amount": "abc"}, {"amount": "nan"},
                                 {"date": "05/10/2026"}, {"category": "Nope"}, {"kind": "gift"}])
def test_validation_rejects_bad_input(client, bad):
    signup(client)
    add(client, **bad)
    assert client.get("/api/summary?month=2026-10").json["expense"] == 0


def test_summary_and_savings_rate(client):
    signup(client)
    add(client, kind="income", amount="1000", category="Salary")
    add(client, amount="250", category="Food")
    d = client.get("/api/summary?month=2026-10").json
    assert (d["income"], d["expense"], d["net"], d["savings_rate"]) == (1000, 250, 750, 75.0)
    assert d["by_category"] == {"Food": 250.0}
    assert d["trend"]["expense"][-1] == 250.0


def test_budget_alert_levels(client):
    signup(client)
    client.post("/budgets", data={"category": "Food", "monthly_limit": "1000"})
    add(client, amount="850")
    assert client.get("/api/summary?month=2026-10").json["alerts"][0]["status"] == "warn"
    add(client, amount="200")
    assert client.get("/api/summary?month=2026-10").json["alerts"][0]["status"] == "over"


def test_auto_categorization(client):
    signup(client)
    add(client, category="", description="Swiggy order")
    assert "Food" in client.get("/api/summary?month=2026-10").json["by_category"]


def test_csv_import_export_roundtrip(client):
    signup(client)
    csv_data = "date,description,amount\n2026-10-01,Salary,50000\n2026-10-02,Uber ride,-300\nbad,x,y\n"
    r = client.post("/import", data={"file": (io.BytesIO(csv_data.encode()), "t.csv")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Imported 2 rows, skipped 1" in r.data
    out = client.get("/export").data.decode()
    assert "Transport" in out and "50000" in out


def test_users_cannot_touch_each_others_data(client):
    signup(client, "a@x.com"); add(client)
    client.post("/logout"); signup(client, "b@x.com")
    assert client.get("/api/summary?month=2026-10").json["expense"] == 0
    assert client.post("/transactions/1/delete").status_code == 404


def test_csrf_enforced():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        assert app.test_client().post("/login", data={"email": "a", "password": "b"}).status_code == 400
