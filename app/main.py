from fastapi import FastAPI

from app.api.routes import auth, batches, items

app = FastAPI(title="AI Catalog Assistant")

# Concept: ROUTER. Each file groups related endpoints; the app includes them.
# Why: keeps main.py tiny and each feature in its own file.
# Example: auth.router adds /auth/*, batches.router adds /batches/*, items.router adds /items/*
app.include_router(auth.router)
app.include_router(batches.router)
app.include_router(items.router)      # PATCH /items/{id}, /retry, /image


@app.get("/health")
def health():
    """Why: a quick "is the server up?" check for you, Docker and hosting.
    Example: GET /health -> {"status": "ok"}"""
    return {"status": "ok"}
