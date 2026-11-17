import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_w2v_text as T  # noqa: E402
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402


class TestW2VText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T.init_jieba(json.loads(DEFAULT_DICTIONARY.read_text(encoding="utf-8"))["terms"])
        cls.matcher = AISkillMatcher()

    def test_top_level_split_keeps_groups(self):
        self.assertEqual(T.top_level_alternates("(?:大模型|模型)微调|SFT"), ["(?:大模型|模型)微调", "SFT"])
        self.assertEqual(T.literal_forms("机器学习|Machine Learning|LLMs?"), ["机器学习", "machine learning"])

    def test_tokenize_keeps_terms_and_english_runs(self):
        toks = T.tokenize_clause("熟悉机器学习、C++，了解 machine learning 和 GPT-4")
        self.assertIn("机器学习", toks)
        self.assertIn("c++", toks)
        self.assertIn("gpt-4", toks)
        i = toks.index("machine")
        self.assertEqual(toks[i + 1], "learning")  # 空格不插入断点
        self.assertEqual(list(T.ascii_runs(["a", "|", "machine", "learning", "中文"])), [["machine", "learning"]])
        self.assertNotIn(T.BREAK, T.apply_phrases(toks, None))

    def test_requirement_clauses_drop_company_intro(self):
        desc = "公司简介：我们是一家致力于人工智能的领先企业。任职要求：1、熟悉深度学习"
        clauses = T.requirement_clauses(self.matcher, "算法工程师", desc)
        self.assertEqual(clauses[0], "算法工程师")
        self.assertTrue(any("深度学习" in c for c in clauses))
        self.assertFalse(any("致力于" in c for c in clauses))


if __name__ == "__main__":
    unittest.main()
