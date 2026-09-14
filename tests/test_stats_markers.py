"""Obvious AI-pattern detection (deterministic stats + markers)."""
from paper_humanizer.stats import compute_stats, detect_language, load_markers


def test_obvious_zh_ai_patterns_detected():
    text = ("值得注意的是，本研究的样本具有代表性。综上所述，本文提出了三点贡献。"
            "首先，本文拓展了理论。其次，本文改进了方法。最后，本文给出了政策建议。"
            "值得注意的是，这一结论是稳健的。")
    stats = compute_stats(text)
    phrases = {h["phrase"]: h["count"] for h in stats["template_hits"]}
    assert phrases.get("值得注意的是") == 2
    assert phrases.get("综上所述") == 1
    assert stats["chains"], "首先/其次/最后 chain must be detected"
    assert stats["ai_style_level"] == "high"


def test_obvious_en_ai_patterns_detected():
    text = ("It is worth noting that the results hold. Moreover, the model is robust. "
            "In conclusion, we discuss policy implications.")
    stats = compute_stats(text)
    phrases = {h["phrase"]: h["count"] for h in stats["template_hits"]}
    assert phrases.get("it is worth noting that") == 1
    assert phrases.get("moreover") == 1
    assert phrases.get("in conclusion") == 1


def test_uniform_rhythm_flags_low_cv():
    uniform = "本研究发现了第一组结果。本研究发现了第二组结果。本研究发现了第三组结果。"
    varied = "样本覆盖了制造业企业。规模差异很大——从几十人的小厂到上万人的集团都在其中，这为识别提供了足够的变异。"
    assert compute_stats(uniform)["sentence_cv"] < compute_stats(varied)["sentence_cv"]


def test_language_detection():
    assert detect_language("这是一个中文句子。") == "zh"
    assert detect_language("This is an English sentence about firms and data.") == "en"


def test_markers_load():
    markers = load_markers()
    assert "zh" in markers and "en" in markers
    assert markers["zh"]["template_phrases"]
