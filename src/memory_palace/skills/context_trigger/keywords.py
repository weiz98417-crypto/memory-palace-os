"""
关键词库定义 (Keywords Library)

本模块定义了 docx 中描述的两阶段事件触发系统的关键词数据类。
包含：TRIGGER_KEYWORDS（触发词）、EXCLUDE_KEYWORDS（排除词）、
以及按景区类型扩展的关键词。

设计原则：
- 关键词库与业务逻辑分离，便于运营人员调参而不改代码
- 支持景区类型组合加载
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class KeywordCategory:
    """关键词分类"""
    name: str
    keywords: List[str]
    description: str = ""


# ============================================================================
# 触发关键词库 (TRIGGER_KEYWORDS)
# ============================================================================

TRIGGER_KEYWORDS: Dict[str, KeywordCategory] = {
    "personnel_status": KeywordCategory(
        name="人员状态",
        keywords=[
            "晕", "晕倒", "昏迷", "受伤", "摔", "摔倒", "跌倒", "流血", "骨折",
            "发烧", "不舒服", "恶心", "过敏", "抽搐", "哭", "哭泣", "走散", "迷路", "找不到"
        ],
        description="人员身体状态异常"
    ),
    "emotion_conflict": KeywordCategory(
        name="情绪与冲突",
        keywords=[
            "投诉", "投诉了", "投诉说", "要投诉", "举报", "不满", "不高兴",
            "打架", "冲突", "吵", "吵架", "骂", "推", "争执", "闹", "大声"
        ],
        description="游客情绪激动或发生冲突"
    ),
    "urgency": KeywordCategory(
        name="紧迫情境词",
        keywords=[
            "突然", "紧急", "赶紧", "马上", "立刻", "快", "救", "帮忙",
            "出现了", "发生了", "怎么办", "怎么处理", "该怎么", "现在", "刚才"
        ],
        description="表达紧迫性或紧急求助"
    ),
    "facility_equipment": KeywordCategory(
        name="设施与设备",
        keywords=[
            "坏了", "故障", "漏水", "漏电", "停电", "跳闸", "停运", "卡住",
            "堵了", "堵塞", "挤", "爆满", "满了", "关闭了", "开不了"
        ],
        description="设施设备故障或运营异常"
    ),
    "weather_environment": KeywordCategory(
        name="天气与环境",
        keywords=[
            "下雨", "暴雨", "大雨", "台风", "大风", "打雷", "闪电",
            "暴晒", "太热", "太冷", "起雾", "能见度", "积水"
        ],
        description="天气条件异常"
    ),
    "external_relation": KeywordCategory(
        name="外部关系",
        keywords=[
            "媒体", "记者", "拍摄", "直播", "网红", "博主", "曝光",
            "警察", "救护车", "120", "消防", "110"
        ],
        description="涉及外部机构或人员"
    ),
}


# ============================================================================
# 排除关键词库 (EXCLUDE_KEYWORDS)
# ============================================================================

EXCLUDE_KEYWORDS: Dict[str, KeywordCategory] = {
    "resolved": KeywordCategory(
        name="已完成类",
        keywords=[
            "已解决", "处理完", "搞定了", "好了", "没事了", "解决了",
            "恢复了", "修好了", "撤了", "走了", "离开了"
        ],
        description="事件已处理完毕，无需跟进"
    ),
    "notification": KeywordCategory(
        name="通知计划类",
        keywords=[
            "通知", "提醒大家", "明天", "后天", "下周", "安排",
            "会议", "报告", "总结", "计划", "预计", "预约"
        ],
        description="通知类或未来计划类消息"
    ),
    "daily_checkin": KeywordCategory(
        name="日常打卡类",
        keywords=[
            "早安", "晚安", "收到", "好的", "嗯", "OK", "好", "知道了",
            "到岗", "下班", "交接", "签到"
        ],
        description="日常打卡确认类消息"
    ),
}


# ============================================================================
# 景区类型扩展关键词库
# ============================================================================

SCENIC_TYPE_KEYWORDS: Dict[str, Dict[str, KeywordCategory]] = {
    "ancient_town": {
        "古镇/古街型": KeywordCategory(
            name="古镇/古街型",
            keywords=[
                "走廊", "屋顶", "漏雨", "倒塌", "香客", "上香", "表演", "舞台",
                "夜市", "摊位", "占道", "火烛", "明火", "点燃"
            ],
            description="古镇特有场景"
        ),
    },
    "museum": {
        "博物馆/展馆型": KeywordCategory(
            name="博物馆/展馆型",
            keywords=[
                "展品", "文物", "触碰", "碰到了", "拍照", "闪光灯", "破损", "损坏",
                "安全门", "报警器", "触发了", "参观团", "讲解员"
            ],
            description="博物馆特有场景"
        ),
    },
    "theme_park": {
        "主题公园/游乐型": KeywordCategory(
            name="主题公园/游乐型",
            keywords=[
                "项目停了", "故障停机", "卡住了", "吓到了", "坐下不了",
                "安全带", "排队", "插队", "黄牛", "身高不够"
            ],
            description="主题公园特有场景"
        ),
    },
    "mountain": {
        "山岳/户外型": KeywordCategory(
            name="山岳/户外型",
            keywords=[
                "失联", "失踪", "没信号", "迷路了", "受困", "缆车", "索道",
                "落石", "山体", "滑坡", "蛇", "马蜂", "蚂蜂窝"
            ],
            description="山岳户外特有场景"
        ),
    },
}


# ============================================================================
# 关键词匹配器
# ============================================================================

import re


class KeywordMatcher:
    """
    关键词匹配器
    提供 Stage1 的极速关键词匹配功能（O(n) 字符串扫描）
    """

    # 中文 Unicode 范围（用于检测单字符是否构成多音节词的一部分）
    _CHINESE_RANGE = '\u4e00-\u9fff'

    def __init__(
        self,
        include_scenic_types: List[str] = None,
        enable_extended: bool = True
    ):
        """
        Args:
            include_scenic_types: 要加载的景区类型列表，如 ["ancient_town", "museum"]
            enable_extended: 是否启用扩展关键词
        """
        self._trigger_keywords: Set[str] = set()
        self._exclude_keywords: Set[str] = set()
        self._keyword_hit_info: Dict[str, str] = {}  # 命中的关键词 -> 分类名

        # 预编译的正则表达式缓存
        self._trigger_patterns: Dict[str, re.Pattern] = {}
        self._exclude_patterns: Dict[str, re.Pattern] = {}

        self._load_base_keywords()

        if enable_extended and include_scenic_types:
            self._load_extended_keywords(include_scenic_types)

    def _load_base_keywords(self):
        """加载基础关键词库"""
        for cat in TRIGGER_KEYWORDS.values():
            for kw in cat.keywords:
                self._trigger_keywords.add(kw)
                self._keyword_hit_info[kw] = cat.name
                self._trigger_patterns[kw] = self._build_pattern(kw)

        for cat in EXCLUDE_KEYWORDS.values():
            for kw in cat.keywords:
                self._exclude_keywords.add(kw)
                self._exclude_patterns[kw] = self._build_pattern(kw)

    def _load_extended_keywords(self, scenic_types: List[str]):
        """加载景区扩展关键词"""
        for scenic_type in scenic_types:
            if scenic_type in SCENIC_TYPE_KEYWORDS:
                for cat in SCENIC_TYPE_KEYWORDS[scenic_type].values():
                    for kw in cat.keywords:
                        self._trigger_keywords.add(kw)
                        self._keyword_hit_info[kw] = cat.name
                        self._trigger_patterns[kw] = self._build_pattern(kw)

    def _build_pattern(self, keyword: str) -> re.Pattern:
        """
        为关键词构建正则表达式

        多字符关键词（如"晕倒"）：精确子串匹配
        单字符关键词（如"晕"）：不能紧跟中文字符（避免"我有点晕"误触发）
        """
        if len(keyword) == 1:
            # 单字符：不能紧跟中文字符（避免匹配到多音节词中间的单字）
            # 例如"晕"不能匹配"晕倒"中的"晕"，但可以匹配句尾的"晕"
            return re.compile(
                rf'{re.escape(keyword)}(?![\u4e00-\u9fff])',
                re.UNICODE
            )
        else:
            # 多字符：精确子串匹配
            return re.compile(re.escape(keyword), re.UNICODE)

    def check_exclude(self, text: str) -> bool:
        """
        检查是否命中排除关键词
        命中则消息直接跳过，不进入 Stage2
        """
        for kw in self._exclude_keywords:
            pattern = self._exclude_patterns[kw]
            if pattern.search(text):
                return True
        return False

    def check_trigger(self, text: str) -> tuple[bool, List[str]]:
        """
        检查是否命中触发关键词

        Returns:
            (is_triggered, hit_keywords)
            is_triggered: 是否命中触发词
            hit_keywords: 命中的关键词列表
        """
        hit_keywords = []
        for kw in self._trigger_keywords:
            pattern = self._trigger_patterns[kw]
            if pattern.search(text):
                hit_keywords.append(kw)

        return len(hit_keywords) > 0, hit_keywords

    def get_hit_category(self, keyword: str) -> str:
        """获取关键词对应的分类名称"""
        return self._keyword_hit_info.get(keyword, "未知分类")

    def match(self, text: str) -> Dict[str, any]:
        """
        执行完整的 Stage1 匹配流程

        Returns:
            {
                "should_process": bool,      # 是否应该进入 Stage2
                "excluded": bool,            # 是否被排除
                "triggered": bool,          # 是否触发
                "hit_keywords": List[str],  # 命中的关键词
                "hit_categories": List[str] # 命中关键词的分类
            }
        """
        excluded = self.check_exclude(text)
        triggered, hit_keywords = self.check_trigger(text)

        hit_categories = [self.get_hit_category(kw) for kw in hit_keywords]

        return {
            "should_process": not excluded,
            "excluded": excluded,
            "triggered": triggered,
            "hit_keywords": hit_keywords,
            "hit_categories": list(set(hit_categories)),  # 去重
        }
