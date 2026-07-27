from fastapi import APIRouter, Depends, HTTPException

from .models import (
    EnvironmentSnapshot,
    RunActionRequest,
    ScenarioDefinition,
    ScenarioReport,
    ScenarioRun,
    ScenarioSummary,
)
from .scenario_controller import (
    ScenarioConflictError,
    ScenarioController,
    ScenarioVersionConflictError,
    get_scenario_controller,
)


router = APIRouter(prefix="/demo", tags=["Enterprise Demo"])


@router.get("/environment", response_model=EnvironmentSnapshot)
async def get_environment(
    controller: ScenarioController = Depends(get_scenario_controller),
) -> EnvironmentSnapshot:
    return controller.get_environment()


@router.get("/scenarios", response_model=list[ScenarioSummary])
async def list_scenarios(
    controller: ScenarioController = Depends(get_scenario_controller),
) -> list[ScenarioSummary]:
    return controller.list_scenarios()


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDefinition)
async def get_scenario(
    scenario_id: str,
    controller: ScenarioController = Depends(get_scenario_controller),
) -> ScenarioDefinition:
    try:
        return controller.get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenarios/{scenario_id}/runs", response_model=ScenarioRun, status_code=201)
async def create_run(
    scenario_id: str,
    controller: ScenarioController = Depends(get_scenario_controller),
) -> ScenarioRun:
    try:
        return await controller.create_run(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=ScenarioRun)
async def get_run(
    run_id: str,
    controller: ScenarioController = Depends(get_scenario_controller),
) -> ScenarioRun:
    try:
        return controller.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/report", response_model=ScenarioReport)
async def get_run_report(
    run_id: str,
    controller: ScenarioController = Depends(get_scenario_controller),
) -> ScenarioReport:
    try:
        return controller.get_report(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/actions", response_model=ScenarioRun)
async def apply_run_action(
    run_id: str,
    request: RunActionRequest,
    controller: ScenarioController = Depends(get_scenario_controller),
) -> ScenarioRun:
    try:
        return await controller.apply_action(run_id, request.action, request.expected_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RUN_VERSION_CONFLICT",
                "message": str(exc),
                "latest_run": controller.get_run(run_id).model_dump(mode="json"),
            },
        ) from exc
    except ScenarioConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RUN_STATE_CONFLICT",
                "message": str(exc),
                "latest_run": controller.get_run(run_id).model_dump(mode="json"),
            },
        ) from exc
