# Finance Manager

Personal finance tracking application built with Flask and SQLite. Tracks monthly income and expenses with accounting-period logic, budget alerts, recurring fixed expenses, and a calendar ledger view.

---

## What This App Does

Finance Manager is not a simple expense tracker. It implements proper **accounting period logic**:

- Each month is an isolated **accounting period** that can be open or closed
- Closed months are **immutable** — no direct edits allowed
- Forgotten transactions from a closed month are added via **Late Entry** from an open month (with a timestamp and note)
- **Recurring fixed expenses** (rent, subscriptions) are defined once and tracked per month as paid/unpaid
- **Budget limits** per category with alerts at 75%, 90%, and 100%
- Full **analytics** across all months with charts
- **Calendar ledger** view showing transactions per day
- **Search** across all transactions (category, subcategory, description)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite (via raw SQL) |
| Frontend | Jinja2 templates, vanilla JS, Chart.js |
| Auth | Session-based, PBKDF2-SHA256 password hashing |
| Security | CSRF tokens, rate limiting, ownership checks |
| Styling | Custom CSS (DM Sans + DM Mono fonts) |

---

## Project Structure

```
Pou_ta_xodevw/
├── app.py                  # Flask routes (HTTP in/out), auth & CSRF helpers
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test dependencies (pytest)
├── Dockerfile / docker-compose.yml / .dockerignore
│
├── services/
│   ├── db.py               # Connection (Flask g), schema, migrations
│   ├── transactions.py     # Add / edit / delete transactions + validation
│   ├── months.py           # Create / close / delete months, stats
│   ├── fixed.py            # Fixed expenses + paid/unpaid toggling
│   ├── analytics.py        # Analytics, dashboard, calendar helpers
│   ├── pdf_report.py       # Monthly PDF report (ReportLab)
│   ├── validation.py       # Shared input validation
│   ├── rate_limit.py       # In-memory sliding-window rate limiter
│   ├── constants.py        # Months, categories, colors
│   └── repair_db.py        # One-off DB repair script
│
├── templates/              # Jinja2 pages (base, dashboard, month, analytics, ...)
├── static/                 # style.css, main.js
└── tests/                  # pytest suite
```

---

## Database Schema

```
users
  id, username (UNIQUE), password_hash, salt, created_at

months
  id, user_id → users, year, month, name
  is_closed (0/1), closed_at
  UNIQUE(user_id, year, month)

transactions
  id, month_id → months, category, subcategory
  type (income/expense), amount, description
  transaction_date, late_entry (0/1), late_entry_note
  created_at

budgets
  id, user_id → users, category, amount
  UNIQUE(user_id, category)

fixed_expenses
  id, user_id → users, label, amount, category, sort_order

fixed_payments
  id, fixed_expense_id → fixed_expenses, month_id → months
  paid (0/1), paid_at, transaction_id → transactions (auto-created expense)
  UNIQUE(fixed_expense_id, month_id)
```

---

## How to Run (Development)

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd finance_manager
pip install -r requirements.txt
```

### 2. Set the secret key (important)

```bash
# Linux / macOS
export SECRET_KEY="your-random-secret-key-here"

# Windows
set SECRET_KEY=your-random-secret-key-here
```

Never use the default key in production. The app will print a warning if you do.

### 3. Run

```bash
python app.py
```

The app starts on `http://localhost:5000`. The database is created automatically on first run.

---

## Security Features

### Password Hashing
PBKDF2-SHA256 with 200,000 iterations and a unique random salt per user. This is production-level hashing strength.

### CSRF Protection
A session-bound CSRF token is generated for every session and validated on HTML form POST requests. It is exposed to Jinja2 templates globally via `csrf_token()`.

### Rate Limiting (Login)
Login attempts are rate-limited per IP address: 10 failed attempts within 5 minutes triggers a lockout. This is in-memory (resets on server restart). For production, use Redis-backed rate limiting.

### Ownership Validation (IDOR Prevention)
Every write operation (edit, delete, close) validates that the resource belongs to the logged-in user via a JOIN check:

```sql
SELECT t.id FROM transactions t
JOIN months m ON t.month_id = m.id
WHERE t.id = ? AND m.user_id = ?
```

This prevents Insecure Direct Object Reference (IDOR) attacks where a user could manipulate another user's data.

### Session Secret Key
Read from `SECRET_KEY` environment variable. Never hardcoded. The app warns at startup if using the default dev key.

---

## Key Concepts

### Accounting Periods
Each month is an independent accounting period. When a month's last day passes (23:59:59), it is automatically closed on the next page load. Closed months are read-only.

### Late Entry
If a transaction from a past closed month was missed, it can be added from an open month using the Late Entry form. The transaction is stored in the closed month's `month_id` with `late_entry=1` and a note explaining why it was late.

### Fixed Expenses
Recurring bills (rent, electricity, gym) are defined once in `fixed_expenses`. Each month, the user marks them as paid. Toggling paid status automatically adds or removes the corresponding transaction from the month.

### Budget Alerts
Budget limits are set per expense category. Alerts are generated at 75% (info), 90% (warning), and 100% (danger). A global alert also fires if total expenses reach 90% or 100% of total income.

### Privacy Mode
A privacy toggle in the sidebar blurs all monetary values on screen using CSS `filter: blur()`. The preference is saved in `localStorage` and persists across page navigation.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/month_stats/<month_id>` | Income/expense/balance for one month (JSON) |
| GET | `/api/now` | Current server time and month name (JSON) |

---

## Running the Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The suite (`tests/`) covers auth & password recovery, CSRF, rate limits,
transactions (validation, ownership, closed months, late entries), fixed
expenses, budgets, search, CSV/PDF export and page rendering. Each test runs
against a fresh temporary SQLite database. GitHub Actions runs it on every
push (`.github/workflows/tests.yml`).

---

## Known Limitations & Future Work

| Area | Current State | Future Improvement |
|---|---|---|
| Architecture | Routes in `app.py`, logic in `services/` | Flask Blueprints per area |
| Database | SQLite (WAL mode), raw SQL | PostgreSQL if multi-user grows |
| Rate limiting | In-memory, per Gunicorn worker | Redis-backed (persistent, shared) |
| Background jobs | `close_expired_months` runs on page load (throttled) | Scheduled job |
| Password reset | Security question | Email-based reset flow |
| Categories | Fixed list in `services/constants.py` | User-defined categories |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes (production) | Flask session signing key. Use a long random string. |
| `DATABASE_PATH` | No | SQLite file path (default: `database.db` next to `app.py`). |
| `LOG_PATH` | No | Log file path (default: `finance_app.log` next to the database). |
| `DEBUG` | No | `1` enables the Flask debugger (dev only). |
| `PRODUCTION` | No | `1` refuses to start with the default `SECRET_KEY`. |
| `SESSION_COOKIE_SECURE` | No | `1` when served over HTTPS (cookie sent only over TLS). |

---

## Logging

All events are written to `finance_app.log` (next to the database, see `LOG_PATH`) and printed to the console. Logged events include:

- Successful and failed login attempts (with IP address)
- Month close events
- Unauthorized access attempts (ownership violations)
- App startup

---





<img width="1920" height="924" alt="Screenshot_20260402_073239" src="https://github.com/user-attachments/assets/01f2384b-bbcf-4d71-b54f-32846109abe4" />
<img width="1916" height="920" alt="Screenshot_20260402_073219" src="https://github.com/user-attachments/assets/d0b6b3a1-7bd2-4dd6-adb1-19d5a564cc45" />
<img width="1920" height="923" alt="Screenshot_20260402_073012" src="https://github.com/user-attachments/assets/893d714f-fac6-4905-acad-47061d582724" />
<img width="1920" height="926" alt="Screenshot_20260402_072934" src="https://github.com/user-attachments/assets/813d3f82-001a-4b83-a939-df5384739330" />
<img width="1920" height="923" alt="Screenshot_20260402_072836" src="https://github.com/user-attachments/assets/02b677b9-4bb2-4c59-8928-3cfa65f4a1a0" />
<img width="1920" height="924" alt="Screenshot_20260402_072735" src="https://github.com/user-attachments/assets/115c9df9-3d57-47f8-9d9f-142cf7fc1082" />


## License

Personal project. All rights reserved.
