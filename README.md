# CoopCore Backend

Flask 3.x REST API for **CoopCore**, a cooperative management system for Philippine multi-purpose credit cooperatives. The backend handles authentication, member management, loan applications and releases, savings transactions, share capital, audit logging, and administrative operations.

## Stack

- Python 3.11
- Flask 3.x
- Flask-JWT-Extended
- PyMongo
- Marshmallow
- bcrypt
- MongoDB 7.x

## Architecture

The backend follows a strict layered structure:

```text
backend/
├── app/
│   ├── __init__.py
│   ├── blueprints/      # Route handlers only
│   ├── services/        # Business logic only
│   ├── schemas/         # Marshmallow validation
│   ├── models/          # MongoDB document models/helpers
│   ├── middleware/      # Auth and audit middleware
│   └── utils/           # Shared utilities
├── tests/
├── scripts/
├── requirements.txt
└── run.py
```

### Rules

- Use the **app factory** pattern via `create_app()`.
- Use **Blueprints only** for routes.
- Keep **business logic in services**, not in route handlers.
- Validate all request payloads with **Marshmallow**.
- Protect routes with `@jwt_required()`.
- Add `@roles_required(...)` for restricted endpoints.
- Never expose `password_hash` in responses.
- Use atomic MongoDB updates such as `$set`, `$inc`, and `$push`.
- Use projection to exclude sensitive fields.
- Cast `ObjectId` safely before querying by `_id`.

## Business Rules

The backend enforces these core cooperative rules:

- Member must be **Active**.
- A member can have at most **2 active loans**.
- Loans above **₱30,000** require a **co-maker**.
- Withdrawals cannot exceed the available balance.
- Share payments require a valid `share_id`.
- All financial records must include `posted_by`.
- Penalty is **3% monthly** or **0.1% daily**.
- Members can submit **loan applications through the member portal** using the standard cooperative loan flow, then staff review, approve, and release them.

## Main Modules

- **Auth**: login, token refresh, current user
- **Members**: registration, profile updates, summaries
- **Loans**: applications, approval, release, payments, amortization
- **Savings**: account management, deposits, withdrawals, ledger
- **Shares**: subscriptions and share capital payments
- **Admin**: users, settings, reports, audit logs

## Setup

### 1. Create a virtual environment

```bash
cd backend
python -m venv venv
```

### 2. Activate it

Linux/macOS:

```bash
source venv/bin/activate
```

Windows:

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create environment file

Copy `.env.example` to `.env`.

Example:

```env
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=change-me
MONGO_URI=mongodb://localhost:27017/coopcore
MONGO_DB_NAME=coopcore
JWT_SECRET_KEY=change-me
JWT_ACCESS_TOKEN_EXPIRES=3600
JWT_REFRESH_TOKEN_EXPIRES=604800
CORS_ORIGINS=http://localhost:3000
COOP_NAME=CoopCore Multi-Purpose Cooperative
DEFAULT_LOAN_RATE=12
DEFAULT_SAVINGS_RATE=3
SHARE_PAR_VALUE=100
```

### 5. Run the API

```bash
python run.py
```

Default local API base URL:

```text
http://localhost:5000/api/v1
```

## MongoDB

Default local connection:

```text
mongodb://localhost:27017/coopcore
```

Recommended indexes include:

- `members.member_id` unique
- `members.email` unique sparse
- `loans.loan_id` unique
- `loans.member_id`
- `loans.status`
- `savings_accounts.account_id` unique
- `share_capital.share_id` unique

Create indexes during initialization or with a dedicated startup script.

## API Conventions

### Standard paginated response

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "per_page": 10,
    "total": 100,
    "pages": 10
  }
}
```

### Standard error response

```json
{
  "error": "Descriptive error message"
}
```

## Authentication

JWT is used for protected routes.

Typical flow:

1. `POST /api/v1/auth/login`
2. Receive `access_token` and `refresh_token`
3. Send `Authorization: Bearer <access_token>` in protected requests
4. Refresh access token via `POST /api/v1/auth/refresh`

## Example Endpoints

### Auth

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`

### Members

- `GET /api/v1/members`
- `GET /api/v1/members/<member_id>`
- `POST /api/v1/members`
- `PUT /api/v1/members/<member_id>`
- `GET /api/v1/members/<member_id>/summary`

### Loans

- `GET /api/v1/loans`
- `GET /api/v1/loans/<loan_id>`
- `POST /api/v1/loans`
- `PUT /api/v1/loans/<loan_id>/approve`
- `PUT /api/v1/loans/<loan_id>/reject`
- `PUT /api/v1/loans/<loan_id>/release`
- `POST /api/v1/loans/<loan_id>/payments`
- `GET /api/v1/loans/<loan_id>/schedule`

### Savings

- `GET /api/v1/savings`
- `GET /api/v1/savings/<account_id>`
- `POST /api/v1/savings`
- `POST /api/v1/savings/<account_id>/transactions`
- `GET /api/v1/savings/<account_id>/ledger`

### Shares

- `GET /api/v1/shares`
- `GET /api/v1/shares/<share_id>`
- `PUT /api/v1/shares/<share_id>/subscribe`
- `POST /api/v1/shares/<share_id>/payments`

## Development Guidelines

### Route layer

Routes should only handle:

- request parsing
- auth decorators
- schema loading/validation
- returning HTTP responses

### Service layer

Services should handle:

- cooperative business rules
- MongoDB reads/writes
- financial calculations
- workflow status changes
- audit logging hooks

### Validation

Use Marshmallow schemas for:

- member creation/update
- loan application
- loan payment posting
- savings transactions
- share subscriptions and payments

## Security Notes

- Hash passwords with `bcrypt` only.
- Never return `password_hash`.
- Validate all input.
- Safely cast MongoDB `ObjectId`.
- Restrict endpoints by role.
- Record `posted_by` for all financial transactions.
- Add audit logs for critical actions such as approvals, releases, reversals, and user changes.

Safe `ObjectId` pattern:

```python
from bson import ObjectId

try:
    obj_id = ObjectId(id)
except Exception:
    return {"error": "Invalid ID"}, 400
```

## Testing

Install test dependencies if needed:

```bash
pip install pytest pytest-flask pytest-cov
```

Run tests:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=app --cov-report=html
```

Suggested test coverage:

- auth flows
- role restrictions
- member registration and update
- loan eligibility rules
- co-maker requirement
- payment posting and penalty computation
- savings withdrawal validation
- share capital validations

## Seed Data

If your project includes seed scripts:

```bash
python scripts/seed.py
```

Use seed data only for local development.

## Production Notes

- Run with Gunicorn behind Nginx.
- Use environment variables for all secrets.
- Use MongoDB replica set in production.
- Enforce CORS origin allowlist.
- Create indexes before large-scale use.
- Store uploads in durable object storage if member photos or signatures are supported.

Example Gunicorn command:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'app'`

```bash
cd backend
python run.py
```

### MongoDB connection timeout

```bash
mongosh --eval "db.adminCommand({ ping: 1 })"
```

### CORS issues

Make sure `CORS_ORIGINS` matches the frontend origin exactly.

## Suggested Next Backend Docs

Good follow-up files to add later:

- `backend/docs/API.md`
- `backend/docs/DEPLOYMENT.md`
- `backend/docs/TESTING.md`
- `backend/docs/BUSINESS_RULES.md`

---

Built for CoopCore backend development based on the project guide and architecture reference.
