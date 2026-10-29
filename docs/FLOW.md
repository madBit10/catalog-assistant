# AI Catalog Assistant: How the Code Connects

Read this before reading the code. It answers:
1. **What is connected to what?** (system map)
2. **What happens when I run or call X?** (one flow per endpoint / function)
3. **Where does data live, and who writes or reads it?** (data map)

Status: ✅ **exists** · 🔜 **planned** (designed in `SYSTEM_DESIGN.md`, not written yet).
Updated with every code change. If a diagram and the code disagree, the code wins and this file gets fixed.

*Last updated: 2026-10-29: config, DB connection, `Base`, all three models and the first Alembic migration exist; tables are live in PostgreSQL. Auth next.*

---

## 1. System map

```mermaid
flowchart LR
    subgraph CLIENT["Browser 🔜"]
        UI["React + Vite + Tailwind<br/>login · upload · progress · review · export"]
    end

    subgraph API["FastAPI 🔜 (app/)"]
        AUTH["auth routes<br/>register · login → JWT"]
        BATCH["batch routes<br/>upload · list · detail · export"]
        ITEM["item routes<br/>image · edit · retry"]
        DEP["get_current_user()<br/>verifies JWT on every request"]
        OWN["get_item_for_user()<br/>owner check via batches join"]
    end

    subgraph WORKER["Worker 🔜 (app/worker.py)"]
        CLAIM["claim item<br/>BLMOVE → processing list"]
        CLEAN["clean_image()<br/>rembg + white 2048px canvas"]
        LLM["describe_item()<br/>Claude → validated JSON"]
        SAVE["save result<br/>skip edited_fields"]
    end

    DB[("PostgreSQL ✅ container<br/>users · batches · items ✅ (Alembic)")]
    Q[("Redis ✅ container<br/>queue + processing list 🔜")]
    FS[("storage/ 🔜<br/>originals · clean")]
    CL[("Claude API<br/>claude-haiku-5-5")]

    UI -->|Bearer JWT| DEP
    DEP --> AUTH & BATCH & ITEM
    ITEM --> OWN
    BATCH --> DB
    BATCH -->|push item IDs| Q
    BATCH --> FS
    Q --> CLAIM --> CLEAN --> LLM --> SAVE
    CLEAN --> FS
    LLM --> CL
    SAVE --> DB
```

**Read it left to right:** the API only **saves and enqueues** (fast); the worker does the **slow work** (seconds per photo). They never call each other directly; they meet through Redis and PostgreSQL.

---

## 2. Flows: "what happens if I call this?" (all 🔜)

### 2.1 `POST /batches`: uploading photos
```mermaid
flowchart TD
    A["POST /batches<br/>files + Idempotency-Key"] --> B{"valid JWT?"}
    B -->|no| B1["401"]
    B -->|yes| C{"same Idempotency-Key<br/>for this user before?"}
    C -->|yes| C1["200 + the EXISTING batch<br/>(double-click safe)"]
    C -->|no| D{"1-50 files?<br/>daily quota left?"}
    D -->|no| D1["422 / 429"]
    D -->|yes| E["for each file:<br/>check REAL contents (not the name)"]
    E -->|not an image| E1["item status = failed<br/>reason saved · batch continues"]
    E -->|image| F["save under a random name<br/>INSERT item (queued)<br/>push id → Redis"]
    F --> G["201 {batch_id}"]
```

### 2.2 The worker: one photo
```mermaid
flowchart TD
    A["BLMOVE: claim item id"] --> B["status = processing"]
    B --> C["clean_image(): rembg → white 2048px"]
    C -->|crash| C1{"first failure?"}
    C1 -->|yes| C2["re-queue once"]
    C1 -->|no| C3["failed"]
    C -->|empty cutout| C4["needs_review"]
    C -->|ok| D["describe_item(): image → Claude → Pydantic"]
    D -->|429 / 5xx / timeout| D1["re-queue with backoff"]
    D -->|not clothing| D2["needs_review"]
    D -->|valid JSON| E["UPDATE item fields<br/>EXCEPT edited_fields → done"]
    E --> F["LREM: ack (remove from processing list)"]
    C3 --> F
    C4 --> F
    D2 --> F
```

### 2.3 `GET /batches/{id}`: the progress bar
```mermaid
sequenceDiagram
    participant B as Browser (every 2 s)
    participant A as FastAPI
    participant D as PostgreSQL
    B->>A: GET /batches/{id}
    A->>D: batch WHERE id = ? AND user_id = me
    alt not mine / missing
        A-->>B: 404 (never 403)
    else mine
        A->>D: SELECT status, COUNT(*) GROUP BY status
        A-->>B: items + {done: 37, failed: 2, total: 50}
    end
```

---

## 2.4 Startup: how settings and the database connection load ✅
```mermaid
flowchart LR
    ENV[".env"] -->|read + type-checked| CFG["app/core/config.py<br/>settings = Settings()<br/>(app refuses to start if a value is missing/wrong)"]
    CFG -->|settings.database_url| DBF["app/db/database.py<br/>engine (pool_pre_ping) · SessionLocal · get_db()"]
    BASE["app/db/base.py<br/>class Base(DeclarativeBase)"] --> MOD["app/db/models.py ✅<br/>User · Batch · Item"]
    DBF -->|get_db() per request| ROUTES["API routes 🔜"]
    MOD -.->|Base.metadata| ALE["alembic/env.py ✅<br/>imports models · URL from settings"]
```
`base.py` imports nothing from the app, so models never open a DB connection just by being imported.

## 3. Data map: who writes, who reads

| Location | Written by | Read by | In git? |
|---|---|---|---|
| `.env` | you, by hand | `app/core/config.py` ✅ (pydantic-settings validates it at startup), docker-compose ✅ | ❌ never |
| `.env.example` | Claude (placeholders only) ✅ | new developers, as a template | ✅ |
| `README.md` | Claude ✅, updated as features land | GitHub visitors, recruiters | ✅ |
| `requirements.txt` | updated whenever a package is added ✅ | `pip install -r`, CI, deployment | ✅ |
| PostgreSQL `users` | `POST /auth/register` 🔜 | login, `get_current_user` 🔜 | ❌ |
| PostgreSQL `batches` | `POST /batches` 🔜 | batch routes, quota check 🔜 | ❌ |
| PostgreSQL `items` | `POST /batches`, worker, `PATCH /items` 🔜 | everything 🔜 | ❌ |
| Redis queue | `POST /batches`, `/retry` 🔜 | worker 🔜 | ❌ |
| `storage/originals/` | `POST /batches` 🔜 | worker 🔜, image route 🔜 | ❌ |
| `storage/clean/` | worker 🔜 | image route, zip export 🔜 | ❌ |
| `alembic/versions/*.py` | `alembic revision --autogenerate`, then reviewed by hand ✅ | `alembic upgrade head` → creates/changes tables | ✅ |
| `docs/SYSTEM_DESIGN.md` | design sessions ✅ | you, interviewers | ✅ |
| `docs/FLOW.md` | updated with every code change ✅ | you, before reading code | ✅ |
| `docs/CHANGES_MADE.md` | every change Claude makes ✅ | you | your choice |

---

## 4. Rule for keeping this file honest
When code is added or changed, update this file **in the same step**: new endpoint or function → a flow in §2; new file or storage location → a row in §3; planned part now written → flip 🔜 to ✅ in §1.
