"""Word2Vec扩词和共现相关度（规则v0.2第2、3步）共用的文本处理。

- requirement_clauses：岗位名称 + 职位描述中非公司介绍句（沿用 ai_skill_matcher 的分句和介绍句判断）；
- tokenize_clause：jieba分词（加载自定义词典），英文转小写，去停用词、纯数字和单字；
  标点处插入 BREAK（空格不算），用于界定英文连续片段；
- apply_phrases：用训练好的 gensim Phrases 只合并相邻英文词（如 machine_learning）。

方案见 docs/AI技能识别调整方案与对接_2026-11-16.md 第3、4节。
"""

from __future__ import annotations

import re

import jieba

from ai_skill_matcher import AISkillMatcher

BREAK = "|"
CHATGPT_RELEASE = "2022-11-30"
SEED = 20261116

# 现有词典里正则写法展开不了的词，以及常见IT技术词，加入jieba自定义词典，避免被切开。
EXTRA_WORDS = """
大语言模型 ai大模型 人工智能大模型 预训练大模型 多模态大模型 通用大模型 行业大模型 垂直大模型 开源大模型
大模型 大模型技术 大模型算法 大模型应用 大模型训练 大模型微调 大模型推理 大模型开发 大模型产品
生成式人工智能 生成式ai 生成式模型 模型微调 模型精调 指令微调 智能体 ai智能体 提示词 提示词工程 prompt工程
检索增强生成 文生图 图生图 文生视频 ai绘画 ai绘图 ai作画 ai生图 扩散模型 多模态 预训练 预训练模型
gpt-4 gpt-4o gpt-3.5 gpt-3 llm llms chatgpt aigc agent
机器学习 深度学习 强化学习 迁移学习 联邦学习 对比学习 自监督学习 半监督学习 监督学习 无监督学习 集成学习 元学习 主动学习
神经网络 卷积神经网络 循环神经网络 图神经网络 生成对抗网络 注意力机制 知识蒸馏 模型压缩 模型量化 模型剪枝 模型部署 模型推理
计算机视觉 机器视觉 图像识别 图像处理 图像算法 视觉算法 目标检测 目标识别 目标跟踪 图像分割 语义分割 实例分割 人脸识别 行人重识别
姿态估计 三维重建 点云 光学字符识别 图像分类 图像增强 图像生成 视频分析 缺陷检测
自然语言处理 自然语言理解 文本挖掘 文本分类 情感分析 命名实体识别 实体识别 关系抽取 信息抽取 意图识别 语义理解 机器翻译
对话系统 问答系统 聊天机器人 智能客服 语音识别 语音合成 声纹识别 语音交互 语音信号处理
推荐系统 推荐算法 个性化推荐 搜索算法 排序算法 召回 ctr预估 用户画像 知识图谱
特征工程 数据挖掘 数据科学 数据分析 大数据 云计算 分布式 数据结构 操作系统 嵌入式 单片机 自动驾驶 智能驾驶 无人驾驶
""".split()

STOPWORDS = set("""
以及 或者 并且 而且 及其 其他 其中 以上 以下 之一 一定 一些 一种 一个 相关 能够 可以 进行 通过 根据 包括 对于 关于
我们 你们 他们 公司 本公司 如果 但是 因为 所以 并 及 等 的 了 和 与 或 在 对 为 是 有 能 会 将 把 被 从 向 由 于
""".split())

_ASCII = re.compile(r"^[a-z0-9+#.\-_]+$")
_DIGITS = re.compile(r"^[\d.\-%]+$")
_WORDISH = re.compile(r"[\w一-鿿]")


def top_level_alternates(pattern: str) -> list[str]:
    """按顶层 | 拆分正则（不拆括号内的 |）。"""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            cur += pattern[i:i + 2]
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return parts


def literal_forms(pattern: str) -> list[str]:
    """正则里不含元字符的顶层写法（小写），如 '机器学习|Machine Learning' → 两个词。"""
    return [p.lower() for p in top_level_alternates(pattern)
            if p and re.fullmatch(r"[\w一-鿿+#.\- ]+", p)]


_initialized = False


def init_jieba(matcher_spec_terms: list[dict]) -> None:
    """每个进程调用一次：加载自定义词典（只含不带空格的写法，带空格的英文词组交给Phrases）。"""
    global _initialized
    if _initialized:
        return
    jieba.setLogLevel(60)
    words = set(EXTRA_WORDS)
    for t in matcher_spec_terms:
        words.update(w for w in literal_forms(t["pattern"]) if " " not in w)
    for w in sorted(words):
        jieba.add_word(w, freq=200_000)
    jieba.initialize()
    _initialized = True


def requirement_clauses(matcher: AISkillMatcher, title: object, desc: object) -> list[str]:
    """岗位名称 + 职位描述中不是公司介绍的句子。"""
    out = []
    if isinstance(title, str) and title.strip():
        out.append(title.strip())
    if isinstance(desc, str) and desc.strip():
        for clause, section in matcher.clauses(desc.strip()):
            if not matcher.is_intro(clause, section):
                out.append(clause)
    return out


def tokenize_clause(clause: str) -> list[str]:
    """分词；标点记为 BREAK（随后在 apply_phrases 中去掉）。"""
    toks: list[str] = []
    for w in jieba.cut(clause.lower()):
        w = w.strip()
        if not w:  # 空格不断开英文片段（machine learning 要能合并）
            continue
        if not _WORDISH.search(w):
            if toks and toks[-1] != BREAK:
                toks.append(BREAK)
            continue
        if w in STOPWORDS or _DIGITS.match(w) or (len(w) == 1 and w not in ("c", "r")):
            continue
        toks.append(w)
    return toks


def ascii_runs(tokens: list[str]):
    """切出连续英文片段（Phrases只在这些片段上训练和应用）。"""
    run: list[str] = []
    for t in tokens:
        if t != BREAK and _ASCII.match(t):
            run.append(t)
        else:
            if len(run) >= 2:
                yield run
            run = []
    if len(run) >= 2:
        yield run


def apply_phrases(tokens: list[str], phraser) -> list[str]:
    """合并英文词组，去掉 BREAK。phraser 为 None 时只去 BREAK。"""
    out: list[str] = []
    run: list[str] = []

    def flush():
        if run:
            out.extend(phraser[run] if phraser is not None and len(run) >= 2 else run)
            run.clear()

    for t in tokens:
        if t != BREAK and _ASCII.match(t):
            run.append(t)
        else:
            flush()
            if t != BREAK:
                out.append(t)
    flush()
    return out
