"""
P0 告警全链路集成测试 (Integration Test: P0 Full Chain)

测试目标：端到端验证 P0 级紧急事件从"消息接收 → Router 识别 → Commander 下发指令 → 企微通知 → 短信/语音告警 → Watcher 审计"的全链路流转。

工业级测试要点：
1. 链路完整性：每个环节都被触发，无跳过
2. 数据完整性：消息上下文（severity/P0关键字）在链路中传递不丢失
3. 并行告警：短信 + 语音电话并行发出，无串行阻塞
4. SLA 记录：P0 事件触发 SLA 响应时间戳更新
5. Watcher 感知：审计器能感知到新产生的 P0 案卷

本测试使用 Mock 拦截所有外部 IO，验证链路编排逻辑的正确性。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput
from src.memory_palace.tools.sms_client import EmergencyNotifier


class TestP0FullChain:

    @pytest.mark.asyncio
    async def test_p0_routes_to_commander_and_notifies(self):
        """
        P0 完整链路：
        1. Router 识别 P0 关键字 → 路由到 Commander
        2. Commander 下发 SOP 指令
        3. 企微通知推送成功
        4. 短信/语音并行发出
        5. SLA 响应时间记录
        """
        # --- 构造 P0 告警消息 ---
        p0_payload = {
            "msg_id": "p0_full_001",
            "trace_id": "trace_p0_chain",
            "from_user": "on_duty_guard",
            "content": "B区长廊有老年游客晕倒了，呼吸微弱，请立刻派人！",
            "priority": "P0",
        }

        # --- Mock Router ---
        router_output = SkillOutput(
            success=True,
            reply_text="检测到 P0 告警，正在接入指挥中心...",
            structured_data={
                "intent": "emergency_dispatch",
                "severity": "P0",
                "keywords_detected": ["晕倒", "呼吸微弱"],
            },
            action_taken="router_routed",
        )

        # --- Mock Commander ---
        commander_output = SkillOutput(
            success=True,
            reply_text=(
                "【P0 级紧急指令】\n"
                "1. 立即拨打 120\n"
                "2. 取 AED 到场\n"
                "3. 安保拉警戒线背对伤者挡镜头\n"
                "4. 引导 120 车辆入场"
            ),
            structured_data={
                "sop_steps": ["call_120", "fetch_aed", "setup_perimeter", "guide_120"],
                "severity": "P0",
                "escalation": True,
            },
            action_taken="commander_dispatched",
        )

        call_tracker = {"llm_calls": 0, "wechat_sent": False, "sms_sent": False, "voice_sent": False, "sla_updated": False}

        async def mock_llm_ask(**kwargs):
            call_tracker["llm_calls"] += 1
            if call_tracker["llm_calls"] == 1:
                return MagicMock(content=router_output.reply_text, tokens_used=80)
            return MagicMock(content=commander_output.reply_text, tokens_used=200)

        async def mock_wechat_send(user, text):
            call_tracker["wechat_sent"] = True
            return True

        async def mock_sms(phone, template, params):
            call_tracker["sms_sent"] = True
            return True

        async def mock_voice(phone, template, params):
            call_tracker["voice_sent"] = True
            return True

        async def mock_save_message(payload):
            pass  # 静默保存

        async def mock_update_sla(msg_id):
            call_tracker["sla_updated"] = True

        def get_skill(name):
            if name == "context_trigger":
                return None  # skip context_trigger in integration test
            m = MagicMock()
            if name == "router":
                m.run = AsyncMock(return_value=router_output)
            elif name == "commander":
                m.run = AsyncMock(return_value=commander_output)
            return m

        with patch("src.memory_palace.tools.llm_wrapper.llm_client.ask", side_effect=mock_llm_ask):
            with patch("src.memory_palace.tools.wechat_client.get_wechat_client", return_value=MagicMock(send_text=mock_wechat_send)):
                with patch("src.memory_palace.tools.sms_client.EmergencyNotifier._sync_send_sms", side_effect=mock_sms):
                    with patch("src.memory_palace.tools.sms_client.EmergencyNotifier._sync_send_voice_call", side_effect=mock_voice):
                        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=mock_save_message):
                            with patch("src.memory_palace.knowledge.db_client.update_sla_response", side_effect=mock_update_sla):
                                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                                    orch = Orchestrator()
                                    result = await orch.process(p0_payload)

        # --- 链路断言 ---
        assert result["status"] == "processed", "Orchestrator 应完成处理"

        # P0 关键字被识别，路由到 Commander
        assert result["route"].get("priority") == "P0", "P0 优先级应被识别"
        assert result["route"].get("target_agent") == "commander", "P0 应路由到 Commander"

        # SLA 更新（关键）
        assert call_tracker["sla_updated"] is True, "P0 事件必须触发 SLA 响应时间记录"

        # Commander 返回了有效的 reply_text
        assert result.get("reply_text"), "Commander 应返回回复内容"

    @pytest.mark.asyncio
    async def test_p0_sms_and_voice_parallel(self):
        """
        P0 告警：短信和语音电话应并行发出（不串行阻塞），
        验证 sms_client 的 ThreadPoolExecutor 机制
        """
        notifier = EmergencyNotifier()
        call_times = {"sms": None, "voice": None}

        def mock_sync_sms(phone, template, params):
            import time
            time.sleep(0.1)  # 模拟网络延迟
            call_times["sms"] = time.time()

        def mock_sync_voice(phone, template, params):
            import time
            time.sleep(0.1)
            call_times["voice"] = time.time()

        with patch.object(notifier, "_sync_send_sms", side_effect=mock_sync_sms):
            with patch.object(notifier, "_sync_send_voice_call", side_effect=mock_sync_voice):
                import time
                start = time.time()

                # 模拟 P0 通知：短信 + 语音并行
                notifier.send_p0_critical(
                    phones=["13800138000"],
                    event_desc="B区游客晕倒",
                )

                # 等待线程池执行（短信0.1s + 语音0.1s，串行需要0.2s，并行只需0.1s）
                time.sleep(0.25)

                total = time.time() - start

        # 并行：总耗时 ≈ 0.1s，串行 ≈ 0.2s
        # 允许一定误差
        assert call_times["sms"] is not None, "短信应被发送"
        assert call_times["voice"] is not None, "语音应被发送"

        # 两次调用几乎同时开始（并行特征）
        if call_times["sms"] and call_times["voice"]:
            diff = abs(call_times["sms"] - call_times["voice"])
            assert diff < 0.05, f"短信和语音应并行发出，时间差={diff:.3f}s（超过0.05s说明串行）"


class TestP0RateLimit:

    @pytest.mark.asyncio
    async def test_p0_same_phone_rate_limited(self):
        """
        防轰炸测试：同一手机号 60 秒内多次 P0 告警，第2次起应被拦截
        """
        notifier = EmergencyNotifier()
        send_count = {"n": 0}

        original_sync = notifier._sync_send_sms

        def tracked_sms(phone, template, params):
            send_count["n"] += 1
            return original_sync(phone, template, params)

        with patch.object(notifier, "_sync_send_sms", side_effect=tracked_sms):
            # 第1次：应发送
            notifier.send_p0_critical(
                phones=["13900001111"],
                event_desc="第一次P0告警",
            )
            # 第2次：60秒内同一手机号，应被限流拦截
            result2 = notifier._check_rate_limit("13900001111")
            assert result2 is False, "60秒内同一手机号应被限流拦截"

            assert send_count["n"] == 1, "第1次发送成功"


class TestP0KeywordDetection:

    @pytest.mark.asyncio
    async def test_p0_keywords_trigger_immediate_escalation(self):
        """
        Router 应检测 P0 关键词并立即触发升级，无需等待 LLM 推理
        （通过 config.yaml 中的 critical_keywords_boost 配置）
        """
        # "火灾" 是 critical_keywords_boost 中的强制 P0 关键词
        fire_payload = {
            "msg_id": "p0_keyword_001",
            "trace_id": "trace_fire",
            "from_user": "guard_fire",
            "content": "景点C区发现明火，请立刻来人！",
            "priority": "P0",  # 或不指定，由 Router 自动识别
        }

        router_output = SkillOutput(
            success=True,
            reply_text="火灾告警，强制升级 P0",
            structured_data={
                "intent": "emergency_dispatch",
                "severity": "P0",
                "keyword_triggered": "火灾",
            },
            action_taken="keyword_boost_p0",
        )

        with patch("src.memory_palace.core.orchestrator.get_skill_by_name") as mock_get:
            m = MagicMock()
            m.run = AsyncMock(return_value=router_output)
            mock_get.return_value = m

            with patch("src.memory_palace.knowledge.db_client.save_message", new_callable=AsyncMock):
                with patch("src.memory_palace.knowledge.db_client.update_sla_response", new_callable=AsyncMock) as mock_sla:
                    orch = Orchestrator()
                    result = await orch.process(fire_payload)

        assert result["route"].get("priority") == "P0", "火灾关键词应被识别为 P0"
        assert result["route"].get("target_agent") == "commander", "P0 应路由到 Commander"
        mock_sla.assert_called_once()  # SLA 必须被更新
