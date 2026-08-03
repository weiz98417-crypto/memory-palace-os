from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from src.memory_palace.operations.uat_bootstrap import (
    UATBootstrapConfig,
    UATBootstrapError,
    bootstrap_uat_master_data,
)


class UATAPIState:
    def __init__(self) -> None:
        self.venues = [
            {
                "id": "venue-hq",
                "name": "旧演示场地",
                "status": "ACTIVE",
            }
        ]
        self.users = [
            {
                "id": "user-admin",
                "username": "uat-admin",
                "display_name": "旧管理员",
                "role": "admin",
                "venue_id": "venue-hq",
                "department": None,
                "job_title": None,
                "status": "ACTIVE",
            }
        ]
        self.identities: dict[tuple[str, str, str], dict] = {}
        self.settings: dict[tuple[str, str], object] = {}
        self.sops: list[dict] = []
        self.experts: list[dict] = []
        self.approval_rules = [
            {
                "code": "SUSPEND_PASSENGER_VEHICLE",
                "approval_required": True,
                "approver_roles": ["manager"],
            },
            {
                "code": "ACTIVATE_BACKUP_VEHICLE",
                "approval_required": True,
                "approver_roles": ["manager"],
            },
            {
                "code": "SEND_CRITICAL_DISPATCH_ALERT",
                "approval_required": True,
                "approver_roles": ["manager"],
                "delivery_channel": "WECOM_SIMULATOR_OUTBOX",
            },
        ]
        self.process_counts = {
            "sessions": 0,
            "messages": 0,
            "message_runs": 0,
            "events": 0,
            "tasks": 0,
            "task_decompositions": 0,
            "approvals": 0,
            "push_logs": 0,
            "tool_invocations": 0,
            "watcher_runs": 0,
            "watcher_findings": 0,
            "experience_interviews": 0,
            "experience_cards": 0,
        }
        self.password_resets: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.next_user = 1

    def principal_venue(self, request: httpx.Request) -> str:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer token:"):
            return authorization.removeprefix("Bearer token:")
        return "venue-hq"

    def response(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.calls.append((method, path))
        body = json.loads(request.content or b"{}")
        venue_id = self.principal_venue(request)

        if method == "POST" and path == "/api/v1/auth/login":
            admin = next(user for user in self.users if user["username"] == body["username"])
            return self.ok(
                request,
                {
                    "access_token": f"token:{admin['venue_id']}",
                    "refresh_token": "r" * 64,
                    "token_type": "bearer",
                    "expires_in": 1800,
                    "user": admin,
                },
            )

        if method == "GET" and path == "/api/v1/admin/venues":
            return self.ok(request, {"venues": self.venues})
        if method == "POST" and path == "/api/v1/admin/venues":
            venue = {**body, "status": "ACTIVE"}
            self.venues.append(venue)
            return self.ok(request, {"venue": venue}, 201)
        if method == "PATCH" and path.startswith("/api/v1/admin/venues/"):
            target_id = path.rsplit("/", 1)[-1]
            venue = next(item for item in self.venues if item["id"] == target_id)
            venue.update(body)
            return self.ok(request, {"venue": venue})

        if method == "GET" and path == "/api/v1/admin/users":
            return self.ok(request, {"users": self.users})
        if method == "POST" and path == "/api/v1/admin/users":
            user = {
                "id": f"user-{self.next_user}",
                "status": "ACTIVE",
                **{key: value for key, value in body.items() if key != "password"},
            }
            self.next_user += 1
            self.users.append(user)
            return self.ok(request, {"user": user}, 201)
        if method == "PATCH" and path.startswith("/api/v1/admin/users/"):
            target_id = path.rsplit("/", 1)[-1]
            user = next(item for item in self.users if item["id"] == target_id)
            user.update(body)
            return self.ok(request, {"user": user})
        if method == "POST" and path.endswith("/reset-password"):
            target_id = path.split("/")[-2]
            self.password_resets.append(target_id)
            return self.ok(request, {"reset": True})

        if method == "PUT" and path == "/api/v1/admin/settings/organization_name":
            self.settings[(venue_id, "organization_name")] = body["value"]
            return self.ok(request, {"key": "organization_name", "value": body["value"]})

        if method == "GET" and path == "/api/v1/admin/uat-baseline":
            return self.ok(
                request,
                {
                    "captured_at": 1785751200.0,
                    "channel": {
                        "mode": "WECOM_SIMULATOR_ONLY",
                        "identity_channel": "WECOM_SIMULATOR",
                        "real_wecom_enabled": False,
                    },
                    "scope": {
                        "organization_name": self.settings.get((venue_id, "organization_name")),
                        "venue": next(item for item in self.venues if item["id"] == venue_id),
                    },
                    "master_data": {
                        "users": [user for user in self.users if user["venue_id"] == venue_id],
                        "simulator_identities": [
                            identity
                            for identity in self.identities.values()
                            if identity["venue_id"] == venue_id
                        ],
                        "published_sops": [sop for sop in self.sops if sop["status"] == "PUBLISHED"],
                        "signed_experts": [
                            expert
                            for expert in self.experts
                            if expert["authorization_status"] == "SIGNED"
                        ],
                        "approval_rules": self.approval_rules,
                    },
                    "process_counts": self.process_counts,
                },
            )

        if method == "GET" and path == "/api/v1/sessions/":
            return self.ok(request, [])
        if method == "GET" and path == "/api/v1/admin/events":
            return self.ok(request, {"events": []})
        if method == "GET" and path == "/api/v1/admin/tasks":
            return self.ok(request, {"tasks": []})
        if method == "GET" and path == "/api/v1/admin/approvals":
            assert parse_qs(request.url.query.decode())["status"] == ["ALL"]
            return self.ok(request, [])
        if method == "GET" and path == "/api/v1/admin/experience-interviews":
            return self.ok(request, {"interviews": []})
        if method == "GET" and path == "/api/v1/admin/experience-cards":
            return self.ok(request, {"experience_cards": []})

        if method == "POST" and path == "/api/v1/channels/identities":
            key = (body["channel"], body["external_tenant_id"], body["external_user_id"])
            identity = {
                "id": "identity-" + body["external_user_id"],
                "venue_id": venue_id,
                "created_at": 1.0,
                "updated_at": 1.0,
                **body,
            }
            self.identities[key] = identity
            return self.ok(request, identity, 201)
        if method == "GET" and path == "/api/v1/channels/simulator-identities":
            identities = []
            for user in self.users:
                if user["venue_id"] != venue_id or user["role"] not in {"operator", "manager"}:
                    continue
                identities.append(
                    {
                        "user_id": user["id"],
                        "username": user["username"],
                        "display_name": user["display_name"],
                        "role": user["role"],
                        "venue_id": venue_id,
                        "organization_name": self.settings[(venue_id, "organization_name")],
                        "venue_name": next(item["name"] for item in self.venues if item["id"] == venue_id),
                        "department": user["department"],
                        "job_title": user["job_title"],
                        "external_tenant_id": "wecom-yueshan",
                        "external_user_id": "wecom-" + user["username"],
                        "wecom_binding_status": "ACTIVE",
                        "status": user["status"],
                    }
                )
            return self.ok(request, {"identities": identities})

        if method == "GET" and path == "/api/v1/admin/sops":
            return self.ok(request, {"sops": self.sops})
        if method == "POST" and path == "/api/v1/admin/sops":
            sop = {"id": 1, "status": "DRAFT", **body}
            self.sops.append(sop)
            return self.ok(request, {"sop": sop}, 201)
        if method == "POST" and path == "/api/v1/admin/sops/1/submit":
            self.sops[0]["status"] = "IN_REVIEW"
            return self.ok(request, {"sop": self.sops[0]})
        if method == "POST" and path == "/api/v1/admin/sops/1/publish":
            self.sops[0]["status"] = "PUBLISHED"
            return self.ok(request, {"sop": self.sops[0]})

        if method == "GET" and path == "/api/v1/admin/experts":
            return self.ok(request, {"experts": self.experts})
        if method == "POST" and path == "/api/v1/admin/experts":
            expert = {"id": "expert-1", "status": "ACTIVE", **body}
            self.experts.append(expert)
            return self.ok(request, {"expert": expert}, 201)
        if method == "PATCH" and path == "/api/v1/admin/experts/expert-1":
            self.experts[0].update(body)
            return self.ok(request, {"expert": self.experts[0]})

        return httpx.Response(404, request=request, json={"detail": {"message": f"Unhandled {method} {path}"}})

    @staticmethod
    def ok(request: httpx.Request, payload: object, status_code: int = 200) -> httpx.Response:
        return httpx.Response(status_code, request=request, json=payload)


@pytest.mark.asyncio
async def test_uat_bootstrap_is_repeatable_and_uses_formal_apis() -> None:
    state = UATAPIState()
    transport = httpx.MockTransport(state.response)
    config = UATBootstrapConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
        employee_password="employee-secret-password",
    )

    async with httpx.AsyncClient(transport=transport, base_url=config.base_url) as client:
        first = await bootstrap_uat_master_data(config, client=client)
        second = await bootstrap_uat_master_data(config, client=client)

    assert first.venue_name == "悦山景区"
    assert second.user_count == 7
    assert len(state.users) == 7
    assert len(state.identities) == 7
    assert {channel for channel, _, _ in state.identities} == {"WECOM_SIMULATOR"}
    assert len(state.sops) == 1
    assert state.sops[0]["version"] == "2.1"
    assert state.sops[0]["status"] == "PUBLISHED"
    assert len(state.experts) == 1
    assert state.experts[0]["display_name"] == "张建国"
    assert state.experts[0]["authorization_status"] == "SIGNED"
    assert state.settings[("venue-yueshan", "organization_name")] == "悦山文旅集团"
    assert first.baseline_snapshot["channel"] == {
        "mode": "WECOM_SIMULATOR_ONLY",
        "identity_channel": "WECOM_SIMULATOR",
        "real_wecom_enabled": False,
    }
    assert len(first.baseline_snapshot["master_data"]["users"]) == 7
    assert len(first.baseline_snapshot["master_data"]["simulator_identities"]) == 7
    assert {
        rule["code"] for rule in first.baseline_snapshot["master_data"]["approval_rules"]
    } == {
        "SUSPEND_PASSENGER_VEHICLE",
        "ACTIVATE_BACKUP_VEHICLE",
        "SEND_CRITICAL_DISPATCH_ALERT",
    }
    assert set(first.baseline_snapshot["process_counts"].values()) == {0}
    assert ("POST", "/api/v1/channels/identities") in state.calls
    assert all(path.startswith("/api/v1/") for _, path in state.calls)


def test_uat_bootstrap_config_reads_password_files_without_exposing_values(tmp_path: Path) -> None:
    admin_file = tmp_path / "admin"
    employee_file = tmp_path / "employee"
    admin_file.write_text("\ufeffadmin-file-secret", encoding="utf-8")
    employee_file.write_text("\ufeffemployee-file-secret", encoding="utf-8")

    config = UATBootstrapConfig.from_environment(
        {
            "MEMORY_PALACE_UAT_BASE_URL": "http://app:8000",
            "ADMIN_USERNAME": "uat-admin",
            "ADMIN_PASSWORD_FILE": str(admin_file),
            "UAT_EMPLOYEE_PASSWORD_FILE": str(employee_file),
        }
    )

    assert config.admin_password == "admin-file-secret"
    assert config.employee_password == "employee-file-secret"
    assert "admin-file-secret" not in repr(config)
    assert "employee-file-secret" not in repr(config)


def test_uat_bootstrap_config_rejects_missing_credentials() -> None:
    with pytest.raises(UATBootstrapError, match="ADMIN_PASSWORD"):
        UATBootstrapConfig.from_environment(
            {
                "MEMORY_PALACE_UAT_BASE_URL": "http://app:8000",
                "ADMIN_USERNAME": "uat-admin",
            }
        )
