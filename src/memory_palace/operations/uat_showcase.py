"""Repeatable showcase-data seeding through formal HTTP APIs only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import quote

import httpx

from .uat_bootstrap import UATBootstrapError, _FormalAPI


SHOWCASE_SOURCE_PREFIX = "showcase:"
SUPPORTED_SHOWCASE_SECTIONS = frozenset({"experiences", "knowledge", "sops", "watcher"})


class UATShowcaseError(RuntimeError):
    """Raised when showcase data cannot be created without breaking UAT policy."""


@dataclass(frozen=True)
class UATShowcaseConfig:
    base_url: str
    admin_username: str
    admin_password: str = field(repr=False)
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls, environment: Optional[Mapping[str, str]] = None) -> "UATShowcaseConfig":
        values = os.environ if environment is None else environment
        base_url = values.get("MEMORY_PALACE_UAT_BASE_URL", "http://localhost:8000").strip()
        username = values.get("ADMIN_USERNAME", "").strip().lower()
        password = _read_secret(values, "ADMIN_PASSWORD")
        missing = [
            name
            for name, value in (
                ("MEMORY_PALACE_UAT_BASE_URL", base_url),
                ("ADMIN_USERNAME", username),
                ("ADMIN_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise UATShowcaseError(f"缺少 UAT 展示数据配置：{', '.join(missing)}")
        if len(password) < 8:
            raise UATShowcaseError("ADMIN_PASSWORD 长度不能少于 8 位")
        return cls(
            base_url=base_url.rstrip("/"),
            admin_username=username,
            admin_password=password,
        )


@dataclass(frozen=True)
class UATShowcaseResult:
    counts: dict[str, int]
    created: dict[str, int]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _KnowledgeSpec:
    key: str
    title: str
    category: str
    tags: tuple[str, ...]
    content: str

    @property
    def source_id(self) -> str:
        return f"{SHOWCASE_SOURCE_PREFIX}knowledge:{self.key}"

    def payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "source_type": "IMPORT",
            "source_id": self.source_id,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class _SOPSpec:
    key: str
    title: str
    category: str
    priority: int
    version: str
    desired_status: str
    content: str

    def payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "priority": self.priority,
            "version": self.version,
        }


@dataclass(frozen=True)
class _ExpertSpec:
    username: str
    display_name: str
    job_title: str
    department: str
    years_experience: int
    expertise: tuple[str, ...]

    def payload(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "display_name": self.display_name,
            "job_title": self.job_title,
            "department": self.department,
            "years_experience": self.years_experience,
            "expertise": list(self.expertise),
            "authorization_status": "SIGNED",
            "authorization_statement": (
                f"{self.display_name}授权将本人在{self.department}形成的专业经验用于组织内部访谈、审核、检索和员工辅助决策；"
                "系统必须保留来源和审核记录，不得超出授权范围对外传播。"
            ),
        }


@dataclass(frozen=True)
class _InterviewSpec:
    key: str
    expert_username: str
    title: str
    desired_interview_status: str
    desired_card_status: Optional[str]
    answers: tuple[str, str, str, str]

    @property
    def source_id(self) -> str:
        return f"{SHOWCASE_SOURCE_PREFIX}interview:{self.key}"


@dataclass(frozen=True)
class _EventSpec:
    key: str
    raw_text: str
    event_type: str
    severity: str
    reporter_username: str

    @property
    def source_id(self) -> str:
        return f"{SHOWCASE_SOURCE_PREFIX}event:{self.key}"


@dataclass(frozen=True)
class _TaskSpec:
    key: str
    event_key: str
    description: str
    assignee_username: str
    desired_status: str = "PENDING"
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class _WatcherPolicySpec:
    key: str
    name: str
    description: str
    schedule_cron: str
    check_types: tuple[str, ...]
    run_on_seed: bool


def _interview_answers(
    *,
    signals: str,
    actions: str,
    redlines: str,
    context: str,
) -> tuple[str, str, str, str]:
    return (
        f"我在现场首先看这些信号：{signals}。单看一个信号容易误判，至少要把时间、位置和连续变化一起记录。",
        f"正确顺序是：{actions}。先控制风险，再收集证据，最后才讨论恢复，顺序颠倒会让一线员工承担不必要的风险。",
        f"这些情况是红线：{redlines}。遇到红线必须停止当前操作并升级值班经理，不能用口头承诺代替审批和现场复核。",
        f"这条经验适用于{context}。例外是生命安全受到直接威胁时，应立即呼叫专业救援并先执行现场急救，不等待常规流程完成。",
    )


SHOWCASE_KNOWLEDGE = (
    _KnowledgeSpec(
        "rainfall-grades",
        "强降雨响应分级与现场口径",
        "应急处置",
        ("强降雨", "响应分级", "游客安全"),
        "气象预警达到黄色时，户外项目负责人每 15 分钟复核雨量、积水和雷电距离；达到橙色时暂停高空及水上项目并组织游客进入室内避险点；达到红色时启动闭园评估。所有升级动作必须记录时间、责任人和现场照片，恢复开放前由值班经理复核。",
    ),
    _KnowledgeSpec(
        "crowd-east-gate",
        "东门客流三级预警阈值",
        "客流管理",
        ("客流", "东门", "分流"),
        "东门闸机 10 分钟入园人数超过 800 人进入黄色预警，超过 1100 人进入橙色预警，超过 1400 人进入红色预警。黄色增开两条通道，橙色启用蛇形隔离栏并开放南门分流，红色暂停团队票核验并由现场总指挥统一放行节奏。",
    ),
    _KnowledgeSpec(
        "shuttle-brake",
        "观光车制动异常识别要点",
        "设备安全",
        ("观光车", "制动", "设备巡检"),
        "出现制动距离明显增长、踏板回弹迟滞、车轮单侧高温或车辆制动跑偏时，应立即停止载客并封存车辆。检修后必须完成三轮空载低速试车，每轮记录制动距离、跑偏情况和轮端温度，任何一项异常都不得恢复运营。",
    ),
    _KnowledgeSpec(
        "ropeway-power",
        "索道临时停电的乘客安抚与信息同步",
        "应急处置",
        ("索道", "停电", "信息同步"),
        "索道停电后 2 分钟内由站务员通过广播说明正在核查，避免承诺具体恢复时间；设备组确认故障范围，客服组每 5 分钟同步一次进展。超过 15 分钟时启动饮水和重点游客照护，超过 30 分钟时报请现场总指挥评估救援预案。",
    ),
    _KnowledgeSpec(
        "food-complaint",
        "疑似食品安全投诉证据保全清单",
        "服务质量",
        ("食品安全", "投诉", "证据保全"),
        "接到疑似食品安全投诉时，先安排游客就医并记录联系方式，不得争辩责任。现场应封存同批次食品、留样、进货凭证、销售记录和操作区监控，记录接触人员名单；达到两人及以上相似症状时立即升级值班经理和食品安全负责人。",
    ),
    _KnowledgeSpec(
        "lost-child",
        "儿童走失事件的最小信息集",
        "游客服务",
        ("儿童走失", "广播", "联动"),
        "受理儿童走失后应记录姓名或称呼、年龄、衣着、最后出现位置、同行人联系方式和一张近期照片。广播不得公开完整姓名和联系方式；调度中心同步门岗、巡逻、监控和游客服务点，并安排专人陪同家属保持单一联络窗口。",
    ),
    _KnowledgeSpec(
        "night-clearance",
        "夜间闭园清场双人复核点位",
        "安全管理",
        ("闭园", "清场", "双人复核"),
        "闭园清场按游客动线逆向执行，重点复核卫生间、母婴室、观景平台、设备夹层入口和临时施工围挡。每个区域由巡逻员与场馆员工双人签字，发现滞留游客或未关闭电源时立即中止该区域签退并通知值班经理。",
    ),
    _KnowledgeSpec(
        "weather-reopen",
        "恶劣天气后恢复开放检查表",
        "运营恢复",
        ("恢复开放", "天气", "检查表"),
        "恢复开放前需确认气象预警解除、主要道路无积水和落物、供电与广播正常、疏散通道畅通、户外设备完成点检。值班经理汇总设备、安全、客服三方签字后下达开放指令，单一部门口头确认不能替代联合复核。",
    ),
    _KnowledgeSpec(
        "escalation-matrix",
        "高风险事件升级矩阵",
        "应急处置",
        ("升级", "P0", "P1"),
        "涉及人员生命安全、群体性冲突、重大设备失控的事件定为 P0，必须立即通知现场总指挥并持续更新；可能造成运营中断或较大舆情的事件定为 P1，10 分钟内完成责任人指派；其他可控异常按 P2 至 P4 分级处置。等级只能由值班经理或更高权限下调。",
    ),
    _KnowledgeSpec(
        "handover",
        "跨班次事件交接的五项必填信息",
        "运营管理",
        ("交接班", "事件", "责任人"),
        "跨班次未结事件必须交接当前状态、已完成动作、未完成任务及截止时间、下一责任人、证据与沟通记录五项信息。接班人确认后方可完成交接，原责任人不能只以口头说明或聊天截图替代系统记录。",
    ),
    _KnowledgeSpec(
        "complaint-tone",
        "游客投诉首次响应话术原则",
        "服务质量",
        ("投诉", "首次响应", "服务"),
        "首次响应先复述游客核心诉求并确认事实，不抢先判定责任，不使用“规定就是这样”等封闭表达。能够现场解决的给出明确时间点；需要跨部门核查的说明下一次反馈时间和唯一联系人，并在系统中保留原始诉求与后续承诺。",
    ),
    _KnowledgeSpec(
        "temporary-construction",
        "临时施工区域开放前验收要求",
        "安全管理",
        ("施工", "围挡", "验收"),
        "临时施工结束后，工程负责人和运营负责人共同检查围挡稳定性、地面残留、临时用电、消防通道和游客导向。夜间施工还需复核照明与噪声影响；验收照片、施工单位签字和开放时间必须归档。",
    ),
    _KnowledgeSpec(
        "group-arrival",
        "大型团队集中入园协同规则",
        "客流管理",
        ("团队游客", "入园", "协同"),
        "单批 300 人以上团队应提前 30 分钟确认到达时间、车辆数量和带队联系人。票务预留核验通道，交通组划定落客区，客服安排集合点；如与散客高峰重叠，优先执行分批下车和错峰核验，不得占用消防车道。",
    ),
    _KnowledgeSpec(
        "radio-protocol",
        "高峰期对讲机沟通规范",
        "运营管理",
        ("对讲机", "沟通", "高峰期"),
        "高峰期对讲信息按“位置、事件、需求、回报时间”四段式表达，例如“东门外广场、排队外溢、需要两名秩序员、5 分钟后回报”。涉及游客隐私的信息改用系统私密记录，不在公共频道播报身份证号、电话或健康信息。",
    ),
    _KnowledgeSpec(
        "aed-response",
        "游客突发晕厥与 AED 联动要点",
        "医疗救援",
        ("AED", "晕厥", "急救"),
        "发现游客晕厥后先判断现场安全和意识呼吸，立即呼叫医疗点并指定一人取 AED、一人拨打急救电话、一人疏散围观。非专业人员按调度员和 AED 语音提示操作，持续记录关键时间点，并为急救车辆保持最短通道。",
    ),
)


SHOWCASE_SOPS = (
    _SOPSpec(
        "rain-evacuation",
        "强降雨游客疏散与恢复开放",
        "应急处置",
        0,
        "3.2",
        "PUBLISHED",
        "一、预警触发：气象橙色预警或现场 20 分钟雨量超过 30 毫米时，值班经理启动疏散。二、现场动作：停止户外项目，按东区、西区、山顶区三条路线引导游客进入室内避险点，安排专人照护老人、儿童和行动不便游客。三、信息同步：客服每 10 分钟发布一次进展，设备组和安全组分别回报点位状态。四、恢复开放：预警解除后完成道路、供电、广播、设备和疏散通道联合检查，三方签字后方可开放。",
    ),
    _SOPSpec(
        "east-gate-crowd",
        "东门高峰客流分级处置",
        "客流管理",
        1,
        "2.4",
        "PUBLISHED",
        "一、监测：每 5 分钟读取闸机入园量和排队长度。二、黄色预警：增开两条核验通道并补充秩序员。三、橙色预警：启用蛇形隔离栏，团队游客转南门分流。四、红色预警：暂停团队票核验，按现场总指挥口令分批放行。五、解除：连续 15 分钟低于黄色阈值后恢复常态，并记录峰值、持续时间和采取动作。",
    ),
    _SOPSpec(
        "ropeway-outage",
        "索道停运联动与替代接驳",
        "设备运营",
        0,
        "1.8",
        "PUBLISHED",
        "一、索道异常后立即停止进站并确认轿厢位置。二、站务员在 2 分钟内首次广播，设备组每 5 分钟回报排查进度。三、预计停运超过 20 分钟时，调度组启动山顶至游客中心替代接驳，客服在售票端和主要路口同步提示。四、恢复前完成空载试运行、制动检查和上下站通信测试，由设备主管和值班经理共同批准。",
    ),
    _SOPSpec(
        "food-safety",
        "食品安全投诉升级处置",
        "服务质量",
        0,
        "1.3",
        "IN_REVIEW",
        "一、客服先安排就医并登记原始诉求。二、餐饮负责人封存同批次食品、留样、进货凭证和监控。三、出现两名及以上相似症状时，事件升级为 P1，通知值班经理和食品安全负责人。四、对外信息只由指定负责人发布，现场员工不得自行判断责任。五、结案前补齐医疗、检测、沟通和整改证据。",
    ),
    _SOPSpec(
        "night-clearance",
        "夜间闭园清场核验",
        "安全管理",
        1,
        "2.0",
        "IN_REVIEW",
        "一、闭园后按游客动线逆向清场。二、卫生间、母婴室、观景平台、设备夹层入口和施工围挡必须双人复核。三、每个区域上传点位照片并由巡逻员、场馆员工共同签字。四、发现游客滞留、火源、未关闭电源或围挡破损时，中止区域签退并升级值班经理。五、所有区域完成后由总控统一锁定闭园状态。",
    ),
    _SOPSpec(
        "lost-property",
        "失物招领跨部门交接",
        "游客服务",
        3,
        "1.0",
        "DRAFT",
        "一、接收物品时记录时间、地点、发现人和物品特征。二、贵重物品由两人共同清点并封袋。三、跨班次交接时核对系统编号和封袋状态。四、领取人需描述关键特征并完成身份核验。五、超过保管期限的物品按财务与法务确认后的规则处置。",
    ),
    _SOPSpec(
        "group-lost-person",
        "团体游客走失应急协同",
        "游客服务",
        1,
        "1.1",
        "REJECTED",
        "一、记录走失人员信息和最后出现位置。二、通知门岗、巡逻、监控和服务点。三、安排专人与团队领队保持联系。四、广播时避免公开完整姓名和电话。五、找到人员后由服务点核验同行关系并关闭事件。",
    ),
)


SHOWCASE_EXPERTS = (
    _ExpertSpec("zhang-jianguo", "张建国", "资深设备主管", "设备保障部", 18, ("观光车检修", "雨后复运", "轮端异常判断")),
    _ExpertSpec("chen-yu", "陈雨", "设备检修员", "设备保障部", 12, ("索道机电", "制动系统", "预防性维护")),
    _ExpertSpec("wang-fang", "王芳", "当日值班经理", "运营管理部", 15, ("应急指挥", "跨部门协同", "服务升级")),
    _ExpertSpec("zhao-min", "赵敏", "知识负责人", "知识运营部", 10, ("SOP 治理", "复盘访谈", "经验审核")),
    _ExpertSpec("zhou-qi", "周琦", "早班运营员", "早班运营组", 9, ("客流组织", "门区调度", "游客沟通")),
)


SHOWCASE_INTERVIEWS = (
    _InterviewSpec(
        "vehicle-rain-reopen",
        "zhang-jianguo",
        "观光车雨后复运的三轮空载验证",
        "COMPLETED",
        "PUBLISHED",
        _interview_answers(
            signals="轮端金属摩擦声、制动跑偏、涉水痕迹、制动盘温差和防尘护板间隙",
            actions="先停车断电并设置警戒，再检查制动和轮端，完成维修后做三轮空载低速试车，最后由值班经理批准复运",
            redlines="护板持续摩擦、间隙小于 2 毫米、试车跑偏、轮端温度持续上升或检修证据不全",
            context="强降雨、积水或涉水之后的观光车恢复运营，以及检修后首次载客前的安全确认",
        ),
    ),
    _InterviewSpec(
        "ropeway-bearing-noise",
        "chen-yu",
        "索道驱动轮异响的停机判断",
        "COMPLETED",
        "PUBLISHED",
        _interview_answers(
            signals="异响频率随转速变化、轴承座温升、润滑脂颜色、振动值和驱动电流波动",
            actions="先降速确认声音来源，再无载停机检查轴承与联轴器，保存振动和温度曲线，检修后完成空载试运行",
            redlines="轴承温度超过设备限值、振动快速上升、润滑脂出现金属屑或驱动电流连续异常",
            context="索道启动、换季复运和高负荷运行期间出现的持续异响，不适用于瞬时外部碰撞声",
        ),
    ),
    _InterviewSpec(
        "east-gate-crowd-control",
        "zhou-qi",
        "东门排队外溢前的分流信号",
        "COMPLETED",
        "IN_REVIEW",
        _interview_answers(
            signals="闸机十分钟入园量、队尾位置、团队车辆到达量、安检平均耗时和游客逆行比例",
            actions="先增开核验通道，再布置蛇形栏和队尾提示，随后协调团队转南门，必要时按批次暂停放行",
            redlines="队列进入车行道、消防通道被占用、出现推挤倒地或现场指令不统一",
            context="节假日开园后两小时和大型团队集中到达时的门区客流组织",
        ),
    ),
    _InterviewSpec(
        "food-complaint-escalation",
        "wang-fang",
        "食品安全投诉从服务问题升级为事件的条件",
        "COMPLETED",
        "EXPERT_CONFIRMED",
        _interview_answers(
            signals="相似症状人数、就餐时间和摊位、同批次食品、就医情况以及投诉是否在短时间集中出现",
            actions="先协助就医并登记，再封存食品和凭证，安排单一联系人持续沟通，两人以上相似症状立即升级 P1",
            redlines="继续销售涉事批次、销毁留样、员工擅自承诺责任或遗漏游客联系方式",
            context="景区餐饮商户、临时售卖点和团餐服务出现的疑似食品安全投诉",
        ),
    ),
    _InterviewSpec(
        "experience-quality-review",
        "zhao-min",
        "专家经验卡发布前的证据质量判断",
        "COMPLETED",
        "DRAFT",
        _interview_answers(
            signals="经验是否包含具体观察信号、动作顺序、判断阈值、禁忌、例外和可回溯原话",
            actions="先核对来源访谈，再检查适用范围和授权，补齐反例后由专家确认，最后交给不同人员审核发布",
            redlines="没有原始来源、专家未授权、用绝对结论替代条件判断或审核人与专家为同一人",
            context="把复盘、访谈和优秀案例转化为组织内部可检索经验卡的全过程",
        ),
    ),
    _InterviewSpec(
        "night-clearance-signoff",
        "chen-yu",
        "夜间设备区清场的双人签退方法",
        "COMPLETED",
        "DRAFT",
        _interview_answers(
            signals="设备电源状态、检修门锁、施工围挡、遗留工具、异常气味和点位照片时间",
            actions="按清单逐点检查，由设备人员和巡逻员交叉复核，异常点位中止签退，处理完成后重新走完整检查",
            redlines="单人代签、照片与点位不符、临时用电未断、检修门未锁或围挡存在可进入缺口",
            context="闭园后的设备机房外围、临时施工区和非游客开放区域清场",
        ),
    ),
    _InterviewSpec(
        "peak-radio-protocol",
        "wang-fang",
        "高峰期对讲机信息压缩与复述",
        "IN_PROGRESS",
        None,
        _interview_answers(
            signals="频道占用时长、重复询问次数、位置描述是否明确以及请求是否包含回报时间",
            actions="用位置、事件、需求、回报时间四段式播报，接收方复述关键动作，复杂信息转系统记录",
            redlines="在公共频道播报游客隐私、多人同时下达冲突指令或没有明确责任人",
            context="节假日高峰、突发事件和跨区域协同时的对讲机沟通",
        ),
    ),
    _InterviewSpec(
        "group-arrival-staging",
        "zhou-qi",
        "大型团队集中到达的落客区预排",
        "INVITED",
        None,
        _interview_answers(
            signals="团队人数、车辆数量、到达时间偏差、散客峰值和落客区周转速度",
            actions="提前确认到达批次，预留核验通道和集合点，车辆分批进入，散客高峰时启用备用落客区",
            redlines="占用消防通道、游客在车行道集合、团队无人带队或车辆长时间停留",
            context="单批三百人以上团队和多支旅行团在半小时内集中抵达的场景",
        ),
    ),
)


SHOWCASE_EVENTS = (
    _EventSpec("east-gate-crowd", "东门外广场排队已越过第二隔离区，团队大巴仍在连续到达，需要立即分流并保护消防通道。", "客流拥堵", "P1", "zhou-qi"),
    _EventSpec("shuttle-brake", "2 号观光车雨后空载检查出现右后轮金属摩擦声和轻微制动跑偏，车辆已暂停使用。", "设备异常", "P1", "chen-yu"),
    _EventSpec("ropeway-power", "索道上站突发停电，轿厢已停止运行，站务正在安抚乘客并等待设备组确认故障范围。", "运营中断", "P0", "wang-fang"),
    _EventSpec("food-complaint", "餐饮街两组游客在相近时段反馈腹痛，其中一人已前往医务室，需封存同批次食品并核对销售记录。", "食品安全", "P1", "wang-fang"),
    _EventSpec("night-access", "闭园清场时发现西区设备夹层检修门未上锁，附近留有工具箱，现场已设置临时警戒。", "安全隐患", "P2", "chen-yu"),
    _EventSpec("lost-child", "游客服务中心接报一名 7 岁儿童在中心湖附近与家人走散，已取得衣着信息和近期照片。", "游客求助", "P1", "zhou-qi"),
)


SHOWCASE_TASKS = (
    _TaskSpec("crowd-barrier", "east-gate-crowd", "在东门外广场加设蛇形隔离栏并保持消防通道净宽", "zhou-qi", "RUNNING"),
    _TaskSpec("crowd-diversion", "east-gate-crowd", "通知团队车辆改从南门落客并每 10 分钟回报排队长度", "wang-fang"),
    _TaskSpec("vehicle-isolation", "shuttle-brake", "封存 2 号观光车钥匙并完成轮端、制动盘和防尘护板检查", "chen-yu", "RUNNING"),
    _TaskSpec("vehicle-temperature", "shuttle-brake", "补录三轮空载试车的轮端温度和制动距离", "zhang-jianguo", "FAILED"),
    _TaskSpec("ropeway-broadcast", "ropeway-power", "每 5 分钟向受影响乘客更新一次故障排查进展", "wang-fang"),
    _TaskSpec("ropeway-shuttle", "ropeway-power", "确认停运超过 20 分钟后启用山顶替代接驳车辆", "zhou-qi", "BLOCKED", ("ropeway-broadcast",)),
    _TaskSpec("food-evidence", "food-complaint", "封存涉事批次食品、留样、进货凭证和操作区监控", "wang-fang"),
    _TaskSpec("night-lock", "night-access", "核对设备夹层人员记录并完成检修门双人上锁复核", "chen-yu"),
    _TaskSpec("lost-child-camera", "lost-child", "调取中心湖四个方向最近 20 分钟监控并标记移动轨迹", "zhou-qi"),
    _TaskSpec("lost-child-gates", "lost-child", "向各门岗下发隐私脱敏后的衣着特征并确认接收", "wang-fang"),
)


SHOWCASE_WATCHER_POLICIES = (
    _WatcherPolicySpec("continuous-risk", "综合风险连续巡检", "每 5 分钟复核开放事件、未完成任务和 SOP 执行证据。", "*/5 * * * *", ("SLA", "TASK", "SOP"), True),
    _WatcherPolicySpec("critical-sla", "重点事件 SLA 预警", "持续检查 P0/P1 事件响应时长和责任人落实情况。", "*/10 * * * *", ("SLA",), True),
    _WatcherPolicySpec("stale-tasks", "未完成任务滞留检查", "识别长时间未启动、阻塞或失败后未重试的处置任务。", "*/15 * * * *", ("TASK",), True),
    _WatcherPolicySpec("sop-deviation", "SOP 执行偏差复核", "对照已发布 SOP 检查现场动作、审批和证据是否完整。", "0,30 * * * *", ("SOP",), False),
    _WatcherPolicySpec("night-safety", "夜间闭园安全巡查", "每天闭园后检查清场、设备断电、门禁和未结安全事件。", "0 22 * * *", ("SLA", "TASK", "SOP"), False),
)


def _read_secret(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if value:
        return value.strip()
    secret_path = values.get(f"{name}_FILE", "").strip()
    if not secret_path:
        return ""
    try:
        return Path(secret_path).read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise UATShowcaseError(f"无法读取 {name}_FILE 指向的密钥文件") from exc


def _normalize_sections(sections: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(section.strip().lower() for section in sections if section.strip()))
    unknown = sorted(set(normalized) - SUPPORTED_SHOWCASE_SECTIONS)
    if unknown:
        raise UATShowcaseError(f"未知展示数据分区：{', '.join(unknown)}")
    if not normalized:
        raise UATShowcaseError("至少选择一个展示数据分区")
    return normalized


async def _assert_simulator_only(api: _FormalAPI) -> None:
    baseline = await api.request("GET", "/api/v1/admin/uat-baseline")
    channel = baseline.get("channel") if isinstance(baseline, dict) else None
    if channel != {
        "mode": "WECOM_SIMULATOR_ONLY",
        "identity_channel": "WECOM_SIMULATOR",
        "real_wecom_enabled": False,
    }:
        raise UATShowcaseError("展示数据只允许写入企业内部系统接入环境，当前渠道策略不符合要求")


async def _seed_knowledge(api: _FormalAPI) -> tuple[int, int]:
    payload = await api.request("GET", "/api/v1/admin/knowledge?limit=500")
    existing = payload.get("knowledge") if isinstance(payload, dict) else None
    if not isinstance(existing, list):
        raise UATShowcaseError("组织记忆列表接口返回格式不正确")
    existing_source_ids = {item.get("source_id") for item in existing}
    missing = [spec for spec in SHOWCASE_KNOWLEDGE if spec.source_id not in existing_source_ids]
    if missing:
        await api.request(
            "POST",
            "/api/v1/admin/knowledge/import",
            body={"entries": [spec.payload() for spec in missing]},
        )
    return len(SHOWCASE_KNOWLEDGE), len(missing)


async def _advance_sop(api: _FormalAPI, sop: dict[str, Any], desired_status: str) -> dict[str, Any]:
    current_status = str(sop.get("status") or "DRAFT").upper()
    sop_id = sop["id"]
    if desired_status == "DRAFT" or current_status in {desired_status, "PUBLISHED"}:
        return sop
    if current_status in {"DRAFT", "REJECTED"} and desired_status in {
        "IN_REVIEW",
        "PUBLISHED",
        "REJECTED",
    }:
        submitted = await api.request("POST", f"/api/v1/admin/sops/{sop_id}/submit")
        sop = submitted["sop"]
        current_status = str(sop.get("status") or "").upper()
    if current_status == "IN_REVIEW" and desired_status == "PUBLISHED":
        published = await api.request(
            "POST",
            f"/api/v1/admin/sops/{sop_id}/publish",
            body={"comment": "展示数据集内容已复核，批准发布"},
        )
        return published["sop"]
    if current_status == "IN_REVIEW" and desired_status == "REJECTED":
        rejected = await api.request(
            "POST",
            f"/api/v1/admin/sops/{sop_id}/reject",
            body={"comment": "需补充跨部门联络时限和升级责任人后重新提交"},
        )
        return rejected["sop"]
    return sop


async def _seed_sops(api: _FormalAPI) -> tuple[int, int]:
    payload = await api.request("GET", "/api/v1/admin/sops")
    existing = payload.get("sops") if isinstance(payload, dict) else None
    if not isinstance(existing, list):
        raise UATShowcaseError("SOP 列表接口返回格式不正确")
    by_showcase_identity = {
        (
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("category") or ""),
            item.get("priority"),
        ): item
        for item in existing
    }
    created = 0
    for spec in SHOWCASE_SOPS:
        sop = by_showcase_identity.get((spec.title, spec.content, spec.category, spec.priority))
        if sop is None:
            response = await api.request("POST", "/api/v1/admin/sops", body=spec.payload())
            sop = response["sop"]
            created += 1
        await _advance_sop(api, sop, spec.desired_status)
    return len(SHOWCASE_SOPS), created


async def _seed_experts(api: _FormalAPI) -> tuple[dict[str, dict[str, Any]], int]:
    users_payload = await api.request("GET", "/api/v1/admin/users")
    expert_payload = await api.request("GET", "/api/v1/admin/experts")
    users = users_payload.get("users") if isinstance(users_payload, dict) else None
    experts = expert_payload.get("experts") if isinstance(expert_payload, dict) else None
    if not isinstance(users, list) or not isinstance(experts, list):
        raise UATShowcaseError("专家或用户列表接口返回格式不正确")
    users_by_username = {str(item.get("username") or "").lower(): item for item in users}
    experts_by_user_id = {item.get("user_id"): item for item in experts}
    result: dict[str, dict[str, Any]] = {}
    created = 0
    for spec in SHOWCASE_EXPERTS:
        user = users_by_username.get(spec.username)
        if user is None:
            raise UATShowcaseError(f"缺少展示专家对应的员工账号：{spec.username}")
        expert = experts_by_user_id.get(user.get("id"))
        if expert is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/experts",
                body=spec.payload(str(user["id"])),
            )
            expert = response["expert"]
            created += 1
        if expert.get("authorization_status") != "SIGNED" or expert.get("status") != "ACTIVE":
            raise UATShowcaseError(f"展示专家 {spec.display_name} 尚未处于已授权可用状态")
        result[spec.username] = expert
    return result, created


def _acting_path(path: str, user_id: str) -> str:
    return f"{path}?acting_user_id={quote(user_id, safe='')}"


async def _advance_card(
    api: _FormalAPI,
    card: dict[str, Any],
    *,
    desired_status: str,
    expert_user_id: str,
) -> dict[str, Any]:
    current = str(card.get("status") or "DRAFT").upper()
    card_id = card["id"]
    if current == desired_status or current in {"PUBLISHED", "DEPRECATED"}:
        return card
    if current == "DRAFT" and desired_status in {"EXPERT_CONFIRMED", "IN_REVIEW", "PUBLISHED"}:
        response = await api.request(
            "POST",
            _acting_path(f"/api/v1/assistant/experience/cards/{card_id}/confirm", expert_user_id),
        )
        card = response["card"]
        current = str(card.get("status") or "").upper()
    if current == "EXPERT_CONFIRMED" and desired_status in {"IN_REVIEW", "PUBLISHED"}:
        response = await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/submit")
        card = response["card"]
        current = str(card.get("status") or "").upper()
    if current == "IN_REVIEW" and desired_status == "PUBLISHED":
        response = await api.request(
            "POST",
            f"/api/v1/admin/experience-cards/{card_id}/publish",
            body={"comment": "来源、授权范围和适用条件已复核，批准发布"},
        )
        card = response["card"]
    return card


async def _advance_interview(
    api: _FormalAPI,
    interview: dict[str, Any],
    spec: _InterviewSpec,
    *,
    existing_card: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], Optional[dict[str, Any]], bool]:
    interview_id = str(interview["id"])
    expert_user_id = str(interview["expert_user_id"])
    desired = spec.desired_interview_status
    current = str(interview.get("status") or "INVITED").upper()
    if desired == "INVITED":
        return interview, existing_card, False
    if current == "INVITED":
        response = await api.request(
            "POST",
            _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/accept", expert_user_id),
        )
        interview = response["interview"]
        current = str(interview.get("status") or "").upper()

    target_answers = 1 if desired == "IN_PROGRESS" else len(spec.answers)
    answered = int(interview.get("current_question_index") or 0)
    while current != "COMPLETED" and answered < target_answers:
        response = await api.request(
            "POST",
            _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/answers", expert_user_id),
            body={"answer": spec.answers[answered]},
        )
        interview = response["interview"]
        answered = int(interview.get("current_question_index") or answered + 1)
        current = str(interview.get("status") or "").upper()

    card_created = False
    if desired == "COMPLETED" and existing_card is None:
        response = await api.request(
            "POST",
            _acting_path(f"/api/v1/assistant/experience/interviews/{interview_id}/complete", expert_user_id),
        )
        existing_card = response["card"]
        interview["status"] = "COMPLETED"
        card_created = not bool(response.get("idempotent_replay"))
    if existing_card is not None and spec.desired_card_status:
        existing_card = await _advance_card(
            api,
            existing_card,
            desired_status=spec.desired_card_status,
            expert_user_id=expert_user_id,
        )
    return interview, existing_card, card_created


async def _seed_experiences(api: _FormalAPI, venue_id: str) -> tuple[dict[str, int], dict[str, int]]:
    experts, experts_created = await _seed_experts(api)
    interview_payload = await api.request("GET", "/api/v1/admin/experience-interviews")
    card_payload = await api.request("GET", "/api/v1/admin/experience-cards")
    interviews = interview_payload.get("interviews") if isinstance(interview_payload, dict) else None
    cards = card_payload.get("experience_cards") if isinstance(card_payload, dict) else None
    if not isinstance(interviews, list) or not isinstance(cards, list):
        raise UATShowcaseError("访谈或经验卡列表接口返回格式不正确")
    interviews_by_source_id = {
        str(item.get("source_event_id") or ""): item
        for item in interviews
        if str(item.get("source_event_id") or "").startswith(f"{SHOWCASE_SOURCE_PREFIX}interview:")
    }
    cards_by_interview = {
        str((item.get("source") or {}).get("interview_id") or ""): item
        for item in cards
    }
    interviews_created = 0
    cards_created = 0
    for spec in SHOWCASE_INTERVIEWS:
        expert = experts[spec.expert_username]
        interview = interviews_by_source_id.get(spec.source_id)
        if interview is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/experience-interviews",
                body={
                    "expert_id": expert["id"],
                    "title": spec.title,
                    "source_event_id": spec.source_id,
                    "authorization_scopes": [{"scope_type": "VENUE", "scope_value": venue_id}],
                },
            )
            interview = response["interview"]
            interviews_created += 1
        card = cards_by_interview.get(str(interview["id"]))
        interview, card, was_created = await _advance_interview(
            api,
            interview,
            spec,
            existing_card=card,
        )
        cards_created += int(was_created)
        interviews_by_source_id[spec.source_id] = interview
        if card is not None:
            cards_by_interview[str(interview["id"])] = card
    counts = {
        "experts": len(SHOWCASE_EXPERTS),
        "interviews": len(SHOWCASE_INTERVIEWS),
        "experience_cards": sum(spec.desired_card_status is not None for spec in SHOWCASE_INTERVIEWS),
    }
    created = {
        "experts": experts_created,
        "interviews": interviews_created,
        "experience_cards": cards_created,
    }
    return counts, created


async def _showcase_users(api: _FormalAPI) -> dict[str, dict[str, Any]]:
    payload = await api.request("GET", "/api/v1/admin/users")
    users = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(users, list):
        raise UATShowcaseError("用户列表接口返回格式不正确")
    return {str(item.get("username") or "").lower(): item for item in users}


async def _advance_task(api: _FormalAPI, task: dict[str, Any], desired_status: str) -> dict[str, Any]:
    current = str(task.get("status") or "PENDING").upper()
    task_id = task["id"]
    if current == desired_status or current in {"DONE", "FAILED", "BLOCKED"}:
        return task
    if current == "PENDING" and desired_status in {"RUNNING", "FAILED"}:
        response = await api.request("POST", f"/api/v1/admin/tasks/{task_id}/start")
        task = response["task"]
        current = str(task.get("status") or "").upper()
    if current == "RUNNING" and desired_status == "FAILED":
        response = await api.request(
            "POST",
            f"/api/v1/admin/tasks/{task_id}/fail",
            body={"error": "现场温度记录缺少右后轮第二轮数据，需重新采集后提交"},
        )
        task = response["task"]
    return task


async def _seed_operational_targets(
    api: _FormalAPI,
) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, int]]:
    users = await _showcase_users(api)
    event_payload = await api.request("GET", "/api/v1/admin/events?limit=500")
    task_payload = await api.request("GET", "/api/v1/admin/tasks?limit=500")
    events = event_payload.get("events") if isinstance(event_payload, dict) else None
    tasks = task_payload.get("tasks") if isinstance(task_payload, dict) else None
    if not isinstance(events, list) or not isinstance(tasks, list):
        raise UATShowcaseError("事件或任务列表接口返回格式不正确")
    events_by_source_id = {
        str(item.get("push_id") or ""): item
        for item in events
        if str(item.get("push_id") or "").startswith(f"{SHOWCASE_SOURCE_PREFIX}event:")
    }
    event_by_key: dict[str, dict[str, Any]] = {}
    events_created = 0
    for spec in SHOWCASE_EVENTS:
        reporter = users.get(spec.reporter_username)
        if reporter is None:
            raise UATShowcaseError(f"缺少事件上报人账号：{spec.reporter_username}")
        event = events_by_source_id.get(spec.source_id)
        if event is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/events",
                body={
                    "raw_text": spec.raw_text,
                    "event_type": spec.event_type,
                    "severity": spec.severity,
                    "from_user": str(reporter["id"]),
                    "source_id": spec.source_id,
                },
            )
            event = {
                "event_id": response["event_id"],
                "raw_text": spec.raw_text,
                "event_type": spec.event_type,
                "severity": spec.severity,
                "from_user": str(reporter["id"]),
                "push_id": spec.source_id,
                "status": "OPEN",
            }
            events_created += 1
        event_by_key[spec.key] = event

    tasks_by_session_id = {
        str(item.get("session_id") or ""): item
        for item in tasks
        if str(item.get("session_id") or "").startswith("showcase-task-")
    }
    task_by_key: dict[str, dict[str, Any]] = {}
    tasks_created = 0
    for spec in SHOWCASE_TASKS:
        assignee = users.get(spec.assignee_username)
        if assignee is None:
            raise UATShowcaseError(f"缺少任务责任人账号：{spec.assignee_username}")
        task_session_id = f"showcase-task-{spec.key}"
        task = tasks_by_session_id.get(task_session_id)
        if task is None:
            dependency_ids = [str(task_by_key[key]["id"]) for key in spec.dependencies]
            response = await api.request(
                "POST",
                "/api/v1/admin/tasks",
                body={
                    "session_id": task_session_id,
                    "event_id": str(event_by_key[spec.event_key]["event_id"]),
                    "description": spec.description,
                    "dependencies": dependency_ids,
                    "assigned_user_id": str(assignee["id"]),
                    "assigned_agent": "TodoWrite",
                    "max_attempts": 3,
                },
            )
            task = response["task"]
            tasks_created += 1
        task = await _advance_task(api, task, spec.desired_status)
        task_by_key[spec.key] = task
    counts = {"events": len(SHOWCASE_EVENTS), "tasks": len(SHOWCASE_TASKS)}
    created = {"events": events_created, "tasks": tasks_created}
    return event_by_key, counts, created


async def _seed_watcher(api: _FormalAPI) -> tuple[dict[str, int], dict[str, int]]:
    event_by_key, counts, created = await _seed_operational_targets(api)
    users = await _showcase_users(api)
    policy_payload = await api.request("GET", "/api/v1/admin/watcher/policies")
    run_payload = await api.request("GET", "/api/v1/admin/watcher/runs?limit=500")
    finding_payload = await api.request("GET", "/api/v1/admin/watcher/findings?limit=500")
    policies = policy_payload.get("policies") if isinstance(policy_payload, dict) else None
    runs = run_payload.get("runs") if isinstance(run_payload, dict) else None
    findings_before = finding_payload.get("findings") if isinstance(finding_payload, dict) else None
    if not isinstance(policies, list) or not isinstance(runs, list) or not isinstance(findings_before, list):
        raise UATShowcaseError("鹰眼策略、运行或发现列表接口返回格式不正确")
    policies_by_key = {
        str((item.get("config") or {}).get("showcase_key") or ""): item
        for item in policies
        if isinstance(item.get("config"), dict)
    }
    policy_by_key: dict[str, dict[str, Any]] = {}
    policies_created = 0
    for spec in SHOWCASE_WATCHER_POLICIES:
        policy = policies_by_key.get(spec.key)
        if policy is None:
            response = await api.request(
                "POST",
                "/api/v1/admin/watcher/policies",
                body={
                    "name": spec.name,
                    "description": spec.description,
                    "schedule_cron": spec.schedule_cron,
                    "enabled": True,
                    "check_types": list(spec.check_types),
                    "config": {"max_targets": 80, "showcase_key": spec.key},
                },
            )
            policy = response["policy"]
            policies_created += 1
        elif not bool(policy.get("enabled")):
            response = await api.request(
                "PUT",
                f"/api/v1/admin/watcher/policies/{policy['id']}",
                body={"enabled": True},
            )
            policy = response["policy"]
        policy_by_key[spec.key] = policy

    runs_created = 0
    run_policy_ids = {str(item.get("policy_id") or "") for item in runs}
    for spec in SHOWCASE_WATCHER_POLICIES:
        policy_id = str(policy_by_key[spec.key]["id"])
        if spec.run_on_seed and policy_id not in run_policy_ids:
            await api.request("POST", f"/api/v1/admin/watcher/policies/{policy_id}/run")
            run_policy_ids.add(policy_id)
            runs_created += 1

    run_event_ids = {str(item.get("event_id") or "") for item in runs}
    for event_key in ("east-gate-crowd", "shuttle-brake"):
        event_id = str(event_by_key[event_key]["event_id"])
        if event_id not in run_event_ids:
            await api.request("POST", f"/api/v1/admin/events/{event_id}/watcher-check")
            run_event_ids.add(event_id)
            runs_created += 1

    refreshed_runs_payload = await api.request("GET", "/api/v1/admin/watcher/runs?limit=500")
    refreshed_findings_payload = await api.request("GET", "/api/v1/admin/watcher/findings?limit=500")
    refreshed_runs = refreshed_runs_payload.get("runs", [])
    findings = refreshed_findings_payload.get("findings", [])
    if not isinstance(refreshed_runs, list) or not isinstance(findings, list):
        raise UATShowcaseError("鹰眼运行结果列表接口返回格式不正确")

    seeded_policy_ids = {str(item["id"]) for item in policy_by_key.values()}
    seeded_event_ids = {str(event_by_key[key]["event_id"]) for key in ("east-gate-crowd", "shuttle-brake")}
    relevant_runs = [
        item for item in refreshed_runs
        if str(item.get("policy_id") or "") in seeded_policy_ids
        or str(item.get("event_id") or "") in seeded_event_ids
    ]
    relevant_run_ids = {str(item.get("id") or item.get("run_id") or "") for item in relevant_runs}
    showcase_findings = [
        item for item in findings
        if str(item.get("run_id") or "") in relevant_run_ids
    ]

    assignee = users.get("wang-fang")
    if assignee is None:
        raise UATShowcaseError("缺少鹰眼发现责任人账号：wang-fang")
    if not any(str(item.get("status") or "").upper() == "IN_PROGRESS" for item in showcase_findings):
        open_finding = next(
            (item for item in showcase_findings if str(item.get("status") or "OPEN").upper() == "OPEN"),
            None,
        )
        if open_finding is not None:
            await api.request(
                "PATCH",
                f"/api/v1/admin/watcher/findings/{open_finding['id']}",
                body={"assigned_to": str(assignee["id"]), "status": "IN_PROGRESS"},
            )
            open_finding["status"] = "IN_PROGRESS"
    if not any(str(item.get("status") or "").upper() == "CLOSED" for item in showcase_findings):
        open_finding = next(
            (item for item in showcase_findings if str(item.get("status") or "OPEN").upper() == "OPEN"),
            None,
        )
        if open_finding is not None:
            await api.request(
                "POST",
                f"/api/v1/admin/watcher/findings/{open_finding['id']}/close",
                body={"resolution": "已补齐责任人、现场照片和复核时间，值班经理确认闭环。"},
            )
            open_finding["status"] = "CLOSED"

    counts.update(
        {
            "watcher_policies": len(SHOWCASE_WATCHER_POLICIES),
            "watcher_runs": len(relevant_runs),
            "watcher_findings": len(showcase_findings),
        }
    )
    created.update(
        {
            "watcher_policies": policies_created,
            "watcher_runs": runs_created,
            "watcher_findings": max(0, len(findings) - len(findings_before)),
        }
    )
    return counts, created


async def seed_uat_showcase_data(
    config: UATShowcaseConfig,
    *,
    client: Optional[httpx.AsyncClient] = None,
    sections: Iterable[str] = SUPPORTED_SHOWCASE_SECTIONS,
) -> UATShowcaseResult:
    """Create a repeatable presentation dataset without direct database writes."""
    selected = _normalize_sections(sections)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        follow_redirects=True,
    )
    api = _FormalAPI(active_client)
    counts: dict[str, int] = {}
    created: dict[str, int] = {}
    try:
        principal = await api.login(config.admin_username, config.admin_password)
        await _assert_simulator_only(api)
        if "knowledge" in selected:
            counts["knowledge"], created["knowledge"] = await _seed_knowledge(api)
        if "sops" in selected:
            counts["sops"], created["sops"] = await _seed_sops(api)
        if "experiences" in selected:
            venue_id = str(principal.get("venue_id") or "")
            if not venue_id:
                raise UATShowcaseError("管理员身份缺少场地范围")
            experience_counts, experience_created = await _seed_experiences(api, venue_id)
            counts.update(experience_counts)
            created.update(experience_created)
        if "watcher" in selected:
            watcher_counts, watcher_created = await _seed_watcher(api)
            counts.update(watcher_counts)
            created.update(watcher_created)
        return UATShowcaseResult(counts=counts, created=created)
    except UATBootstrapError as exc:
        raise UATShowcaseError(str(exc)) from exc
    finally:
        if owns_client:
            await active_client.aclose()
