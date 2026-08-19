from fastapi import APIRouter

from app.api import answers, documents, feedback, folders, health, jobs, search, videos

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(folders.router)
api_router.include_router(documents.router)
api_router.include_router(videos.router)
api_router.include_router(jobs.router)
api_router.include_router(search.router)
api_router.include_router(answers.router)
api_router.include_router(feedback.router)
