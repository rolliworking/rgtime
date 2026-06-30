# RG Time

Staff time-tracking for Rolliworks LLC — kiosk punch capture + admin portal for audit, PTO, and reports.

## Stack

- **Database / Auth:** Supabase (`rgtime` schema)
- **API:** FastAPI (`backend/`)
- **Frontend:** React + TypeScript — kiosk (`frontend/kiosk/`) and admin portal (`frontend/portal/`)

## Phase 0 — Scaffold

```bash
# Apply migrations (requires Docker + Supabase CLI)
supabase start
supabase db reset

# Print schema
python scripts/print_schema.py

# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir .

# Kiosk
cd frontend/kiosk && npm install && npm run dev

# Portal
cd frontend/portal && npm install && npm run dev
```

## Design principle

**The kiosk captures facts. The biweekly audit makes decisions. Nothing is fabricated in between.**
