# QuickFund

A Flask loan application prototype. A guarantor secures an application with a 30% deposit, after which the system enforces a minimum 14-day communication waiting period.

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
