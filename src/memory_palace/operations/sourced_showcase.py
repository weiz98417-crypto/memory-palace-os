"""Sourced showcase data adapted from public guidance, seeded only through formal APIs."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

SOURCES: dict[str, dict[str, str]] = {
    "gb42101": {
        "title": "GB/T 42101-2022 旅游景区安全与客流疏导要求",
        "publisher": "国家标准",
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3432/site/attach/0/4b020844005848a69939a5001acb6113.pdf",
    },
    "safe-city": {
        "title": "国家安全发展示范城市建设指导手册",
        "publisher": "国务院安委会办公室",
        "url": "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202012/t20201207_374342.shtml",
    },
    "holiday-safety": {
        "title": "应急管理部假期安全提示",
        "publisher": "应急管理部",
        "url": "https://www.sz.gov.cn/cn/xxgk/zfxxgj/yjgl/yjgg_81606/content/post_12421696.html",
    },
    "large-crowd": {
        "title": "旅游景区超大客流安全风险防范与应对方案",
        "publisher": "重庆市九龙坡区人民政府",
        "url": "http://cqjlp.gov.cn/bmjz/qzfbm_97119/qwhlyw_97727/zwgk_97124/gkml/jczwgk/lyly/ggfw/lyaqyjczxx/202505/t20250516_14628624.html",
    },
    "weather-guide": {
        "title": "焉耆县旅游安全极端天气应急处置信息指南",
        "publisher": "焉耆县人民政府",
        "url": "https://www.xjyq.gov.cn/xjyqx/c118406/202507/3141420829c643bf9308011b4e5c70e0.shtml",
    },
    "ropeway-rule": {
        "title": "客运索道安全监督管理规定",
        "publisher": "国家市场监督管理总局",
        "url": "https://scjgj.cq.gov.cn/zfxxgk_225/fdzdgknr/lzyj/gz/gjbwgz/202012/W020211103719087450111.pdf",
    },
    "food-law": {
        "title": "中华人民共和国食品安全法（2021修正）",
        "publisher": "全国人民代表大会常务委员会",
        "url": "https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=90359",
    },
    "lost-person": {
        "title": "旅游景区游客走失联动处置公开案例",
        "publisher": "公安机关公开信息",
        "url": "https://gaj.wuhan.gov.cn/hjfc/jdxw/202608/t20260826_2838773.html",
    },
}

def watcher_policy_metadata(scenario: dict[str, str]) -> tuple[str, str]:
    return (
        f"安全巡检-{scenario['title']}",
        f"关注{scenario['signals']}；发现异常时{scenario['actions']}。",
    )


# Each scenario is a neutral adaptation of public guidance, not an interview quote.
SCENARIOS: tuple[dict[str, str], ...] = (
    {"key": "crowd-monitor", "title": "客流监测与分级预警", "type": "客流管理", "severity": "P1", "source": "gb42101", "signals": "入口分时人数、队尾位置、主通道密度、逆行人数", "actions": "实时监测，达到阈值后增开通道、分流并向值班经理回报", "redlines": "消防通道被占用、出现对冲拥挤、现场广播口径不一致", "context": "入口、核心游览区和索道站等人员密集区域", "task": "复核入口分时客流并回报阈值状态"},
    {"key": "one-way-flow", "title": "单向循环与流线隔离", "type": "客流管理", "severity": "P2", "source": "large-crowd", "signals": "双向游客对冲、瓶颈点停留时长、隔离设施缺口", "actions": "设置单向循环、加固临建设施并安排现场引导", "redlines": "游客逆行进入作业区、隔离栏倾倒、瓶颈点无人值守", "context": "节假日高峰和大型活动期间的游客流线组织", "task": "检查单向循环隔离设施和引导点位"},
    {"key": "fire-lane", "title": "消防通道占用处置", "type": "消防安全", "severity": "P1", "source": "safe-city", "signals": "通道宽度、临时摊位位置、车辆停放和巡查记录", "actions": "立即清理占道物、设置警戒和复测通道净宽", "redlines": "消防车通道净宽不足、疏散出口锁闭、巡查记录缺失", "context": "商业街、门区和临时集市等人员密集区域", "task": "复测消防通道净宽并清理违规占道物"},
    {"key": "capacity-check", "title": "大型活动容量与限流", "type": "客流管理", "severity": "P1", "source": "safe-city", "signals": "核定容量、预计人数、在园人数、入口放行速度", "actions": "启动分区护栏、限流和分批放行，必要时停止售票", "redlines": "超过核定容量继续放行、出口单点拥堵、应急广播失效", "context": "节庆演出、团队集中到达和大型群众性活动", "task": "核对活动核定容量和实时在园人数"},
    {"key": "rain-close", "title": "强降雨闭园评估", "type": "气象灾害", "severity": "P0", "source": "holiday-safety", "signals": "气象预警、雨量、积水点、雷电距离和地质灾害风险", "actions": "果断关闭受影响区域、疏散游客并保留现场证据", "redlines": "预警升级仍开放高风险项目、游客进入山洪沟谷、信息发布延迟", "context": "暴雨、山洪、滑坡和道路积水风险场景", "task": "复核气象预警并执行受影响区域闭园评估"},
    {"key": "flood-evacuate", "title": "山洪风险游客疏散", "type": "气象灾害", "severity": "P0", "source": "weather-guide", "signals": "上游降雨、河道水位、撤离路线、通信状态", "actions": "按预定路线撤离到安全区，清点人数并持续回报", "redlines": "逆行返回危险区、撤离路线被占、失联人员未登记", "context": "山地游线、河谷和临水区域", "task": "确认山洪撤离路线和人员清点结果"},
    {"key": "lightning-stop", "title": "雷电天气户外项目停运", "type": "气象灾害", "severity": "P0", "source": "weather-guide", "signals": "雷电预警、闪电距离、项目高度和游客暴露程度", "actions": "暂停户外高空及水上项目并引导游客进入避险点", "redlines": "雷电临近仍排队、避险点容量不足、停运指令未同步", "context": "索道、观景平台、水上游乐和高空项目", "task": "确认雷电预警下户外项目停运和避险点开放"},
    {"key": "strong-wind", "title": "大风天气高空设施管控", "type": "设备安全", "severity": "P1", "source": "weather-guide", "signals": "风速、阵风、设备风速联锁状态和乘客滞留点", "actions": "按设备限值降速或停运，疏散排队区并检查结构", "redlines": "超过设备风速限值继续运行、联锁报警被忽略", "context": "索道、大型游乐设施和高空观景设施", "task": "复核风速联锁和停运疏散执行情况"},
    {"key": "shuttle-brake", "title": "观光车制动异常停运", "type": "设备安全", "severity": "P1", "source": "safe-city", "signals": "制动距离、跑偏、踏板回弹、轮端温度", "actions": "停运封存车辆，检修后完成空载试车和审批", "redlines": "带故障载客、试车记录缺失、未审批复运", "context": "景区观光车和场内机动车辆", "task": "封存异常观光车并复核制动试车记录"},
    {"key": "ropeway-daily", "title": "索道每日试运行与例行检查", "type": "设备安全", "severity": "P1", "source": "ropeway-rule", "signals": "试运行结果、安全装置、通信、制动和风速", "actions": "每日投用前完成试运行和例行检查并确认记录", "redlines": "未试运行直接载客、安全装置未确认、记录代签", "context": "客运索道每日运营前检查", "task": "检查索道每日试运行和安全装置确认记录"},
    {"key": "ropeway-power", "title": "索道临时停电乘客安抚", "type": "设备安全", "severity": "P1", "source": "ropeway-rule", "signals": "停电范围、滞留人数、通信、备用电源和恢复时间", "actions": "广播说明、持续同步进展并启动替代接驳评估", "redlines": "承诺未确认的恢复时间、忽视重点游客、救援通道受阻", "context": "索道故障停运和临时停电", "task": "核对索道停电信息发布和滞留乘客状态"},
    {"key": "ride-trial", "title": "大型游乐设施投用前检查", "type": "设备安全", "severity": "P1", "source": "safe-city", "signals": "试运行、安全带锁止、制动、限位和异常响声", "actions": "逐项检查安全装置，确认后按操作规程开放", "redlines": "安全装置失效、超员运行、异常未排除", "context": "大型游乐设施每日投用前和异常维修后", "task": "复核大型游乐设施安全装置检查记录"},
    {"key": "food-complaint", "title": "食品安全投诉先处置", "type": "食品安全", "severity": "P1", "source": "food-law", "signals": "症状、就餐时间、同批次食品、就医和集中投诉", "actions": "协助就医、登记信息、封存证据并单一联系人沟通", "redlines": "继续销售涉事食品、销毁留样、擅自承诺责任", "context": "景区餐饮商户、临时售卖点和团餐服务", "task": "封存涉事批次食品和投诉证据材料"},
    {"key": "food-sample", "title": "餐饮留样与批次追溯", "type": "食品安全", "severity": "P2", "source": "food-law", "signals": "留样数量、保存时间、批次记录、进货凭证", "actions": "按制度留样并建立批次追溯台账", "redlines": "留样缺失、记录补写、批次信息不一致", "context": "景区餐饮和大型旅游团餐", "task": "抽查餐饮留样和批次追溯记录"},
    {"key": "mass-symptom", "title": "多人相似症状升级", "type": "食品安全", "severity": "P0", "source": "food-law", "signals": "短时间内相似症状人数、共同餐食、就医人数", "actions": "立即报告并联合医疗、卫生和运营处置", "redlines": "隐瞒人数、延迟报告、未保留共同餐食信息", "context": "群体性食品安全异常", "task": "核实相似症状人数并执行升级报告"},
    {"key": "lost-child", "title": "儿童走失最小信息集", "type": "游客服务", "severity": "P1", "source": "lost-person", "signals": "称呼、年龄、衣着、最后位置、同行人和照片", "actions": "启动门岗、巡逻、监控和广播联动，安排单一联络人", "redlines": "公开完整身份信息、无人陪同家属、门岗未同步", "context": "儿童走失和重点人群走失", "task": "登记走失儿童最小信息并同步门岗监控"},
    {"key": "lost-elder", "title": "老人走失联动处置", "type": "游客服务", "severity": "P1", "source": "lost-person", "signals": "健康状况、认知障碍、衣帽特征、最后出现位置", "actions": "确认特征后分组搜寻并同步路面巡查和视频追踪", "redlines": "未记录健康风险、搜索区域遗漏、信息重复传播", "context": "患有认知障碍或行动不便游客走失", "task": "确认走失老人特征并划分搜寻区域"},
    {"key": "night-clearance", "title": "夜间闭园清场双人复核", "type": "安全管理", "severity": "P2", "source": "safe-city", "signals": "滞留游客、未关电源、夹层入口和围挡", "actions": "按动线逆向清场，双人复核并签字", "redlines": "单人签退、夹层未检查、电源未关闭", "context": "闭园清场和夜间安全管理", "task": "复核闭园清场双人签退记录"},
    {"key": "construction", "title": "临时施工区域开放验收", "type": "安全管理", "severity": "P2", "source": "safe-city", "signals": "围挡稳定、地面残留、临时用电和消防通道", "actions": "联合验收后再开放并归档照片", "redlines": "围挡松动、通道占用、临时用电裸露", "context": "临时施工结束后的游客区域恢复开放", "task": "联合验收临时施工区域并归档证据"},
    {"key": "radio-protocol", "title": "高峰对讲机信息规范", "type": "运营管理", "severity": "P3", "source": "gb42101", "signals": "位置、事件、需求和回报时间是否完整", "actions": "按四段式沟通并保持统一指挥口径", "redlines": "公共频道传播隐私、关键指令无回报、多人同时占频", "context": "节假日高峰和突发事件现场通信", "task": "抽查高峰对讲沟通记录和回报时限"},
    {"key": "aed", "title": "游客突发晕厥与 AED 联动", "type": "医疗救援", "severity": "P0", "source": "holiday-safety", "signals": "意识呼吸、现场安全、AED 位置、急救通道", "actions": "呼叫医疗、取 AED、拨打急救并疏散围观", "redlines": "延误呼叫、AED 无人取用、急救通道阻塞", "context": "游客突发晕厥和心脏骤停风险", "task": "复核 AED 点位和急救联动流程"},
    {"key": "weather-reopen", "title": "恶劣天气后恢复开放", "type": "气象灾害", "severity": "P1", "source": "weather-guide", "signals": "预警解除、道路积水、落物、供电广播和设备点检", "actions": "完成多部门联合复核后下达开放指令", "redlines": "单部门口头确认、隐患未排除、恢复信息未同步", "context": "暴雨大风结束后的恢复运营", "task": "复核恢复开放联合检查签字"},
    {"key": "handover", "title": "跨班次事件交接", "type": "运营管理", "severity": "P3", "source": "gb42101", "signals": "当前状态、已完成动作、未完成任务、责任人和证据", "actions": "接班人确认后再完成交接并保留系统记录", "redlines": "口头交接、截止时间缺失、证据链断裂", "context": "跨班次未结事件和任务交接", "task": "检查跨班次未结事件交接字段"},
    {"key": "public-info", "title": "突发事件信息发布与舆情", "type": "应急沟通", "severity": "P2", "source": "holiday-safety", "signals": "事实状态、影响范围、恢复时间、唯一发言人", "actions": "统一口径、定时更新并保留发布时间线", "redlines": "未经确认承诺、信息前后矛盾、多个渠道口径不一", "context": "停运、闭园和游客滞留等公开沟通场景", "task": "核对突发事件信息发布口径和更新时间"},
)

EXPERT_USERNAMES = ("knowledge-owner", "wangfang", "chenyu", "liming")


def source_notes(source_key: str) -> str:
    source = SOURCES[source_key]
    return f"参考依据：{source['title']}｜{source['url']}"


def neutral_answers(scenario: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        f"建议观察：{scenario['signals']}。",
        f"处置顺序：{scenario['actions']}。",
        f"风险红线：{scenario['redlines']}。",
        f"适用范围：{scenario['context']}。实际处置以现场制度为准。",
    )


def knowledge_content(scenario: dict[str, str]) -> str:
    source = SOURCES[scenario["source"]]
    return (
        f"观察信号：{scenario['signals']}\n"
        f"处置顺序：{scenario['actions']}\n"
        f"风险红线：{scenario['redlines']}\n"
        f"适用场景：{scenario['context']}\n"
        f"参考依据：{source['title']}（{source['publisher']}）\n"
        f"原文链接：{source['url']}"
    )


def _legacy_knowledge_content(scenario: dict[str, str]) -> str:
    source = SOURCES[scenario["source"]]
    return (
        f"来源：{source['title']}（{source['publisher']}）\n"
        f"链接：{source['url']}\n"
        f"观察信号：{scenario['signals']}\n"
        f"处置顺序：{scenario['actions']}\n"
        f"风险红线：{scenario['redlines']}\n"
        f"适用场景：{scenario['context']}\n"
        "说明：本条目为公开资料中性改编，不代表真实个人访谈或现场事故记录。"
    )


def _acting_path(path: str, user_id: str) -> str:
    return f"{path}?acting_user_id={quote(user_id, safe='')}"


async def _list_all(api: Any, path: str, key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        suffix = f"&offset={offset}" if offset else ""
        payload = await api.request("GET", f"{path}?limit=500{suffix}")
        page = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(page, list):
            raise RuntimeError(f"sourced showcase list invalid: {key}")
        items.extend(page)
        if len(page) < 500:
            return items
        offset += len(page)


def find_existing_interview(
    *,
    title: str,
    scenario_title: str,
    event_id: str,
    expert_id: str,
    exact_index: dict[tuple[str, str, str], dict[str, Any]],
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Locate an existing interview for (event, expert), tolerating legacy titles.

    Older releases seeded a different interview title format, so an exact
    (event, title, expert) match misses rows created by an older build and a
    naive re-seed would create duplicate interviews and experience cards.
    Fall back to (event, expert) + scenario-title containment before creating.
    """
    interview = exact_index.get((event_id, title, expert_id))
    if interview is not None:
        return interview
    for candidate in grouped.get((event_id, expert_id), []):
        if scenario_title and scenario_title in str(candidate.get("title") or ""):
            return candidate
    return None


async def seed_sourced_showcase(api: Any) -> tuple[dict[str, int], dict[str, int]]:
    """Seed source-labelled showcase data without direct database writes."""
    users_payload = await api.request("GET", "/api/v1/admin/users")
    users = {str(item.get("username") or "").lower(): item for item in users_payload["users"]}
    missing_users = [username for username in EXPERT_USERNAMES if username not in users]
    if missing_users:
        raise RuntimeError(f"sourced showcase missing real users: {', '.join(missing_users)}")

    experts_payload = await _list_all(api, "/api/v1/admin/experts", "experts")
    experts_by_user = {str(item.get("user_id") or ""): item for item in experts_payload}
    experts: list[dict[str, Any]] = []
    experts_created = 0
    for index, username in enumerate(EXPERT_USERNAMES):
        user = users[username]
        expert = experts_by_user.get(str(user["id"]))
        if expert is None:
            source = SOURCES[tuple(SOURCES)[index % len(SOURCES)]]
            response = await api.request(
                "POST",
                "/api/v1/admin/experts",
                body={
                    "user_id": str(user["id"]),
                    "display_name": str(user.get("display_name") or user.get("username") or username),
                    "job_title": "知识运营专员",
                    "department": "知识运营部",
                    "years_experience": 5 + index,
                    "expertise": ["资料整理", "应急流程复核", "运营安全"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": (
                        f"本账号用于依据{source['title']}整理安全巡检资料；"
                        "不声称个人原创经验，不替代现场制度和专业判断。"
                    ),
                },
            )
            expert = response["expert"]
            experts_created += 1
        experts.append(expert)

    # Source knowledge records carry the public provenance into the existing memory UI.
    existing_knowledge = await _list_all(api, "/api/v1/admin/knowledge", "knowledge")
    knowledge_by_source = {
        str(item.get("source_id") or ""): item for item in existing_knowledge
    }
    knowledge_entries = []
    knowledge_updated = 0
    for scenario in SCENARIOS:
        source_id = f"public-source:{scenario['key']}"
        existing = knowledge_by_source.get(source_id)
        if existing:
            if existing.get("content") == _legacy_knowledge_content(scenario):
                await api.request(
                    "PUT",
                    f"/api/v1/admin/knowledge/{existing['id']}",
                    body={"content": knowledge_content(scenario)},
                )
                knowledge_updated += 1
            continue
        knowledge_entries.append(
            {
                "title": scenario['title'],
                "content": knowledge_content(scenario),
                "category": scenario["type"],
                "source_type": "IMPORT",
                "source_id": source_id,
                "tags": ["安全巡检", scenario["type"]],
            }
        )
    if knowledge_entries:
        await api.request("POST", "/api/v1/admin/knowledge/import", body={"entries": knowledge_entries})

    existing_events = await _list_all(api, "/api/v1/admin/events", "events")
    events_by_source = {
        str(item.get("push_id") or ""): item for item in existing_events
    }
    event_by_key: dict[str, dict[str, Any]] = {}
    events_created = 0
    reporters = ("liming", "chenyu")
    for index, scenario in enumerate(SCENARIOS):
        reporter = users[reporters[index % len(reporters)]]
        source_id = f"public-source:event:{scenario['key']}"
        event = events_by_source.get(source_id)
        if event is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/events",
                body={
                    "raw_text": f"{scenario['title']}：{scenario['context']}",
                    "event_type": scenario["type"],
                    "severity": scenario["severity"],
                    "from_user": str(reporter["id"]),
                    "source_id": source_id,
                },
            )
            event = {
                "event_id": response["event_id"],
                "push_id": source_id,
                "status": "OPEN",
            }
            events_created += 1
        event_by_key[scenario["key"]] = event

    existing_tasks = await _list_all(api, "/api/v1/admin/tasks", "tasks")
    tasks_by_session = {
        str(item.get("session_id") or ""): item for item in existing_tasks
    }
    tasks_created = 0
    for index, scenario in enumerate(SCENARIOS):
        session_id = f"public-source-task-{scenario['key']}"[:64]
        if session_id in tasks_by_session:
            continue
        assignee = users[EXPERT_USERNAMES[index % len(EXPERT_USERNAMES)]]
        await api.request(
            "POST",
            "/api/v1/admin/tasks",
            body={
                "session_id": session_id,
                "event_id": str(event_by_key[scenario["key"]]["event_id"]),
                "description": scenario["task"],
                "dependencies": [],
                "assigned_user_id": str(assignee["id"]),
                "assigned_agent": "TodoWrite",
                "max_attempts": 3,
            },
        )
        tasks_created += 1

    existing_interviews = await _list_all(
        api,
        "/api/v1/admin/experience-interviews",
        "interviews",
    )
    existing_cards = await _list_all(
        api,
        "/api/v1/admin/experience-cards",
        "experience_cards",
    )
    interviews_by_identity = {
        (
            str(item.get("source_event_id") or ""),
            str(item.get("title") or ""),
            str(item.get("expert_id") or ""),
        ): item
        for item in existing_interviews
    }
    interviews_by_event_expert: dict[tuple[str, str], list[dict]] = {}
    for item in existing_interviews:
        interviews_by_event_expert.setdefault(
            (
                str(item.get("source_event_id") or ""),
                str(item.get("expert_id") or ""),
            ),
            [],
        ).append(item)
    cards_by_interview = {
        str((item.get("source") or {}).get("interview_id") or ""): item
        for item in existing_cards
    }
    interviews_created = 0
    cards_created = 0
    failed_card_keys: list[str] = []
    for index, scenario in enumerate(SCENARIOS):
        expert = experts[index % len(experts)]
        event = event_by_key[scenario["key"]]
        suffix = "结构化V3" if scenario["key"] == "capacity-check" else "结构化"
        title = f"{scenario['title']}（{suffix}）"
        interview = find_existing_interview(
            title=title,
            scenario_title=scenario["title"],
            event_id=str(event["event_id"]),
            expert_id=str(expert["id"]),
            exact_index=interviews_by_identity,
            grouped=interviews_by_event_expert,
        )
        if interview is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/experience-interviews",
                body={
                    "expert_id": expert["id"],
                    "title": title,
                    "source_event_id": event["event_id"],
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": str(expert["venue_id"])}
                    ],
                },
            )
            interview = response["interview"]
            interviews_created += 1
        interview_id = str(interview["id"])
        expert_user_id = str(interview.get("expert_user_id") or expert["user_id"])
        if str(interview.get("status") or "").upper() == "INVITED":
            await api.request(
                "POST",
                _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/accept", expert_user_id),
            )
        answers = neutral_answers(scenario)
        current_answers = int(interview.get("current_question_index") or 0)
        complete_interview = True
        target_answers = len(answers) if complete_interview else min(1, len(answers))
        while current_answers < target_answers:
            body = {
                "answer": answers[current_answers],
                "source_excerpt": source_notes(scenario["source"])[:2000],
            }
            response = await api.request(
                "POST",
                _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/answers", expert_user_id),
                body=body,
            )
            interview = response["interview"]
            current_answers = int(interview.get("current_question_index") or current_answers + 1)
        if complete_interview and interview_id not in cards_by_interview:
            try:
                response = await api.request(
                    "POST",
                    _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/complete", expert_user_id),
                )
            except Exception:
                failed_card_keys.append(scenario["key"])
            else:
                card = response.get("card") or {}
                if card.get("id"):
                    cards_by_interview[interview_id] = card
                    if not response.get("idempotent_replay", False):
                        cards_created += 1

    existing_policies_payload = await api.request("GET", "/api/v1/admin/watcher/policies")
    existing_policies = existing_policies_payload.get("policies", [])
    policies_by_key = {
        str((item.get("config") or {}).get("sourced_key") or ""): item
        for item in existing_policies
        if isinstance(item.get("config"), dict)
    }
    policies_created = 0
    policies_updated = 0
    policies: list[dict[str, Any]] = []
    for index, scenario in enumerate(SCENARIOS[:15]):
        key = f"sourced:{scenario['key']}"
        policy = policies_by_key.get(key)
        policy_name, policy_description = watcher_policy_metadata(scenario)
        if policy is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/watcher/policies",
                body={
                    "name": policy_name,
                    "description": policy_description,
                    "schedule_cron": ("*/5 * * * *", "*/10 * * * *", "*/15 * * * *")[index % 3],
                    "enabled": True,
                    "check_types": [("SLA", "TASK", "SOP")[index % 3]],
                    "config": {
                        "max_targets": 80,
                        "sourced_key": key,
                        "data_origin": "public_source_adaptation",
                        "source_keys": [scenario["source"]],
                    },
                },
            )
            policy = response["policy"]
            policies_created += 1
        elif policy.get("name") != policy_name or policy.get("description") != policy_description:
            response = await api.request(
                "PUT",
                f"/api/v1/admin/watcher/policies/{policy['id']}",
                body={"name": policy_name, "description": policy_description},
            )
            policy = response["policy"]
            policies_updated += 1
        policies.append(policy)

    existing_runs_payload = await api.request("GET", "/api/v1/admin/watcher/runs?limit=500")
    existing_runs = existing_runs_payload.get("runs", [])
    run_policy_ids = {str(item.get("policy_id") or "") for item in existing_runs}
    runs_created = 0
    for policy in policies:
        if str(policy["id"]) not in run_policy_ids:
            await api.request("POST", f"/api/v1/admin/watcher/policies/{policy['id']}/run")
            runs_created += 1

    # Give each source-derived event one explicit Watcher check so the evidence is visible.
    existing_run_event_ids = {str(item.get("event_id") or "") for item in existing_runs}
    event_runs_created = 0
    for scenario in SCENARIOS[:15]:
        event_id = str(event_by_key[scenario["key"]]["event_id"])
        if event_id not in existing_run_event_ids:
            await api.request("POST", f"/api/v1/admin/events/{event_id}/watcher-check")
            event_runs_created += 1

    actual_cards = await _list_all(api, "/api/v1/admin/experience-cards", "experience_cards")
    actual_interviews = await _list_all(api, "/api/v1/admin/experience-interviews", "interviews")
    counts = {
        "sourced_experts": len(experts),
        "sourced_knowledge": len(SCENARIOS),
        "sourced_events": len(SCENARIOS),
        "sourced_tasks": len(SCENARIOS),
        "sourced_interviews": len(actual_interviews),
        "sourced_cards": len(actual_cards),
        "sourced_watcher_policies": len(policies),
        "sourced_watcher_runs": len(policies) + event_runs_created,
    }
    created = {
        "sourced_experts": experts_created,
        "sourced_knowledge": len(knowledge_entries),
        "sourced_knowledge_updated": knowledge_updated,
        "sourced_events": events_created,
        "sourced_tasks": tasks_created,
        "sourced_interviews": interviews_created,
        "sourced_cards": cards_created,
        "sourced_watcher_policies": policies_created,
        "sourced_watcher_policies_updated": policies_updated,
        "sourced_watcher_runs": runs_created + event_runs_created,
        "sourced_card_failures": len(failed_card_keys),
    }
    return counts, created
