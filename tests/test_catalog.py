from app.catalog import Catalog, normalize_title, parse_title_lines


def test_parse_title_lines_deduplicates_case_and_punctuation():
    titles = parse_title_lines("# heading\nNaruto\n naruto \nJujutsu-Kaisen\n\nJujutsu Kaisen\n")
    assert titles == ["Naruto", "Jujutsu-Kaisen"]


def test_bulk_add_skips_duplicates_and_cross_list_conflicts():
    catalog = Catalog(available=["Naruto"], unavailable=["Gintama"])
    result = catalog.add("available", ["Naruto", "Black Clover", "gintama", "Solo Leveling"])
    assert result["added"] == ["Black Clover", "Solo Leveling"]
    assert result["duplicates"] == ["Naruto"]
    assert result["conflicts"] == ["gintama"]
    assert len(catalog.available) == 3


def test_bulk_remove_is_exact_and_reports_missing_titles():
    catalog = Catalog(available=["Naruto", "Naruto Shippuden", "Jujutsu Kaisen"])
    result = catalog.remove("available", ["Naruto", "missing", "naruto"])
    assert result["removed"] == ["Naruto"]
    assert result["not_found"] == ["missing"]
    assert catalog.available == ["Naruto Shippuden", "Jujutsu Kaisen"]


def test_replace_does_not_create_cross_list_overlap():
    catalog = Catalog(available=["Naruto"], unavailable=["Gintama"])
    result = catalog.replace("available", ["Black Clover", "Gintama", "Solo Leveling"])
    assert catalog.available == ["Black Clover", "Solo Leveling"]
    assert result["conflicts"] == ["Gintama"]
    assert catalog.unavailable == ["Gintama"]


def test_title_mention_finds_title_inside_longer_message_and_prefers_longest():
    catalog = Catalog(available=["Naruto", "Naruto Shippuden"], unavailable=["Gintama"])
    assert catalog.find_mentioned("Bro, Naruto Shippuden Tamil la iruka?") == ("Naruto Shippuden", "available")
    assert catalog.find_mentioned("GINTAMA bro") == ("Gintama", "unavailable")
    assert catalog.find_mentioned("I like football") is None


def test_fuzzy_spelling_suggestion_for_short_title_like_input():
    catalog = Catalog(available=["Naruto"], unavailable=["Gintama", "Jujutsu Kaisen"])
    assert catalog.suggest_correction("Gintma") == "Gintama"
    assert catalog.suggest_correction("Gintma bro") == "Gintama"
    assert catalog.suggest_correction("Naruto") is None
    assert catalog.suggest_correction("I watched gintma yesterday and liked it") is None
    assert normalize_title("Jujutsu-Kaisen!") == "jujutsu kaisen"


def test_tamil_title_normalization_preserves_unicode_letters():
    assert normalize_title("தமிழ் அனிமே") == "தமிழ் அனிமே"
