from fastapi import FastAPI

from app.api.routes import auth

app = FastAPI(title="AI Catalog Assistant")

app.include_router(auth.router)


@app.get("/health")
def health():
    return {"status": "ok"}
