# [CivicMind]

Report it. Route it. Resolve it.

Citizens report civic problems (text, photos, video, GPS). An AI engine classifies each report, routes it to the responsible department, merges duplicates, and ranks urgency. Officials work from a priority queue and map; every stage is timestamped and visible to the citizen, and completion requires photo proof.

## Features

| Citizens | Government officials | Public |
|---|---|---|
| OTP login / register | OTP login / register (department-scoped) | Transparency feed, no login |
| Report with text, photos, video, map pin | AI-ranked priority queue with explainable score | Live stats: open, resolved, avg. time to resolve |
| Auto-routing to the right department | Map view (circle size = merged reports, dashed ring = overdue) | Department performance table |
| Live status timeline + notifications | Acknowledge with target date, post progress, complete with mandatory photo | |
| Confirm the fix or reopen within 7 days | Override AI category / priority with a recorded reason | |

**Stage machine:** Received → Acknowledged → In progress → Completed (+ Reopened). Stages cannot be skipped. Unacknowledged issues turn *overdue* after 48 h.

## AI engine

* **Local engine (always on, offline):** weighted multilingual classifier (English, Hinglish, Devanagari) over a 9-category / 27-sub-category taxonomy, rule-based severity model (1-5), school / hospital / transit proximity detector.
* **Claude layer (optional):** set `ANTHROPIC_API_KEY` and Claude also reads up to 2 photos per report. Its answer is validated against the taxonomy and blended with the local result. If Claude is slow, down, or returns bad output, the local result is used, so submitting a complaint never fails because of AI.
* **Duplicate merging:** same category + within 150 m (or within 300 m with similar wording) + still open + within 30 days.
* **Priority score (0-100):** `0.30·reports + 0.30·severity + 0.15·category + 0.15·age + 0.10·vulnerability`. Fully visible in the UI; weights configurable via `PRIORITY_WEIGHTS`. Officers can override with an audited reason.

## Quick start

**Python (SQLite, zero setup)**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

**Docker (app + PostgreSQL)**
```bash
docker compose up --build
# open http://localhost:8000
```

**Tests**
```bash
cd backend && python -m pytest -q tests
```

## Demo accounts and OTP

`OTP_MODE=demo` (default): **the OTP is always `123456`** and is displayed on the verify screen. No SMS is sent.

| Role | Contact | Notes |
|---|---|---|
| Citizen | `9000000001` | has sample complaints |
| Official | `9000000002` | Roads & Public Works |

Or register new accounts on the Login page (Citizen or Government official tab, then Register). Set `SEED_DEMO=false` to start empty.

## Deploy

### 1. Push to GitHub
```bash
git init && git add . && git commit -m "Civic Mind"
git branch -M main
git remote add origin https://github.com/<you>/civic-mind.git
git push -u origin main
```
GitHub Actions (`.github/workflows/ci.yml`) then runs the tests, a JS syntax check, a Docker build, and a container smoke test on every push.

### 2. Deploy on Render
1. Render dashboard → **New → Blueprint** → select the repo. `render.yaml` creates the web service (Docker) and a PostgreSQL database.
2. Optionally add `ANTHROPIC_API_KEY` in the service's environment.
3. Open the URL Render gives you.

Free-tier caveats: the free web service sleeps when idle, its disk is ephemeral (**uploaded photos are lost on restart**), and free Postgres expires after 30 days. For permanent uploads use a paid plan and uncomment the `disk:` block in `render.yaml`.

## Before real public use

* Set `OTP_MODE=log` or integrate an SMS / email provider in `routers/auth.py` (`request_otp`). Demo mode accepts a public code.
* Set `OFFICIAL_INVITE_CODE`, so only genuine staff can register as officials.
* Set `SEED_DEMO=false` and a long random `SECRET_KEY` (Render generates one).
* Move uploads to object storage (S3 or compatible) if you scale beyond one instance.
* Add a privacy notice: citizen photos can contain faces or number plates, and the public feed shows the first photo of an issue.

## Configuration

See `.env.example` for every variable. Key ones: `SECRET_KEY`, `DATABASE_URL`, `OTP_MODE`, `DEMO_OTP`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `CLUSTER_RADIUS_M`, `ACK_SLA_HOURS`, `REOPEN_WINDOW_DAYS`, `MAP_DEFAULT`.

## Project structure

```
civic-mind/
├── backend/
│   ├── app/
│   │   ├── ai_engine.py      taxonomy, classifier, severity, Claude layer
│   │   ├── services.py       clustering, priority engine, stage machine, stats
│   │   ├── models.py         SQLAlchemy tables
│   │   ├── routers/          auth, issues (citizen + officer actions), official, public
│   │   ├── seed.py           demo data
│   │   └── main.py           FastAPI app, serves the frontend
│   ├── tests/test_api.py     end-to-end lifecycle tests
│   └── requirements*.txt
├── frontend/                 vanilla JS single-page app (no build step)
├── Dockerfile · docker-compose.yml · docker-entrypoint.sh
├── render.yaml · .github/workflows/ci.yml
└── .env.example · .gitignore · LICENSE
```

## API (all under `/api`)

`POST /auth/request-otp` · `POST /auth/verify-otp` · `GET /auth/me` · `POST /complaints` · `GET /complaints/mine` · `GET /issues/{id}` · `POST /issues/{id}/{confirm|reopen|acknowledge|progress|complete|override}` · `GET /notifications` · `GET /official/{queue|analytics}` · `GET /public/{stats|issues|weights}` · `GET /config` · `GET /taxonomy`. Interactive docs at `/docs`.

## Scope notes

This is a self-contained application. It does not integrate with any government system and carries no government branding or symbols. Computer-vision object detection (e.g. YOLO) is not bundled; photo understanding is provided by Claude vision when a key is configured.
