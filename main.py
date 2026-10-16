"""
王者荣耀交友扩列 QQ 群 · 自动化运营引擎
================================================

AstrBot 插件 v2.0：把「王者荣耀开黑交友群」的运营动作**全自动**跑起来。

v1 → v2 的核心变化：从「手动执行」变为「自动运转」。

自动化能力（无需人工干预）：
1. 自动数据采集 —— 定时拉取群成员，自动算新增/退群/活跃，无需手工录入
2. 自动新人跟进 —— 入群后 30min/24h/72h 三级自动跟进，未发言自动引导
3. 自动冷场救场 —— 检测群内长时间无消息，自动发话题激活
4. 自动沉睡唤醒 —— 识别多日未发言成员，自动 @ 召回
5. 自动积分结算 —— 每日自动给活跃成员结算积分，无需用户发命令
6. 自动运营日报 —— 每天定时输出运营日报给管理员
7. 自动周榜发布 —— 每周定时发布积分排行榜
8. 自动关键词应答 —— 命中关键词自动回复常见问题
9. 自动 SOP 推送 —— 按计划时间点自动推送 16 套话术模板
10. 自动新人欢迎 —— 入群即自动欢迎并引导身份卡

作者：WorkBuddy
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone

# 北京时间（UTC+8）。服务器系统时区可能与北京时间不一致时，
# 所有 datetime.now() 统一替换为 _bj_now()，保证定时任务/日报周榜/
# 活跃时段判断/签到日期全部按北京时间走。
_BJ_TZ = timezone(timedelta(hours=8))


def _bj_now() -> datetime:
    """返回当前北京时间（不受服务器系统时区影响）。"""
    return datetime.now(_BJ_TZ).replace(tzinfo=None)
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_wzry_group_ops"

# ---------------------------------------------------------------------------
# 话术模板库
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, str]] = {
    "morning": {
        "name": "早安话题",
        "slot": "10:30",
        "content": (
            "【早安话题·{date}】\n"
            "各位召唤师早！今天想聊：{topic}\n"
            "群里的兄弟昨晚开黑战况如何？发张战绩图来晒晒 👇\n"
            "今晚20:00车队照常开黑，段位房已经建好，想上分的先冒个泡~"
        ),
    },
    "noon": {
        "name": "午后互动",
        "slot": "13:00",
        "content": (
            "【午后小互动】\n"
            "猜英雄环节来啦——描述如下：\n"
            "「一个战士，能吸血，大招是范围伤害，经常一打五」\n"
            "直接在群里回英雄名字就行，看看谁手速快 👇\n"
            "（推送时会自动追加一道正式题目，答对有奖，具体分值以题目为准）"
        ),
    },
    "team_call": {
        "name": "车队集结令",
        "slot": "17:30",
        "content": (
            "【今晚车队集结令·{date}】\n"
            "⏰ 时间：20:00 准时开黑\n"
            "🏠 分房：\n"
            "　· 青铜/白银房（娱乐局，带飞萌新）\n"
            "　· 黄金/铂金房（认真上分）\n"
            "　· 钻石以上房（大神互殴）\n"
            "想上车的按格式报名：昵称+主玩位置+段位\n"
            "例：小乔+中路+钻石\n"
            "报名满5人立刻开房，人不够就合并段位~"
        ),
    },
    "team_live": {
        "name": "开黑进行中",
        "slot": "20:00",
        "content": (
            "【车队开黑中·房间已开】\n"
            "🆔 房间号：{room}\n"
            "🎙️ 语音已开，进来先说话报位置\n"
            "还差 {need} 人，速度上车！连跪的兄弟进来躺赢~\n"
            "（不会玩的也欢迎，群里大神带飞）"
        ),
    },
    "mvp_show": {
        "name": "战绩秀场",
        "slot": "22:30",
        "content": (
            "【今日战绩秀场·{date}】\n"
            "来看看今天的群内MVP 👑\n"
            "MVP：{mvp}\n\n"
            "其他精彩战绩也发上来，群里评出「今日最秀」，\n"
            "每日活跃积分由系统自动结算，攒够可换皮肤碎片 🎁\n"
            "（明天同一时间继续，别潜水了！）"
        ),
    },
    "night": {
        "name": "夜宵话题+预告",
        "slot": "23:00",
        "content": (
            "【夜宵时间·明天见】\n"
            "今天开黑很过瘾！没上车的兄弟别急，明天继续 🎮\n\n"
            "📢 明日预告：\n"
            "· 20:00 车队照常\n"
            "· 新增「交友扩列专场」——想找CP/闺蜜/师傅的，明天别错过\n"
            "· 群内积分兑换表已更新，攒分换皮肤！\n\n"
            "晚安，明天见 🌙"
        ),
    },
    "welcome": {
        "name": "新人欢迎语",
        "slot": "",
        "content": (
            "🎉 欢迎 @{nickname} 加入王者开黑大家庭！\n"
            "先看置顶群规，然后发个身份卡让大家认识你 👇\n"
            "格式：昵称+段位+主玩位置+想找什么（队友/CP/师傅）\n"
            "例：小乔+钻石+中路+找上分队友\n"
            "今晚20:00有车队，新人优先带飞哦~"
        ),
    },
    "icebreak": {
        "name": "破冰引导",
        "slot": "",
        "content": (
            "@{nickname} 别潜水呀，冒个泡~\n"
            "随便说一句就行：你王者玩了多久了？\n"
            "群里都是自己人，没有大神架子，萌新也欢迎 😄"
        ),
    },
    "recruit": {
        "name": "拉新话术（转发用）",
        "slot": "",
        "content": (
            "【王者开黑群·招队友啦】\n"
            "群里每晚20:00准时开黑，青铜到王者都有房 🎮\n"
            "✅ 免费带飞，萌新也有人带\n"
            "✅ 找CP/闺蜜/师傅，扩列交友\n"
            "✅ 群内积分能换皮肤碎片\n"
            "一起上分的兄弟速度进：{group_no}"
        ),
    },
    "event": {
        "name": "活动招募",
        "slot": "",
        "content": (
            "【本周群内赛报名】\n"
            "🏆 5V5 内部对抗赛，本周六晚开打\n"
            "报名格式：昵称+段位+位置\n"
            "奖励：冠军队伍每人送皮肤/红包 🎁\n"
            "报名截止周五24点，速来！"
        ),
    },
    "friend_match": {
        "name": "交友扩列专场",
        "slot": "",
        "content": (
            "【交友扩列专场·{date}】\n"
            "想找队友/CP/闺蜜/师傅的，按格式发一条：\n"
            "「昵称+段位+想找XX+一句自我介绍」\n"
            "管理员会帮你@匹配的人~\n"
            "例：阿轲+星耀+找上分队友+能打野能辅助，脾气好"
        ),
    },
    "save_cold": {
        "name": "冷场救场",
        "slot": "",
        "content": (
            "群里安静得能听见打野刷野的声音了 😂\n"
            "来个投票：你们觉得当前版本最强打野是？\n"
            "A 铠  B 娜可露露  C 露娜  D 其他\n"
            "扣字母，A/B/C/D 都可以，选完扣 1~"
        ),
    },
    "points_rule": {
        "name": "积分规则说明",
        "slot": "",
        "content": (
            "【群积分规则】\n"
            "· 每日活跃自动加分：+5\n"
            "· 参与开黑车队：+10\n"
            "· 邀请新人进群并发言：+30\n"
            "· 内部赛获奖：+50\n"
            "积分可兑换：皮肤碎片 / 点券 / 红包 / 优先带飞\n"
            "积分每周日自动结算公示，月底清零兑换~"
        ),
    },
    "rules": {
        "name": "群规（置顶用）",
        "slot": "",
        "content": (
            "【王者荣耀开黑交友群 · 群规】\n"
            "欢迎各位召唤师！为保持良好氛围，请遵守以下规则：\n\n"
            "1️⃣ 文明交流，禁止辱骂、人身攻击、地域歧视\n"
            "2️⃣ 禁止发广告、外链、拉人进其他群\n"
            "3️⃣ 禁止讨论政治、色情、赌博等违规内容\n"
            "4️⃣ 开黑请勿恶意挂机、送人头、辱骂队友\n"
            "5️⃣ 交友扩列请尊重他人，禁止骚扰\n"
            "6️⃣ 交易/代练请自行辨别风险，群主不担保\n"
            "7️⃣ 违反者：首次警告，二次移出群聊\n\n"
            "💡 积极发言、参与开黑、邀请好友都有积分奖励，\n"
            "积分可兑换皮肤碎片/红包，详见置顶积分规则。\n\n"
            "一起上分，一起变强！🎮"
        ),
    },
    "warn": {
        "name": "违规警告（管理用）",
        "slot": "",
        "content": (
            "@{nickname} 提醒一下，本群禁止发广告/外链/拉人私群，\n"
            "第一次口头警告，再犯移出群聊。感谢配合 🙏\n"
            "（群规见置顶，大家都是来开黑交友的，别破坏氛围）"
        ),
    },
    "recall": {
        "name": "沉睡用户召回",
        "slot": "",
        "content": (
            "兄弟好久没见你冒泡了~\n"
            "群里最近搞了内部赛和皮肤抽奖，回来玩两把？\n"
            "今晚20:00车队还差人，就等你上车了 🎮"
        ),
    },
}

# 自动冷场救场时轮换使用的话题
RESCUE_TOPICS = [
    "群里安静得能听见打野刷野的声音了 😂\n来个投票：当前版本最强打野是？\nA 铠  B 娜可露露  C 露娜  D 其他\n扣个 1 选你心里的答案~",
    "有没有今晚想上分的？扣个 1，凑够5人开黑 🎮",
    "来聊个话题：你上分最怕遇到什么队友？\n（我先说：辅助不买眼的）",
    "猜英雄时间：一个法师，技能能位移，大招是范围控制，经常一打五。是谁？",
    "冒泡时间到~ 在线扣个「1」，看看今晚有多少人在线 👀",
    "问个问题：你们打王者用几指操作？\nA 二指  B 三指  C 四指  D 五指大佬",
]

# 自动新人跟进（按入群后的秒数分级）
FOLLOWUP_STAGES = [
    {
        "after": 1800,  # 30 分钟
        "key": "icebreak_soft",
        "content": (
            "新人还在吗？群里每晚20:00都有车队，青铜到王者都有房 🎮\n"
            "想开黑直接冒个泡，大神带飞，萌新也欢迎~"
        ),
    },
    {
        "after": 86400,  # 24 小时
        "key": "icebreak_day",
        "content": (
            "@{nickname} 昨天进群的兄弟还没冒过泡呀~\n"
            "发个身份卡让大家认识你：昵称+段位+主玩位置\n"
            "今晚20:00车队还缺人，新人优先带飞 🎁"
        ),
    },
    {
        "after": 259200,  # 72 小时
        "key": "icebreak_72h",
        "content": (
            "@{nickname} 送你一份新人福利~\n"
            "在群里冒个泡就能累计活跃积分，参与互动还有额外加分 🎁\n"
            "群里都是自己人，别害羞，一起上分！"
        ),
    },
]

# 自动关键词应答规则
DEFAULT_REPLY_RULES: list[dict[str, Any]] = [
    {
        "keywords": ["怎么进车队", "车队怎么", "怎么开黑", "开黑怎么"],
        "reply": "车队每晚20:00准时开黑 🎮\n按格式报名：昵称+位置+段位\n青铜到王者都有房，萌新也有人带，直接冒泡就行~",
        "enabled": True,
    },
    {
        "keywords": ["群规", "规矩", "规则"],
        "reply": "群规见置顶公告 📌\n核心：文明交流、禁止广告外链、禁止骚扰、开黑别挂机。\n一起上分，一起变强！",
        "enabled": True,
    },
    {
        "keywords": ["积分怎么", "积分规则", "怎么攒分", "积分换"],
        "reply": "【积分规则】\n· 每日活跃自动加分 +5\n· 参与开黑 +10\n· 邀请新人 +30\n· 内部赛获奖 +50\n积分可换皮肤碎片/红包，每周日自动结算公示 🎁",
        "enabled": True,
    },
    {
        "keywords": ["找cp", "找CP", "找对象", "找搭子", "扩列"],
        "reply": "交友扩列直接发一条 👇\n「昵称+段位+想找什么+一句自我介绍」\n例：阿轲+星耀+找上分队友+能打野能辅助\n管理员会帮你@匹配的人~",
        "enabled": True,
    },
]

# 默认每日 SOP 推送计划
DEFAULT_SCHEDULE: list[dict[str, Any]] = [
    {"time": "10:30", "template": "morning", "enabled": True},
    {"time": "13:00", "template": "noon", "enabled": True},
    {"time": "17:30", "template": "team_call", "enabled": True},
    {"time": "20:00", "template": "team_live", "enabled": True},
    {"time": "22:30", "template": "mvp_show", "enabled": True},
    {"time": "23:00", "template": "night", "enabled": True},
]

# 积分规则默认值（可在 WebUI「积分管理」页自由配置）
POINT_RULES = {
    "sign": 5,
    "team": 10,
    "invite": 30,
    "event": 50,
    "interact": 5,
    "captain": 20,
}

# 积分规则元信息：驱动 WebUI 渲染说明与输入范围
POINT_RULE_META = [
    {"key": "sign", "label": "每日签到", "desc": "群内发送 /签到，每人每天记一次", "min": 0, "max": 999},
    {"key": "interact", "label": "自动活跃结算", "desc": "引擎每天给当日发言过的成员自动加分", "min": 0, "max": 999},
    {"key": "team", "label": "参与开黑", "desc": "参与车队 / 开黑活动", "min": 0, "max": 999},
    {"key": "invite", "label": "邀请新人", "desc": "群内发送 /邀请，每记录一次加的分", "min": 0, "max": 999},
    {"key": "event", "label": "活动获奖", "desc": "内部赛 / 群活动获奖", "min": 0, "max": 999},
    {"key": "captain", "label": "担任队长", "desc": "组织车队并担任队长", "min": 0, "max": 999},
]

# 默认兑换表（可在 WebUI 增删改）
DEFAULT_REDEEM_ITEMS = [
    {"name": "皮肤碎片", "cost": 100, "desc": "攒够 100 分兑换 1 个皮肤碎片", "enabled": True},
    {"name": "点券红包", "cost": 300, "desc": "300 分兑换 10 元点券红包", "enabled": True},
    {"name": "优先带飞", "cost": 500, "desc": "500 分换一次高段位优先带飞", "enabled": True},
]

# 邀请自动播报默认话术（{inviter} 邀请人 / {invitee} 新人 / {points} 获得积分）
DEFAULT_INVITE_BROADCAST = "🎉 感谢 {inviter} 拉来了新同学 {invitee}，邀请积分 +{points}！"

# ---------------------------------------------------------------------------
# 答题活动题库（群内消息匹配判定，全自动发分）
# ---------------------------------------------------------------------------
# 每题结构：
#   q       题干
#   answers 可接受答案列表（大小写/空格/全角已做归一化，这里只填小写核心词）
#   hint    提示（答错时可选公布）
#   limit   本群每轮最多几人获奖（0 = 不限，默认 3 人，防刷）
#   reward  覆盖分值（留空则用 rules.quiz）
QUIZ_BANK: list[dict[str, Any]] = [
    {
        "id": "hero_1",
        "q": "一个法师，技能能位移，大招是范围控制，经常一打五。是谁？",
        "answers": ["诸葛亮", "孔明"],
        "hint": "三个字，人称「军师」。",
        "limit": 3,
    },
    {
        "id": "hero_2",
        "q": "一个战士，能吸血，大招是范围伤害，经常一打五。是谁？",
        "answers": ["曹操", "曹老板"],
        "hint": "魏国主公，开大吸血。",
        "limit": 3,
    },
    {
        "id": "hero_3",
        "q": "一个刺客，位移多、能隐身，玩家都喊他「猴子」。是谁？",
        "answers": ["孙悟空", "猴子", "猴哥"],
        "hint": "两根毛的棒子。",
        "limit": 3,
    },
    {
        "id": "hero_4",
        "q": "一个射手，一技能放地雷，大招全图支援。是谁？",
        "answers": ["后羿", "鲁班七号", "鲁班", "黄忠"],
        "hint": "答案不唯一，上面任一都算对。",
        "limit": 3,
    },
    {
        "id": "hero_5",
        "q": "峡谷里被称为「团战发动机」，大招能把一群人拉到一起的辅助是谁？",
        "answers": ["鬼谷子", "鲁班大师", "盾山", "孙膑"],
        "hint": "开团型辅助。",
        "limit": 3,
    },
    {
        "id": "game_1",
        "q": "王者荣耀里「红 BUFF」的别名叫什么？（两个字）",
        "answers": ["红爸爸", "红爸", "赤甲"],
        "hint": "打野都怕被反的那个。",
        "limit": 3,
    },
    {
        "id": "game_2",
        "q": "王者荣耀一局正常排位最多能 ban 几个英雄？",
        "answers": ["4", "四个", "4个"],
        "hint": "双方各 2 个。",
        "limit": 3,
    },
    {
        "id": "game_3",
        "q": "「五杀」英文在王者荣耀结算界面里叫什么？",
        "answers": ["penta kill", "pentakill"],
        "hint": "P 开头。",
        "limit": 3,
    },
    {
        "id": "group_1",
        "q": "本群的晚间车队几点开黑？",
        "answers": ["20:00", "20点", "八点", "20"],
        "hint": "晚上八点。",
        "limit": 5,
    },
    {
        "id": "group_2",
        "q": "在本群发什么命令可以查自己的积分？",
        "answers": ["/积分", "积分"],
        "hint": "斜杠开头。",
        "limit": 5,
    },
]

# 答题活动配置（默认值，可在 WebUI 配置）
DEFAULT_QUIZ_CONFIG: dict[str, Any] = {
    "quiz_enabled": True,        # 总开关
    "quiz_reward": 10,           # 答对得分（覆盖则按题上的 reward）
    "quiz_limit": 3,             # 每轮每群最多几人获奖（0=不限）
    "quiz_timeout": 600,         # 每题有效期（秒），超时自动公布答案并开下一题
    "quiz_ai_judge": True,       # 允许 AI 判定接近答案（仅在规则匹配失败时）
}

# 积分体系总配置（规则数值 + 邀请限制 + 兑换表 + 说明文案）
DEFAULT_POINTS_CONFIG = {
    "rules": dict(POINT_RULES),
    "sign_enabled": True,      # /签到 命令开关（关掉可与其他签到插件共存，避免重复回复）
    "invite_daily_limit": 3,   # 每人每天最多记录邀请次数；0 = 不限
    "quiz": dict(DEFAULT_QUIZ_CONFIG),  # 答题活动配置
    "auto_invite": True,       # 自动捕获入群事件并记录邀请人（无需成员手动 /邀请）
    "invite_broadcast": True,  # 邀请成功后在群内播报
    "invite_broadcast_text": DEFAULT_INVITE_BROADCAST,
    "count_on_approve": False,  # 管理员审批入群（拿不到邀请人）时是否也自动计分
    "default_inviter": "",      # 审批入群时默认归属的邀请人 QQ（留空=不自动归属）
    "redeem_items": [dict(x) for x in DEFAULT_REDEEM_ITEMS],
    "redeem_note": "积分每周日自动结算公示，月底清零兑换~",
}

# 群级功能开关（每个群独立控制，默认全开）
GROUP_FEATURES: dict[str, str] = {
    "collect": "数据采集",
    "followup": "新人跟进",
    "welcome": "入群欢迎",
    "schedule": "SOP 定时推送",
    "cold_rescue": "冷场救场",
    "wake": "沉睡唤醒",
    "reply": "关键词应答",
    "report": "日报 / 周榜",
}

DEFAULT_GROUP_FEATURES: dict[str, bool] = {k: True for k in GROUP_FEATURES}

# 默认欢迎词（可在 WebUI / 群命令中自定义，支持 {nickname} {group_no} 占位符）
DEFAULT_WELCOME_TEXT = (
    "🎉 欢迎 {nickname} 加入王者开黑大家庭！\n"
    "先看置顶群规，然后发个身份卡让大家认识你 👇\n"
    "格式：昵称+段位+主玩位置+想找什么（队友/CP/师傅）\n"
    "今晚 20:00 有车队，新人优先带飞哦~"
)

# 默认自动化配置
DEFAULT_AUTOMATION: dict[str, Any] = {
    # 自动数据采集
    "auto_collect": True,
    "collect_interval": 1800,          # 每 30 分钟采集一次群成员
    # 自动新人跟进
    "auto_followup": True,
    # 自动冷场救场
    "auto_cold_rescue": True,
    "cold_threshold": 7200,            # 2 小时无消息触发
    "cold_cooldown": 7200,             # 救场后 2 小时内不再救
    "active_hour_start": 9,            # 活跃时段起
    "active_hour_end": 23,             # 活跃时段止
    # 自动沉睡唤醒
    "auto_wake": True,
    "wake_days": 7,                    # 7 天未发言
    "wake_cooldown": 604800,           # 7 天内不重复唤醒
    "wake_max_per_round": 5,           # 每轮最多唤醒人数，防刷屏
    # 自动积分结算
    "auto_settle": True,
    # 自动运营日报
    "auto_daily_report": True,
    "report_time": "23:30",
    "report_admin_qq": "",             # 日报接收人 QQ（多个用逗号/空格分隔），留空则发群
    "report_to_group": False,          # 私聊管理员的同也会发一份到群
    # 自动周榜
    "auto_weekly_board": True,
    "weekly_board_weekday": 6,         # 0=周一 … 6=周日
    "weekly_board_time": "21:00",
    # 自动关键词应答
    "auto_reply": True,
    "reply_cooldown": 300,             # 同一关键词 5 分钟内不重复回复
    "reply_rules": DEFAULT_REPLY_RULES,
}

# ---------------------------------------------------------------------------
# AI 大模型接入配置
# ---------------------------------------------------------------------------
# 复用 AstrBot 已配置的模型（无需另填 API Key）。
# 任何一步失败都会优雅降级到固定模板，绝不让运营中断。

DEFAULT_AI: dict[str, Any] = {
    "ai_enabled": False,          # AI 总开关（默认关闭，避免意外消耗额度）
    "ai_provider_id": "",         # 留空 = 使用 AstrBot 当前默认对话模型
    "ai_timeout": 20,             # 单次调用超时（秒）
    "ai_temperature": 0.6,        # 生成温度；高温度更易产生幻觉，群聊场景建议 0.4~0.7
    # 各场景独立开关
    "ai_for_generate": True,      # WebUI 里 AI 生成 / 润色话术
    "ai_for_rescue": True,        # 冷场救场用 AI 生成话题
    "ai_for_reply": True,         # 关键词应答允许走 AI
    "ai_for_welcome": False,      # 入群欢迎语用 AI 生成（默认关，欢迎语要稳定）
    "ai_for_schedule": True,      # SOP 定时推送用 AI 实时生成（每次内容都不同）
    # 周榜设置
    "weekly_top_n": 5,            # 周榜展示人数（防消息过长）
    # 人设与约束
    "ai_persona": (
        "你是这个王者荣耀开黑交友 QQ 群里的群友，不是客服也不是机器人。"
        "说话自然、口语化、像真人打字：可以用短句，可以接梗，可以说「不知道」「我也在看」。"
        "群聊内容以王者荣耀和开黑为主，但别人聊别的也正常接话。"
    ),
    "ai_guard": (
        "硬性要求："
        "① 只输出要发到群里的正文，不要任何解释、前言、序号或 markdown 标记；"
        "② 长度控制在 40-150 字，适合手机一屏看完；"
        "③ 必须带一个明确的互动引导（提问 / 扣1 / 报名 / 投票）；"
        "④ 禁止出现任何虚假承诺、抽奖保证、充值返利、外部链接、二维码；"
        "⑤ 禁止承诺发积分、发礼物、发奖励（积分由系统自动结算，不由你分配）；"
        "⑥ 禁止编造具体数据、战绩、段位、版本数值，不确定就说让大家说说看；"
        "⑦ 禁止涉政、涉黄、辱骂、地域歧视；"
        "⑧ 不要每条都拐去打游戏/开黑，顺着对方说的话题接。"
    ),
}

# AI 场景提示词模板
AI_SCENES: dict[str, dict[str, str]] = {
    "morning": {
        "label": "早安话题",
        "brief": "写一条早安互动话题，唤醒群成员并制造发言，结尾引导今晚 20:00 开黑。",
    },
    "noon": {
        "label": "午后互动",
        "brief": "写一条午后轻互动（猜英雄 / 投票 / 小问答），让大家愿意接话，不要承诺发奖品或积分。",
    },
    "team_call": {
        "label": "车队集结令",
        "brief": "写一条今晚开黑车队召集令，说明时间 20:00、分房规则、报名格式。",
    },
    "team_live": {
        "label": "开黑进行中",
        "brief": "写一条开黑进行中的实时播报，催人上车、说明房间号和语音已开。",
    },
    "mvp_show": {
        "label": "战绩秀场",
        "brief": "写一条鼓励晒战绩的消息，营造荣誉感，引导大家发截图互动。",
    },
    "night": {
        "label": "夜宵话题+预告",
        "brief": "写一条睡前闲聊话题，并预告明天群里的活动，留下次日回访钩子。",
    },
    "welcome": {
        "label": "新人欢迎语",
        "brief": "写一条新人入群欢迎语，热情、@新人、引导发身份卡并告知今晚有车队。",
    },
    "icebreak": {
        "label": "破冰引导",
        "brief": "写一条引导新人和潜水成员开口说话的破冰消息，降低发言门槛。",
    },
    "recruit": {
        "label": "拉新话术",
        "brief": "写一条可直接转发到其它平台的招人话术，突出免费带飞、交友扩列、积分换奖励。",
    },
    "event": {
        "label": "活动招募",
        "brief": "写一条群内活动招募公告（内部赛 / 皮肤抽奖 / 组队挑战），说清参与方式和奖励。",
    },
    "friend_match": {
        "label": "交友扩列专场",
        "brief": "写一条交友扩列专场消息，引导大家发身份卡互相匹配队友 / CP / 师傅。",
    },
    "save_cold": {
        "label": "冷场救场",
        "brief": "群刚冷场了，写一条能立刻打破沉默的话题或小活动，让人愿意接话。",
    },
    "points_rule": {
        "label": "积分规则说明",
        "brief": "写一条积分规则说明，列出获取方式和兑换奖励，鼓励攒分。",
    },
    "rules": {
        "label": "群规（置顶用）",
        "brief": "写一份简洁的群规，覆盖文明交流、禁广告外链、禁骚扰、开黑不挂机。",
    },
    "warn": {
        "label": "违规警告",
        "brief": "写一条对违规成员的管理警告，语气严肃但不失体面，说明后果。",
    },
    "recall": {
        "label": "沉睡用户召回",
        "brief": "写一条召回长期潜水成员的消息，用福利和人情味把人拉回来。",
    },
}

TOPIC_POOL = [
    "你最近一次五杀是用哪个英雄？",
    "你上分最怕遇到什么队友？",
    "如果只能玩一个英雄，你选谁？",
    "你王者最高打到什么段位？",
    "你最喜欢哪个皮肤？为什么？",
    "你觉得哪个英雄最难上手？",
    "你打野喜欢红开还是蓝开？",
    "你最讨厌对面选哪个英雄？",
    "你打游戏会开语音吗？",
    "你第一个上手的英雄是谁？",
]


def _safe_format(content: str, ctx: dict[str, Any]) -> str:
    """容错渲染：只替换 ctx 中已知的 {key} 占位符。

    与 str.format 不同，遇到未知占位符（如用户文案里的裸 `{` 或 `{foo}`）时
    保留原样而不抛异常，避免整条消息退化成未渲染的模板。
    """
    if not content:
        return content
    import re as _re

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        return m.group(0)

    return _re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", _sub, content)


# ---------------------------------------------------------------------------
# 数据存储
# ---------------------------------------------------------------------------

class OpsStore:
    """插件数据存储：群绑定 / 积分 / 运营数据 / 活跃度 / 跟进 / 自动化配置。"""

    def __init__(self, plugin_name: str) -> None:
        base = Path(get_astrbot_data_path()) / "plugin_data" / plugin_name
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "data.json"
        self._lock = asyncio.Lock()
        self.data: dict[str, Any] = {
            "groups": {},        # group_id -> {umo, name, bound_at, enabled, features{}}
            "points": {},        # group_id -> {user_id: {name, points, invites, last_sign}}
            "stats": {},         # group_id -> [{date, total, new, leave, active, team}]
            "activity": {},      # group_id -> {last_msg_ts, last_rescue_ts, members{}, member_ids[], recent[]}
            "followups": {},     # group_id -> {user_id: {name, joined_ts, sent_stages[]}}
            "invite_log": {},    # group_id -> [{inviter, inviter_name, invitee, invitee_name,
                                 #               ts, date, source, points, counted, claimed}]
            "quiz_active": {},   # group_id -> {quiz_id, q, answers, reward, limit, winners[],
                                 #                  started_ts, expires_ts}
            "fired": {},         # 发送去重标记（持久化，防重启后重复推送）
            "discovered_groups": {},  # group_id -> 群名（收到过消息的群，供 WebUI 自助绑定）
            "schedule": DEFAULT_SCHEDULE,
            "automation": json.loads(json.dumps(DEFAULT_AUTOMATION)),
            "ai": json.loads(json.dumps(DEFAULT_AI)),
            "points_config": json.loads(json.dumps(DEFAULT_POINTS_CONFIG)),
            "config": {
                "auto_welcome": True,
                "schedule_enabled": True,
                "topic_pool": TOPIC_POOL,
                "welcome_text": DEFAULT_WELCOME_TEXT,
            },
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for key in self.data:
                    if key in loaded:
                        self.data[key] = loaded[key]
                # 补齐新增的自动化配置项
                auto = self.data.setdefault("automation", {})
                for k, v in DEFAULT_AUTOMATION.items():
                    auto.setdefault(k, json.loads(json.dumps(v)))
                # 补齐 AI 配置项（旧数据自动迁移）
                ai = self.data.setdefault("ai", {})
                if not isinstance(ai, dict):
                    ai = self.data["ai"] = {}
                for k, v in DEFAULT_AI.items():
                    ai.setdefault(k, json.loads(json.dumps(v)))
                # 补齐 config 新增项
                cfg = self.data.setdefault("config", {})
                cfg.setdefault("welcome_text", DEFAULT_WELCOME_TEXT)
                cfg.setdefault("topic_pool", TOPIC_POOL)
                # 补齐「已发现群」记录（WebUI 自助绑定用的兜底数据源）
                dg = self.data.setdefault("discovered_groups", {})
                if not isinstance(dg, dict):
                    self.data["discovered_groups"] = {}
                # 旧数据迁移：为已绑定群补齐 enabled / features
                for gid, g in (self.data.get("groups") or {}).items():
                    if not isinstance(g, dict):
                        self.data["groups"][gid] = {"umo": "", "name": "", "bound_at": ""}
                        g = self.data["groups"][gid]
                    g.setdefault("enabled", True)
                    feats = g.setdefault("features", {})
                    for k, v in DEFAULT_GROUP_FEATURES.items():
                        feats.setdefault(k, v)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] 读取数据失败，使用默认数据: {e}")

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 保存数据失败: {e}")

    async def asave(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self.save)

    # --- 群绑定 ---
    def bind_group(self, group_id: str, umo: str, name: str = "") -> None:
        old = self.data["groups"].get(group_id) or {}
        self.data["groups"][group_id] = {
            "umo": umo,
            "name": name or old.get("name", ""),
            "bound_at": old.get("bound_at") or _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
            "enabled": old.get("enabled", True),
            "features": old.get("features") or dict(DEFAULT_GROUP_FEATURES),
        }

    def unbind_group(self, group_id: str) -> bool:
        return self.data["groups"].pop(group_id, None) is not None

    def bound_groups(self) -> dict[str, Any]:
        """全部已绑定群（含被停用的）。"""
        return self.data["groups"]

    def group_enabled(self, group_id: str) -> bool:
        """该群是否被绑定且启用（总开关）。"""
        g = self.data["groups"].get(group_id)
        return bool(g) and bool(g.get("enabled", True))

    def group_feature(self, group_id: str, feature: str) -> bool:
        """该群是否启用某项功能（总开关 + 该功能开关）。"""
        if not self.group_enabled(group_id):
            return False
        feats = self.data["groups"].get(group_id, {}).get("features") or {}
        return bool(feats.get(feature, True))

    def set_group_enabled(self, group_id: str, enabled: bool) -> bool:
        g = self.data["groups"].get(group_id)
        if not g:
            return False
        g["enabled"] = bool(enabled)
        return True

    def set_group_feature(self, group_id: str, feature: str, enabled: bool) -> bool:
        g = self.data["groups"].get(group_id)
        if not g or feature not in GROUP_FEATURES:
            return False
        g.setdefault("features", {})[feature] = bool(enabled)
        return True

    def enabled_groups(self, feature: str = "") -> dict[str, Any]:
        """返回启用的群；若指定 feature，则同时要求该功能开启。"""
        out: dict[str, Any] = {}
        for gid, g in self.data["groups"].items():
            if not g.get("enabled", True):
                continue
            if feature and not (g.get("features") or {}).get(feature, True):
                continue
            out[gid] = g
        return out

    # --- 积分 ---
    def _group_points(self, group_id: str) -> dict[str, Any]:
        return self.data["points"].setdefault(group_id, {})

    def get_user(self, group_id: str, user_id: str, name: str = "") -> dict[str, Any]:
        users = self._group_points(group_id)
        u = users.setdefault(
            user_id, {"name": name, "points": 0, "invites": 0, "last_sign": ""}
        )
        if name:
            u["name"] = name
        return u

    def add_points(self, group_id: str, user_id: str, delta: int, name: str = "") -> int:
        u = self.get_user(group_id, user_id, name)
        u["points"] = max(0, int(u.get("points", 0)) + delta)
        return u["points"]

    def add_invite(self, group_id: str, user_id: str, name: str = "", points: int | None = None) -> int:
        u = self.get_user(group_id, user_id, name)
        today = _bj_now().strftime("%Y-%m-%d")
        if u.get("invite_date") != today:
            u["invite_date"] = today
            u["invite_today"] = 0
        u["invites"] = int(u.get("invites", 0)) + 1
        u["invite_today"] = int(u.get("invite_today", 0)) + 1
        gain = int(points) if points is not None else int(POINT_RULES["invite"])
        u["points"] = max(0, int(u.get("points", 0)) + gain)
        return u["invites"]

    def invite_quota_left(self, group_id: str, user_id: str, daily_limit: int) -> int:
        """今日剩余可记录邀请次数；daily_limit<=0 表示不限，返回一个大数。"""
        if not daily_limit or int(daily_limit) <= 0:
            return 10 ** 9
        u = self.get_user(group_id, user_id)
        today = _bj_now().strftime("%Y-%m-%d")
        if u.get("invite_date") != today:
            return int(daily_limit)
        return max(0, int(daily_limit) - int(u.get("invite_today", 0)))

    def revoke_invite(self, group_id: str, inviter: str, points: int = 0) -> None:
        """撤销一次邀请计分（撤回积分/邀请数）。"""
        if not inviter:
            return
        u = self.get_user(group_id, inviter)
        u["invites"] = max(0, int(u.get("invites", 0)) - 1)
        u["invite_today"] = max(0, int(u.get("invite_today", 0)) - 1)
        u["points"] = max(0, int(u.get("points", 0)) - int(points or 0))

    # --- 邀请记录明细 ---
    INVITE_LOG_CAP = 200

    def _invite_log_raw(self, group_id: str) -> list[dict[str, Any]]:
        logs = self.data.setdefault("invite_log", {})
        if not isinstance(logs, dict):
            logs = self.data["invite_log"] = {}
        arr = logs.get(group_id)
        if not isinstance(arr, list):
            arr = logs[group_id] = []
        return arr

    def add_invite_log(self, group_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        arr = self._invite_log_raw(group_id)
        arr.append(entry)
        if len(arr) > self.INVITE_LOG_CAP:
            del arr[: len(arr) - self.INVITE_LOG_CAP]
        return entry

    def invite_log_of(self, group_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """最近的邀请记录（新 → 旧）。"""
        arr = self._invite_log_raw(group_id)
        return list(reversed(arr))[: max(1, int(limit))]

    def find_invite_log(self, group_id: str, ts: Any) -> dict[str, Any] | None:
        for r in self._invite_log_raw(group_id):
            if str(r.get("ts")) == str(ts):
                return r
        return None

    def remove_invite_log(self, group_id: str, ts: Any) -> dict[str, Any] | None:
        arr = self._invite_log_raw(group_id)
        for i, r in enumerate(arr):
            if str(r.get("ts")) == str(ts):
                return arr.pop(i)
        return None

    def invitee_recorded(self, group_id: str, invitee: str) -> bool:
        """同一新人是否已有邀请记录（防重复计分）。"""
        if not invitee:
            return False
        return any(str(r.get("invitee")) == str(invitee) for r in self._invite_log_raw(group_id))

    def leaderboard(self, group_id: str, top: int = 10) -> list[dict[str, Any]]:
        users = self._group_points(group_id)
        rows = [
            {"user_id": uid, "name": v.get("name") or uid, "points": v.get("points", 0),
             "invites": v.get("invites", 0)}
            for uid, v in users.items()
        ]
        rows.sort(key=lambda x: (x["points"], x["invites"]), reverse=True)
        return rows[:top]

    # --- 运营数据 ---
    def add_stat(self, group_id: str, record: dict[str, Any]) -> None:
        arr = self.data["stats"].setdefault(group_id, [])
        # 自动采集不覆盖人工录入的成团次数
        if record.get("auto") and not record.get("team"):
            for r in arr:
                if r.get("date") == record.get("date") and r.get("team"):
                    record = dict(record)
                    record["team"] = r["team"]
                    break
        arr[:] = [r for r in arr if r.get("date") != record.get("date")]
        arr.append(record)
        arr.sort(key=lambda x: x.get("date", ""))

    def get_stats(self, group_id: str) -> list[dict[str, Any]]:
        return self.data["stats"].get(group_id, [])

    # --- 发送去重标记（持久化，避免插件重启后重复推送） ---
    def fired(self, key: str) -> str:
        return str((self.data.get("fired") or {}).get(key, ""))

    def mark_fired(self, key: str, value: str) -> None:
        fired = self.data.setdefault("fired", {})
        fired[key] = value
        # 只保留最近 200 条，避免无限增长
        if len(fired) > 200:
            for k in list(fired)[: len(fired) - 200]:
                fired.pop(k, None)

    # --- 活跃度 ---
    def activity_of(self, group_id: str) -> dict[str, Any]:
        return self.data["activity"].setdefault(
            group_id,
            {"last_msg_ts": 0.0, "last_rescue_ts": 0.0, "members": {},
             "member_ids": [], "recent": [], "rescue_idx": 0},
        )

    def record_message(self, group_id: str, user_id: str, name: str) -> None:
        act = self.activity_of(group_id)
        now = time.time()
        act["last_msg_ts"] = now
        m = act["members"].setdefault(
            user_id, {"name": name, "last_active_ts": 0.0, "msg_count": 0,
                      "joined_ts": 0.0, "last_wake_ts": 0.0}
        )
        m["name"] = name or m.get("name") or user_id
        m["last_active_ts"] = now
        m["msg_count"] = int(m.get("msg_count", 0)) + 1
        # 滑动窗口只保留最近 100 条
        recent = act.setdefault("recent", [])
        recent.append([now, user_id])
        if len(recent) > 100:
            del recent[:-100]

    # --- 新人跟进 ---
    def followup_of(self, group_id: str) -> dict[str, Any]:
        return self.data["followups"].setdefault(group_id, {})

    def register_newcomer(self, group_id: str, user_id: str, name: str) -> None:
        fu = self.followup_of(group_id)
        if user_id not in fu:
            fu[user_id] = {"name": name, "joined_ts": time.time(), "sent_stages": []}

    def clear_followup(self, group_id: str, user_id: str) -> None:
        self.followup_of(group_id).pop(user_id, None)


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------

class WzryGroupOpsPlugin(Star):
    """王者荣耀交友扩列 QQ 群 · 自动化运营引擎

    绑定群后全自动运转：数据采集 / 新人跟进 / 冷场救场 / 沉睡唤醒 /
    积分结算 / 日报周榜 / 关键词应答 / SOP 推送 / 入群欢迎。

    群内发送 /运营 帮助 查看全部命令。
    """

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.store = OpsStore(PLUGIN_NAME)
        self._engine_task: asyncio.Task | None = None
        self._last_fired: dict[str, str] = {}
        self._last_reply: dict[str, float] = {}   # 关键词应答冷却
        self._task_mark: dict[str, Any] = {}       # 各任务上次执行标记
        self._today_settled: str = ""              # 积分已结算的日期
        self._self_id_cache: str = ""              # 机器人自身 QQ 缓存

        self._register_web_apis()

    # ==================================================================
    # 生命周期
    # ==================================================================
    async def initialize(self) -> None:
        """插件启用时启动自动化引擎。"""
        if not self._engine_task or self._engine_task.done():
            self._engine_task = asyncio.create_task(self._engine_loop())
            groups = len(self.store.bound_groups())
            logger.info(f"[{PLUGIN_NAME}] 自动化引擎已启动，已绑定 {groups} 个群")

    async def terminate(self) -> None:
        """插件卸载/停用时停止引擎。"""
        if self._engine_task and not self._engine_task.done():
            self._engine_task.cancel()
            try:
                await self._engine_task
            except asyncio.CancelledError:
                pass
            self._engine_task = None
        logger.info(f"[{PLUGIN_NAME}] 自动化引擎已停止")

    # ==================================================================
    # 平台能力：直接调用 OneBot 接口（用于自动采集群数据）
    # ==================================================================
    def _get_bot(self):
        """获取 aiocqhttp 适配器的 bot 实例（用于主动调用群接口）。"""
        try:
            pf = self.context.get_platform("aiocqhttp")
            if pf is not None:
                bot = getattr(pf, "bot", None)
                if bot is not None and hasattr(bot, "call_action"):
                    return bot
        except Exception:  # noqa: BLE001
            pass
        # 兜底：遍历所有平台实例
        try:
            for p in self.context.platform_manager.platform_insts:
                bot = getattr(p, "bot", None)
                if bot is not None and hasattr(bot, "call_action"):
                    return bot
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _api(self, action: str, **params):
        """调用 OneBot API，失败返回 None。"""
        bot = self._get_bot()
        if bot is None:
            return None
        try:
            return await bot.call_action(action, **params)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] 调用 {action} 失败: {e}")
            return None

    def _bot_self_id(self) -> str:
        """获取机器人自身 QQ 号（用于排除自己）。"""
        if getattr(self, "_self_id_cache", ""):
            return self._self_id_cache
        bot = self._get_bot()
        for attr in ("self_id", "qq"):
            v = getattr(bot, attr, None)
            if v:
                self._self_id_cache = str(v)
                return self._self_id_cache
        return ""

    def _is_bot_uid(self, uid: str) -> bool:
        """判断该 QQ 号是否为机器人自己。"""
        sid = self._bot_self_id()
        return bool(sid) and str(uid) == sid

    def _mark_fired(self, kind: str, key: str) -> None:
        """持久化记录一次发送（防重启重复）。"""
        self.store.mark_fired(f"{kind}#{key}", _bj_now().strftime("%Y-%m-%d"))

    def _fired_today(self, kind: str, key: str) -> bool:
        """今天是否已发送过（读持久化标记）。"""
        today = _bj_now().strftime("%Y-%m-%d")
        return self.store.fired(f"{kind}#{key}") == today

    @staticmethod
    def _bound_ts(info: dict[str, Any]) -> float:
        """解析群绑定时间戳（用于无消息记录时的兜底计时）。"""
        raw = str(info.get("bound_at") or "")
        if not raw:
            return 0.0
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).timestamp()
            except ValueError:
                continue
        return 0.0

    async def _fetch_group_members(self, group_id: str) -> list[dict[str, Any]]:
        """拉取群成员列表。"""
        res = await self._api("get_group_member_list", group_id=int(group_id))
        if isinstance(res, list):
            return [x for x in res if isinstance(x, dict)]
        return []

    async def _fetch_group_info(self, group_id: str) -> dict[str, Any]:
        res = await self._api("get_group_info", group_id=int(group_id))
        return res if isinstance(res, dict) else {}

    async def _fetch_bot_groups(self) -> list[dict[str, Any]]:
        """拉取机器人（当前账号）已加入的所有群。

        对应 OneBot 的 `get_group_list`。返回 [{group_id, name, member_count}]。
        不同适配器/协议实现可能返回 None，此时返回空列表（由调用方兜底）。
        """
        res = await self._api("get_group_list")
        rows: list[dict[str, Any]] = []
        if isinstance(res, list):
            for g in res:
                if not isinstance(g, dict):
                    continue
                gid = g.get("group_id") or g.get("group")
                if gid is None:
                    continue
                rows.append({
                    "group_id": str(gid),
                    "name": str(g.get("group_name") or g.get("name") or gid),
                    "member_count": g.get("member_count") or g.get("max_member_count") or 0,
                })
        return rows

    @staticmethod
    def _make_umo(group_id: str) -> str:
        """构造 aiocqhttp 群会话标识（默认平台 ID 为 aiocqhttp）。"""
        return f"aiocqhttp:GroupMessage:{group_id}"

    def _platform_id(self) -> str:
        """取当前 aiocqhttp 平台实例的 ID（用户可能自定义，默认 aiocqhttp）。"""
        try:
            for p in self.context.platform_manager.platform_insts:
                if not hasattr(p, "bot"):
                    continue
                try:
                    meta = p.meta()
                except Exception:  # noqa: BLE001
                    continue
                name = str(getattr(meta, "name", "") or "")
                pid = str(getattr(meta, "id", "") or "")
                if name == "aiocqhttp" and pid:
                    return pid
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] 读取平台 ID 失败: {e}")
        return "aiocqhttp"

    def _umo_for_group(self, group_id: str) -> str:
        """为该群构造正确的 unified_msg_origin（用真实平台实例 ID）。"""
        return f"{self._platform_id()}:GroupMessage:{group_id}"

    @staticmethod
    def _platform_prefix(umo: str, fallback: str = "aiocqhttp") -> str:
        """从 unified_msg_origin 提取平台前缀（aiocqhttp / qq_official ...）。

        用于给管理员发私聊：和群消息走同一个平台，避免适配器不是
        aiocqhttp 时私聊永远发不出去。
        """
        prefix = (umo or "").split(":", 1)[0].strip()
        return prefix or fallback

    async def _send_to(self, umo: str, chain: Any, label: str = "") -> bool:
        """统一发送入口。

        ``context.send_message`` 的返回值语义是「是否找到匹配平台」，
        找不到平台时返回 False 并打 warning，不发异常——所以必须显式
        检查返回值，否则「平台掉线 / 适配器没连上」会被误判为发送成功。
        返回 True = 已交给平台；False = 平台不可达（消息未发出）。
        """
        try:
            ok = await self.context.send_message(umo, chain)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[{PLUGIN_NAME}] 发送失败{('[' + label + ']') if label else ''}: {e}"
            )
            return False
        if ok is False:
            logger.error(
                f"[{PLUGIN_NAME}] 平台不可达，消息未发出"
                f"{('[' + label + ']') if label else ''} umo={umo}"
                "（通常是 QQ 适配器掉线/未连接，重连后自动恢复）"
            )
            return False
        return True

    def _discovered_groups(self) -> dict[str, str]:
        """从历史消息/事件中发现的群（群号 -> 群名）。

        作为 `get_group_list` 不可用时的兜底数据源：
        机器人收到过消息的群会被记录在这里。
        """
        d = self.store.data.get("discovered_groups")
        if not isinstance(d, dict):
            d = self.store.data["discovered_groups"] = {}
        return d

    def _remember_group(self, group_id: str, name: str = "") -> None:
        """记录一个可见的群（收到消息时调用）。"""
        if not group_id:
            return
        d = self._discovered_groups()
        is_new = group_id not in d
        old = d.get(group_id) or ""
        name_changed = bool(name) and name != group_id and old != name
        if name_changed:
            d[group_id] = name
        elif is_new:
            d[group_id] = name or group_id

        if not (is_new or name_changed):
            return
        # 新群 / 名称变化 → 立即落盘，保证 WebUI「扫描群」马上能看到；
        # 纯名称刷新的高频更新走节流（10 分钟一次）。
        need_save = is_new or (time.time() - getattr(self, "_dg_save_ts", 0) > 600)
        if need_save:
            self._dg_save_ts = time.time()
            try:
                self.store.save()
            except Exception:  # noqa: BLE001
                pass

    # ==================================================================
    # 自动化引擎主循环
    # ==================================================================
    async def _engine_loop(self) -> None:
        """每 30 秒 tick 一次，按各任务周期调度。"""
        while True:
            try:
                await asyncio.sleep(30)
                auto = self.store.data.get("automation", {})
                now = time.time()

                # 1) SOP 定时推送（每 tick 检查）
                if self.store.data.get("config", {}).get("schedule_enabled", True):
                    await self._job_schedule()

                # 2) 自动数据采集
                if auto.get("auto_collect", True):
                    if now - self._task_mark.get("collect", 0) >= int(auto.get("collect_interval", 1800)):
                        self._task_mark["collect"] = now
                        await self._job_collect()

                # 3) 自动新人跟进（每 5 分钟）
                if auto.get("auto_followup", True):
                    if now - self._task_mark.get("followup", 0) >= 300:
                        self._task_mark["followup"] = now
                        await self._job_followup()

                # 4) 自动冷场救场（每 tick 检查，内部有冷却）
                if auto.get("auto_cold_rescue", True):
                    await self._job_cold_rescue()

                # 4.5) 答题活动超时结算
                await self._quiz_timeout_check()

                # 5) 自动沉睡唤醒（每 1 小时）
                if auto.get("auto_wake", True):
                    if now - self._task_mark.get("wake", 0) >= 3600:
                        self._task_mark["wake"] = now
                        await self._job_wake()

                # 6) 自动积分结算（每天一次）
                if auto.get("auto_settle", True):
                    await self._job_settle()

                # 7) 自动运营日报（每天定时）
                if auto.get("auto_daily_report", True):
                    await self._job_daily_report()

                # 8) 自动周榜（每周定时）
                if auto.get("auto_weekly_board", True):
                    await self._job_weekly_board()

            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"[{PLUGIN_NAME}] 自动化引擎异常: {e}")

    # ------------------------------------------------------------------
    # 任务 1：SOP 定时推送
    # ------------------------------------------------------------------
    async def _job_schedule(self) -> None:
        schedule = self.store.data.get("schedule", [])
        if not schedule:
            return
        # 只看启用了 SOP 推送的群
        if not self.store.enabled_groups("schedule"):
            return
        now = _bj_now()
        hhmm = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        for item in schedule:
            if not item.get("enabled", True) or item.get("time") != hhmm:
                continue
            key = f"{hhmm}#{item.get('template')}"
            if self._last_fired.get(key) == today:
                continue
            self._last_fired[key] = today
            self._mark_fired("sched", key)
            await self._broadcast_template(item.get("template", ""))

    # ------------------------------------------------------------------
    # 任务 2：自动数据采集（核心自动化）
    # ------------------------------------------------------------------
    async def _job_collect(self) -> None:
        """定时拉取群成员，自动算出新增/退群/活跃，写入运营数据。"""
        groups = self.store.enabled_groups("collect")
        if not groups:
            return
        today = _bj_now().strftime("%Y-%m-%d")

        for gid in groups:
            try:
                members = await self._fetch_group_members(gid)
                if not members:
                    continue
                cur_ids = [
                    str(m.get("user_id")) for m in members
                    if m.get("user_id") and not self._is_bot_uid(str(m.get("user_id")))
                ]
                cur_set = set(cur_ids)
                act = self.store.activity_of(gid)
                prev_ids = act.get("member_ids") or []
                prev_set = set(prev_ids)

                new_cnt = len(cur_set - prev_set) if prev_set else 0
                leave_cnt = len(prev_set - cur_set) if prev_set else 0

                # 更新成员名称与档案
                for m in members:
                    uid = str(m.get("user_id", ""))
                    if not uid:
                        continue
                    if self._is_bot_uid(uid):
                        continue
                    nm = m.get("card") or m.get("nickname") or uid
                    rec = act["members"].setdefault(
                        uid, {"name": nm, "last_active_ts": 0.0, "msg_count": 0,
                              "joined_ts": 0.0, "last_wake_ts": 0.0}
                    )
                    rec["name"] = nm
                    # 新成员建档（跟进链）
                    if prev_set and uid not in prev_set:
                        self.store.register_newcomer(gid, uid, nm)

                act["member_ids"] = cur_ids
                act["last_collect_ts"] = time.time()

                # 统计今日发言人数
                day_start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                active_cnt = sum(
                    1 for v in act["members"].values()
                    if v.get("last_active_ts", 0) >= day_start
                )

                self.store.add_stat(gid, {
                    "date": today,
                    "total": len(cur_set),
                    "new": new_cnt,
                    "leave": leave_cnt,
                    "active": active_cnt,
                    "team": 0,  # 成团次数由人工或后续扩展补充
                    "auto": True,
                })
                logger.info(
                    f"[{PLUGIN_NAME}] 自动采集群 {gid}: 总{len(cur_set)} 新增{new_cnt} 退群{leave_cnt} 活跃{active_cnt}"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 采集群 {gid} 数据失败: {e}")

        await self.store.asave()

    # ------------------------------------------------------------------
    # 任务 3：自动新人跟进
    # ------------------------------------------------------------------
    async def _job_followup(self) -> None:
        """入群后 30min/24h/72h 分级跟进，已发言则停止跟进。"""
        groups = self.store.enabled_groups("followup")
        if not groups:
            return
        now = time.time()
        changed = False

        for gid, info in groups.items():
            act = self.store.activity_of(gid)
            fu = self.store.followup_of(gid)
            day_start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

            for uid, rec in list(fu.items()):
                # 已在群里发过言 → 结束跟进
                m = act["members"].get(uid, {})
                if m.get("last_active_ts", 0) >= rec.get("joined_ts", 0):
                    fu.pop(uid, None)
                    changed = True
                    continue

                elapsed = now - rec.get("joined_ts", now)
                sent = rec.get("sent_stages", [])
                for stage in FOLLOWUP_STAGES:
                    if stage["after"] in sent or elapsed < stage["after"]:
                        continue
                    name = rec.get("name") or uid
                    raw_tpl = stage["content"]
                    text = raw_tpl.replace("{nickname}", name)
                    try:
                        chain = MessageChain()
                        if "{nickname}" in raw_tpl:
                            chain = chain.at(name, uid)
                            chain = chain.message("\n" + text)
                        else:
                            chain = chain.message(text)
                        await self._send_to(info.get("umo", ""), chain, f"新人跟进 {gid}")
                        sent.append(stage["after"])
                        rec["sent_stages"] = sent
                        changed = True
                        logger.info(f"[{PLUGIN_NAME}] 新人跟进 {gid}/{uid} 阶段 {stage['key']}")
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[{PLUGIN_NAME}] 新人跟进发送失败: {e}")

        if changed:
            await self.store.asave()

    # ------------------------------------------------------------------
    # 任务 4：自动冷场救场
    # ------------------------------------------------------------------
    async def _job_cold_rescue(self) -> None:
        """群内长时间无消息时，自动发话题激活。"""
        auto = self.store.data.get("automation", {})
        groups = self.store.enabled_groups("cold_rescue")
        if not groups:
            return

        now = time.time()
        hour = _bj_now().hour
        h_start = int(auto.get("active_hour_start", 9))
        h_end = int(auto.get("active_hour_end", 23))
        if not (h_start <= hour < h_end):
            return

        threshold = int(auto.get("cold_threshold", 7200))
        cooldown = int(auto.get("cold_cooldown", 7200))

        for gid, info in groups.items():
            act = self.store.activity_of(gid)
            last_msg = act.get("last_msg_ts", 0)
            last_rescue = act.get("last_rescue_ts", 0)
            if not last_msg:
                # 群刚绑定、还没有任何消息记录 → 以绑定时间为起点计时
                last_msg = self._bound_ts(info)
                if not last_msg:
                    continue
            if now - last_msg < threshold:
                continue
            if now - last_rescue < cooldown:
                continue

            idx = int(act.get("rescue_idx", 0)) % len(RESCUE_TOPICS)
            text = ""
            # AI 救场：让模型结合"冷场"情境现场编一条，比固定话题更自然
            if self.ai_ready() and self._ai_cfg().get("ai_for_rescue", True):
                text = await self.ai_custom(
                    "群刚刚冷场了，已经很久没人说话。写一条能立刻打破沉默、"
                    "让人愿意接话的话题或小活动，可以带一个投票或扣1互动。",
                    "save_cold",
                )
            if not text:
                text = RESCUE_TOPICS[idx]
            try:
                await self._send_to(
                    info.get("umo", ""), MessageChain().message(text), f"冷场救场 {gid}"
                )
                act["rescue_idx"] = idx + 1
                act["last_rescue_ts"] = now
                act["last_msg_ts"] = now  # 重置，避免连续触发
                await self.store.asave()
                logger.info(f"[{PLUGIN_NAME}] 自动冷场救场：群 {gid}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 冷场救场失败: {e}")

    # ------------------------------------------------------------------
    # 任务 5：自动沉睡唤醒
    # ------------------------------------------------------------------
    async def _job_wake(self) -> None:
        """识别多日未发言成员，自动 @ 召回（带冷却与数量上限）。"""
        auto = self.store.data.get("automation", {})
        groups = self.store.enabled_groups("wake")
        if not groups:
            return

        now = time.time()
        wake_after = int(auto.get("wake_days", 7)) * 86400
        cooldown = int(auto.get("wake_cooldown", 604800))
        max_per_round = int(auto.get("wake_max_per_round", 5))
        hour = _bj_now().hour
        if not (int(auto.get("active_hour_start", 9)) <= hour < int(auto.get("active_hour_end", 23))):
            return

        changed = False
        for gid, info in groups.items():
            act = self.store.activity_of(gid)

            candidates = []
            for uid, m in act["members"].items():
                if self._is_bot_uid(uid):
                    continue
                last = m.get("last_active_ts", 0)
                if not last:
                    continue
                if now - last < wake_after:
                    continue
                if now - m.get("last_wake_ts", 0) < cooldown:
                    continue
                candidates.append((uid, m))

            # 优先唤醒历史活跃度高的（msg_count 大）
            candidates.sort(key=lambda x: x[1].get("msg_count", 0), reverse=True)
            for uid, m in candidates[:max_per_round]:
                name = m.get("name") or uid
                try:
                    chain = MessageChain().at(name, uid).message(
                        "\n兄弟好久没见你冒泡了~\n"
                        "群里最近搞了内部赛和皮肤抽奖，回来玩两把？\n"
                        "今晚20:00车队还差人，就等你上车了 🎮"
                    )
                    await self._send_to(info.get("umo", ""), chain, f"沉睡唤醒 {gid}")
                    m["last_wake_ts"] = now
                    changed = True
                    logger.info(f"[{PLUGIN_NAME}] 自动唤醒沉睡成员 {gid}/{uid}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[{PLUGIN_NAME}] 沉睡唤醒失败: {e}")

        if changed:
            await self.store.asave()

    # ------------------------------------------------------------------
    # 任务 6：自动积分结算
    # ------------------------------------------------------------------
    async def _job_settle(self) -> None:
        """每天自动给当日发言过的成员结算活跃积分。"""
        today = _bj_now().strftime("%Y-%m-%d")
        if self._today_settled == today:
            return
        # 在 23:00 之后结算，避免过早
        if _bj_now().hour < 23:
            return

        groups = self.store.enabled_groups("report")
        day_start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        settled = 0
        for gid in groups:
            act = self.store.activity_of(gid)
            for uid, m in act["members"].items():
                if self._is_bot_uid(uid):
                    continue
                if m.get("last_active_ts", 0) >= day_start and m.get("msg_count", 0) > 0:
                    self.store.add_points(gid, uid, self._rule("interact"), m.get("name", ""))
                    settled += 1
        if settled:
            await self.store.asave()
            logger.info(f"[{PLUGIN_NAME}] 自动积分结算完成，共 {settled} 人次")
        self._today_settled = today
        self._mark_fired("settle", today)
        await self.store.asave()

    # ------------------------------------------------------------------
    # 任务 7：自动运营日报
    # ------------------------------------------------------------------
    async def _job_daily_report(self) -> None:
        auto = self.store.data.get("automation", {})
        now = _bj_now()
        target = str(auto.get("report_time", "23:30"))
        today = now.strftime("%Y-%m-%d")
        # 容错：到点或已过点均触发，避免 tick 漂移导致当天永久漏发
        if now.strftime("%H:%M") < target:
            return
        if self._fired_today("report", today):
            return
        self._mark_fired("report", today)

        groups = self.store.enabled_groups("report")
        for gid, info in groups.items():
            stats = self.store.get_stats(gid)
            latest = stats[-1] if stats else {}
            if latest.get("date") != today:
                # 用活跃度实时兜底
                act = self.store.activity_of(gid)
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                active = sum(1 for v in act["members"].values() if v.get("last_active_ts", 0) >= day_start)
                latest = {"total": len(act.get("member_ids", [])), "new": 0, "leave": 0,
                          "active": active, "team": 0}

            total = latest.get("total", 0) or 1
            rate = round(latest.get("active", 0) / total * 100, 1)
            top = self.store.leaderboard(gid, top=3)
            top_txt = "、".join(f"{r['name']}({r['points']}分)" for r in top) if top else "暂无"

            lines = [
                f"📊 【运营日报·{today}】",
                "━━━━━━━━━━━━━",
                f"👥 群人数：{latest.get('total', 0)}",
                f"📈 今日新增：+{latest.get('new', 0)}　📉 退群：-{latest.get('leave', 0)}",
                f"💬 发言人数：{latest.get('active', 0)}（日活 {rate}%）",
                f"🎮 开黑成团：{latest.get('team', 0)} 次",
                f"🏆 积分 Top3：{top_txt}",
                "━━━━━━━━━━━━━",
                "（本报告由运营助手自动生成）",
            ]
            text = "\n".join(lines)
            # 发送目标：私聊 QQ（支持多个，逗号/空格分隔）+ 可选同时发群
            raw_admins = str(auto.get("report_admin_qq", "") or "")
            admins = [x.strip() for x in re.split(r"[，,;；\s]+", raw_admins) if x.strip()]
            also_group = bool(auto.get("report_to_group", False))
            sent_any = False
            # 私聊前缀从本群 umo 动态取（和群消息同一平台），适配 aiocqhttp/qq_official
            pm_prefix = self._platform_prefix(info.get("umo", ""))
            for admin in admins:
                ok = await self._send_to(
                    f"{pm_prefix}:FriendMessage:{admin}",
                    MessageChain().message(text),
                    f"日报私聊 {admin}",
                )
                sent_any = sent_any or ok
            if also_group or not admins:
                ok = await self._send_to(
                    info.get("umo", ""), MessageChain().message(text), f"日报群发 {gid}"
                )
                sent_any = sent_any or ok
            if sent_any:
                logger.info(f"[{PLUGIN_NAME}] 自动日报已发送：群 {gid}")

    # ------------------------------------------------------------------
    # 任务 8：自动周榜
    # ------------------------------------------------------------------
    async def _job_weekly_board(self) -> None:
        auto = self.store.data.get("automation", {})
        now = _bj_now()
        if now.weekday() != int(auto.get("weekly_board_weekday", 6)):
            return
        target = str(auto.get("weekly_board_time", "21:00"))
        # 容错：到点或已过点均触发，避免 tick 漂移导致漏发
        if now.strftime("%H:%M") < target:
            return
        week_key = now.strftime("%Y-%W")
        if self.store.fired(f"weekly#{week_key}"):
            return
        self.store.mark_fired(f"weekly#{week_key}", "1")

        ai_cfg = self._ai_cfg()
        top_n = max(3, min(20, int(ai_cfg.get("weekly_top_n", 5))))
        for gid, info in self.store.enabled_groups("report").items():
            rows = self.store.leaderboard(gid, top=top_n)
            if not rows:
                continue
            medals = ["🥇", "🥈", "🥉"]
            lines = [f"🏆 【本周积分排行榜 Top{top_n}】"]
            for i, r in enumerate(rows):
                icon = medals[i] if i < 3 else f"{i + 1}."
                lines.append(f"{icon} {r['name']} — {r['points']} 分（邀请 {r['invites']} 人）")
            lines.append("积分可兑换皮肤碎片/红包，继续加油！🎁")
            try:
                await self._send_to(
                    info.get("umo", ""),
                    MessageChain().message("\n".join(lines)),
                    f"自动周榜 {gid}",
                )
                logger.info(f"[{PLUGIN_NAME}] 自动周榜已发布：群 {gid}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 周榜发布失败: {e}")
        await self.store.asave()

    # ==================================================================
    # 消息监听：活跃度追踪 + 关键词自动应答
    # ==================================================================
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理所有群消息：入群 notice / 活跃度记录 / 关键词应答。"""
        try:
            raw = getattr(event.message_obj, "raw_message", None)
            if raw is None:
                return

            def _get(k: str, default: Any = None) -> Any:
                try:
                    return raw.get(k, default)  # type: ignore[union-attr]
                except AttributeError:
                    return getattr(raw, k, default)

            # ---- A. 入群 notice ----
            if _get("post_type") == "notice":
                gid_notice = str(_get("group_id", "") or "")
                if gid_notice:
                    # 记录该群已被发现（即使未绑定，也供 WebUI「扫描群」使用）
                    self._remember_group(gid_notice)
                if _get("notice_type") == "group_increase":
                    await self._handle_group_increase(event, _get)
                return

            # ---- B. 普通群消息 ----
            group_id = str(event.get_group_id() or "")
            user_id = str(event.get_sender_id() or "")
            name = event.get_sender_name() or user_id
            if not group_id or not user_id:
                return

            # 记录发现的群（未绑定的也记，供 WebUI 自助绑定）
            self._remember_group(group_id)

            # 忽略机器人自己
            self_id = str(getattr(event.message_obj, "self_id", "") or "") or self._bot_self_id()
            if self_id and user_id == self_id:
                return

            # 只追踪已绑定且启用的群
            if not self.store.group_enabled(group_id):
                return

            self.store.record_message(group_id, user_id, name)
            # 已发言 → 结束新人跟进
            if user_id in self.store.followup_of(group_id):
                self.store.clear_followup(group_id, user_id)

            # ---- C. 答题判定（优先于关键词应答，避免模板吃回复） ----
            try:
                if self._quiz_cfg().get("quiz_enabled", True):
                    handled = await self.quiz_handle_answer(
                        event, group_id, user_id, name, event.message_str or ""
                    )
                    if handled:
                        return
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[{PLUGIN_NAME}] 答题判定异常: {e}")

            # ---- D. 关键词自动应答 ----
            auto = self.store.data.get("automation", {})
            if auto.get("auto_reply", True) and self.store.group_feature(group_id, "reply"):
                await self._maybe_auto_reply(event, group_id, event.message_str or "")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] 群消息处理异常: {e}")

    async def _handle_group_increase(self, event: AstrMessageEvent, _get) -> None:
        """新人入群：自动记录邀请 + 自动欢迎 + 建档跟进。"""
        self_id = str(_get("self_id", "") or "") or self._bot_self_id()
        new_uid = str(_get("user_id", "") or "")
        if self_id and new_uid == self_id:
            return

        group_id = str(_get("group_id", "") or "")
        if not group_id:
            return

        # ---- A. 自动记录邀请（不受群欢迎功能开关影响，只看群是否绑定） ----
        try:
            await self._auto_record_invite(
                event,
                group_id,
                new_uid,
                str(_get("sub_type", "") or ""),
                str(_get("operator_id", "") or "") or str(_get("operator_uid", "") or ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] 自动邀请记录异常: {e}")

        # ---- B. 欢迎 + 建档（未绑定 / 未开欢迎功能的群不处理） ----
        if not self.store.group_feature(group_id, "welcome"):
            return
        cfg = self.store.data.get("config", {})
        if not cfg.get("auto_welcome", True):
            return

        nickname = f"新同学{new_uid[-4:]}" if new_uid else "新同学"
        bot = getattr(event, "bot", None)
        if bot is not None and group_id and new_uid:
            try:
                info = await bot.call_action(
                    "get_group_member_info",
                    group_id=int(group_id),
                    user_id=int(new_uid),
                )
                if isinstance(info, dict):
                    nickname = info.get("card") or info.get("nickname") or nickname
            except Exception:  # noqa: BLE001
                pass

        # 发送欢迎语（@新人）
        try:
            text = self._welcome_text(group_id, nickname)
            # 可选：AI 生成个性化欢迎语（默认关闭，避免欢迎语不稳定）
            if self.ai_ready() and self._ai_cfg().get("ai_for_welcome", False):
                ai_text = await self.ai_custom(
                    f"新人「{nickname}」刚加入了本群。写一条热情、有网感的欢迎语，"
                    f"@一下这位新人，引导他发身份卡（昵称+段位+主玩位置），"
                    f"并告诉他今晚 20:00 有车队、新人优先带飞。",
                    "welcome",
                )
                if ai_text:
                    text = ai_text.replace("{nickname}", nickname).replace("{group_no}", group_id)
            if new_uid:
                chain = MessageChain().at(nickname, new_uid).message("\n" + text)
            else:
                chain = MessageChain().message(text)
            await self._send_to(
                event.unified_msg_origin, chain, f"入群欢迎 {group_id}"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] 欢迎语发送失败: {e}")

        # 建档：积分 + 新人跟进（仅在开启新人跟进时登记）
        self.store.get_user(group_id, new_uid, nickname)
        if self.store.group_feature(group_id, "followup"):
            self.store.register_newcomer(group_id, new_uid, nickname)
        await self.store.asave()

    async def _auto_record_invite(
        self,
        event: AstrMessageEvent,
        group_id: str,
        new_uid: str,
        sub_type: str,
        operator_id: str,
    ) -> None:
        """入群事件自动识别邀请人并记录邀请明细。

        OneBot 11 的 ``group_increase`` notice：
          · ``sub_type=invite``  → ``operator_id`` 是邀请人（被拉进群）
          · ``sub_type=approve`` → ``operator_id`` 是审批入群的管理员，拿不到真实邀请人

        拿不到邀请人时记一条「待认领」记录（``source=unclaimed``），
        可在 WebUI 邀请记录里指定邀请人后补计分。
        """
        cfg = self._points_cfg()
        if not cfg.get("auto_invite", True):
            return
        if group_id not in self.store.bound_groups():
            return
        if not new_uid:
            return
        if self.store.invitee_recorded(group_id, new_uid):
            return  # 同一新人只记一次，防重复计分

        inviter = ""
        if sub_type == "invite" and operator_id and operator_id != new_uid:
            inviter = operator_id
        elif sub_type in ("approve", "admin") and cfg.get("count_on_approve"):
            inviter = str(cfg.get("default_inviter") or "").strip()

        bot = getattr(event, "bot", None)
        name_cache: dict[str, str] = {}

        async def _name(uid: str, fallback: str = "") -> str:
            if not uid:
                return ""
            if uid in name_cache:
                return name_cache[uid]
            nm = ""
            if bot is not None:
                try:
                    info = await bot.call_action(
                        "get_group_member_info", group_id=int(group_id), user_id=int(uid)
                    )
                    if isinstance(info, dict):
                        nm = str(info.get("card") or info.get("nickname") or "")
                except Exception:  # noqa: BLE001
                    nm = ""
            name_cache[uid] = nm or fallback or uid
            return name_cache[uid]

        inviter_name = await _name(inviter) if inviter else ""
        invitee_name = await _name(new_uid, f"新同学{new_uid[-4:]}")

        points = 0
        counted = False
        if inviter:
            limit = int(cfg.get("invite_daily_limit", 0) or 0)
            if self.store.invite_quota_left(group_id, inviter, limit) > 0:
                gain = self._rule("invite")
                self.store.add_invite(group_id, inviter, inviter_name, points=gain)
                points, counted = gain, True

        entry: dict[str, Any] = {
            "inviter": inviter,
            "inviter_name": inviter_name,
            "invitee": new_uid,
            "invitee_name": invitee_name,
            "ts": time.time(),
            "time": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
            "date": _bj_now().strftime("%Y-%m-%d"),
            "source": "auto" if counted else ("limit" if inviter else "unclaimed"),
            "sub_type": sub_type or "",
            "points": points,
            "counted": counted,
        }
        self.store.add_invite_log(group_id, entry)
        await self.store.asave()
        logger.info(
            f"[{PLUGIN_NAME}] 邀请记录：{inviter or '(待认领)'} → {new_uid}，+{points} 分"
        )

        if counted and cfg.get("invite_broadcast", True):
            await self._broadcast_invite(
                group_id, inviter_name or inviter, invitee_name, points, cfg
            )

    async def _broadcast_invite(
        self, group_id: str, inviter: str, invitee: str, points: int, cfg: dict[str, Any]
    ) -> None:
        """邀请成功后在群内播报（话术可在 WebUI 自定义）。"""
        tpl = str(cfg.get("invite_broadcast_text") or DEFAULT_INVITE_BROADCAST)
        try:
            text = tpl.format(inviter=inviter, invitee=invitee, points=points)
        except (KeyError, IndexError, ValueError):
            text = DEFAULT_INVITE_BROADCAST.format(inviter=inviter, invitee=invitee, points=points)
        try:
            await self._send_to(
                self._umo_for_group(group_id),
                MessageChain().message(text),
                f"邀请播报 {group_id}",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] 邀请播报失败: {e}")

    async def _maybe_auto_reply(self, event: AstrMessageEvent, group_id: str, text: str) -> None:
        """命中关键词自动应答（带冷却）。"""
        if not text:
            return
        auto = self.store.data.get("automation", {})
        rules = auto.get("reply_rules") or []
        cooldown = int(auto.get("reply_cooldown", 300))
        now = time.time()

        for rule in rules:
            if not rule.get("enabled", True):
                continue
            kws = rule.get("keywords") or []
            hit = next((k for k in kws if k and k in text), None)
            if not hit:
                continue
            ck = f"{group_id}#{hit}"
            if now - self._last_reply.get(ck, 0) < cooldown:
                return
            self._last_reply[ck] = now
            try:
                await self._send_to(
                    event.unified_msg_origin,
                    MessageChain().message(rule.get("reply", "")),
                    "关键词应答",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 关键词应答失败: {e}")
            return

        # ---- 规则未命中：可选 AI 兜底 ----
        # 保守触发：只在消息明确是提问且非闲聊时才用 AI 回，绝不抢普通聊天的话
        ai = self._ai_cfg()
        if not (ai.get("ai_enabled") and ai.get("ai_for_reply", True)):
            return
        text = (text or "").strip()
        if not text or len(text) > 120:
            return
        # 必须是真提问（问号 / 疑问词）才接话；聊天、晒图、口号一律不回
        if not any(k in text for k in ("?", "？", "吗", "怎么", "如何", "能不能",
                                       "有没有", "什么", "哪", "请问", "求问")):
            return
        # 命中规则词却不该回的场景（如"有队吗"由规则处理），这里仅兜底
        ck = f"{group_id}#__ai__"
        if now - self._last_reply.get(ck, 0) < cooldown:
            return
        self._last_reply[ck] = now
        answer = await self.ai_custom(
            f"群成员问：「{text}」\n"
            f"请像群里真实的老玩家一样，简短自然地回答他。"
            f"规则：① 只答他问的这件事，不要生硬地把话题拐到游戏/开黑/报名上；"
            f"② 如果确实和王者荣耀、群规则、积分有关，可以顺带提一句；"
            f"③ 不确定的事（战绩、别人段位、具体版本数据）不要编，就说让大家说说看；"
            f"④ 40 字以内，口语化。",
        )
        if not answer:
            return
        try:
            await self._send_to(
                event.unified_msg_origin, MessageChain().message(answer), "AI 应答"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] AI 应答失败: {e}")

    # ==================================================================
    # AI 大模型接入
    # ==================================================================
    def _ai_cfg(self) -> dict[str, Any]:
        ai = self.store.data.get("ai")
        if not isinstance(ai, dict):
            ai = self.store.data["ai"] = json.loads(json.dumps(DEFAULT_AI))
        return ai

    def _points_cfg(self) -> dict[str, Any]:
        """积分配置；与默认值深合并，保证升级后新增字段自动补齐。"""
        cfg = self.store.data.get("points_config")
        if not isinstance(cfg, dict):
            cfg = {}
        merged = json.loads(json.dumps(DEFAULT_POINTS_CONFIG))
        for k, v in cfg.items():
            if k == "rules" and isinstance(v, dict):
                merged["rules"].update({kk: vv for kk, vv in v.items() if kk in merged["rules"]})
            elif k == "redeem_items" and isinstance(v, list):
                merged["redeem_items"] = v
            elif k in merged:
                merged[k] = v
        self.store.data["points_config"] = merged
        return merged

    def _rule(self, key: str) -> int:
        """取某条积分规则的数值。"""
        cfg = self._points_cfg()
        try:
            return int(cfg.get("rules", {}).get(key, POINT_RULES.get(key, 0)))
        except (TypeError, ValueError):
            return int(POINT_RULES.get(key, 0))

    # ==================================================================
    # 答题活动引擎
    # ==================================================================
    def _quiz_cfg(self) -> dict[str, Any]:
        """答题活动配置；与默认值深合并。"""
        cfg = self._points_cfg()
        q = cfg.get("quiz")
        if not isinstance(q, dict):
            q = {}
        merged = json.loads(json.dumps(DEFAULT_QUIZ_CONFIG))
        for k, v in q.items():
            if k in merged:
                merged[k] = v
        cfg["quiz"] = merged
        return merged

    def quiz_active_of(self, group_id: str) -> dict[str, Any] | None:
        """返回该群进行中的题目；已过期则自动结算并返回 None。"""
        logs = self.store.data.setdefault("quiz_active", {})
        act = logs.get(group_id)
        if not isinstance(act, dict):
            return None
        expires = float(act.get("expires_ts") or 0)
        if expires and time.time() > expires:
            self.quiz_close(group_id, "timeout")
            return None
        return act

    def quiz_close(self, group_id: str, reason: str = "done") -> None:
        """结束该群当前题目（不发送消息，仅清理状态）。"""
        (self.store.data.get("quiz_active") or {}).pop(group_id, None)

    async def quiz_start(self, group_id: str, quiz_id: str | None = None) -> str:
        """出一题并群内播报。返回播报文本（空串 = 未开启/无题/已有进行中的题）。"""
        cfg = self._quiz_cfg()
        if not cfg.get("quiz_enabled", True):
            return ""
        if group_id not in self.store.bound_groups():
            return ""
        if self.quiz_active_of(group_id):
            return ""  # 已有进行中的题，等它结束

        pool = QUIZ_BANK
        pick = next((q for q in pool if q["id"] == quiz_id), None) if quiz_id else None
        if pick is None:
            done = set((self.store.data.get("quiz_active") or {}).get("_used", []) or [])
            remaining = [q for q in pool if q["id"] not in done]
            pick = random.choice(remaining or pool)

        used = (self.store.data.get("quiz_active") or {}).setdefault("_used", [])
        if not isinstance(used, list):
            used = (self.store.data["quiz_active"])["_used"] = []
        used.append(pick["id"])
        if len(used) > 20:
            used[:] = used[-20:]

        limit = int(cfg.get("quiz_limit", 3))
        timeout = int(cfg.get("quiz_timeout", 600))
        reward = int(pick.get("reward") or cfg.get("quiz_reward", 10))
        self.store.data["quiz_active"][group_id] = {
            "quiz_id": pick["id"],
            "q": pick["q"],
            "answers": list(pick.get("answers") or []),
            "hint": pick.get("hint", ""),
            "reward": reward,
            "limit": limit,
            "winners": [],
            "started_ts": time.time(),
            "expires_ts": time.time() + max(60, timeout),
        }
        await self.store.asave()
        limit_txt = f"（本场前 {limit} 名答对有效）" if limit > 0 else ""
        return (
            f"🧠 【答题挑战】\n{pick['q']}\n"
            f"直接回答案即可{limit_txt}，答对自动 +{reward} 分 🎁"
        )

    async def quiz_handle_answer(self, event: AstrMessageEvent, group_id: str,
                                 user_id: str, name: str, text: str) -> bool:
        """判定一条群消息是否是当前题目的正确答案。命中则自动加分并播报。"""
        if not text or len(text) > 40:
            return False
        act = self.quiz_active_of(group_id)
        if not act:
            return False
        winners = act.setdefault("winners", [])
        # 已获奖者不再重复计分（防重复发同一答案刷分）
        if any(str(w.get("user_id")) == user_id for w in winners):
            return False

        limit = int(act.get("limit", 0))
        if limit > 0 and len(winners) >= limit:
            return False

        cfg = self._quiz_cfg()
        answers = [str(a) for a in (act.get("answers") or [])]
        hit = self._quiz_match(text, answers)

        # 规则未命中：可选 AI 判题（严格模式，只回答"是/否"）
        if not hit and cfg.get("quiz_ai_judge", True) and self.ai_ready():
            hit = await self._quiz_ai_judge(act.get("q", ""), answers, text)

        if not hit:
            return False

        reward = int(act.get("reward") or 0)
        self.store.add_points(group_id, user_id, reward, name)
        winners.append({
            "user_id": user_id,
            "name": name,
            "points": reward,
            "ts": time.time(),
            "time": _bj_now().strftime("%H:%M:%S"),
        })
        await self.store.asave()

        # 名额用满 → 公布答案并结束本题
        if limit > 0 and len(winners) >= limit:
            answer_txt = " / ".join(answers[:3])
            msg = (
                f"🎊 答题结束！正确答案：{answer_txt}\n"
                f"获奖名单：{'、'.join(w['name'] for w in winners)}，各 +{reward} 分 🎁"
            )
            self.quiz_close(group_id)
        else:
            msg = (
                f"✅ 答对了！{name} +{reward} 分，当前 {self.store.get_user(group_id, user_id)['points']} 分。\n"
                f"（本场还剩 {max(0, limit - len(winners))} 个获奖名额）"
            )
        try:
            await self._send_to(
                self._umo_for_group(group_id), MessageChain().message(msg), f"答题播报 {group_id}"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] 答题播报失败: {e}")
        return True

    @staticmethod
    def _quiz_match(text: str, answers: list[str]) -> bool:
        """答案归一化后匹配：忽略大小写、空格、全角括号等差异。"""
        def norm(s: str) -> str:
            s = str(s).lower().strip()
            s = re.sub(r"[\s　]+", "", s)
            s = re.sub(r"[，,。.！!？?、~～\-—_*\"'「」『』（）()【】\[\]]", "", s)
            return s
        t = norm(text)
        if not t:
            return False
        for a in answers:
            a_norm = norm(a)
            if not a_norm:
                continue
            if t == a_norm or a_norm in t:
                return True
        return False

    async def _quiz_ai_judge(self, question: str, answers: list[str], reply: str) -> bool:
        """让 AI 严格判定玩家回答是否等于标准答案。只回 Y/N。"""
        prompt = (
            f"你在做一道王者荣耀群答题活动的判题。\n"
            f"【题目】{question}\n"
            f"【标准答案】{'、'.join(answers)}\n"
            f"【玩家回答】{reply}\n\n"
            f"请判断玩家回答是否与标准答案等价（包含同义表述、错别字、昵称等）。"
            f"只回答一个字：是 或 否。不要任何解释。"
        )
        try:
            verdict = await self._ai_chat(
                prompt, "你是严格的中文判题员，只输出「是」或「否」一个字。"
            )
        except Exception:  # noqa: BLE001
            return False
        if not verdict:
            return False
        return verdict.strip().startswith(("是", "Y", "y", "对", "正确"))

    async def _quiz_timeout_check(self) -> None:
        """定时检查各群进行中的题目是否超时，超时公布答案。"""
        active = self.store.data.get("quiz_active") or {}
        for gid in list(active.keys()):
            if gid == "_used":
                continue
            act = active.get(gid)
            if not isinstance(act, dict):
                continue
            if time.time() <= float(act.get("expires_ts") or 0):
                continue
            answers = [str(a) for a in (act.get("answers") or [])]
            winners = act.get("winners") or []
            self.quiz_close(gid)
            await self.store.asave()
            answer_txt = " / ".join(answers[:3]) or "（无）"
            if winners:
                msg = f"⏰ 答题超时结束。正确答案：{answer_txt}\n已获奖：{'、'.join(w['name'] for w in winners)} 🎁"
            else:
                msg = f"⏰ 答题超时结束，没人答对~ 正确答案是：{answer_txt}\n下一题马上来！"
            try:
                await self._send_to(
                    self._umo_for_group(gid), MessageChain().message(msg), f"答题超时 {gid}"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 答题超时播报失败: {e}")

    def ai_ready(self) -> bool:
        """AI 是否可用（总开关开启）。"""
        return bool(self._ai_cfg().get("ai_enabled", False))

    async def _resolve_provider(self):
        """兼容各版本 AstrBot 获取当前对话模型。

        - v4.29+  ：`get_using_provider_async()`（async）
        - v4.26~4.28：`get_using_provider()`（sync）
        返回 Provider 实例或 None。
        """
        ctx = self.context
        # 优先 async 版本（4.29+）
        fn = getattr(ctx, "get_using_provider_async", None)
        if callable(fn):
            try:
                prov = fn()
                if asyncio.iscoroutine(prov):
                    prov = await prov
                if prov is not None:
                    return prov
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[{PLUGIN_NAME}] get_using_provider_async 不可用: {e}")
        # 回退同步版本（4.26~4.28）
        fn = getattr(ctx, "get_using_provider", None)
        if callable(fn):
            try:
                prov = fn()
                if asyncio.iscoroutine(prov):
                    prov = await prov
                if prov is not None:
                    return prov
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[{PLUGIN_NAME}] get_using_provider 调用失败: {e}")
        return None

    def _all_providers(self) -> list:
        """获取所有对话模型（兼容各版本）。"""
        ctx = self.context
        # 首选 Context.get_all_providers()（4.26+ 均有）
        try:
            fn = getattr(ctx, "get_all_providers", None)
            if callable(fn):
                provs = fn()
                if provs:
                    return list(provs)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] get_all_providers 失败: {e}")
        # 回退：直接读 provider_manager 的各种属性名
        try:
            pm = getattr(ctx, "provider_manager", None)
            if pm is not None:
                for attr in ("provider_insts", "providers", "insts"):
                    v = getattr(pm, attr, None)
                    if isinstance(v, (list, tuple)) and v:
                        return list(v)
                m = getattr(pm, "inst_map", None)
                if isinstance(m, dict) and m:
                    return list(m.values())
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] provider_manager 读取失败: {e}")
        return []

    def _provider_label(self, prov) -> tuple[str, str]:
        """安全取出 provider 的 (id, name)。"""
        try:
            meta = prov.meta()
            pid = str(getattr(meta, "id", "") or "")
            pname = str(getattr(meta, "name", "") or "") or pid
            return pid, pname
        except Exception:  # noqa: BLE001
            return "", ""

    async def _ai_chat(self, prompt: str, system: str = "") -> str:
        """调用 AstrBot 已配置的大模型，失败返回空串（由调用方降级）。

        复用 `context.llm_generate`，无需用户另填 API Key。
        """
        ai = self._ai_cfg()
        if not ai.get("ai_enabled", False):
            return ""
        provider_id = str(ai.get("ai_provider_id") or "").strip()
        try:
            if not provider_id:
                # 未指定则用当前默认对话模型
                prov = await self._resolve_provider()
                if prov is None:
                    logger.warning(f"[{PLUGIN_NAME}] AI 已开启，但未找到可用的对话模型")
                    return ""
                provider_id = self._provider_label(prov)[0]
            timeout = max(5, min(120, int(ai.get("ai_timeout", 20))))
            resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system or None,
                    temperature=float(ai.get("ai_temperature", 0.6)),
                ),
                timeout=timeout,
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            return self._clean_ai_text(text)
        except asyncio.TimeoutError:
            logger.warning(f"[{PLUGIN_NAME}] AI 调用超时（>{ai.get('ai_timeout', 20)}s），降级到固定模板")
            return ""
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] AI 调用失败，降级到固定模板: {e}")
            return ""

    @staticmethod
    def _clean_ai_text(text: str) -> str:
        """清洗模型输出：去掉 markdown 包裹、代码块、多余引号与前缀。"""
        if not text:
            return ""
        t = text.strip()
        # 去掉 ``` 代码块（可带语言标注）
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        t = t.strip()
        # 去掉整体包裹的成对引号（注意 「」 是不同字符，必须按对匹配）
        pairs = [('"', '"'), ("'", "'"), ("「", "」"), ("“", "”"),
                 ("『", "』"), ("《", "》"), ("‘", "’"), ("【", "】")]
        changed = True
        while changed and len(t) > 2:
            changed = False
            for a, b in pairs:
                if t.startswith(a) and t.endswith(b):
                    t = t[len(a):-len(b)].strip()
                    changed = True
                    break
        # 去掉模型爱加的口头前缀（可叠加多层）
        t = re.sub(
            r"^(好的|当然|没问题|可以|以下是|这是|下面是|给你)[，,。：:、\s]*",
            "", t,
        ).strip()
        t = re.sub(r"^(内容|文案|话术|结果)[，,。：:、\s]*", "", t).strip()
        # 折叠 3 个以上连续换行
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    async def ai_generate_template(self, key: str, extra_hint: str = "", group_id: str = "") -> str:
        """用 AI 生成某个模板的内容；失败返回空串（调用方回退固定模板）。"""
        ai = self._ai_cfg()
        if not ai.get("ai_enabled", False):
            return ""
        scene = AI_SCENES.get(key)
        if not scene:
            return ""
        tpl = TEMPLATES.get(key, {})
        date = _bj_now().strftime("%m月%d日")
        lines = [
            f"【任务】{scene['brief']}",
            f"【今天是】{date}",
        ]
        if group_id:
            lines.append(f"【群号】{group_id}")
        if tpl.get("content"):
            # 给模型参考模板风格，但要求它重写而非照抄
            ref = _safe_format(tpl["content"], {
                "date": date, "topic": random.choice(TOPIC_POOL),
                "room": "待定", "need": "3", "mvp": "等你上榜",
                "nickname": "召唤师", "group_no": group_id or "（群号）",
            })
            lines.append(f"【参考风格（请重写，不要照抄）】\n{ref}")
        if extra_hint:
            lines.append(f"【额外要求】{extra_hint}")
        lines.append(f"【输出要求】{ai.get('ai_guard', '')}")
        prompt = "\n\n".join(lines)
        system = str(ai.get("ai_persona") or "")
        return await self._ai_chat(prompt, system)

    async def ai_polish_template(self, key: str, current: str, instruction: str = "") -> str:
        """润色/改写现有话术。"""
        ai = self._ai_cfg()
        if not ai.get("ai_enabled", False):
            return ""
        scene = AI_SCENES.get(key)
        label = scene["label"] if scene else key
        prompt = (
            f"【任务】把下面这条王者荣耀群运营话术（{label}）改写得更吸引人、更适合发到 QQ 群。\n\n"
            f"【原文】\n{current}\n\n"
            f"【改写要求】{instruction or '保持原意，语言更口语化、更有网感，增强互动引导。'}\n\n"
            f"【输出要求】{ai.get('ai_guard', '')}"
        )
        return await self._ai_chat(prompt, str(ai.get("ai_persona") or ""))

    async def ai_custom(self, instruction: str, key: str = "") -> str:
        """按用户自由指令生成一条群消息。"""
        ai = self._ai_cfg()
        if not ai.get("ai_enabled", False):
            return ""
        scene = AI_SCENES.get(key)
        ctx_line = f"【场景】{scene['label']}（{scene['brief']}）\n" if scene else ""
        prompt = (
            f"{ctx_line}"
            f"【用户要求】{instruction}\n\n"
            f"【输出要求】{ai.get('ai_guard', '')}"
        )
        return await self._ai_chat(prompt, str(ai.get("ai_persona") or ""))

    # ==================================================================
    # 渲染与广播
    # ==================================================================
    def _render(self, key: str, group_id: str = "", extra: dict | None = None) -> str:
        tpl = TEMPLATES.get(key)
        if not tpl:
            return ""
        cfg = self.store.data.get("config", {})
        # 优先级：AI 生成内容（用户已采纳）> 自定义欢迎词 > 内置模板
        overrides = cfg.get("template_overrides") or {}
        ai_ver = str(overrides.get(key) or "").strip()
        if ai_ver:
            content = ai_ver
        elif key == "welcome":
            content = str(cfg.get("welcome_text") or "").strip() or tpl["content"]
        else:
            content = tpl["content"]
        today = _bj_now().strftime("%m月%d日")
        pool = cfg.get("topic_pool") or TOPIC_POOL
        ctx = {
            "date": today,
            "topic": random.choice(pool) if pool else "今天想聊点什么？",
            "room": "待定",
            "need": str(random.randint(1, 4)),
            "mvp": "等你上榜",
            "nickname": "召唤师",
            "group_no": group_id or "（群号）",
        }
        if extra:
            ctx.update(extra)
        return _safe_format(content, ctx)

    def _welcome_text(self, group_id: str, nickname: str) -> str:
        """渲染欢迎语（支持自定义模板）。"""
        cfg = self.store.data.get("config", {})
        content = str(cfg.get("welcome_text") or "").strip() or DEFAULT_WELCOME_TEXT
        return _safe_format(content, {
            "nickname": nickname or "召唤师",
            "group_no": group_id or "（群号）",
            "date": _bj_now().strftime("%m月%d日"),
        })

    async def _broadcast_template(self, key: str, group_id: str = "", force_ai: bool | None = None) -> int:
        """广播模板。group_id 为空时向全部「已启用」的群发送。

        指定 group_id 时只发给该群；若该群未绑定或已停用，则不发送
        （绝不退化成群发，避免误触）。

        AI 实时生成逻辑：
        - force_ai=True  → 无条件用 AI 生成（WebUI「AI 生成并推送」）
        - force_ai=False → 无条件用固定模板（已采纳内容/内置模板）
        - force_ai=None  → 自动：ai_enabled 且 ai_for_schedule 且该模板无已采纳内容时走 AI
        每个群单独生成一次，确保不同群、不同天的内容都有差异。
        """
        groups = self.store.enabled_groups()
        if group_id:
            if group_id not in groups:
                logger.info(f"[{PLUGIN_NAME}] 群 {group_id} 未绑定或已停用，跳过推送")
                return 0
            targets = {group_id: groups[group_id]}
        else:
            targets = groups
        sent = 0
        overrides = (self.store.data.get("config") or {}).get("template_overrides") or {}
        ai_cfg = self._ai_cfg()
        # 自动模式：AI 开 + schedule 开 + 该模板没有被手动采纳过
        auto_ai = (
            force_ai is None
            and bool(ai_cfg.get("ai_enabled"))
            and bool(ai_cfg.get("ai_for_schedule", True))
            and key not in overrides
        )
        for gid, info in targets.items():
            text = ""
            use_ai = force_ai if force_ai is not None else auto_ai
            if use_ai:
                # 每个群现场生成一次 → 内容天然不同
                text = await self.ai_generate_template(key, group_id=gid)
            if not text:
                # AI 关 / 生成失败 → 降级固定模板（已采纳 > 内置）
                text = self._render(key, gid)
            if not text:
                continue
            # noon 模板 → 真正开一道题（模板文本仅作引导，实际判定走题库）
            if key == "noon":
                quiz_text = await self.quiz_start(gid)
                if quiz_text:
                    text = text.rstrip() + "\n\n" + quiz_text
            try:
                ok = await self._send_to(
                    info.get("umo", ""), MessageChain().message(text), f"推送 {key}->{gid}"
                )
                if ok:
                    sent += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 向群 {gid} 推送 {key} 失败: {e}")
        return sent

    # ==================================================================
    # 命令
    # ==================================================================
    @filter.command("运营")
    async def cmd_ops(self, event: AstrMessageEvent):
        """运营助手主命令：/运营 查看帮助。"""
        arg = event.message_str.replace("/运营", "").strip()
        group_id = str(event.get_group_id() or "")

        if arg in ("", "帮助", "help"):
            yield event.plain_result(self._help_text())
            return

        if arg in ("绑定", "bind"):
            if not group_id:
                yield event.plain_result("❌ 请在群里执行此命令。")
                return
            self.store.bind_group(group_id, event.unified_msg_origin)
            await self.store.asave()
            yield event.plain_result(
                f"✅ 已绑定本群（{group_id}）为运营目标。\n"
                "自动化引擎已接管：数据采集 / 新人跟进 / 冷场救场 / 沉睡唤醒 /\n"
                "积分结算 / 日报周榜 / 关键词应答 将全自动运行。\n"
                "发送 /运营 状态 查看运行详情，/运营 关闭 可单独停用本群。"
            )
            return

        if arg in ("解绑", "unbind"):
            if self.store.unbind_group(group_id):
                await self.store.asave()
                yield event.plain_result(f"✅ 已解绑本群（{group_id}）。")
            else:
                yield event.plain_result("ℹ️ 本群尚未绑定。")
            return

        if arg in ("状态", "status"):
            yield event.plain_result(self._status_text(group_id))
            return

        # ---- 本群开关：/运营 关闭 | /运营 开启 ----
        if arg in ("关闭", "停用", "off", "disable"):
            if not group_id:
                yield event.plain_result("❌ 请在群里执行此命令。")
                return
            if self.store.set_group_enabled(group_id, False):
                await self.store.asave()
                yield event.plain_result(
                    f"⏸️ 已停用本群（{group_id}）的全部自动化。\n"
                    "本群将不再自动推送/欢迎/应答，其它群不受影响。\n"
                    "发送 /运营 开启 可恢复。"
                )
            else:
                yield event.plain_result("ℹ️ 本群尚未绑定，请先 /运营 绑定。")
            return

        if arg in ("开启", "启用", "on", "enable"):
            if not group_id:
                yield event.plain_result("❌ 请在群里执行此命令。")
                return
            if self.store.set_group_enabled(group_id, True):
                await self.store.asave()
                yield event.plain_result(f"▶️ 已恢复本群（{group_id}）的自动化运营。")
            else:
                yield event.plain_result("ℹ️ 本群尚未绑定，请先 /运营 绑定。")
            return

        # ---- 功能开关：/运营 功能 [功能名] [on|off] ----
        if arg.startswith(("功能", "feature")):
            yield event.plain_result(self._feature_cmd(group_id, arg))
            return

        # ---- 欢迎词：/运营 欢迎词 <内容> | /运营 欢迎词 查看 | 重置 ----
        if arg.startswith(("欢迎词", "welcome")):
            yield event.plain_result(self._welcome_cmd(group_id, arg))
            return

        if arg.startswith(("发送", "send")):
            parts = arg.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("用法：/运营 发送 <模板key>\n可用模板见 /运营 帮助")
                return
            key = parts[1].strip()
            if key not in TEMPLATES:
                yield event.plain_result(f"❌ 未找到模板「{key}」。\n可用：{', '.join(TEMPLATES)}")
                return
            n = await self._broadcast_template(key)
            yield event.plain_result(f"✅ 已向 {n} 个群推送「{TEMPLATES[key]['name']}」。")
            return

        if arg in ("采集", "collect"):
            await self._job_collect()
            yield event.plain_result("✅ 已触发一次群数据采集，结果见 /运营数据")
            return

        if arg in ("救场", "rescue"):
            await self._broadcast_template("save_cold")
            yield event.plain_result("✅ 已推送冷场救场话题。")
            return

        if arg in ("测试欢迎", "testwelcome"):
            nickname = event.get_sender_name() or "召唤师"
            yield event.plain_result(self._welcome_text(group_id, nickname))
            return

        # ---- AI 生成：/运营 ai <场景key> [额外要求] ----
        if arg.startswith(("ai", "AI", "Ai")):
            body = arg[2:].strip()
            if not body:
                yield event.plain_result(
                    "🤖 【AI 话术生成】\n"
                    "用法：/运营 ai <模板key> [额外要求]\n"
                    "例：/运营 ai morning 今天聊版本更新\n"
                    f"可用场景：{', '.join(AI_SCENES)}\n"
                    "（需先在 WebUI「AI 话术」页打开 AI 总开关）"
                )
                return
            if not self.ai_ready():
                yield event.plain_result(
                    "⚠️ AI 尚未开启。请到 WebUI → 插件 → 运营作战台 →「AI 话术」页开启总开关。"
                )
                return
            parts = body.split(maxsplit=1)
            key = parts[0].strip()
            hint = parts[1].strip() if len(parts) > 1 else ""
            if key not in AI_SCENES:
                yield event.plain_result(
                    f"❌ 未知场景「{key}」。\n可用：{', '.join(AI_SCENES)}"
                )
                return
            yield event.plain_result(f"🤖 正在生成「{AI_SCENES[key]['label']}」…")
            text = await self.ai_generate_template(key, hint, group_id)
            if not text:
                yield event.plain_result("❌ AI 生成失败（模型未配置 / 超时）。请稍后重试。")
                return
            yield event.plain_result(
                f"🤖 【AI 生成·{AI_SCENES[key]['label']}】\n"
                f"━━━━━━━━━━━━\n{text}\n━━━━━━━━━━━━\n"
                f"采纳为正式内容：/运营 采纳 {key}"
            )
            self._ai_draft = getattr(self, "_ai_draft", {})
            self._ai_draft[f"{group_id}#{key}"] = text
            return

        # ---- 采纳 AI 草稿：/运营 采纳 <模板key> ----
        if arg.startswith("采纳"):
            key = arg.replace("采纳", "").strip()
            drafts = getattr(self, "_ai_draft", {})
            text = drafts.get(f"{group_id}#{key}", "")
            if not key or not text:
                yield event.plain_result("❌ 没有找到该场景的 AI 草稿，请先 /运营 ai <key> 生成。")
                return
            cfg = self.store.data.setdefault("config", {})
            cfg.setdefault("template_overrides", {})[key] = text
            if key == "welcome":
                cfg["welcome_text"] = text
            await self.store.asave()
            yield event.plain_result(f"✅ 已采纳为「{TEMPLATES.get(key, {}).get('name', key)}」的正式内容。")
            return

        yield event.plain_result(self._help_text())

    @filter.command("签到")
    async def cmd_sign(self, event: AstrMessageEvent):
        """手动签到（自动化已默认每日结算，此为额外加分）：/签到"""
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        name = event.get_sender_name() or user_id
        if not group_id:
            yield event.plain_result("❌ 签到请在群内进行。")
            return
        # 签到总开关（关闭后本插件不再接管签到，避免与其他签到插件重复回复）
        if not self._points_cfg().get("sign_enabled", True):
            return
        today = _bj_now().strftime("%Y-%m-%d")
        u = self.store.get_user(group_id, user_id, name)
        if u.get("last_sign") == today:
            yield event.plain_result(f"ℹ️ {name} 今天已经签到过了，当前积分 {u.get('points', 0)}。")
            return
        u["last_sign"] = today
        gain = self._rule("sign")
        pts = self.store.add_points(group_id, user_id, gain, name)
        await self.store.asave()
        yield event.plain_result(
            f"✅ {name} 签到成功！+{gain} 积分，当前共 {pts} 分。\n"
            "（发言、开黑、邀请好友也会自动加分 🎁）"
        )

    @filter.command("积分")
    async def cmd_points(self, event: AstrMessageEvent):
        """查询积分：/积分"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("❌ 请在群内查询。")
            return
        user_id = str(event.get_sender_id() or "")
        name = event.get_sender_name() or user_id
        u = self.store.get_user(group_id, user_id, name)
        yield event.plain_result(
            f"🏅 {name} 的群积分\n"
            f"当前积分：{u.get('points', 0)}\n"
            f"累计邀请：{u.get('invites', 0)} 人\n"
            f"今日签到：{'已签' if u.get('last_sign') == _bj_now().strftime('%Y-%m-%d') else '未签'}"
        )

    @filter.command("积分榜")
    async def cmd_leaderboard(self, event: AstrMessageEvent):
        """查看积分排行榜：/积分榜"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("❌ 请在群内查看。")
            return
        rows = self.store.leaderboard(group_id, top=10)
        if not rows:
            yield event.plain_result("📭 还没有人攒积分，快去群里发言（自动加分）！")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 【群积分排行榜·Top10】"]
        for i, r in enumerate(rows):
            icon = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{icon} {r['name']} — {r['points']} 分（邀请 {r['invites']} 人）")
        lines.append("积分可兑换皮肤碎片/红包，发言即自动加分~")
        yield event.plain_result("\n".join(lines))

    @filter.command("邀请")
    async def cmd_invite(self, event: AstrMessageEvent):
        """记录邀请新人的积分：/邀请（受每日次数限制保护，防刷分）"""
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        name = event.get_sender_name() or user_id
        if not group_id:
            yield event.plain_result("❌ 请在群内使用。")
            return
        cfg = self._points_cfg()
        limit = int(cfg.get("invite_daily_limit", 0) or 0)
        left = self.store.invite_quota_left(group_id, user_id, limit)
        if left <= 0:
            yield event.plain_result(
                f"ℹ️ {name} 今天记录的邀请已达上限（{limit} 次/天），明天再来吧~"
            )
            return
        gain = self._rule("invite")
        invites = self.store.add_invite(group_id, user_id, name, points=gain)
        pts = self.store.get_user(group_id, user_id, name).get("points", 0)
        await self.store.asave()
        left_after = self.store.invite_quota_left(group_id, user_id, limit)
        tail = f"（今日还可记录 {left_after} 次）" if limit > 0 else ""
        yield event.plain_result(
            f"✅ 已记录 {name} 的邀请 +1（累计 {invites} 人），"
            f"+{gain} 积分，当前 {pts} 分。{tail}"
        )

    @filter.command("邀请记录")
    async def cmd_invite_log(self, event: AstrMessageEvent):
        """查看本群邀请记录（自动记录）：/邀请记录"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("❌ 请在群内使用。")
            return
        rows = self.store.invite_log_of(group_id, 20)
        if not rows:
            yield event.plain_result("📭 本群暂无邀请记录。有新人被拉进群时会自动记录~")
            return
        lines = ["📨 【本群邀请记录】最近 20 条", "━━━━━━━━━━━━"]
        for r in rows:
            who = r.get("inviter_name") or r.get("inviter") or "待认领"
            new = r.get("invitee_name") or r.get("invitee") or "?"
            tag = f"+{int(r.get('points', 0) or 0)} 分" if r.get("counted") else "未计分"
            lines.append(f"· {who} 邀请 {new}（{tag}）")
        total = len((self.store.data.get("invite_log", {}) or {}).get(group_id) or [])
        lines.append("━━━━━━━━━━━━")
        lines.append(f"本群累计记录 {total} 次邀请 · 邀请分值 {self._rule('invite')} 分/人")
        yield event.plain_result("\n".join(lines))

    @filter.command("答题")
    async def cmd_quiz(self, event: AstrMessageEvent):
        """出题/查看当前题目：/答题（直接出下一题），/答题 看"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("❌ 请在群内使用。")
            return
        cfg = self._quiz_cfg()
        if not cfg.get("quiz_enabled", True):
            yield event.plain_result("ℹ️ 答题活动当前已关闭。")
            return
        arg = (event.message_str or "").replace("/答题", "").strip()

        if arg in ("看", "当前", "status"):
            act = self.quiz_active_of(group_id)
            if not act:
                yield event.plain_result("🕳️ 当前没有进行中的题目。发「/答题」开一题。")
                return
            winners = act.get("winners") or []
            left = ""
            limit = int(act.get("limit", 0))
            if limit > 0:
                left = f"\n剩余名额：{max(0, limit - len(winners))} 个"
            yield event.plain_result(
                f"🧠 当前题目：\n{act.get('q', '')}\n"
                f"奖励：答对 +{act.get('reward', 0)} 分{left}"
            )
            return

        text = await self.quiz_start(group_id)
        if not text:
            if self.quiz_active_of(group_id):
                act = self.quiz_active_of(group_id)
                yield event.plain_result(
                    f"⏳ 上一题还没结束：\n{act.get('q', '')}\n直接回答案就行~"
                )
            else:
                yield event.plain_result("ℹ️ 暂时无法出题（活动未开启或本群未绑定）。")
            return
        yield event.plain_result(text)

    @filter.command("兑换")
    async def cmd_redeem(self, event: AstrMessageEvent):
        """查看积分兑换表：/兑换"""
        cfg = self._points_cfg()
        items = [i for i in (cfg.get("redeem_items") or []) if i.get("enabled", True)]
        if not items:
            yield event.plain_result("ℹ️ 暂未配置兑换项，请联系群管理。")
            return
        lines = ["🎁 【积分兑换表】", "━━━━━━━━━━━━"]
        for it in items:
            lines.append(f"· {it.get('name','')} —— {int(it.get('cost',0))} 分"
                         + (f"（{it.get('desc')}）" if it.get("desc") else ""))
        note = cfg.get("redeem_note") or ""
        if note:
            lines.append("━━━━━━━━━━━━")
            lines.append(note)
        yield event.plain_result("\n".join(lines))

    @filter.command("运营数据")
    async def cmd_stats(self, event: AstrMessageEvent):
        """查看群运营数据（自动采集）：/运营数据"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("❌ 请在群内查看。")
            return
        stats = self.store.get_stats(group_id)
        if not stats:
            yield event.plain_result(
                "📭 本群暂无数据。自动化采集会在绑定后 30 分钟内自动生成首条记录，"
                "也可发送 /运营 采集 立即采集。"
            )
            return
        latest = stats[-1]
        total = latest.get("total", 0) or 1
        rate = round(latest.get("active", 0) / total * 100, 1)
        yield event.plain_result(
            f"📈 【本群运营数据】\n"
            f"日期：{latest.get('date')}（{'自动采集' if latest.get('auto') else '手动录入'}）\n"
            f"群人数：{latest.get('total', 0)}\n"
            f"新增：+{latest.get('new', 0)}　退群：-{latest.get('leave', 0)}\n"
            f"发言人数：{latest.get('active', 0)}\n"
            f"日活率：{rate}%"
        )

    def _feature_cmd(self, group_id: str, arg: str) -> str:
        """/运营 功能 [名称] [on|off] —— 查看或切换本群功能开关。"""
        if not group_id:
            return "❌ 请在群里执行此命令。"
        g = self.store.bound_groups().get(group_id)
        if not g:
            return "ℹ️ 本群尚未绑定，请先 /运营 绑定。"

        parts = arg.split()
        feats = g.get("features") or {}
        flag = lambda b: "✅" if b else "⛔"  # noqa: E731

        # 仅查看
        if len(parts) < 2:
            lines = [
                "🎛️ 【本群功能开关】",
                "━━━━━━━━━━━━━",
                f"总开关：{'✅ 运行中' if g.get('enabled', True) else '⛔ 已停用'}",
                "── 单项功能 ──",
            ]
            for k, label in GROUP_FEATURES.items():
                lines.append(f"{flag(feats.get(k, True))} {k} —— {label}")
            lines.append("")
            lines.append("用法：/运营 功能 <功能名> on|off")
            lines.append("例如：/运营 功能 wake off")
            return "\n".join(lines)

        name = parts[1].strip()
        if name not in GROUP_FEATURES:
            return (
                f"❌ 未知功能「{name}」。\n"
                f"可选：{', '.join(GROUP_FEATURES)}"
            )
        if len(parts) < 3:
            cur = feats.get(name, True)
            return f"ℹ️ 本群「{GROUP_FEATURES[name]}」当前：{'开启' if cur else '关闭'}"

        val = parts[2].strip().lower()
        if val in ("on", "1", "true", "开", "开启", "启用"):
            enabled = True
        elif val in ("off", "0", "false", "关", "关闭", "停用"):
            enabled = False
        else:
            return "❌ 请使用 on / off"

        self.store.set_group_feature(group_id, name, enabled)
        # 命令是同步返回，这里直接落盘（下次 asave 也会写）
        self.store.save()
        return f"{'✅ 已开启' if enabled else '⛔ 已关闭'}本群「{GROUP_FEATURES[name]}」"

    def _welcome_cmd(self, group_id: str, arg: str) -> str:
        """/运营 欢迎词 [内容|查看|重置] —— 自定义入群欢迎语。"""
        if not group_id:
            return "❌ 请在群里执行此命令。"
        cfg = self.store.data.setdefault("config", {})
        body = arg[len("欢迎词"):].strip() if arg.startswith("欢迎词") else arg[len("welcome"):].strip()

        if not body or body in ("查看", "show"):
            cur = str(cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT)
            demo = self._welcome_text(group_id, "示例昵称")
            return (
                "📝 【当前入群欢迎词】\n"
                "━━━━━━━━━━━━━\n"
                f"{cur}\n"
                "━━━━━━━━━━━━━\n"
                "可用占位符：{nickname} 新人昵称、{group_no} 群号、{date} 日期\n\n"
                "【渲染效果预览】\n"
                f"{demo}\n\n"
                "修改：/运营 欢迎词 <新内容>\n"
                "恢复默认：/运营 欢迎词 重置"
            )

        if body in ("重置", "reset", "默认"):
            cfg["welcome_text"] = DEFAULT_WELCOME_TEXT
            self.store.save()
            return f"✅ 已恢复默认欢迎词。\n\n当前内容：\n{DEFAULT_WELCOME_TEXT}"

        cfg["welcome_text"] = body
        self.store.save()
        demo = self._welcome_text(group_id, "示例昵称")
        return (
            "✅ 入群欢迎词已更新（对所有启用欢迎的群生效）。\n\n"
            "【渲染效果预览】\n"
            f"{demo}"
        )

    def _status_text(self, group_id: str) -> str:
        auto = self.store.data.get("automation", {})
        cfg = self.store.data.get("config", {})
        groups = self.store.bound_groups()

        def flag(b: bool) -> str:
            return "✅" if b else "⛔"

        lines = [
            "🤖 【自动化运营引擎·运行状态】",
            "━━━━━━━━━━━━━",
            f"已绑定群：{len(groups)} 个（启用 {len(self.store.enabled_groups())} 个）",
            f"引擎：{'运行中' if self._engine_task and not self._engine_task.done() else '已停止'}",
            "── 自动化任务 ──",
            f"{flag(auto.get('auto_collect', True))} 数据采集（每 {int(auto.get('collect_interval', 1800)) // 60} 分钟）",
            f"{flag(auto.get('auto_followup', True))} 新人跟进（30min/24h/72h）",
            f"{flag(auto.get('auto_cold_rescue', True))} 冷场救场（{int(auto.get('cold_threshold', 7200)) // 60} 分钟无消息）",
            f"{flag(auto.get('auto_wake', True))} 沉睡唤醒（{auto.get('wake_days', 7)} 天未发言）",
            f"{flag(auto.get('auto_settle', True))} 积分自动结算",
            f"{flag(auto.get('auto_daily_report', True))} 运营日报（{auto.get('report_time', '23:30')}）",
            f"{flag(auto.get('auto_weekly_board', True))} 周榜发布（{auto.get('weekly_board_time', '21:00')}）",
            f"{flag(auto.get('auto_reply', True))} 关键词应答",
            f"{flag(cfg.get('auto_welcome', True))} 入群自动欢迎",
            f"{flag(cfg.get('schedule_enabled', True))} SOP 定时推送",
        ]
        if group_id:
            g = groups.get(group_id)
            act = self.store.activity_of(group_id)
            members = act.get("members", {})
            if not g:
                lines += ["", "⚠️ 本群尚未绑定，发送 /运营 绑定 即可接管。"]
            else:
                feats = g.get("features") or {}
                lines += [
                    "── 本群状态 ──",
                    f"总开关：{'✅ 运行中' if g.get('enabled', True) else '⛔ 已停用'}",
                    f"已记录成员：{len(members)} 人",
                    f"待跟进新人：{len(self.store.followup_of(group_id))} 人",
                    "── 本群功能 ──",
                ]
                for k, label in GROUP_FEATURES.items():
                    lines.append(f"{flag(feats.get(k, True))} {label}")
                lines.append("")
                lines.append("调整：/运营 功能 <功能名> on|off ｜ /运营 关闭")
        return "\n".join(lines)

    def _help_text(self) -> str:
        return (
            "🎮 【王者荣耀群·自动化运营引擎】\n"
            "━━━━━━━━━━━━━━\n"
            "【群管理命令】\n"
            "/运营 绑定 —— 绑定本群，自动化引擎接管\n"
            "/运营 状态 —— 查看运行状态与本群功能开关\n"
            "/运营 关闭 / 开启 —— 单独停用/恢复本群自动化\n"
            "/运营 功能 —— 查看本群各项功能开关\n"
            "/运营 功能 <名称> on|off —— 单项功能开关\n"
            "/运营 欢迎词 —— 查看/修改入群欢迎语\n"
            "/运营 采集 —— 立即采集一次群数据\n"
            "/运营 发送 <key> —— 手动推送模板\n"
            "/运营 救场 —— 推送冷场救场话题\n"
            "/运营数据 —— 查看自动采集的运营数据\n"
            "/运营 ai <key> —— 用 AI 生成话术（需先开启 AI）\n"
            "/运营 采纳 <key> —— 采纳 AI 生成的话术\n\n"
            "【群成员命令】\n"
            "/签到 /积分 /积分榜 /邀请 /邀请记录 /兑换\n\n"
            "━━━━━━━━━━━━━━\n"
            "⚡ 绑定后全自动：数据采集·新人跟进·冷场救场·沉睡唤醒\n"
            "　 积分结算·日报周榜·关键词应答·SOP推送·入群欢迎\n"
            f"可用模板：{', '.join(TEMPLATES)}\n"
            f"可开关功能：{', '.join(GROUP_FEATURES)}\n"
            "可视化作战台：WebUI → 插件 → 王者荣耀私域运营助手"
        )

    # ==================================================================
    # WebUI 后端 API
    # ==================================================================
    def _register_web_apis(self) -> None:
        api = self.context.register_web_api
        try:
            api(f"/{PLUGIN_NAME}/status", self.api_status, ["GET"], "插件状态")
            api(f"/{PLUGIN_NAME}/templates", self.api_templates, ["GET"], "话术模板列表")
            api(f"/{PLUGIN_NAME}/send", self.api_send, ["POST"], "推送内容到群")
            api(f"/{PLUGIN_NAME}/groups", self.api_groups, ["GET"], "已绑定群列表")
            api(f"/{PLUGIN_NAME}/groups/scan", self.api_groups_scan, ["GET"], "扫描机器人所在群")
            api(f"/{PLUGIN_NAME}/group/bind", self.api_group_bind, ["POST"], "绑定 / 解绑群")
            api(f"/{PLUGIN_NAME}/group/toggle", self.api_group_toggle, ["POST"], "群开关 / 功能开关")
            api(f"/{PLUGIN_NAME}/welcome", self.api_welcome_get, ["GET"], "获取入群欢迎词")
            api(f"/{PLUGIN_NAME}/welcome/save", self.api_welcome_save, ["POST"], "保存入群欢迎词")
            api(f"/{PLUGIN_NAME}/points", self.api_points, ["GET"], "积分榜")
            api(f"/{PLUGIN_NAME}/points/config", self.api_points_config_get, ["GET"], "获取积分配置")
            api(f"/{PLUGIN_NAME}/points/config/save", self.api_points_config_save, ["POST"], "保存积分配置")
            api(f"/{PLUGIN_NAME}/points/adjust", self.api_points_adjust, ["POST"], "调整积分")
            api(f"/{PLUGIN_NAME}/points/reset", self.api_points_reset, ["POST"], "清空积分")
            api(f"/{PLUGIN_NAME}/invite/log", self.api_invite_log, ["GET"], "邀请记录明细")
            api(f"/{PLUGIN_NAME}/invite/manual", self.api_invite_manual, ["POST"], "手动补录邀请")
            api(f"/{PLUGIN_NAME}/invite/claim", self.api_invite_claim, ["POST"], "认领待归属邀请")
            api(f"/{PLUGIN_NAME}/invite/undo", self.api_invite_undo, ["POST"], "撤销邀请记录")
            api(f"/{PLUGIN_NAME}/schedule", self.api_schedule_get, ["GET"], "获取推送计划")
            api(f"/{PLUGIN_NAME}/schedule/save", self.api_schedule_save, ["POST"], "保存推送计划")
            api(f"/{PLUGIN_NAME}/stats", self.api_stats_get, ["GET"], "获取运营数据")
            api(f"/{PLUGIN_NAME}/stats/add", self.api_stats_add, ["POST"], "录入运营数据")
            api(f"/{PLUGIN_NAME}/config/save", self.api_config_save, ["POST"], "保存插件配置")
            api(f"/{PLUGIN_NAME}/automation", self.api_auto_get, ["GET"], "获取自动化配置")
            api(f"/{PLUGIN_NAME}/automation/save", self.api_auto_save, ["POST"], "保存自动化配置")
            api(f"/{PLUGIN_NAME}/automation/trigger", self.api_auto_trigger, ["POST"], "手动触发任务")
            api(f"/{PLUGIN_NAME}/activity", self.api_activity, ["GET"], "群活跃度数据")
            api(f"/{PLUGIN_NAME}/ai", self.api_ai_get, ["GET"], "获取 AI 配置")
            api(f"/{PLUGIN_NAME}/ai/save", self.api_ai_save, ["POST"], "保存 AI 配置")
            api(f"/{PLUGIN_NAME}/ai/generate", self.api_ai_generate, ["POST"], "AI 生成话术")
            api(f"/{PLUGIN_NAME}/ai/polish", self.api_ai_polish, ["POST"], "AI 润色话术")
            api(f"/{PLUGIN_NAME}/ai/apply", self.api_ai_apply, ["POST"], "采纳 AI 话术")
            api(f"/{PLUGIN_NAME}/ai/restore", self.api_ai_restore, ["POST"], "还原模板为内置版")
            api(f"/{PLUGIN_NAME}/ai/providers", self.api_ai_providers, ["GET"], "可用模型列表")
            api(f"/{PLUGIN_NAME}/quiz/config", self.api_quiz_config_get, ["GET"], "获取答题活动配置")
            api(f"/{PLUGIN_NAME}/quiz/config/save", self.api_quiz_config_save, ["POST"], "保存答题活动配置")
            api(f"/{PLUGIN_NAME}/quiz/start", self.api_quiz_start, ["POST"], "手动出一题")
            api(f"/{PLUGIN_NAME}/quiz/status", self.api_quiz_status, ["GET"], "查看各群进行中的题目")
            logger.info(f"[{PLUGIN_NAME}] WebUI API 路由注册完成")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 注册 WebUI API 失败: {e}")

    async def api_status(self):
        auto = self.store.data.get("automation", {})
        cfg = self.store.data.get("config", {})
        return json_response({
            "plugin": PLUGIN_NAME,
            "version": "1.3.0",
            "bound_groups": len(self.store.bound_groups()),
            "auto_welcome": cfg.get("auto_welcome", True),
            "schedule_enabled": cfg.get("schedule_enabled", True),
            "template_count": len(TEMPLATES),
            "engine_running": bool(self._engine_task and not self._engine_task.done()),
            "automation": {k: auto.get(k) for k in (
                "auto_collect", "auto_followup", "auto_cold_rescue", "auto_wake",
                "auto_settle", "auto_daily_report", "auto_weekly_board", "auto_reply"
            )},
        })

    async def api_templates(self):
        rows = [
            {"key": k, "name": v["name"], "slot": v.get("slot", ""), "content": v["content"]}
            for k, v in TEMPLATES.items()
        ]
        return json_response({"templates": rows})

    async def api_groups(self):
        """已绑定群列表（WebUI 展示与开关用）。"""
        groups = self.store.bound_groups()
        rows = []
        for gid, v in groups.items():
            feats = dict(DEFAULT_GROUP_FEATURES)
            feats.update(v.get("features") or {})
            rows.append({
                "group_id": gid,
                "name": v.get("name") or gid,
                "bound_at": v.get("bound_at", ""),
                "enabled": v.get("enabled", True),
                "features": feats,
            })
        return json_response({"groups": rows, "feature_labels": GROUP_FEATURES})

    async def api_groups_scan(self):
        """扫描机器人所在的所有群，供 WebUI 自助绑定。

        数据来源（三路合并，任一可用即可）：
          1. OneBot `get_group_list`（最准确，含全部群）
          2. 插件已记录的历史可见群（收到过消息的群）
          3. 已绑定群（补充名称）
        """
        bound = self.store.bound_groups()
        merged: dict[str, dict[str, Any]] = {}

        # 1) OneBot get_group_list
        live = []
        try:
            live = await self._fetch_bot_groups()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] get_group_list 失败: {e}")
        for g in live:
            merged[g["group_id"]] = {
                "group_id": g["group_id"],
                "name": g.get("name") or g["group_id"],
                "member_count": g.get("member_count") or 0,
                "source": "live",
            }

        # 2) 历史可见群
        for gid, nm in self._discovered_groups().items():
            if gid not in merged:
                merged[gid] = {
                    "group_id": gid,
                    "name": nm or gid,
                    "member_count": 0,
                    "source": "seen",
                }

        # 3) 已绑定群（补进列表，避免"已绑定但当前不在群"的群消失）
        for gid, v in bound.items():
            if gid not in merged:
                merged[gid] = {
                    "group_id": gid,
                    "name": v.get("name") or gid,
                    "member_count": 0,
                    "source": "bound",
                }
            else:
                # 已绑定群的名称以本地记录为准（可能是人工命名的）
                if v.get("name"):
                    merged[gid]["name"] = v["name"]

        rows = []
        for gid, m in merged.items():
            b = bound.get(gid)
            rows.append({
                **m,
                "bound": b is not None,
                "enabled": bool(b and b.get("enabled", True)),
            })
        # 已绑定优先，其次按群号
        rows.sort(key=lambda x: (not x["bound"], x["group_id"]))

        return json_response({
            "groups": rows,
            "live_available": bool(live),
            "live_count": len(live),
            "seen_count": len(self._discovered_groups()),
            "bound_count": len(bound),
        })

    async def api_group_bind(self):
        """从 WebUI 绑定 / 解绑一个群（无需在群里发指令）。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", "")).strip()
        if not group_id:
            return error_response("缺少 group_id", status_code=400)
        action = str(payload.get("action", "bind")).lower()
        name = str(payload.get("name", "")).strip()

        if action in ("unbind", "remove", "delete"):
            ok = self.store.unbind_group(group_id)
            await self.store.asave()
            if ok:
                return json_response({"ok": True, "group_id": group_id, "bound": False})
            return error_response("该群未绑定", status_code=404)

        # 绑定：补全群名（若没传则尝试即时查询）
        if not name:
            try:
                info = await self._fetch_group_info(group_id)
                name = str(info.get("group_name") or info.get("name") or "")
            except Exception:  # noqa: BLE001
                name = ""
        if not name:
            name = self._discovered_groups().get(group_id) or group_id

        self.store.bind_group(group_id, self._umo_for_group(group_id), name)
        await self.store.asave()
        return json_response({
            "ok": True, "group_id": group_id, "bound": True, "name": name,
        })

    async def api_group_toggle(self):
        """启用/停用某个群，或切换该群的单项功能。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", ""))
        if not group_id:
            return error_response("缺少 group_id", status_code=400)
        if group_id not in self.store.bound_groups():
            return error_response("该群未绑定", status_code=404)

        if "enabled" in payload:
            self.store.set_group_enabled(group_id, bool(payload["enabled"]))
        feature = str(payload.get("feature", ""))
        if feature:
            if feature not in GROUP_FEATURES:
                return error_response(f"未知功能 {feature}", status_code=400)
            self.store.set_group_feature(group_id, feature, bool(payload.get("value", True)))
        await self.store.asave()
        g = self.store.bound_groups().get(group_id, {})
        return json_response({
            "group_id": group_id,
            "enabled": g.get("enabled", True),
            "features": g.get("features") or {},
        })

    async def api_welcome_get(self):
        cfg = self.store.data.get("config", {})
        cur = str(cfg.get("welcome_text") or DEFAULT_WELCOME_TEXT)
        demo = self._welcome_text("", "示例昵称")
        return json_response({
            "welcome_text": cur,
            "default_text": DEFAULT_WELCOME_TEXT,
            "is_default": cur.strip() == DEFAULT_WELCOME_TEXT.strip(),
            "preview": demo,
        })

    async def api_welcome_save(self):
        payload = await request.json(default={})
        text = str(payload.get("welcome_text", ""))
        if "reset" in payload and payload["reset"]:
            text = DEFAULT_WELCOME_TEXT
        if not text.strip():
            return error_response("欢迎词不能为空", status_code=400)
        self.store.data.setdefault("config", {})["welcome_text"] = text
        await self.store.asave()
        return json_response({
            "saved": True,
            "welcome_text": text,
            "preview": self._welcome_text("", "示例昵称"),
        })

    async def api_send(self):
        payload = await request.json(default={})
        key = str(payload.get("template", ""))
        group_id = str(payload.get("group_id", ""))
        custom = payload.get("content")
        if key not in TEMPLATES and not custom:
            return error_response("template 不存在且未提供自定义内容", status_code=400)
        groups = self.store.enabled_groups()
        if not groups:
            return error_response("没有可用的群（未绑定或已全部停用）", status_code=400)
        if group_id:
            if group_id not in groups:
                return error_response(f"群 {group_id} 未绑定或已停用", status_code=400)
            targets = {group_id: groups[group_id]}
        else:
            targets = groups
        text_tpl = custom if custom else TEMPLATES[key]["content"]
        sent, failed, errors = 0, 0, []
        for gid, info in targets.items():
            try:
                text = self._render(key, gid) if not custom else text_tpl
                # _send_to：异常或平台不可达（返回 False）均计失败
                ok = await self._send_to(
                    info.get("umo", ""), MessageChain().message(text), f"WebUI 推送 {gid}"
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                    errors.append(f"{gid}: 平台不可达（QQ 适配器是否在线？）")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] WebUI 推送失败 group={gid}: {e}")
                failed += 1
                errors.append(f"{gid}: {e}")
        return json_response({
            "sent": sent, "failed": failed, "total": len(targets),
            "errors": errors[:3],
        })

    async def api_points(self):
        group_id = request.query.get("group_id", "")
        groups = self.store.enabled_groups() or self.store.bound_groups()
        if not group_id:
            group_id = next(iter(groups), "")
        if not group_id:
            return json_response({"group_id": "", "leaderboard": []})
        return json_response({
            "group_id": group_id,
            "leaderboard": self.store.leaderboard(group_id, top=50),
        })

    async def api_points_adjust(self):
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", ""))
        user_id = str(payload.get("user_id", ""))
        try:
            delta = int(payload.get("delta", 0))
        except (TypeError, ValueError):
            return error_response("delta 必须是整数", status_code=400)
        if not group_id or not user_id:
            return error_response("缺少 group_id 或 user_id", status_code=400)
        pts = self.store.add_points(group_id, user_id, delta)
        await self.store.asave()
        return json_response({"user_id": user_id, "points": pts})

    async def api_points_reset(self):
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", ""))
        if group_id:
            self.store.data["points"][group_id] = {}
        else:
            self.store.data["points"] = {}
        await self.store.asave()
        return json_response({"reset": True, "group_id": group_id or "ALL"})

    async def api_points_config_get(self):
        cfg = self._points_cfg()
        return json_response({
            "config": cfg,
            "rule_meta": POINT_RULE_META,
        })

    async def api_points_config_save(self):
        payload = await request.json(default={})
        cfg = self._points_cfg()
        # 规则数值
        rules = payload.get("rules")
        if isinstance(rules, dict):
            for k, v in rules.items():
                if k not in cfg["rules"]:
                    continue
                try:
                    cfg["rules"][k] = max(0, min(999, int(v)))
                except (TypeError, ValueError):
                    pass
        # 邀请每日上限
        if "invite_daily_limit" in payload:
            try:
                cfg["invite_daily_limit"] = max(0, min(999, int(payload["invite_daily_limit"])))
            except (TypeError, ValueError):
                pass
        # 签到总开关
        if "sign_enabled" in payload:
            cfg["sign_enabled"] = bool(payload["sign_enabled"])
        # 邀请自动捕获相关
        for flag in ("auto_invite", "invite_broadcast", "count_on_approve"):
            if flag in payload:
                cfg[flag] = bool(payload[flag])
        if "invite_broadcast_text" in payload:
            cfg["invite_broadcast_text"] = (
                str(payload["invite_broadcast_text"] or "").strip() or DEFAULT_INVITE_BROADCAST
            )
        if "default_inviter" in payload:
            cfg["default_inviter"] = re.sub(r"\D", "", str(payload["default_inviter"] or ""))[:12]
        # 兑换表
        if isinstance(payload.get("redeem_items"), list):
            items = []
            for it in payload["redeem_items"]:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name", "")).strip()
                if not name:
                    continue
                try:
                    cost = max(0, min(999999, int(it.get("cost", 0))))
                except (TypeError, ValueError):
                    cost = 0
                items.append({
                    "name": name,
                    "cost": cost,
                    "desc": str(it.get("desc", "")).strip(),
                    "enabled": bool(it.get("enabled", True)),
                })
            cfg["redeem_items"] = items
        if "redeem_note" in payload:
            cfg["redeem_note"] = str(payload["redeem_note"] or "").strip()
        self.store.data["points_config"] = cfg
        await self.store.asave()
        return json_response({"saved": True, "config": cfg})

    # ---------------- 邀请记录（自动捕获 / 手动补录 / 认领 / 撤销） ----------------
    def _name_of(self, group_id: str, uid: str) -> str:
        """取已知群昵称（未知则返回空，避免把 QQ 号当昵称展示）。"""
        if not uid:
            return ""
        try:
            u = self.store.get_user(group_id, uid)
        except Exception:  # noqa: BLE001
            return ""
        nm = str(u.get("name") or "")
        return "" if nm == str(uid) else nm

    def _invite_credit(self, group_id: str, inviter: str) -> tuple[int, bool]:
        """按配置给邀请人计分；返回 (得分, 是否已计分)。"""
        if not inviter:
            return 0, False
        cfg = self._points_cfg()
        limit = int(cfg.get("invite_daily_limit", 0) or 0)
        if self.store.invite_quota_left(group_id, inviter, limit) <= 0:
            return 0, False
        gain = self._rule("invite")
        self.store.add_invite(group_id, inviter, self._name_of(group_id, inviter), points=gain)
        return gain, True

    async def api_invite_log(self):
        groups = self.store.bound_groups()
        group_id = str(request.query.get("group_id", "") or "").strip()
        if not group_id or group_id not in groups:
            group_id = next(iter(groups), "")
        try:
            limit = max(1, min(200, int(request.query.get("limit", 100))))
        except (TypeError, ValueError):
            limit = 100

        rows = self.store.invite_log_of(group_id, limit) if group_id else []
        all_rows = (self.store.data.get("invite_log", {}) or {}).get(group_id) or []

        summary: dict[str, dict[str, Any]] = {}
        for r in all_rows:
            who = str(r.get("inviter") or "")
            key = who or "__unclaimed__"
            s = summary.setdefault(key, {
                "inviter": who,
                "name": (r.get("inviter_name") or "") or ("待认领" if not who else who),
                "count": 0,
                "points": 0,
            })
            s["count"] += 1
            s["points"] += int(r.get("points", 0) or 0)

        cfg = self._points_cfg()
        return json_response({
            "group_id": group_id,
            "groups": [
                {"group_id": g, "name": (v or {}).get("name") or g}
                for g, v in groups.items()
            ],
            "entries": rows,
            "summary": sorted(summary.values(), key=lambda x: (x["count"], x["points"]), reverse=True),
            "total": len(all_rows),
            "unclaimed": sum(1 for r in all_rows if not r.get("inviter")),
            "config": {
                "auto_invite": bool(cfg.get("auto_invite", True)),
                "invite_broadcast": bool(cfg.get("invite_broadcast", True)),
                "invite_broadcast_text": str(cfg.get("invite_broadcast_text") or DEFAULT_INVITE_BROADCAST),
                "count_on_approve": bool(cfg.get("count_on_approve", False)),
                "default_inviter": str(cfg.get("default_inviter") or ""),
                "invite_points": self._rule("invite"),
                "invite_daily_limit": int(cfg.get("invite_daily_limit", 0) or 0),
            },
        })

    async def api_invite_manual(self):
        """手动补录一次邀请（自动捕获漏记时使用）。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", "") or "").strip()
        inviter = re.sub(r"\D", "", str(payload.get("inviter", "") or ""))[:12]
        invitee = re.sub(r"\D", "", str(payload.get("invitee", "") or ""))[:12]
        if group_id not in self.store.bound_groups():
            return error_response("请选择已绑定的群", status_code=400)
        if not inviter:
            return error_response("请填写邀请人 QQ", status_code=400)
        if not invitee:
            return error_response("请填写被邀请人 QQ", status_code=400)
        if inviter == invitee:
            return error_response("邀请人和被邀请人不能是同一个 QQ", status_code=400)
        if self.store.invitee_recorded(group_id, invitee):
            return error_response("该 QQ 已有邀请记录（同一新人只记一次）", status_code=409)

        points, counted = self._invite_credit(group_id, inviter)
        entry: dict[str, Any] = {
            "inviter": inviter,
            "inviter_name": self._name_of(group_id, inviter),
            "invitee": invitee,
            "invitee_name": self._name_of(group_id, invitee) or f"新同学{invitee[-4:]}",
            "ts": time.time(),
            "time": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
            "date": _bj_now().strftime("%Y-%m-%d"),
            "source": "manual",
            "sub_type": "manual",
            "points": points,
            "counted": counted,
            "note": str(payload.get("note", "") or "").strip(),
        }
        self.store.add_invite_log(group_id, entry)
        await self.store.asave()
        return json_response({"ok": True, "entry": entry, "counted": counted, "points": points})

    async def api_invite_claim(self):
        """给「待认领」记录指定邀请人并补计分。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", "") or "").strip()
        inviter = re.sub(r"\D", "", str(payload.get("inviter", "") or ""))[:12]
        if group_id not in self.store.bound_groups():
            return error_response("请选择已绑定的群", status_code=400)
        if not inviter:
            return error_response("请填写邀请人 QQ", status_code=400)
        rec = self.store.find_invite_log(group_id, payload.get("ts"))
        if not rec:
            return error_response("找不到该邀请记录", status_code=404)
        if rec.get("inviter"):
            return error_response("该记录已有邀请人", status_code=400)
        if str(rec.get("invitee")) == inviter:
            return error_response("邀请人和被邀请人不能是同一个 QQ", status_code=400)

        points, counted = self._invite_credit(group_id, inviter)
        rec["inviter"] = inviter
        rec["inviter_name"] = self._name_of(group_id, inviter)
        rec["points"] = points
        rec["counted"] = counted
        rec["source"] = "auto" if counted else "limit"
        rec["claimed_at"] = _bj_now().strftime("%Y-%m-%d %H:%M:%S")
        await self.store.asave()

        cfg = self._points_cfg()
        if counted and cfg.get("invite_broadcast", True):
            await self._broadcast_invite(
                group_id,
                rec.get("inviter_name") or inviter,
                rec.get("invitee_name") or str(rec.get("invitee") or ""),
                points,
                cfg,
            )
        return json_response({"ok": True, "entry": rec})

    async def api_invite_undo(self):
        """撤销一条邀请记录（已计分的会扣回积分与邀请数）。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", "") or "").strip()
        if group_id not in self.store.bound_groups():
            return error_response("请选择已绑定的群", status_code=400)
        rec = self.store.remove_invite_log(group_id, payload.get("ts"))
        if not rec:
            return error_response("找不到该邀请记录", status_code=404)
        if rec.get("counted") and rec.get("inviter"):
            self.store.revoke_invite(group_id, str(rec["inviter"]), int(rec.get("points", 0) or 0))
        await self.store.asave()
        return json_response({"ok": True, "removed": rec})

    async def api_schedule_get(self):
        return json_response({
            "schedule": self.store.data.get("schedule", []),
            "enabled": self.store.data.get("config", {}).get("schedule_enabled", True),
        })

    async def api_schedule_save(self):
        payload = await request.json(default={})
        schedule = payload.get("schedule")
        if schedule is not None:
            if not isinstance(schedule, list):
                return error_response("schedule 必须是列表", status_code=400)
            cleaned = []
            for item in schedule:
                if not isinstance(item, dict):
                    continue
                t = str(item.get("time", "")).strip()
                tpl = str(item.get("template", "")).strip()
                if not t or tpl not in TEMPLATES:
                    continue
                cleaned.append({"time": t, "template": tpl, "enabled": bool(item.get("enabled", True))})
            self.store.data["schedule"] = cleaned
        if "enabled" in payload:
            self.store.data.setdefault("config", {})["schedule_enabled"] = bool(payload["enabled"])
        await self.store.asave()
        return json_response({"saved": True, "count": len(self.store.data.get("schedule", []))})

    async def api_stats_get(self):
        group_id = request.query.get("group_id", "")
        groups = self.store.enabled_groups() or self.store.bound_groups()
        if not group_id:
            group_id = next(iter(groups), "")
        return json_response({
            "group_id": group_id,
            "stats": self.store.get_stats(group_id) if group_id else [],
        })

    async def api_stats_add(self):
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", ""))
        if not group_id:
            groups = self.store.enabled_groups() or self.store.bound_groups()
            group_id = next(iter(groups), "")
        if not group_id:
            return error_response("尚未绑定群，无法录入数据", status_code=400)
        record = {
            "date": str(payload.get("date") or _bj_now().strftime("%Y-%m-%d")),
            "total": int(payload.get("total", 0) or 0),
            "new": int(payload.get("new", 0) or 0),
            "leave": int(payload.get("leave", 0) or 0),
            "active": int(payload.get("active", 0) or 0),
            "team": int(payload.get("team", 0) or 0),
            "auto": False,
        }
        self.store.add_stat(group_id, record)
        await self.store.asave()
        return json_response({"saved": True, "record": record})

    async def api_config_save(self):
        payload = await request.json(default={})
        cfg = self.store.data.setdefault("config", {})
        if "auto_welcome" in payload:
            cfg["auto_welcome"] = bool(payload["auto_welcome"])
        if "schedule_enabled" in payload:
            cfg["schedule_enabled"] = bool(payload["schedule_enabled"])
        if "topic_pool" in payload and isinstance(payload["topic_pool"], list):
            cfg["topic_pool"] = [str(x) for x in payload["topic_pool"] if str(x).strip()]
        await self.store.asave()
        return json_response({"saved": True})

    # --- 自动化配置 ---
    async def api_auto_get(self):
        auto = self.store.data.get("automation", {})
        return json_response({
            "automation": auto,
            "reply_rules": auto.get("reply_rules", []),
            "running": bool(self._engine_task and not self._engine_task.done()),
        })

    async def api_auto_save(self):
        payload = await request.json(default={})
        auto = self.store.data.setdefault("automation", {})
        bool_keys = ["auto_collect", "auto_followup", "auto_cold_rescue", "auto_wake",
                     "auto_settle", "auto_daily_report", "auto_weekly_board", "auto_reply",
                     "report_to_group"]
        # (最小值, 最大值)：超出范围则钳制，避免存入非法值
        int_ranges = {
            "collect_interval": (60, 86400),
            "cold_threshold": (300, 86400),
            "cold_cooldown": (300, 86400),
            "active_hour_start": (0, 23),
            "active_hour_end": (1, 24),
            "wake_days": (1, 365),
            "wake_cooldown": (3600, 2592000),
            "wake_max_per_round": (1, 50),
            "weekly_board_weekday": (0, 6),
            "reply_cooldown": (0, 86400),
        }
        for k in bool_keys:
            if k in payload:
                auto[k] = bool(payload[k])
        for k, (lo, hi) in int_ranges.items():
            if k in payload:
                try:
                    auto[k] = max(lo, min(hi, int(payload[k])))
                except (TypeError, ValueError):
                    pass
        # 活跃时段必须 起 < 止，否则回退默认
        if int(auto.get("active_hour_start", 9)) >= int(auto.get("active_hour_end", 23)):
            auto["active_hour_start"] = 9
            auto["active_hour_end"] = 23

        def _valid_hhmm(v: Any, fallback: str) -> str:
            s = str(v or "").strip()
            try:
                h, m = s.split(":")
                if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
                    return f"{int(h):02d}:{int(m):02d}"
            except (ValueError, AttributeError):
                pass
            return fallback

        if "report_time" in payload:
            auto["report_time"] = _valid_hhmm(payload["report_time"], "23:30")
        if "report_admin_qq" in payload:
            auto["report_admin_qq"] = str(payload["report_admin_qq"]).strip()
        if "weekly_board_time" in payload:
            auto["weekly_board_time"] = _valid_hhmm(payload["weekly_board_time"], "21:00")
        if "reply_rules" in payload and isinstance(payload["reply_rules"], list):
            rules = []
            for r in payload["reply_rules"]:
                if not isinstance(r, dict):
                    continue
                kws = [str(x).strip() for x in (r.get("keywords") or []) if str(x).strip()]
                if not kws:
                    continue
                rules.append({
                    "keywords": kws,
                    "reply": str(r.get("reply", "")),
                    "enabled": bool(r.get("enabled", True)),
                })
            auto["reply_rules"] = rules
        await self.store.asave()
        return json_response({"saved": True})

    async def api_auto_trigger(self):
        payload = await request.json(default={})
        job = str(payload.get("job", ""))
        mapping = {
            "collect": self._job_collect,
            "followup": self._job_followup,
            "cold": self._job_cold_rescue,
            "wake": self._job_wake,
            "settle": self._job_settle,
            "report": self._job_daily_report,
            "weekly": self._job_weekly_board,
        }
        fn = mapping.get(job)
        if fn is None:
            return error_response(f"未知任务: {job}（可选 {', '.join(mapping)}）", status_code=400)
        try:
            if job in ("report", "weekly", "settle"):
                # 这几项有定时判断，手动触发时绕过时间判断
                await self._force_job(job)
            else:
                await fn()
            return json_response({"triggered": job, "ok": True})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{PLUGIN_NAME}] 手动触发 {job} 失败: {e}")
            return error_response(f"触发失败: {e}", status_code=500)

    async def _force_job(self, job: str) -> None:
        """强制立即执行定时类任务（忽略时间点判断）。"""
        if job == "collect":
            await self._job_collect()
        elif job == "settle":
            self._today_settled = ""
            await self._job_settle()
        elif job == "report":
            await self._send_report_now()
        elif job == "weekly":
            await self._send_weekly_now()

    async def _send_report_now(self) -> None:
        """立即生成并发送日报。"""
        auto = self.store.data.get("automation", {})
        now = _bj_now()
        today = now.strftime("%Y-%m-%d")
        for gid, info in self.store.enabled_groups("report").items():
            stats = self.store.get_stats(gid)
            latest = stats[-1] if stats else {}
            total = latest.get("total", 0) or 1
            rate = round(latest.get("active", 0) / total * 100, 1)
            top = self.store.leaderboard(gid, top=3)
            top_txt = "、".join(f"{r['name']}({r['points']}分)" for r in top) if top else "暂无"
            text = "\n".join([
                f"📊 【运营日报·{today}】",
                "━━━━━━━━━━━━━",
                f"👥 群人数：{latest.get('total', 0)}",
                f"📈 今日新增：+{latest.get('new', 0)}　📉 退群：-{latest.get('leave', 0)}",
                f"💬 发言人数：{latest.get('active', 0)}（日活 {rate}%）",
                f"🏆 积分 Top3：{top_txt}",
                "━━━━━━━━━━━━━",
                "（本报告由运营助手自动生成）",
            ])
            raw_admins = str(auto.get("report_admin_qq", "") or "")
            admins = [x.strip() for x in re.split(r"[，,;；\s]+", raw_admins) if x.strip()]
            also_group = bool(auto.get("report_to_group", False))
            # 私聊前缀从本群 umo 动态取（和群消息同一平台）
            pm_prefix = self._platform_prefix(info.get("umo", ""))
            for admin in admins:
                await self._send_to(
                    f"{pm_prefix}:FriendMessage:{admin}",
                    MessageChain().message(text),
                    f"日报私聊 {admin}",
                )
            if also_group or not admins:
                await self._send_to(
                    info.get("umo", ""), MessageChain().message(text), f"日报群发 {gid}"
                )

    async def _send_weekly_now(self) -> None:
        top_n = max(3, min(20, int(self._ai_cfg().get("weekly_top_n", 5))))
        for gid, info in self.store.enabled_groups("report").items():
            rows = self.store.leaderboard(gid, top=top_n)
            if not rows:
                continue
            medals = ["🥇", "🥈", "🥉"]
            lines = [f"🏆 【本周积分排行榜 Top{top_n}】"]
            for i, r in enumerate(rows):
                icon = medals[i] if i < 3 else f"{i + 1}."
                lines.append(f"{icon} {r['name']} — {r['points']} 分（邀请 {r['invites']} 人）")
            await self._send_to(
                info.get("umo", ""),
                MessageChain().message("\n".join(lines)),
                f"手动周榜 {gid}",
            )

    async def api_activity(self):
        group_id = request.query.get("group_id", "")
        groups = self.store.enabled_groups() or self.store.bound_groups()
        if not group_id:
            group_id = next(iter(groups), "")
        if not group_id:
            return json_response({"group_id": "", "members": [], "summary": {}})
        act = self.store.activity_of(group_id)
        members = act.get("members", {})
        now = time.time()
        rows = []
        for uid, m in members.items():
            rows.append({
                "user_id": uid,
                "name": m.get("name") or uid,
                "msg_count": m.get("msg_count", 0),
                "last_active_ts": m.get("last_active_ts", 0),
                "idle_days": round((now - m.get("last_active_ts", 0)) / 86400, 1) if m.get("last_active_ts") else None,
                "points": self.store.get_user(group_id, uid).get("points", 0),
            })
        rows.sort(key=lambda x: x["msg_count"], reverse=True)
        day_start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        summary = {
            "total_members": len(act.get("member_ids", [])),
            "tracked_members": len(members),
            "today_active": sum(1 for v in members.values() if v.get("last_active_ts", 0) >= day_start),
            "pending_followup": len(self.store.followup_of(group_id)),
            "last_msg_ts": act.get("last_msg_ts", 0),
            "last_collect_ts": act.get("last_collect_ts", 0),
        }
        return json_response({"group_id": group_id, "members": rows[:100], "summary": summary})

    # ==================================================================
    # AI 相关 Web API
    # ==================================================================
    async def api_ai_get(self):
        ai = self._ai_cfg()
        overrides = (self.store.data.get("config") or {}).get("template_overrides") or {}
        # 探测当前是否有可用模型（兼容 4.26~4.29+）
        provider_name = ""
        provider_id = ""
        available = False
        all_provs = self._all_providers()
        try:
            prov = await self._resolve_provider()
            if prov is not None:
                pid, pname = self._provider_label(prov)
                provider_id, provider_name = pid, pname
                available = True
            elif all_provs:
                # 有模型但没设默认：视为可用，用第一个
                pid, pname = self._provider_label(all_provs[0])
                provider_id, provider_name = pid, pname
                available = True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[{PLUGIN_NAME}] 探测默认模型失败: {e}")
        return json_response({
            "ai": ai,
            "scenes": [{"key": k, "label": v["label"], "brief": v["brief"]} for k, v in AI_SCENES.items()],
            "provider_name": provider_name,
            "provider_id": provider_id,
            "provider_available": available,
            "provider_count": len(all_provs),
            "overrides": overrides,
            "default_persona": DEFAULT_AI["ai_persona"],
            "default_guard": DEFAULT_AI["ai_guard"],
        })

    async def api_ai_providers(self):
        """列出可选的对话模型（兼容各版本 AstrBot）。"""
        rows = []
        seen = set()
        for p in self._all_providers():
            pid, pname = self._provider_label(p)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            rows.append({"id": pid, "name": pname})
        # 兜底：至少把当前默认模型列出来
        if not rows:
            try:
                prov = await self._resolve_provider()
                if prov is not None:
                    pid, pname = self._provider_label(prov)
                    if pid:
                        rows.append({"id": pid, "name": pname})
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[{PLUGIN_NAME}] 兜底获取模型失败: {e}")
        return json_response({"providers": rows})

    # ------------------------------------------------------------------
    # 答题活动 API（v1.2.0 新增：答对自动加分，每轮每群限人数，杜绝重复刷分）
    # ------------------------------------------------------------------
    async def api_quiz_config_get(self):
        """答题活动配置 + 各群进行中的题目（WebUI 卡片用）。"""
        cfg = self._quiz_cfg()
        return json_response({
            "config": {
                "quiz_enabled": bool(cfg.get("quiz_enabled", True)),
                "quiz_reward": int(cfg.get("quiz_reward", 10)),
                "quiz_limit": int(cfg.get("quiz_limit", 3)),
                "quiz_timeout": int(cfg.get("quiz_timeout", 600)),
                "quiz_ai_judge": bool(cfg.get("quiz_ai_judge", True)),
            },
            "bank_size": len(QUIZ_BANK),
            "running": {
                gid: {
                    "q": act.get("q", ""),
                    "reward": act.get("reward", 0),
                    "winners": len(act.get("winners") or []),
                    "limit": int(act.get("limit", 0)),
                }
                for gid, act in (self.store.data.get("quiz_active") or {}).items()
                if isinstance(act, dict) and gid != "_used" and act.get("q")
            },
        })

    async def api_quiz_config_save(self):
        """保存答题活动配置（写回积分配置的 quiz 段，深合并补默认）。"""
        payload = await request.json(default={})
        cfg = self._points_cfg()
        quiz = cfg.setdefault("quiz", dict(DEFAULT_QUIZ_CONFIG))
        for flag in ("quiz_enabled", "quiz_ai_judge"):
            if flag in payload:
                quiz[flag] = bool(payload[flag])
        for num_key, lo, hi in (
            ("quiz_reward", 0, 999),
            ("quiz_limit", 0, 99),
            ("quiz_timeout", 60, 3600),
        ):
            if num_key in payload:
                try:
                    quiz[num_key] = max(lo, min(hi, int(payload[num_key])))
                except (TypeError, ValueError):
                    pass
        await self.store.asave()
        merged = self._quiz_cfg()
        return json_response({
            "saved": True,
            "config": {
                "quiz_enabled": bool(merged.get("quiz_enabled", True)),
                "quiz_reward": int(merged.get("quiz_reward", 10)),
                "quiz_limit": int(merged.get("quiz_limit", 3)),
                "quiz_timeout": int(merged.get("quiz_timeout", 600)),
                "quiz_ai_judge": bool(merged.get("quiz_ai_judge", True)),
            },
        })

    async def api_quiz_start(self):
        """手动向指定群推一道题（与群内 /答题 同一引擎）。"""
        payload = await request.json(default={})
        group_id = str(payload.get("group_id", "") or "")
        if not group_id:
            groups = self.store.enabled_groups()
            if not groups:
                return error_response("没有可用的群（未绑定或已全部停用）", status_code=400)
            group_id = next(iter(groups))
        if group_id not in self.store.bound_groups():
            return error_response(f"群 {group_id} 未绑定", status_code=400)
        text = await self.quiz_start(group_id)
        if not text:
            if self.quiz_active_of(group_id):
                act = self.quiz_active_of(group_id)
                return json_response({
                    "started": False,
                    "reason": "running",
                    "running": {
                        "q": act.get("q", ""),
                        "reward": act.get("reward", 0),
                        "winners": len(act.get("winners") or []),
                        "limit": int(act.get("limit", 0)),
                    },
                })
            return error_response("答题活动未开启或出题失败", status_code=400)
        # 推送到群（与定时答题广播同一路径）
        info = (self.store.enabled_groups() or {}).get(group_id) or {}
        ok = await self._send_to(
            info.get("umo", ""), MessageChain().message(text), f"WebUI 出题 {group_id}"
        )
        if not ok:
            return error_response("出题成功但推送失败（QQ 适配器不在线？）", status_code=500)
        return json_response({"started": True, "group_id": group_id, "content": text})

    async def api_quiz_status(self):
        """答题进行中的题目 + 已获奖名单。"""
        rows = []
        for gid, act in (self.store.data.get("quiz_active") or {}).items():
            if not isinstance(act, dict) or gid == "_used" or not act.get("q"):
                continue
            rows.append({
                "group_id": gid,
                "q": act.get("q", ""),
                "hint": act.get("hint", ""),
                "reward": act.get("reward", 0),
                "limit": int(act.get("limit", 0)),
                "winners": [
                    {"name": w.get("name", ""), "points": w.get("points", 0)}
                    for w in (act.get("winners") or [])
                ],
            })
        return json_response({"running": rows, "bank_size": len(QUIZ_BANK)})

    async def api_ai_save(self):
        payload = await request.json(default={})
        ai = self._ai_cfg()
        bool_keys = ["ai_enabled", "ai_for_generate", "ai_for_rescue",
                     "ai_for_reply", "ai_for_welcome", "ai_for_schedule"]
        for k in bool_keys:
            if k in payload:
                ai[k] = bool(payload[k])
        if "ai_provider_id" in payload:
            ai["ai_provider_id"] = str(payload["ai_provider_id"] or "").strip()
        if "ai_persona" in payload:
            ai["ai_persona"] = str(payload["ai_persona"] or "").strip() or DEFAULT_AI["ai_persona"]
        if "ai_guard" in payload:
            ai["ai_guard"] = str(payload["ai_guard"] or "").strip() or DEFAULT_AI["ai_guard"]
        if "ai_timeout" in payload:
            try:
                ai["ai_timeout"] = max(5, min(120, int(payload["ai_timeout"])))
            except (TypeError, ValueError):
                pass
        if "weekly_top_n" in payload:
            try:
                ai["weekly_top_n"] = max(3, min(20, int(payload["weekly_top_n"])))
            except (TypeError, ValueError):
                pass
        if "ai_temperature" in payload:
            try:
                ai["ai_temperature"] = max(0.0, min(2.0, float(payload["ai_temperature"])))
            except (TypeError, ValueError):
                pass
        await self.store.asave()
        return json_response({"saved": True, "ai": ai})

    async def api_ai_generate(self):
        payload = await request.json(default={})
        key = str(payload.get("template", ""))
        if key not in TEMPLATES:
            return error_response(f"未知模板: {key}", status_code=400)
        if not self.ai_ready():
            return error_response("AI 未开启，请先在「AI 话术」页打开总开关", status_code=400)
        text = await self.ai_generate_template(
            key, str(payload.get("hint", "")), str(payload.get("group_id", ""))
        )
        if not text:
            return error_response(
                "AI 生成失败（模型未配置 / 超时 / 被限流），已保留原模板内容。"
                "可稍后重试，或先关闭 AI 使用固定模板。",
                status_code=502,
            )
        return json_response({"template": key, "content": text})

    async def api_ai_polish(self):
        payload = await request.json(default={})
        key = str(payload.get("template", ""))
        current = str(payload.get("content", "")).strip()
        if not current:
            return error_response("请先填写要润色的内容", status_code=400)
        if not self.ai_ready():
            return error_response("AI 未开启，请先在「AI 话术」页打开总开关", status_code=400)
        text = await self.ai_polish_template(key, current, str(payload.get("instruction", "")))
        if not text:
            return error_response("AI 润色失败（模型未配置 / 超时），原文未改动。", status_code=502)
        return json_response({"template": key, "content": text})

    async def api_ai_apply(self):
        """采纳 AI 内容为某个模板的正式内容。"""
        payload = await request.json(default={})
        key = str(payload.get("template", ""))
        content = str(payload.get("content", "")).strip()
        if key not in TEMPLATES:
            return error_response(f"未知模板: {key}", status_code=400)
        if not content:
            return error_response("内容不能为空", status_code=400)
        cfg = self.store.data.setdefault("config", {})
        overrides = cfg.setdefault("template_overrides", {})
        overrides[key] = content
        # 欢迎语单独存一份，保持与既有逻辑兼容
        if key == "welcome":
            cfg["welcome_text"] = content
        await self.store.asave()
        return json_response({"applied": True, "template": key, "content": content})

    async def api_ai_restore(self):
        """把模板还原为内置版本。"""
        payload = await request.json(default={})
        key = str(payload.get("template", ""))
        if key not in TEMPLATES:
            return error_response(f"未知模板: {key}", status_code=400)
        cfg = self.store.data.setdefault("config", {})
        overrides = cfg.setdefault("template_overrides", {})
        overrides.pop(key, None)
        if key == "welcome":
            cfg["welcome_text"] = DEFAULT_WELCOME_TEXT
        await self.store.asave()
        return json_response({"restored": True, "template": key, "content": TEMPLATES[key]["content"]})
