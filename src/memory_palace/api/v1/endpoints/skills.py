"""
v1/endpoints/skills.py - Skills endpoint
"""
from fastapi import APIRouter, Depends, Request
from ..schemas import SkillInfo
from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error

router = APIRouter()


@router.get("", response_model=list[SkillInfo])
@router.get("/", response_model=list[SkillInfo])
async def list_skills(_principal: dict[str, str] = Depends(require_auth)):
    """列出所有注册的技能"""
    from ....skills import list_skill_names, get_skill_by_name
    names = list_skill_names()
    skills = []
    for name in names:
        instance = get_skill_by_name(name)
        cfg = getattr(instance, "config", {})
        meta = cfg.get("agent_metadata", {})
        skills.append(SkillInfo(
            name=name,
            description=meta.get("description", ""),
            version=meta.get("version", "1.0.0"),
            tags=[name],
        ))
    return skills


@router.get("/{skill_name}", response_model=SkillInfo)
async def get_skill(
    skill_name: str,
    request: Request,
    _principal: dict[str, str] = Depends(require_auth),
):
    """获取技能详情"""
    from ....skills import get_skill_by_name, list_skill_names
    if skill_name not in list_skill_names():
        raise api_error(request, 404, "SKILL_NOT_FOUND", "Agent 不存在。", "刷新 Agent 列表后重试。")
    instance = get_skill_by_name(skill_name)
    cfg = getattr(instance, "config", {})
    meta = cfg.get("agent_metadata", {})
    return SkillInfo(
        name=skill_name,
        description=meta.get("description", ""),
        version=meta.get("version", "1.0.0"),
        tags=[skill_name],
    )


@router.post("/{skill_name}/reload")
async def reload_skill(
    skill_name: str,
    request: Request,
    principal: dict[str, str] = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    """热重载指定技能"""
    from ....skills import reload_skill as _reload
    from ....core.hot_reload import get_hot_reload_manager
    trace_id = request_trace_id(request)
    try:
        _reload(skill_name)
        # Trigger hot reload manager to re-scan files
        manager = get_hot_reload_manager()
        await manager.reload_skill(skill_name)
        await write_audit(
            db,
            principal=principal,
            action="SKILL_RELOADED",
            resource_type="skill",
            resource_id=skill_name,
            outcome="SUCCEEDED",
            trace_id=trace_id,
        )
        return {"status": "ok", "skill_name": skill_name, "trace_id": trace_id}
    except Exception as exc:
        await write_audit(
            db,
            principal=principal,
            action="SKILL_RELOAD_FAILED",
            resource_type="skill",
            resource_id=skill_name,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={"error_type": type(exc).__name__},
        )
        raise api_error(
            request,
            400,
            "SKILL_RELOAD_FAILED",
            "Agent 热重载失败。",
            "检查 Agent 配置和 Prompt 文件后重试。",
        ) from exc
