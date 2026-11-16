"""AI技能规则的手写样例测试。运行：.venv/bin/python -m unittest discover -s code/python/tests

样例是按常见招聘广告写法手工编写的，不是真实数据；真实效果以人工标注结果为准。
每条样例写明期望的 (ai_skill, ai_skill_broad)。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_skill_matcher import AISkillMatcher  # noqa: E402

M = AISkillMatcher()

# (说明, 招聘岗位, 职位描述, 期望ai_skill, 期望ai_skill_broad)
CASES = [
    # ---- 应识别为严格AI技能 ----
    ("传统AI框架", "数据分析师", "任职要求：1、熟悉Python，掌握机器学习常用算法；2、熟练使用TensorFlow或PyTorch。", 1, 1),
    ("NLP职责", "研发工程师", "岗位职责：负责NLP相关模型的开发与优化。", 1, 1),
    ("生成式AI工具使用", "新媒体运营", "工作内容：使用ChatGPT、文心一言等工具辅助撰写文案。", 1, 1),
    ("大模型应用", "后端开发", "有大模型应用开发经验者优先，了解RAG、LangChain。", 1, 1),
    ("标题即AI岗位", "机器学习工程师", "负责公司业务系统维护。", 1, 1),
    ("AIGC设计", "视觉设计师", "熟练掌握Midjourney、Stable Diffusion等AIGC工具。", 1, 1),
    ("GPT带版本号", "运营专员", "会使用GPT-4辅助数据整理。", 1, 1),
    ("提示词工程", "AI训练专员", "负责提示词编写与优化。", 1, 1),
    ("计算机视觉", "算法工程师", "熟悉OpenCV，有目标检测、YOLO项目经验。", 1, 1),
    ("无标题分段但有要求", "工程师", "公司简介：某某科技。任职要求：熟悉深度学习框架。", 1, 1),

    # ---- 只算宽泛AI ----
    ("AI相关专业", "软件工程师", "任职要求：计算机、人工智能等相关专业本科及以上学历。", 0, 1),
    ("会用AI工具", "行政助理", "能熟练使用AI工具提升办公效率。", 0, 1),
    ("数据挖掘", "数据分析", "具备数据挖掘能力。", 0, 1),
    ("标题AI产品经理", "AI产品经理", "负责产品需求整理和项目推进。", 0, 1),

    # ---- 公司介绍，不算 ----
    ("公司做AI", "销售代表", "公司简介：我们是一家专注于人工智能和深度学习的领先企业。岗位职责：负责客户开发与维护。", 0, 0),
    ("致力于大模型", "会计", "集团致力于大模型与计算机视觉技术研发。要求：熟悉财务软件。", 0, 0),
    ("产品介绍", "销售", "公司产品为基于AI的智能客服平台。", 0, 0),

    # ---- 常见误判陷阱 ----
    ("Illustrator", "平面设计师", "熟练使用PS、AI、CDR等设计软件。", 0, 0),
    ("Illustrator2", "美工", "精通Photoshop/AI，有排版经验。", 0, 0),
    ("CV是简历", "行政", "请将CV发送至邮箱。", 0, 0),
    ("毫升", "质检员", "负责500ml产品灌装检测。", 0, 0),
    ("HTML", "前端", "熟悉HTML、CSS、JavaScript。", 0, 0),
    ("MAIL", "客服", "具备良好沟通能力，会使用MAIL。", 0, 0),
    ("GPT分区", "运维工程师", "熟悉MBR/GPT分区及磁盘管理。", 0, 0),
    ("AGENT代理商", "渠道经理", "负责开拓代理商agent渠道。", 0, 0),
    ("智能制造", "生产主管", "熟悉智能制造流程，负责产线管理。", 0, 0),
    ("算法但非AI", "嵌入式工程师", "熟悉数据结构与算法，掌握C语言。", 0, 0),
    ("人名Kimi", "销售", "联系人Kimi，微信同号。", 0, 0),
    ("普通岗位", "司机", "持C1驾照，三年以上驾龄。", 0, 0),
    ("LoRa物联网", "物联网工程师", "熟悉LoRa、NB-IoT通信协议。", 0, 0),

    # ---- Acemoglu等(2022)清单翻译词 ----
    ("机器视觉", "视觉工程师", "负责机器视觉检测系统开发。", 1, 1),
    ("数字图像处理", "研发工程师", "熟悉数字图像处理和模式识别。", 1, 1),
    ("机器翻译", "翻译", "熟悉机器翻译译后编辑。", 1, 1),
    ("文本情感分析", "数据工程师", "负责评论文本的情感分析与文本挖掘。", 1, 1),
    ("聊天机器人", "产品经理", "负责智能客服聊天机器人的需求设计。", 1, 1),
    ("梯度提升", "风控建模", "熟练使用XGBoost、GBDT等模型。", 1, 1),
    ("预测模型降为宽泛", "财务分析", "具备搭建预测模型的能力。", 0, 1),
    ("PS图像处理", "美工", "熟练使用PS进行图像处理。", 0, 0),
    ("婚恋情感分析师", "情感分析师", "为客户提供婚恋情感咨询与情感分析。", 0, 0),
]


class TestCases(unittest.TestCase):
    def test_cases(self):
        failures = []
        for note, title, desc, want_strict, want_broad in CASES:
            r = M.classify(title, desc)
            if (r["ai_skill"], r["ai_skill_broad"]) != (want_strict, want_broad):
                failures.append(f"{note}: 期望{(want_strict, want_broad)} 实际{(r['ai_skill'], r['ai_skill_broad'])} "
                                f"strict={r['ai_strict_terms']} broad={r['ai_broad_terms']}")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_missing_text_is_not_zero(self):
        self.assertIsNone(M.classify("销售", None)["ai_skill"])
        self.assertIsNone(M.classify("销售", "  ")["ai_skill_broad"])
        self.assertEqual(M.classify("深度学习工程师", None)["ai_skill"], 1)

    def test_subcategories(self):
        r = M.classify("运营", "熟练使用ChatGPT，了解机器学习。")
        self.assertEqual((r["ai_genai"], r["ai_traditional"]), (1, 1))

    def test_intro_only_and_review_flags(self):
        self.assertEqual(M.classify("销售", "公司是一家领先的人工智能企业。")["ai_intro_only"], 1)
        self.assertEqual(M.classify("数据标注员", "负责图片标注。")["ai_review_flag"], 1)


if __name__ == "__main__":
    unittest.main()
