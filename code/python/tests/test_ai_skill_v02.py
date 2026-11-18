"""规则v0.2草稿词典的样例测试（方案第6.1节）。运行：.venv/bin/python -m unittest discover -s code/python/tests

每条排除规则至少一个“该排除”和一个“不该排除”的句子；样例为手写的同类句子，不是真实广告。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_skill_matcher import AISkillMatcher  # noqa: E402

V02 = Path(__file__).resolve().parents[3] / "config" / "ai_skill_dictionary_v0.2_draft.json"
M = AISkillMatcher(V02)

# (说明, 招聘岗位, 职位描述, 期望ai_skill, 期望ai_skill_broad)
CASES = [
    # ---- 条件词：降级的7个词 ----
    ("机器视觉单独出现→只算宽泛", "视觉工程师", "负责机器视觉检测系统开发。", 0, 1),
    ("机器视觉+严格词", "视觉工程师", "负责机器视觉检测系统开发，熟悉深度学习。", 1, 1),
    ("两个不同条件词", "研究员", "熟悉机器视觉，了解LDA主题模型。", 1, 1),
    ("AI绘画单独出现", "插画师", "会使用Midjourney辅助出图。", 0, 1),
    ("AI绘画+严格词", "设计师", "会使用Midjourney、ChatGPT等工具。", 1, 1),
    # 11-18筛词后：写法相近的几个条件词匹配同一处文字，只算一个，不能自己凑成一对
    ("LDA单独出现（原词+新词同写法）", "数据分析师", "了解LDA主题模型。", 0, 1),
    ("VisionPro单独出现（多个变体）", "视觉工程师", "熟悉Cognex VisionPro软件调试。", 0, 1),
    # 11-18新词计数核对：短中文词嵌在别的词里
    ("培训推广不是训推", "培训经理", "负责新产品培训推广。", 0, 0),
    ("真正的训推", "算法工程师", "负责大模型训推一体平台建设。", 1, 1),
    ("可灵活不是可灵", "销售", "可灵活安排工作时间。", 0, 0),
    ("分配准确不是配准", "会计", "成本分配准确及时。", 0, 0),
    ("抛光流程不是光流", "工艺员", "优化抛光流程。", 0, 0),
    ("超分支机构不是超分", "核保专员", "负责超分支机构权限业务核保。", 0, 0),
    ("条件词只在公司介绍里","销售", "公司是一家专注于机器视觉的领先企业。岗位职责：负责客户开发。", 0, 0),
    # ---- 宽泛词不升级 ----
    ("人工智能仍只算宽泛", "销售经理", "熟悉人工智能行业，有大客户资源。", 0, 1),
    ("Transformer仍只算宽泛", "电气工程师", "负责Transformer选型与维护。", 0, 1),
    ("AI+自动驾驶不凑成AI", "产品经理", "负责AI与自动驾驶相关产品规划。", 0, 1),
    # ---- 大模型 ----
    ("单独大模型→严格", "产品经理", "负责大模型相关产品的需求分析。", 1, 1),
    ("大模型展示→排除", "前端开发", "负责Web端大模型展示与交互开发。", 0, 0),
    ("大模型数据轻量化→排除", "图形开发", "负责大模型数据轻量化处理。", 0, 0),
    ("城市大模型建模→排除", "建模师", "负责城市大模型建模工作。", 0, 0),
    ("三维语境→排除", "开发工程师", "熟悉三维引擎，负责大模型加载优化。", 0, 0),

    ("放大模型仍不算", "研究员", "开展发酵工艺放大模型建立。", 0, 0),
    ("大模型+场景不排除", "解决方案经理", "负责大模型在金融场景的落地。", 1, 1),
    # 11-18全样本核对发现的误伤（改写的同类句子），排除规则收窄后应判为1
    ("大模型建模工程师不排除", "自然语言大模型建模工程师", "负责相关工作。", 1, 1),
    ("大模型轻量化部署不排除", "研发工程师", "跟踪前沿技术，如大模型轻量化部署。", 1, 1),
    ("视觉大模型+3D视觉不排除", "算法工程师", "跟进视觉大模型、3D视觉等前沿技术。", 1, 1),
    ("BIM大模型仍排除", "BIM工程师", "负责BIM大模型的整合。", 0, 0),
    ("Web端大模型3展示仍排除", "前端", "负责端大模型3展示和特效技术研发。", 0, 0),
    # ---- 误判1：LLM法学硕士 ----
    ("法学硕士LLM→排除", "法务专员", "法学硕士（LLM）优先。", 0, 0),
    ("律师LLM→排除", "律师助理", "具有LLM学位的律师优先。", 0, 0),
    ("真正的LLM", "算法工程师", "熟悉LLM微调与部署。", 1, 1),
    # ---- 误判2：搜索提示词 ----
    ("搜索提示词→排除", "前端开发", "负责搜索提示词下拉框功能开发。", 0, 0),
    ("输入提示词→排除", "测试工程师", "测试输入提示词的显示效果。", 0, 0),
    ("真正的提示词", "运营", "负责提示词编写与优化。", 1, 1),
    # ---- 误判3：PS/AI绘图 ----
    ("PS/AI绘图→排除", "美工", "熟练使用PS/AI绘图。", 0, 0),
    ("PS、AI绘画→排除", "平面设计", "会用PS、AI绘画。", 0, 0),
    ("真正的AI绘画（还需搭配）", "设计师", "熟悉AI绘画和Stable Diffusion，了解大模型。", 1, 1),
    # ---- 误判4：3D/动画里的模型微调 ----
    ("角色模型微调→排除", "3D美术", "负责角色模型微调与贴图。", 0, 0),
    ("动画模型微调→排除", "动画师", "负责动画模型微调。", 0, 0),
    ("同句有大模型不排除", "算法工程师", "负责多模态大模型微调与3D生成。", 1, 1),
    # ---- 误判5：非AI的fine-tune ----
    ("fine-tune流程→排除", "运营经理", "Fine-tune the process to improve efficiency.", 0, 0),
    ("fine-tune模型不排除", "算法工程师", "Experience to fine-tune pretrained models.", 1, 1),
    ("产线fine-tuning→排除", "工艺工程师", "试产前线体准备进度跟进，setup, fine-tuning, buy-off。", 0, 0),
    ("芯片finetune不排除", "算法工程师", "熟悉定点量化，有针对海思芯片finetune经验者优先。", 1, 1),
    ("fine-tune剪枝蒸馏不排除", "算法工程师", "负责二次训练与调优，涵盖fine-tune、剪枝、蒸馏等技术手段。", 1, 1),
    # ---- 误判6：城市智能体 ----
    ("城市智能体→排除", "销售经理", "负责城市智能体产品的推广。", 0, 0),
    ("园区智能体→排除", "项目经理", "负责园区智能体项目交付。", 0, 0),
    ("真正的智能体", "开发工程师", "负责智能体开发与工具调用。", 1, 1),
    # ---- 误判7：GPT会议 ----
    ("GPT会议→排除", "行政", "负责GPT会议的组织协调。", 0, 0),
    ("真正的GPT", "运营专员", "会使用GPT-4辅助数据整理。", 1, 1),
]


class TestV02(unittest.TestCase):
    def test_cases(self):
        failures = []
        for note, title, desc, want_strict, want_broad in CASES:
            r = M.classify(title, desc)
            if (r["ai_skill"], r["ai_skill_broad"]) != (want_strict, want_broad):
                failures.append(f"{note}: 期望{(want_strict, want_broad)} 实际{(r['ai_skill'], r['ai_skill_broad'])} "
                                f"hit={r['ai_hit_terms']} cond={r['ai_conditional_terms']} broad={r['ai_broad_terms']}")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_conditional_fields(self):
        r = M.classify("视觉工程师", "负责机器视觉检测系统开发。")
        self.assertEqual(r["ai_conditional_terms"], "aahr_machine_vision")
        self.assertEqual(r["ai_hit_terms"], "")
        self.assertEqual(r["ai_intensity"], 0.0)
        r = M.classify("视觉工程师", "负责机器视觉检测，熟悉深度学习。")
        self.assertEqual(r["ai_conditional_terms"], "")
        self.assertEqual(r["ai_hit_terms"], "aahr_deep_learning|aahr_machine_vision")
        self.assertTrue(0 < r["ai_intensity"] <= 1)

    def test_two_category(self):
        one = M.classify("算法工程师", "熟悉深度学习和神经网络。")  # 都在“深度学习”组
        two = M.classify("算法工程师", "熟悉深度学习，有目标检测经验。")  # 深度学习 + 计算机视觉
        self.assertEqual((one["ai_skill"], one["ai_skill_2cat"]), (1, 0))
        self.assertEqual((two["ai_skill"], two["ai_skill_2cat"]), (1, 1))
        self.assertIsNone(M.classify("销售", None)["ai_skill_2cat"])

    def test_rule_version(self):
        self.assertTrue(M.rule_version.startswith("ai_skill_dict_v0.2"))


if __name__ == "__main__":
    unittest.main()
