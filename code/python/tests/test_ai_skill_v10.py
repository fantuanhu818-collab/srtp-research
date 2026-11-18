"""规则v1.0（§8微调一轮）的样例测试。运行：.venv/bin/python -m unittest discover -s code/python/tests

只测这一轮改了什么：删除的新词不再单独判AI，图像处理降为条件词。样例为手写句子，不是真实广告。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_skill_matcher import AISkillMatcher  # noqa: E402

CONFIG = Path(__file__).resolve().parents[3] / "config"
V10 = CONFIG / "ai_skill_dictionary_v1.0.json"
M = AISkillMatcher(V10)

# (说明, 招聘岗位, 职位描述, 期望ai_skill)
CASES = [
    # 删除的新词：单独出现不再算AI
    ("聚类单独出现", "数据分析师", "熟悉聚类、分类等数据挖掘方法。", 0),
    ("多模态单独出现", "IOT架构师", "负责图像、激光雷达等多模态数据融合。", 0),
    ("SLAM单独出现", "导航工程师", "熟悉激光SLAM算法与路径规划。", 0),
    ("决策树单独出现", "风控专员", "了解逻辑回归、决策树等统计方法。", 0),
    # 图像处理降为条件词：单独不算，有严格词作证才算
    ("图像处理单独出现", "C++工程师", "熟悉图像处理算法。", 0),
    ("图像处理+深度学习", "图像算法工程师", "熟悉图像处理算法，掌握深度学习。", 1),
    # 未改动的严格词照常
    ("机器学习仍是严格词", "算法工程师", "熟悉机器学习算法。", 1),
    ("OpenCV仍是严格词", "图像算法工程师", "熟练掌握OpenCV。", 1),
    ("大模型仍是严格词", "产品经理", "负责大模型相关产品的需求分析。", 1),
]


class TestV10(unittest.TestCase):
    def test_cases(self):
        for name, title, desc, expected in CASES:
            with self.subTest(name):
                self.assertEqual(M.classify(title, desc)["ai_skill"], expected)

    def test_only_planned_changes(self):
        """v1.0与v0.2相比，只删了changelog里列出的词、只降了列出的词。"""
        v02 = {t["id"]: t for t in json.loads((CONFIG / "ai_skill_dictionary_v0.2_draft.json").read_text(encoding="utf-8"))["terms"]}
        spec = json.loads(V10.read_text(encoding="utf-8"))
        v10 = {t["id"]: t for t in spec["terms"]}
        log = spec["changelog_v1.0"]
        self.assertEqual(set(v02) - set(v10), set(log["rule3_delete_new_terms"]["terms"]))
        self.assertEqual(set(v10) - set(v02), set())
        changed = {k for k in v10 if v10[k] != v02[k]}
        self.assertEqual(changed, set(log["rule1_demote"]["terms"]))
        self.assertTrue(all(v02[k]["source"] == "w2v_expansion" for k in log["rule3_delete_new_terms"]["terms"]))


if __name__ == "__main__":
    unittest.main()
