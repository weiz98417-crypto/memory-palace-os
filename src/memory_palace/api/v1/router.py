"""
v1/router.py - API v1 router aggregator
"""
from fastapi import APIRouter
from .endpoints import (
    admin,
    assistant,
    attachments,
    auth,
    channels,
    experiences,
    knowledge,
    management,
    messages,
    sessions,
    scenic,
    skills,
    watcher,
    workflows,
)

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(attachments.router, tags=["attachments"])
router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
router.include_router(experiences.assistant_router, prefix="/assistant", tags=["experience"])
router.include_router(channels.router, prefix="/channels", tags=["channels"])
router.include_router(messages.router, prefix="/messages", tags=["messages"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
router.include_router(scenic.router, tags=["scenic"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(experiences.admin_router, prefix="/admin", tags=["experience-admin"])
router.include_router(management.router, prefix="/admin", tags=["management"])
router.include_router(workflows.router, prefix="/admin", tags=["workflows"])
router.include_router(knowledge.router, prefix="/admin", tags=["knowledge"])
router.include_router(watcher.router, prefix="/admin", tags=["watcher"])
