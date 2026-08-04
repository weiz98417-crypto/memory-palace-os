from __future__ import annotations

import json

import httpx
import pytest

from src.memory_palace.operations.uat_showcase import (
    UATShowcaseConfig,
    seed_uat_showcase_data,
)


class ShowcaseKnowledgeAPI:
    def __init__(self) -> None:
        self.knowledge: list[dict] = []
        self.sops: list[dict] = []
        self.users = [
            {"id": "user-zhang", "username": "zhang-jianguo", "display_name": "张建国"},
            {"id": "user-chen", "username": "chen-yu", "display_name": "陈雨"},
            {"id": "user-wang", "username": "wang-fang", "display_name": "王芳"},
            {"id": "user-zhao", "username": "zhao-min", "display_name": "赵敏"},
            {"id": "user-zhou", "username": "zhou-qi", "display_name": "周琦"},
        ]
        self.experts: list[dict] = []
        self.interviews: list[dict] = []
        self.cards: list[dict] = []
        self.events: list[dict] = []
        self.tasks: list[dict] = []
        self.policies: list[dict] = []
        self.runs: list[dict] = []
        self.findings: list[dict] = []
        self.calls: list[tuple[str, str]] = []

    def response(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path
        self.calls.append((method, request.url.raw_path.decode("ascii")))
        body = json.loads(request.content or b"{}")

        if method == "POST" and path == "/api/v1/auth/login":
            return self.ok(
                request,
                {
                    "access_token": "showcase-token",
                    "refresh_token": "r" * 64,
                    "token_type": "bearer",
                    "expires_in": 1800,
                    "user": {
                        "id": "user-admin",
                        "username": body["username"],
                        "role": "admin",
                        "venue_id": "venue-yueshan",
                    },
                },
            )
        if method == "GET" and path == "/api/v1/admin/uat-baseline":
            return self.ok(
                request,
                {
                    "channel": {
                        "mode": "WECOM_SIMULATOR_ONLY",
                        "identity_channel": "WECOM_SIMULATOR",
                        "real_wecom_enabled": False,
                    }
                },
            )
        if method == "GET" and path == "/api/v1/admin/knowledge":
            return self.ok(request, {"knowledge": self.knowledge})
        if method == "POST" and path == "/api/v1/admin/knowledge/import":
            for index, entry in enumerate(body["entries"], start=len(self.knowledge) + 1):
                self.knowledge.append(
                    {
                        "id": f"knowledge-{index}",
                        "status": "ACTIVE",
                        "source_type": "IMPORT",
                        "version": 1,
                        **entry,
                    }
                )
            return self.ok(
                request,
                {"batch_id": "showcase-batch", "imported": len(body["entries"])},
            )
        if method == "GET" and path == "/api/v1/admin/sops":
            return self.ok(request, {"sops": self.sops})
        if method == "POST" and path == "/api/v1/admin/sops":
            sop = {
                "id": len(self.sops) + 1,
                "status": "DRAFT",
                **body,
            }
            self.sops.append(sop)
            return self.ok(request, {"sop": sop})
        if method == "POST" and path.startswith("/api/v1/admin/sops/"):
            parts = path.split("/")
            sop = next(item for item in self.sops if item["id"] == int(parts[-2]))
            action = parts[-1]
            sop["status"] = {
                "submit": "IN_REVIEW",
                "publish": "PUBLISHED",
                "reject": "REJECTED",
            }[action]
            return self.ok(request, {"sop": sop})
        if method == "GET" and path == "/api/v1/admin/users":
            return self.ok(request, {"users": self.users})
        if method == "GET" and path == "/api/v1/admin/experts":
            return self.ok(request, {"experts": self.experts})
        if method == "POST" and path == "/api/v1/admin/experts":
            expert = {"id": f"expert-{len(self.experts) + 1}", "status": "ACTIVE", **body}
            self.experts.append(expert)
            return self.ok(request, {"expert": expert})
        if method == "GET" and path == "/api/v1/admin/experience-interviews":
            return self.ok(request, {"interviews": self.interviews})
        if method == "POST" and path == "/api/v1/admin/experience-interviews":
            expert = next(item for item in self.experts if item["id"] == body["expert_id"])
            interview = {
                "id": f"interview-{len(self.interviews) + 1}",
                "business_id": f"FT-{len(self.interviews) + 1:04d}",
                "status": "INVITED",
                "current_question_index": 0,
                "expert_user_id": expert["user_id"],
                "turns": [],
                **body,
            }
            self.interviews.append(interview)
            return self.ok(request, {"interview": interview})
        if method == "POST" and path.endswith("/accept") and "/experience/interviews/" in path:
            interview = self._interview(path)
            interview["status"] = "ACCEPTED"
            return self.ok(request, {"interview": interview})
        if method == "POST" and path.endswith("/answers") and "/experience/interviews/" in path:
            interview = self._interview(path)
            interview["turns"].append(body["answer"])
            interview["current_question_index"] = len(interview["turns"])
            interview["status"] = "IN_PROGRESS"
            return self.ok(request, {"interview": interview, "idempotent_replay": False})
        if method == "POST" and path.endswith("/complete") and "/experience/interviews/" in path:
            interview = self._interview(path)
            existing = next(
                (item for item in self.cards if item["source"]["interview_id"] == interview["id"]),
                None,
            )
            if existing is None:
                expert = next(item for item in self.experts if item["id"] == interview["expert_id"])
                existing = {
                    "id": f"card-{len(self.cards) + 1}",
                    "status": "DRAFT",
                    "title": interview["title"],
                    "expert_user_id": expert["user_id"],
                    "source": {"interview_id": interview["id"]},
                }
                self.cards.append(existing)
            interview["status"] = "COMPLETED"
            return self.ok(request, {"card": existing, "idempotent_replay": False})
        if method == "GET" and path == "/api/v1/admin/experience-cards":
            return self.ok(request, {"experience_cards": self.cards})
        if method == "POST" and path.endswith("/confirm") and "/experience/cards/" in path:
            card = self._card(path)
            card["status"] = "EXPERT_CONFIRMED"
            return self.ok(request, {"card": card})
        if method == "POST" and path.endswith("/submit") and "/admin/experience-cards/" in path:
            card = self._card(path)
            card["status"] = "IN_REVIEW"
            return self.ok(request, {"card": card})
        if method == "POST" and path.endswith("/publish") and "/admin/experience-cards/" in path:
            card = self._card(path)
            card["status"] = "PUBLISHED"
            return self.ok(request, {"card": card})
        if method == "GET" and path == "/api/v1/admin/events":
            return self.ok(request, {"events": self.events})
        if method == "POST" and path == "/api/v1/admin/events":
            source_id = body.pop("source_id", None)
            event = {
                "event_id": f"event-{len(self.events) + 1}",
                "status": "OPEN",
                "push_id": source_id or "manual",
                **body,
            }
            self.events.append(event)
            return self.ok(request, {"event_id": event["event_id"], "status": "created"})
        if method == "GET" and path == "/api/v1/admin/tasks":
            return self.ok(request, {"tasks": self.tasks})
        if method == "POST" and path == "/api/v1/admin/tasks":
            task = {
                "id": f"task-{len(self.tasks) + 1}",
                "status": "BLOCKED" if body.get("dependencies") else "PENDING",
                **body,
            }
            self.tasks.append(task)
            return self.ok(request, {"task": task})
        if method == "POST" and path.endswith("/start") and "/admin/tasks/" in path:
            task = self._task(path)
            task["status"] = "RUNNING"
            return self.ok(request, {"task": task})
        if method == "POST" and path.endswith("/fail") and "/admin/tasks/" in path:
            task = self._task(path)
            task["status"] = "FAILED"
            task["error"] = body["error"]
            return self.ok(request, {"task": task})
        if method == "GET" and path == "/api/v1/admin/watcher/policies":
            return self.ok(request, {"policies": self.policies})
        if method == "POST" and path == "/api/v1/admin/watcher/policies":
            policy = {"id": f"policy-{len(self.policies) + 1}", **body}
            self.policies.append(policy)
            return self.ok(request, {"policy": policy})
        if method == "PUT" and "/api/v1/admin/watcher/policies/" in path:
            policy_id = path.split("/")[-1]
            policy = next(item for item in self.policies if item["id"] == policy_id)
            policy.update(body)
            return self.ok(request, {"policy": policy})
        if method == "GET" and path == "/api/v1/admin/watcher/runs":
            return self.ok(request, {"runs": self.runs})
        if method == "POST" and path.endswith("/run") and "/watcher/policies/" in path:
            policy_id = path.split("/")[-2]
            policy = next(item for item in self.policies if item["id"] == policy_id)
            if not policy.get("enabled"):
                return httpx.Response(
                    409,
                    request=request,
                    json={"detail": {"message": "停用的巡检策略不能运行"}},
                )
            run = self._new_run(policy_id=policy_id)
            finding = self._new_finding(run, source_type="task")
            return self.ok(request, {**run, "findings": [finding]})
        if method == "POST" and path.endswith("/watcher-check") and "/admin/events/" in path:
            event_id = path.split("/")[-2]
            run = self._new_run(policy_id="event-closure", event_id=event_id)
            findings = [
                self._new_finding(run, source_type="event"),
                self._new_finding(run, source_type="task"),
            ]
            return self.ok(request, {"run": run, "findings": findings})
        if method == "GET" and path == "/api/v1/admin/watcher/findings":
            return self.ok(request, {"findings": self.findings})
        if method == "PATCH" and "/api/v1/admin/watcher/findings/" in path:
            finding = self._finding(path)
            finding.update(body)
            return self.ok(request, {"finding": finding})
        if method == "POST" and path.endswith("/close") and "/watcher/findings/" in path:
            finding = self._finding(path)
            finding["status"] = "CLOSED"
            finding["resolution"] = body["resolution"]
            return self.ok(request, {"closed": True, "finding_id": finding["id"]})
        return httpx.Response(
            404,
            request=request,
            json={"detail": {"message": f"Unhandled {method} {path}"}},
        )

    @staticmethod
    def ok(request: httpx.Request, payload: object) -> httpx.Response:
        return httpx.Response(200, request=request, json=payload)

    def _interview(self, path: str) -> dict:
        interview_id = path.split("/")[-2]
        return next(item for item in self.interviews if item["id"] == interview_id)

    def _card(self, path: str) -> dict:
        card_id = path.split("/")[-2]
        return next(item for item in self.cards if item["id"] == card_id)

    def _task(self, path: str) -> dict:
        task_id = path.split("/")[-2]
        return next(item for item in self.tasks if item["id"] == task_id)

    def _finding(self, path: str) -> dict:
        finding_id = path.split("/")[-1 if not path.endswith("/close") else -2]
        return next(item for item in self.findings if item["id"] == finding_id)

    def _new_run(self, *, policy_id: str, event_id: str | None = None) -> dict:
        run = {
            "id": f"run-{len(self.runs) + 1}",
            "run_id": f"run-{len(self.runs) + 1}",
            "policy_id": policy_id,
            "event_id": event_id,
            "status": "SUCCEEDED",
            "target_count": 3,
            "finding_count": 1,
        }
        self.runs.append(run)
        return run

    def _new_finding(self, run: dict, *, source_type: str) -> dict:
        finding = {
            "id": f"finding-{len(self.findings) + 1}",
            "run_id": run["id"],
            "policy_id": run["policy_id"],
            "status": "OPEN",
            "severity": "P2",
            "source_type": source_type,
            "source_id": f"source-{len(self.findings) + 1}",
            "title": "闭环证据待补充",
        }
        self.findings.append(finding)
        return finding


@pytest.mark.asyncio
async def test_showcase_knowledge_is_repeatable_and_uses_only_formal_apis() -> None:
    state = ShowcaseKnowledgeAPI()
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        first = await seed_uat_showcase_data(config, client=client, sections=("knowledge",))
        second = await seed_uat_showcase_data(config, client=client, sections=("knowledge",))

    assert first.created["knowledge"] == 15
    assert second.created["knowledge"] == 0
    assert second.counts["knowledge"] == 15
    assert len(state.knowledge) == 15
    assert len({item["source_id"] for item in state.knowledge}) == 15
    assert all(item["source_id"].startswith("showcase:knowledge:") for item in state.knowledge)
    assert all(path.startswith("/api/v1/") for _, path in state.calls)
    assert not any("/wecom" in path.lower() for _, path in state.calls)
    assert ("GET", "/api/v1/admin/knowledge?limit=500") in state.calls


@pytest.mark.asyncio
async def test_showcase_sops_cover_lifecycle_states_without_duplicates() -> None:
    state = ShowcaseKnowledgeAPI()
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        first = await seed_uat_showcase_data(config, client=client, sections=("sops",))
        second = await seed_uat_showcase_data(config, client=client, sections=("sops",))

    assert first.created["sops"] == 7
    assert second.created["sops"] == 0
    assert second.counts["sops"] == 7
    assert len(state.sops) == 7
    assert {status: sum(item["status"] == status for item in state.sops) for status in {
        "DRAFT", "IN_REVIEW", "PUBLISHED", "REJECTED"
    }} == {
        "DRAFT": 1,
        "IN_REVIEW": 2,
        "PUBLISHED": 3,
        "REJECTED": 1,
    }


@pytest.mark.asyncio
async def test_showcase_sops_do_not_advance_same_title_business_records() -> None:
    state = ShowcaseKnowledgeAPI()
    business_sop = {
        "id": 1,
        "title": "强降雨游客疏散与恢复开放",
        "content": "这是业务团队尚未完成的草稿，不能由展示数据任务推进。",
        "category": "业务草稿",
        "priority": 4,
        "version": "1.0",
        "status": "DRAFT",
    }
    state.sops.append(business_sop)
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        result = await seed_uat_showcase_data(config, client=client, sections=("sops",))

    assert result.created["sops"] == 7
    assert business_sop["status"] == "DRAFT"
    assert sum(item["title"] == business_sop["title"] for item in state.sops) == 2


@pytest.mark.asyncio
async def test_showcase_experiences_cover_experts_interviews_and_card_states() -> None:
    state = ShowcaseKnowledgeAPI()
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        first = await seed_uat_showcase_data(config, client=client, sections=("experiences",))
        second = await seed_uat_showcase_data(config, client=client, sections=("experiences",))

    assert first.created == {"experts": 5, "interviews": 8, "experience_cards": 6}
    assert second.created == {"experts": 0, "interviews": 0, "experience_cards": 0}
    assert second.counts == {"experts": 5, "interviews": 8, "experience_cards": 6}
    assert len(state.experts) == 5
    assert len(state.interviews) == 8
    assert len(state.cards) == 6
    assert {
        status: sum(item["status"] == status for item in state.interviews)
        for status in {"INVITED", "IN_PROGRESS", "COMPLETED"}
    } == {"INVITED": 1, "IN_PROGRESS": 1, "COMPLETED": 6}
    assert {
        status: sum(item["status"] == status for item in state.cards)
        for status in {"DRAFT", "EXPERT_CONFIRMED", "IN_REVIEW", "PUBLISHED"}
    } == {"DRAFT": 2, "EXPERT_CONFIRMED": 1, "IN_REVIEW": 1, "PUBLISHED": 2}


@pytest.mark.asyncio
async def test_showcase_experiences_do_not_advance_same_title_business_interviews() -> None:
    state = ShowcaseKnowledgeAPI()
    business_interview = {
        "id": "interview-business",
        "business_id": "FT-BUSINESS",
        "expert_id": "expert-1",
        "expert_user_id": "user-zhang",
        "title": "观光车雨后复运的三轮空载验证",
        "source_event_id": None,
        "status": "INVITED",
        "current_question_index": 0,
        "turns": [],
    }
    state.interviews.append(business_interview)
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        result = await seed_uat_showcase_data(config, client=client, sections=("experiences",))

    assert result.created["interviews"] == 8
    assert business_interview["status"] == "INVITED"
    assert sum(item["title"] == business_interview["title"] for item in state.interviews) == 2


@pytest.mark.asyncio
async def test_showcase_watcher_has_live_policies_runs_and_actionable_findings() -> None:
    state = ShowcaseKnowledgeAPI()
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        first = await seed_uat_showcase_data(config, client=client, sections=("watcher",))
        second = await seed_uat_showcase_data(config, client=client, sections=("watcher",))

    assert first.created["events"] == 6
    assert first.created["tasks"] == 10
    assert first.created["watcher_policies"] == 5
    assert first.created["watcher_runs"] == 5
    assert second.created == {
        "events": 0,
        "tasks": 0,
        "watcher_policies": 0,
        "watcher_runs": 0,
        "watcher_findings": 0,
    }
    assert second.counts["events"] == 6
    assert second.counts["tasks"] == 10
    assert second.counts["watcher_policies"] == 5
    assert second.counts["watcher_runs"] == 5
    assert second.counts["watcher_findings"] >= 5
    assert all(policy["enabled"] for policy in state.policies)
    assert {finding["status"] for finding in state.findings} >= {"OPEN", "IN_PROGRESS", "CLOSED"}


@pytest.mark.asyncio
async def test_showcase_watcher_reenables_an_existing_showcase_policy() -> None:
    state = ShowcaseKnowledgeAPI()
    state.policies.append(
        {
            "id": "policy-disabled-showcase",
            "name": "综合风险连续巡检",
            "description": "每 5 分钟复核开放事件、未完成任务和 SOP 执行证据。",
            "schedule_cron": "*/5 * * * *",
            "enabled": False,
            "check_types": ["SLA", "TASK", "SOP"],
            "config": {"max_targets": 80, "showcase_key": "continuous-risk"},
        }
    )
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        result = await seed_uat_showcase_data(config, client=client, sections=("watcher",))

    assert result.created["watcher_policies"] == 4
    assert state.policies[0]["enabled"] is True
    assert ("PUT", "/api/v1/admin/watcher/policies/policy-disabled-showcase") in state.calls


@pytest.mark.asyncio
async def test_showcase_watcher_does_not_reuse_same_text_business_records() -> None:
    state = ShowcaseKnowledgeAPI()
    business_event = {
        "event_id": "event-business",
        "push_id": "manual",
        "raw_text": "东门外广场排队已越过第二隔离区，团队大巴仍在连续到达，需要立即分流并保护消防通道。",
        "event_type": "业务事件",
        "severity": "P2",
        "from_user": "user-zhou",
        "status": "OPEN",
    }
    business_task = {
        "id": "task-business",
        "session_id": "business-session",
        "event_id": "event-business",
        "description": "在东门外广场加设蛇形隔离栏并保持消防通道净宽",
        "status": "PENDING",
    }
    business_policy = {
        "id": "policy-business",
        "name": "综合风险连续巡检",
        "enabled": False,
        "config": {},
    }
    state.events.append(business_event)
    state.tasks.append(business_task)
    state.policies.append(business_policy)
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        result = await seed_uat_showcase_data(config, client=client, sections=("watcher",))

    assert result.created["events"] == 6
    assert result.created["tasks"] == 10
    assert result.created["watcher_policies"] == 5
    assert business_task["status"] == "PENDING"
    assert business_policy["enabled"] is False


@pytest.mark.asyncio
async def test_showcase_watcher_only_advances_findings_from_showcase_runs() -> None:
    state = ShowcaseKnowledgeAPI()
    business_finding = {
        "id": "finding-business",
        "run_id": "run-business",
        "policy_id": "policy-business",
        "event_id": "event-business",
        "status": "OPEN",
        "severity": "P1",
        "source_type": "event",
        "source_id": "event-business",
        "title": "业务发现需要人工处置",
    }
    state.findings.append(business_finding)
    config = UATShowcaseConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(state.response),
        base_url=config.base_url,
    ) as client:
        result = await seed_uat_showcase_data(config, client=client, sections=("watcher",))

    assert business_finding["status"] == "OPEN"
    assert result.counts["watcher_findings"] == len(state.findings) - 1
