from fastapi import FastAPI

app = FastAPI(title="TruthLens AI Service")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
