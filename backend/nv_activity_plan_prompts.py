"""活动方案提示词、篇幅参数和批量差异化规则。"""
from __future__ import annotations
import hashlib
from typing import Optional, Sequence

# 单次生成目标篇幅（以模型输出正文的字符规模约束，含汉字、标点及 Markdown 标记）
ACTIVITY_PLAN_LENGTH_MIN = 3500
ACTIVITY_PLAN_LENGTH_MAX = 4000
# 长文策划略降随机性，减少跑题与套话（仅活动方案调用传入）
ACTIVITY_PLAN_GEN_TEMPERATURE = 0.5

# 用户消息中再次强调，与 system 提示互补（防止模型忽略 system）
ACTIVITY_PLAN_USER_RED_LINES = (
    "【内容红线（与系统提示一致，务必遵守）】"
    "不得出现任何具体公司/企业/品牌名称；不得出现具体金额、预算、报价等数字表述；"
    "活动时间仅按用户给定范围复述，勿自行拉长或缩短；"
    "服务院校仅使用用户提供的院校表述，勿编造其他单位。"
)

# 封面批量：标题与同批去重失败时追加到 user，触发整文重生成（最多由批处理再调 1 次）
ACTIVITY_PLAN_TITLE_DEDUP_RETRY_SUFFIX = (
    "【标题去重纠偏】系统检测到：你拟定的「项目名称/活动名称」与本 Excel 同批已生成的某一标题过于接近。\n"
    "请**全文重新输出一版**（章节结构可相近），但必须将「活动概况」中的项目名称/活动名称改为**完全不同**的意象与关键词："
    "更换核心场景词与动词；禁止与同批已列名称仅做一两字修改、同义替换或语序微调；"
    "若项目名称/活动名称行仍与下列「同批已用名称」任一条在语感上易混淆，视为不合格。"
)

# 按输入哈希轮换「写作侧重」，减轻批量生成时标题与开篇雷同
ACTIVITY_PLAN_DIVERSITY_ANGLES: tuple[str, ...] = (
    "本轮侧重「实践教学与课堂转化」：项目名称宜体现示范课、项目制任务包、翻转课堂、现场课业、微项目答辩等意象。",
    "本轮侧重「校企协同与联合培养」：项目名称宜体现联合课题、双师课、案例库共建、产业导师驻课、课程联建等意象。",
    "本轮侧重「创新创业与成果展示」：项目名称宜体现季赛路演、作品联展、概念验证沙盒、里程碑评审、成果发布会等意象。",
    "本轮侧重「研学考察与认知升级」：项目名称宜体现考察路线、行业认知、沉浸式参访、现场观摩与复盘报告等意象。",
    "本轮侧重「数字素养与智能工具」：项目名称宜体现数字化实训、工具链演练、数据可视化课业、智能设计工作流等意象。",
    "本轮侧重「文化传承与美育实践」：项目名称宜体现非遗手作课、传统技艺传习、文化策展、美育公开课等意象。",
    "本轮侧重「绿色可持续与社会责任」：项目名称宜体现低碳设计、材料循环实验、ESG 案例研讨、绿色校园行动等意象。",
    "本轮侧重「跨学科融合与复合能力」：项目名称宜体现跨界课题、联合攻关、复合技能沙盘、交叉课程月等意象。",
    "本轮侧重「职业规划与就业赋能」：项目名称宜体现简历门诊、模拟面试、岗位认知、职业能力测评与反馈等意象。",
    "本轮侧重「国际视野与跨文化沟通」：项目名称宜体现双语案例研读、跨文化对比研讨、国际课程模块、海外经典工作坊等意象。",
    "本轮侧重「竞赛与成果冲刺」：项目名称宜体现备赛攻关、命题拆解、作品打磨与预答辩、路演彩排等意象。",
    "本轮侧重「教研共同体与师资发展」：项目名称宜体现教研沙龙、同课异构、教学诊断、名师公开课等意象。",
    "本轮侧重「成果转化与双创实践」：项目名称宜体现概念验证、孵化路演、专利与软著微课题、项目书门诊等意象。",
)


def _activity_plan_diversity_index(*parts: str, batch_slot: Optional[int] = None) -> int:
    raw = "|".join(str(p) for p in parts)
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()
    base = int(h[:8], 16) % len(ACTIVITY_PLAN_DIVERSITY_ANGLES)
    if batch_slot is not None and batch_slot > 0:
        return (base + batch_slot - 1) % len(ACTIVITY_PLAN_DIVERSITY_ANGLES)
    return base


def _activity_plan_diversity_user_block(
    *parts: str,
    batch_slot: Optional[int] = None,
    batch_total: Optional[int] = None,
    avoid_titles: Optional[Sequence[str]] = None,
) -> str:
    i = _activity_plan_diversity_index(*parts, batch_slot=batch_slot)
    angle = ACTIVITY_PLAN_DIVERSITY_ANGLES[i]
    block = (
        f"{ACTIVITY_PLAN_USER_RED_LINES}\n"
        f"【本轮写作侧重】{angle}\n"
        "【写作密度】各主要章节以完整段落展开；关键措施须写清执行主体、具体动作与阶段归属"
        "（不出现金额与具体企业名）。\n"
        "【Markdown 层级】大章用「# 」、小节用「## 」；导出 Word 时程序为 # / ## 自动加「一、」「（一）」式编号，请勿在标题行手写这些序号。"
        "更细的条目可用「###」乃至「####」等细分，导出时**不再加阿拉伯数字编号**，仅保留标题文字；请勿写成「### # 子标题」这类重复井号。\n"
        "【项目名称/活动名称】在「活动概况」中须明确写出「项目名称：」或「活动名称：」一行；"
        "名称为 10～22 个汉字的具象短语，须包含至少一个动作或场景词（如联展、驻场、研究、策展、沙龙、跟岗、路演、沙盘、综合实践等）；"

    )
    if batch_slot is not None:
        tot_s = str(batch_total) if batch_total is not None else "?"
        block += (
            f"\n【同批次防重复】本工作簿批量任务中的第 {batch_slot}/{tot_s} 份。"
            "「项目名称/活动名称」须与同批其它方案在核心场景词、动词与整体意象上显著不同；"
            "禁止仅改一两个字、仅换同义词或仅调整语序；若与下列已有名称高度相似，须完全更换命名角度。"
        )
    if avoid_titles:
        lines: List[str] = []
        for t in avoid_titles[:8]:
            s = str(t).strip().replace("\n", " ")
            if not s:
                continue
            if len(s) > 48:
                s = s[:48] + "…"
            lines.append(f"- {s}")
        if lines:
            block += "\n【同批已用名称（请避免雷同）】\n" + "\n".join(lines)
    return block

ACTIVITY_PLAN_BODY_SYSTEM = (
    "你是一个产教融合方向的专业活动项目策划。"
    "请输出专业、可执行的活动策划方案，语气正式，结构清晰。"
    "不要体现具体公司与企业名称，不要体现具体金额。"
)

ACTIVITY_PLAN_BODY_SYSTEM_STRICT = (
    "你是高校产教融合项目的资深策划执笔人。请写出“可报批、可执行、可落地”的正式活动方案，文风参考高校项目申报与实施方案写法：专业稳健、信息密度高、避免口号化。\n"
    "格式建议（便于导出 Word）：大章用「# 章节名」，小节用「## 标题」；更细结构可用「###」「####」等，标题行只写主题词，不要手写「一、」「（一）」「1.」等公文序号。\n"
    "导出时：程序仅为「#」「##」自动加「一、」「（一）」；三级及以下标题不再加数字前缀，并会去掉多余「#」符号。\n"
    "正文以完整段落为主，辅以必要分项，不要只有零散短句。\n"
    "结构建议（可灵活调整）：建议覆盖“活动背景、活动概况、组织与对象、实施内容与进度、保障机制、预期成果、总结评估”等模块；允许按实际项目特征合并或拆分。\n"
    "写作细节：应体现项目逻辑主线、阶段安排、执行动作、责任分工、成果产出与可复制机制；语言避免空泛，尽量写出可执行细节。\n"
    "命名与形态：项目名称与实施形态应多样化。\n"
    f"篇幅：请一次性输出完整终稿，不要分多次追问或分卷；全文汉字规模约 {ACTIVITY_PLAN_LENGTH_MIN}～{ACTIVITY_PLAN_LENGTH_MAX} 字"
    f"（不少于 {ACTIVITY_PLAN_LENGTH_MIN}、不超过 {ACTIVITY_PLAN_LENGTH_MAX}），勿在文末输出字数统计或「全文字符数」。\n"
    "硬性约束：不得出现任何具体公司/企业/品牌名称；不得出现任何具体金额数字；活动时间仅复述用户给定范围。"
)

ACTIVITY_PLAN_BODY_SYSTEM_STANDARD = (
    "你是高校活动策划方案撰写助手。请输出专业、清晰、可执行的正式方案文本。"
    "结构完整，表达简洁，重点明确。"
    "请用 Markdown 标题分层：大章「# 」，小节「## 」；需要更细再用「###」「####」等。标题行只写主题词，勿手写「一、」「（一）」「1.」；勿在标题前重复写多个「#」。"
    "项目名称与活动组织形式宜多样，少用「XX训练营」式套名；由于时间跨度较大，请勿用「XX周」字机械收尾堆砌多篇雷同标题。"
    f"篇幅：一次性输出完整终稿，全文汉字约 {ACTIVITY_PLAN_LENGTH_MIN}～{ACTIVITY_PLAN_LENGTH_MAX} 字（不超过 {ACTIVITY_PLAN_LENGTH_MAX}），勿附字数说明。"
    "不得出现任何具体公司/企业/品牌名称；不得出现任何具体金额数字；活动时间仅复述用户给定范围。"
)


