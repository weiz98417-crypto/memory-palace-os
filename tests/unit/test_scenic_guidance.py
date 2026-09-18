from src.memory_palace.scenic.guidance import build_next_actions, project_advice


def activity(activity_type, payload, created_at):
    return {
        "id": f"activity-{activity_type}-{created_at}",
        "activity_type": activity_type,
        "payload_json": payload,
        "created_at": created_at,
    }


def test_project_grounded_advice_allows_adopt_or_ignore():
    advice = project_advice(
        [
            activity(
                "ADVICE_READY",
                {
                    "advice_run_id": "run-1",
                    "state": "READY",
                    "evidence_status": "GROUNDED",
                    "advice": "继续停运并检查右后轮。",
                    "citations": [{"source_id": "1", "title": "复运 SOP", "version": "1.0"}],
                },
                1,
            )
        ]
    )

    assert advice["status"] == "READY"
    assert advice["evidence_status"] == "GROUNDED"
    assert advice["allowed_actions"] == ["ADOPT", "IGNORE"]
    assert advice["citations"][0]["source_id"] == "1"


def test_project_no_evidence_advice_cannot_be_adopted():
    advice = project_advice(
        [
            activity(
                "ADVICE_READY",
                {
                    "advice_run_id": "run-2",
                    "state": "READY",
                    "evidence_status": "NO_EVIDENCE",
                    "advice": "没有依据，需要人工判断。",
                    "citations": [],
                },
                2,
            )
        ]
    )

    assert advice["allowed_actions"] == ["IGNORE", "PROCEED_WITHOUT_WAITING"]
    assert "ADOPT" not in advice["allowed_actions"]


def test_project_pending_advice_can_only_proceed_without_waiting():
    advice = project_advice(
        [
            activity(
                "ADVICE_PENDING",
                {"advice_run_id": "run-3", "state": "PENDING"},
                3,
            )
        ]
    )

    assert advice["status"] == "PENDING"
    assert advice["allowed_actions"] == ["PROCEED_WITHOUT_WAITING"]


def test_build_next_actions_returns_backend_owned_action_codes():
    actions = build_next_actions(
        run={"id": "run-1"},
        alerts=[
            {
                "id": "alert-1",
                "status": "ACTIVE",
                "rule_code": "VEHICLE_12_RIGHT_REAR_WHEEL",
                "title": "12 号观光车右后轮异常",
            }
        ],
        incident=None,
        advice=None,
    )

    assert actions[0]["code"] == "CONVERT_ALERT"
    assert actions[0]["action"]["type"] == "COMMAND"
    assert actions[0]["action"]["kind"] == "CONVERT_ALERT"
    assert actions[0]["action"]["payload"]["alert_ids"] == ["alert-1"]


def test_project_superseded_and_failed_states_remain_explicit():
    superseded = project_advice(
        [
            activity(
                "ADVICE_PENDING",
                {"advice_run_id": "run-4", "state": "PENDING"},
                4,
            ),
            activity(
                "ADVICE_SUPERSEDED",
                {
                    "advice_run_id": "run-4",
                    "decision": "PROCEED_WITHOUT_WAITING",
                    "reason_code": "HUMAN_JUDGMENT",
                    "superseded_by": "user-1",
                },
                5,
            ),
        ]
    )
    failed = project_advice(
        [
            activity(
                "ADVICE_FAILED",
                {
                    "advice_run_id": "run-5",
                    "error_code": "MODEL_UNAVAILABLE",
                    "error_message": "模型不可用",
                },
                6,
            )
        ]
    )

    assert superseded["status"] == "SUPERSEDED"
    assert superseded["display_status"] == "已过期"
    assert superseded["allowed_actions"] == []
    assert failed["display_status"] == "未获得模型建议"
    assert failed["allowed_actions"] == ["PROCEED_WITHOUT_WAITING"]


def test_project_advice_groups_legacy_activities_by_trace_id():
    advice = project_advice(
        [
            {
                "id": "legacy-ready",
                "activity_type": "ADVICE_READY",
                "trace_id": "legacy-trace",
                "payload_json": {
                    "state": "READY",
                    "evidence_status": "GROUNDED",
                    "advice": "继续停运并检查。",
                    "citations": [{"source_id": "1", "title": "SOP", "version": "1.0"}],
                },
                "created_at": 7,
            },
            {
                "id": "legacy-decision",
                "activity_type": "ADVICE_DECIDED",
                "trace_id": "legacy-trace",
                "payload_json": {
                    "advice_run_id": "legacy-run",
                    "decision": "ADOPT",
                },
                "created_at": 8,
            },
        ]
    )

    assert advice["run_id"] == "legacy-run"
    assert advice["status"] == "READY"
    assert advice["decision"]["decision"] == "ADOPT"
