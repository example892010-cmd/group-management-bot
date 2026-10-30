import random

from app.conversations import (
    Cooldown,
    ConversationEngine,
    detect_intent,
    detect_language,
)


def test_tanglish_detection_and_intents():
    assert detect_language("Epdi iruka bro?") == "tanglish"
    assert detect_intent("Epdi iruka bro?") == "how_are_you"
    assert detect_intent("Saptiya?") == "ate"
    assert detect_intent("Good morning bro") == "good_morning"
    assert detect_intent("Hi") == "greeting"


def test_english_and_tamil_detection():
    assert detect_language("How are you today?") == "english"
    assert detect_intent("How are you today?") == "how_are_you"
    assert detect_language("வணக்கம் நண்பா") == "tamil"
    assert detect_intent("வணக்கம்") == "greeting"


def test_engine_returns_language_matched_nonempty_response():
    engine = ConversationEngine(rng=random.Random(7))
    tanglish = engine.reply(-100, 10, "Hi bro")
    english = engine.reply(-100, 11, "Good morning")
    tamil = engine.reply(-100, 12, "வணக்கம்")
    assert tanglish and any(word in tanglish.casefold() for word in ("bro", "nanba", "hey", "dei", "vanakkam"))
    assert english
    assert tamil


def test_recent_reply_history_avoids_immediate_duplicate_base_reply():
    engine = ConversationEngine(rng=random.Random(99))
    replies = [engine.reply(-100, 101, "Hi bro") for _ in range(8)]
    assert len(set(replies)) > 1


def test_engine_has_at_least_one_lakh_reply_combinations():
    engine = ConversationEngine()
    assert engine.estimated_variant_count >= 100_000


def test_gif_and_sticker_reactions_are_available():
    engine = ConversationEngine(rng=random.Random(3))
    assert engine.media_reply(-1, 1, "gif")
    assert engine.media_reply(-1, 1, "sticker")


def test_unknown_long_post_does_not_get_generic_reply():
    assert detect_intent("This is a long unrelated announcement about a schedule for next month") is None


def test_cooldown_limits_fast_replies_per_user_and_chat():
    cooldown = Cooldown(seconds=6)
    assert cooldown.allow(-100, 4, 10.0)
    assert not cooldown.allow(-100, 4, 12.0)
    assert cooldown.allow(-100, 5, 12.0)
    assert cooldown.allow(-101, 4, 12.0)


def test_emoji_only_message_uses_tanglish_default_and_relevant_intent():
    assert detect_language("😂😂") == "tanglish"
    assert detect_language("❤️") == "tanglish"
    assert detect_intent("❤️") == "compliment"
    assert detect_intent("🔥") == "casual"
