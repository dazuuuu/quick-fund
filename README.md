# QuickFund

A complete Flask loan simulation: users sign up, apply with a guarantor, simulate a 30% M-Pesa deposit, pass a 14-day maturity period, withdraw, and make partial or full repayments. Repayment terms are limited by loan size. After withdrawal, simple interest accrues at 0.30% per completed day on outstanding principal until the loan is fully paid. The application calculator automatically displays the full-term interest and projected total of principal plus interest.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000.

## Test

```bash
pip install pytest
pytest
```

The deposit button is a demonstration only. Connect a verified payment provider and add authentication, authorization, identity verification, encryption, audit logs, rate limiting, and production notifications before handling real customer data or money.
