import pytest
from app import create_app

@pytest.fixture()
def client(tmp_path):
    return create_app({"TESTING":True,"DATABASE":str(tmp_path/"test.sqlite"),"SECRET_KEY":"test"}).test_client()

def signup(client):
    return client.post("/signup",data={"name":"Amina Kamau","phone":"0712345678","email":"amina@example.com","password":"secret1"},follow_redirects=True)

def apply(client,amount="50000",term="3"):
    return client.post("/apply",data={"guarantor_name":"John Kamau","guarantor_phone":"0799999999","loan_amount":amount,"term_months":term,"purpose":"Business"},follow_redirects=False)

def test_signup_and_login(client):
    response=signup(client)
    assert b"Hi, Amina" in response.data
    client.get("/logout")
    response=client.post("/login",data={"email":"amina@example.com","password":"secret1"},follow_redirects=True)
    assert b"YOUR DASHBOARD" in response.data

def test_complete_mpesa_loan_lifecycle(client):
    signup(client); response=apply(client); location=response.headers["Location"]
    page=client.get(location); assert b"KES 15,000.00" in page.data
    page=client.post(location+"/deposit",data={"phone":"0799999999"},follow_redirects=True); assert b"Waiting for maturity" in page.data
    page=client.post(location+"/simulate-maturity",follow_redirects=True); assert b"Loan has matured" in page.data
    page=client.post(location+"/withdraw",data={"phone":"0712345678"},follow_redirects=True)
    assert b"Repay your loan" in page.data and b"KES 63,500.00" in page.data
    assert b"KES 49,950.00" in page.data and b"KES 50.00 withdrawal fee" in page.data
    page=client.post(location+"/repay",data={"phone":"0712345678","amount":"63500"},follow_redirects=True); assert b"Loan fully repaid" in page.data
    assert page.data.count(b"QF")>=4

def test_term_limits_are_enforced(client):
    signup(client)
    response=apply(client,"50000","7")
    assert response.status_code==400
    assert b"allowed repayment period" in response.data

def test_application_has_automatic_full_term_total(client):
    signup(client)
    page=client.get("/apply")
    assert b"PROJECTED TOTAL REPAYMENT" in page.data
    assert b"principal+charge" in page.data

def test_protected_dashboard_redirects(client):
    response=client.get("/dashboard")
    assert response.status_code==302 and "/login" in response.headers["Location"]
