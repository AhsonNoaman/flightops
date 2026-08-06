# Deploying

Two pieces, deployed separately because they have opposite cost profiles: a static frontend that
should be free forever, and an API that carries a 7 MB database and needs a process.

```
  Vercel (static)                    Fly.io or Render (container)
  ┌────────────────────┐  fetch      ┌───────────────────────────────┐
  │ Next.js export     │ ──────────► │ FastAPI + uvicorn             │
  │ NEXT_PUBLIC_API_URL│             │ DuckDB, read-only, in the image│
  └────────────────────┘             │ scenarios in process memory   │
                                     └───────────────────────────────┘
```

Nothing is authenticated, and nothing needs to be: every route is a read, the database file is
opened read-only, and the only writes in the system land in per-session scenario overlays that
live in memory and expire in thirty minutes. Live question-answering is the one thing that costs
money, and it stays off unless `ANTHROPIC_API_KEY` is set.

## 1. The API

The image builds the database from the committed CSV at build time, so it is reproducible from
the repository alone and a container that starts is a container whose data loaded.

```bash
make docker                       # build locally, exactly as the deploy does
docker run -p 8000:8000 flightops-api
curl localhost:8000/api/health
```

**Render (the default here)** — `render.yaml` is checked in; point a new Blueprint at the repo
from the dashboard and it reads the file. No CLI, no local credentials, no payment card, and the
deploy is driven entirely from the GitHub repo, which is the property that matters for something
meant to outlive the laptop it was built on. The free tier sleeps when idle, so the first request
after a quiet spell waits out a cold start — the frontend retries for a minute and says so
rather than showing a broken page.

**Fly.io** — `fly.toml` is checked in, as the move-to option. Faster and more reliable than a
sleeping free instance, but it wants a payment card and a CLI login.

```bash
fly launch --no-deploy --copy-config   # claims the app name in fly.toml
fly deploy
fly open /api/health
```

Either way the unit being deployed is the same image built from this repository, so moving
between them — or onto a plain VPS — is one command and a changed URL in the frontend's
environment.

To switch live answering on afterwards, and only then:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...     # or the Render dashboard
```

## 2. The frontend

```bash
cd frontend
vercel link
vercel env add NEXT_PUBLIC_API_URL production    # https://<your-api-host>
vercel --prod
```

`NEXT_PUBLIC_API_URL` is read at **build** time, not runtime, because the output is a static
export. Changing it means redeploying, which is the trade for having no server.

Vercel's project root must be `frontend/`; `frontend/vercel.json` supplies the rest.

## 3. Running it locally

```bash
make install     # venv, package with dev+agent extras, npm install
make api         # :8000, builds data/sample/sample.duckdb on first run
make web         # :3000, pointed at the local API
make check       # ruff, mypy, pytest, and the frontend typecheck
```

## What happens when the API is gone

Free hosting rots. Tiers change, cards expire, and a link on a CV outlives the account it points
at, so this is designed to degrade rather than break:

- The **frontend** retries a sleeping API for a minute, says it is waking, and if it never
  answers says so plainly and points out that the repository and the recorded eval do not depend
  on it.
- The **repository** is the durable artifact. `make docker` reproduces the API image and its
  data from the committed CSV, on any machine, with no account anywhere.
- The **eval transcripts and screenshots** are committed, so the evidence survives the hosting.

## What is deliberately not deployed

**The full month.** The container ships the committed sample — Southwest, 2026-01-01 to
2026-01-07, 26,161 flights — not the full BTS month, which is gitignored and rebuilt on demand
with `scripts/fetch_data.py`. Anyone can reproduce the deployed data from the repo; nobody can
reproduce a file that only existed on my machine.

**Live question-answering, by default.** `POST /api/ask` returns 503 with an explanation rather
than a 404, and the frontend renders the recorded eval instead. Fixed questions with committed
transcripts are a more honest demonstration than a live box anyway: they cannot be cherry-picked
after the fact.

**Any write path.** There is no endpoint that mutates the database, and the connection could not
serve one if there were.
