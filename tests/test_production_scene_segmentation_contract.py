from production_sheet_contract import PRODUCTION_SHEET_COLUMNS, validate_canonical_rows


def _row(excerpt: str, duration: str = "4.0", start: str = "0:00", end: str = "0:04", notes: str = ""):
    row = {c: "" for c in PRODUCTION_SHEET_COLUMNS}
    row.update({
        "scene_id": "S001",
        "start_time": start,
        "end_time": end,
        "duration_sec": duration,
        "scene_purpose": "EXPLAIN",
        "script_excerpt": excerpt,
        "visual_mode": "avatar_only",
        "avatar_required": "YES",
        "avatar_style": "virtual_educational_presenter",
        "background_style": "warm neutral studio",
        "narrative_context": "Current narration beat.",
        "visual_intent": "Keep the presenter on the exact narration idea.",
        "filmable": "PARTIAL",
        "asset_decision_reason": "Presenter explanation is appropriate.",
        "recommended_asset_type": "AVATAR",
        "recommended_shot": "medium presenter shot",
        "asset_source": "AVATAR",
        "asset_status": "READY",
        "motion": "subtle presenter framing",
        "transition": "soft cut",
        "notes": notes,
    })
    return row


def test_tiny_orphan_fragment_is_rejected():
    issues = validate_canonical_rows([_row("Just five.", duration="6", end="0:06")], PRODUCTION_SHEET_COLUMNS)
    assert any("only 2 words" in x for x in issues)
    assert any("too long" in x for x in issues)


def test_intentional_emphasis_can_keep_tiny_fragment_with_plausible_duration():
    issues = validate_canonical_rows([_row("Just five.", duration="1.2", end="0:01", notes="INTENTIONAL_EMPHASIS: deliberate beat")], PRODUCTION_SHEET_COLUMNS)
    assert not any("only 2 words" in x for x in issues)
    assert not any("too long" in x for x in issues)


def test_oversized_scene_is_rejected():
    excerpt = " ".join(["word"] * 40)
    issues = validate_canonical_rows([_row(excerpt, duration="12", end="0:12")], PRODUCTION_SHEET_COLUMNS)
    assert any("40 words" in x and "split" in x for x in issues)


def test_elapsed_time_must_not_be_hhmmss():
    issues = validate_canonical_rows([_row("This is a normal semantic scene with enough spoken words.", start="26:35:00", end="26:41:00")], PRODUCTION_SHEET_COLUMNS)
    assert any("start_time must use elapsed M:SS" in x for x in issues)
    assert any("end_time must use elapsed M:SS" in x for x in issues)


def test_hard_upper_bound_rejects_33_word_normal_scene():
    excerpt = " ".join(["word"] * 33)
    issues = validate_canonical_rows([_row(excerpt, duration="10", end="0:10")], PRODUCTION_SHEET_COLUMNS)
    assert any("33 words" in x and "split" in x for x in issues)


def test_explicit_long_avatar_exception_allows_over_32_words():
    excerpt = " ".join(["word"] * 36)
    issues = validate_canonical_rows([_row(excerpt, duration="10", end="0:10", notes="INTENTIONAL_LONG_AVATAR: one indivisible caution")], PRODUCTION_SHEET_COLUMNS)
    assert not any("36 words" in x and "split" in x for x in issues)
