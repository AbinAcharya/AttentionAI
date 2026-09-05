from attentionai.urgency import UrgencyConfig, score_text


def test_word_boundaries_not_substrings() -> None:
    # v1 matched "help" inside "helpful" and scored it 0.9.
    assert score_text("that was really helpful, thanks").score < 0.2
    assert score_text("this is unhelpful").score < 0.2
    assert score_text("help").score >= 0.5


def test_negation_discounts_urgency() -> None:
    urgent = score_text("emergency, come now")
    negated = score_text("no emergency, just checking in")

    assert urgent.score >= 0.9
    assert negated.score <= 0.3
    assert "emergency" in negated.negated


def test_negation_only_applies_within_window() -> None:
    # "not" is far enough away that it is not modifying "emergency".
    signal = score_text("i am not sure who to ask but this is a real emergency")
    assert signal.score >= 0.9


def test_promotional_wording_suppresses_urgency() -> None:
    spam = score_text("URGENT! Claim your prize now, limited time offer")
    genuine = score_text("urgent, please call me")

    assert spam.score < genuine.score
    assert spam.spam_penalty > 0.5


def test_shouting_and_punctuation_add_a_little() -> None:
    plain = score_text("i need help")
    shouted = score_text("I NEED HELP!!")
    assert shouted.score > plain.score


def test_romanised_hindi_is_recognised() -> None:
    assert score_text("bhai emergency hai, jaldi call me").score >= 0.9
    assert score_text("madad chahiye").score >= 0.8


def test_empty_and_whitespace_are_floored_not_crashing() -> None:
    assert score_text(None).score > 0.0
    assert score_text("").score > 0.0
    assert score_text("   ").score > 0.0


def test_small_talk_scores_near_floor() -> None:
    for message in ["lol ok", "hey, how are you?", "happy new year!", "goodnight"]:
        assert score_text(message).score <= 0.2, message


def test_custom_terms_are_honoured() -> None:
    config = UrgencyConfig(terms={"ping": 0.9})
    assert score_text("please ping me", config).score >= 0.9
    assert score_text("emergency", config).score <= 0.2
