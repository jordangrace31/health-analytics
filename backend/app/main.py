from fastapi import FastAPI

app = FastAPI(title="Health Analytics")

@app.get("/api/health")
def health():
    return {"status": "ok"}
