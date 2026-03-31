"""
v1/endpoints/skills.py - Skills endpoint
"""
from fastapi import APIRouter, HTTPException
from ..schemas import SkillInfo
from ...skills import get_registered_skills

router = APIRouter()


@router.get("/", response_model=list[SkillInfo])
async def list_skills():
    """列出所有注册的技能"""
    from ...skills import list_skill_names, get_skill_by_name
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
async def get_skill(skill_name: str):
    """获取技能详情"""
    from ...skills import get_skill_by_name, list_skill_names
    if skill_name not in list_skill_names():
        raise HTTPException(status_code=404, detail="Skill not found")
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
async def reload_skill(skill_name: str):
    """热重载指定技能"""
    from ...skills import reload_skill as _reload
    from ...core.hot_reload import get_hot_reload_manager
    try:
        _reload(skill_name)
        # Trigger hot reload manager to re-scan files
        manager = get_hot_reload_manager()
        await manager.reload_skill(skill_name)
        return {"status": "ok", "skill_name": skill_name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
