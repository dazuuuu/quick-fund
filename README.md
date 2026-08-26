# QuickFund

A complete Flask loan simulation: users sign up once and can create multiple applications in the same session, apply with a guarantor, simulate a 30% M-Pesa deposit, pass a 14-day maturity period, withdraw, and make partial or full repayments. The dashboard tracks packages, loans, balances, payments, and M-Pesa transactions. The fixed repayment total is the principal plus 0.30% daily interest for every day in the selected term (`months × 30 days`). A 0.1% withdrawal fee is deducted from the principal before disbursement.

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
