"""
v1/router.py - API v1 router aggregator
"""
from fastapi import APIRouter
from .endpoints import messages, skills, sessions, admin

router = APIRouter(prefix="/api/v1")

router.include_router(messages.router, prefix="/messages", tags=["messages"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
