from datetime import datetime, timezone

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite"), "SECRET_KEY": "test"})
    return app.test_client()


def application_data():
    return {"borrower_name": "Amina Kamau", "borrower_phone": "+254700000000", "borrower_email": "a@example.com", "guarantor_name": "John Kamau", "guarantor_phone": "+254711111111", "loan_amount": "100000", "purpose": "Business stock"}


def test_application_calculates_30_percent(client):
    response = client.post("/apply", data=application_data(), follow_redirects=True)
    assert response.status_code == 200
    assert b"KES 30,000.00" in response.data
    assert b"KES 100,000.00" in response.data


def test_confirm_deposit_starts_14_day_wait(client):
    response = client.post("/apply", data=application_data(), follow_redirects=False)
    location = response.headers["Location"]
    response = client.post(location + "/confirm-deposit", follow_redirects=True)
    assert b"14 days remaining" in response.data
    assert b"Deposit confirmed" in response.data


def test_invalid_amount_is_rejected(client):
    data = application_data()
    data["loan_amount"] = "0"
    response = client.post("/apply", data=data)
    assert response.status_code == 400
    assert b"valid loan amount" in response.data
