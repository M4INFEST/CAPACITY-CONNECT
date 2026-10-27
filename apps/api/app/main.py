import os

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.applications import router as applications_router
from app.api.v1.assessments import router as assessments_router
from app.api.v1.courses import router as courses_router
from app.api.v1.credentials import router as credentials_router
from app.api.v1.employer_review import router as employer_review_router
from app.api.v1.learning import router as learning_router
from app.api.v1.job_gaps import router as job_gaps_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.passport import router as passport_router
from app.api.v1.profile import router as profile_router
from app.api.v1.roadmaps import router as roadmaps_router
from app.api.v1.role_matches import router as role_matches_router
from app.core.settings import database_url

app = FastAPI(title="Capacity Connect API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(applications_router)
app.include_router(assessments_router)
app.include_router(passport_router)
app.include_router(profile_router)
app.include_router(roadmaps_router)
app.include_router(job_gaps_router)
app.include_router(jobs_router)
app.include_router(role_matches_router)
app.include_router(courses_router)
app.include_router(credentials_router)
app.include_router(learning_router)
app.include_router(employer_review_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with psycopg.connect(database_url(), connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="Database is unavailable") from error
    return {"status": "ready", "database": "connected"}
