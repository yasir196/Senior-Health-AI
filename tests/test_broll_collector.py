from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("broll_collector", ROOT / "Tools" / "broll_collector.py")
broll_collector = importlib.util.module_from_spec(SPEC)
sys.modules["broll_collector"] = broll_collector
assert SPEC.loader is not None
SPEC.loader.exec_module(broll_collector)


def scene(scene_id: str, narration: str, purpose: str = "PROBLEM", visual_mode: str = "broll", index: int = 1):
    row = {
        "scene_id": scene_id,
        "duration_sec": "6.0",
        "scene_purpose": purpose,
        "script_excerpt": narration,
        "visual_mode": visual_mode,
        "on_screen_text": "",
        "notes": "",
    }
    return broll_collector.Scene(row=row, index=index)


def candidate(
    title: str,
    tags: str = "",
    source: str = "Pexels",
    source_asset_id: str = "asset-1",
    url: str = "https://example.com/video/1",
    download_url: str = "https://cdn.example.com/video/1.mp4",
    preview_image: str = "data:image/jpeg;base64,dGVzdA==",
):
    return broll_collector.VideoCandidate(
        source=source,
        source_page_url=url,
        download_url=download_url,
        license_note="Test License",
        creator="creator",
        duration="10",
        width=1920,
        height=1080,
        title_text=title,
        query_used="test query",
        source_asset_id=source_asset_id,
        tags=tags,
        description=title,
        orientation="landscape",
        preview_image=preview_image,
    )


def shot_plan(searches):
    return broll_collector.ShotPlan(
        recommended_visual_mode="broll",
        scene_intent="routine",
        viewer_emotion="motivation",
        story_function="demonstrate",
        medical_context="none",
        recommended_shot="wide",
        subject="older adult",
        action="walking",
        setting="sidewalk",
        mood="calm",
        searches=searches,
        sequence_id="SEQ-TEST",
        sequence_position="1/1",
        continuity_note="",
        fallback_recommendation="MANUAL_SEARCH_REQUIRED",
    )


class BrollCollectorQueryTests(unittest.TestCase):
    def test_abstract_emotion_terms_are_removed_from_queries(self) -> None:
        query = broll_collector.clean_search_query(
            "older adult walking comfortably quiet neighborhood path tracking motivation and natural curiosity"
        )
        for term in ["motivation", "natural", "curiosity", "trust", "reassurance"]:
            self.assertNotIn(term, query)
        self.assertIn("older adult", query)

    def test_action_extraction_uses_chair_specific_visuals(self) -> None:
        current = scene("S001", "Standing from a chair uses thighs, hips, feet, confidence, and balance.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        self.assertIn("standing from", plan.searches[0])
        self.assertTrue(any("armrests" in query or "knees and feet" in query for query in plan.searches))
        self.assertTrue(broll_collector.alternatives_are_semantically_diverse(plan.searches))

    def test_long_sitting_generates_daily_life_visuals(self) -> None:
        current = scene("S002", "A whole afternoon can slip by while watching television without a standing break.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        joined = " | ".join(plan.searches)
        self.assertIn("television", joined)
        self.assertIn("standing up after sitting", joined)
        self.assertIn("movement break", joined)

    def test_balance_and_stairs_extract_distinct_actions(self) -> None:
        balance = scene("S003", "Balance changes when someone turns in a hallway or steps from carpet to tile.")
        stairs = scene("S004", "A person may pause at the first stair and use the handrail.")
        balance_plan = broll_collector.plan_scene(balance, 2, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/2"))
        stairs_plan = broll_collector.plan_scene(stairs, 2, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "2/2"))
        self.assertTrue(any("carpet to tile" in query for query in balance_plan.searches))
        self.assertTrue(any("handrail" in query or "stair rail" in query for query in stairs_plan.searches))
        self.assertNotEqual(broll_collector.base_query_key(balance_plan.searches[0]), broll_collector.base_query_key(stairs_plan.searches[0]))

    def test_evidence_scene_avoids_generic_documents_as_default(self) -> None:
        current = scene(
            "S005",
            "In one trial, a home-based strength and balance program for older women was linked to fewer falls.",
            purpose="PROOF",
        )
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        self.assertEqual(plan.recommended_visual_mode, "broll")
        self.assertNotIn("generic documents showing neutral research materials clean desk", " ".join(plan.searches))
        self.assertTrue(any("exercise instruction sheet" in query or "printed strength and balance routine" in query for query in plan.searches))

    def test_normalized_duplicate_detection_ignores_shot_only_changes(self) -> None:
        wide = "older adult standing from dining chair at home wide shot"
        close = "older adult standing from dining chair at home close up"
        self.assertEqual(broll_collector.normalize_query(wide), broll_collector.normalize_query(close))

    def test_select_diverse_primary_avoids_duplicate_and_category_caps(self) -> None:
        used = {
            "actions": [],
            "shots": [],
            "queries": [],
            "normalized_queries": [broll_collector.normalize_query("older man walking on quiet neighborhood sidewalk")],
            "base_queries": [broll_collector.base_query_key("older man walking on quiet neighborhood sidewalk")],
            "categories": ["walking", "walking"],
        }
        queries = [
            "older man walking on quiet neighborhood sidewalk",
            "senior shoes walking on even pavement",
            "older adult feet shifting weight near support",
            "senior hand holding stair rail",
        ]
        selected = broll_collector.select_diverse_primary(queries, used, {"repetition_window": 8})
        self.assertNotEqual(broll_collector.query_category(selected[0]), "walking")
        self.assertNotEqual(broll_collector.normalize_query(selected[0]), broll_collector.normalize_query(queries[0]))

    def test_eight_distinct_concrete_actions_are_represented(self) -> None:
        narrations = [
            "The chair reveals how someone stands from a seat.",
            "Long sitting can mean watching television for several episodes.",
            "Balance changes when stepping from carpet to tile.",
            "A front step may require using a handrail.",
            "Fear can make someone hesitate at the doorway.",
            "Walking on a sidewalk still supports endurance.",
            "A home exercise program can be followed from a printed routine.",
            "A safety conversation may happen with a physical therapist.",
        ]
        actions = set()
        used = {"actions": [], "shots": [], "queries": [], "normalized_queries": [], "base_queries": [], "categories": []}
        for index, narration in enumerate(narrations, start=1):
            current = scene(f"S{index:03d}", narration, purpose="PROOF" if "program" in narration else "PROBLEM", index=index)
            plan = broll_collector.plan_scene(current, len(narrations), broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", f"{index}/8"))
            plan.searches = broll_collector.select_diverse_primary(plan.searches, used, broll_collector.DEFAULT_CONFIG)
            actions.add(plan.action)
            broll_collector.update_repetition_state(plan, used)
        self.assertGreaterEqual(len(actions), 8)

    def test_unfilmable_abstract_scene_skips_stock_search(self) -> None:
        current = scene("S009", "The real framework is a system of confidence, reserve, and daily independence.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        self.assertFalse(plan.filmable)
        self.assertNotEqual(plan.recommended_visual_mode, "broll")
        self.assertIn(plan.fallback_recommendation, {"AI_IMAGE_RECOMMENDED", "GRAPHIC_RECOMMENDED", "AVATAR_RECOMMENDED"})

    def test_concreteness_prioritizes_filmable_query_details(self) -> None:
        ideas = [
            ("older adult", "thinking about independence", "daily life"),
            ("older adult", "holding handrail while stepping onto stair", "home staircase"),
            ("senior", "considering a better way", "front area"),
        ]
        ranked = broll_collector.rank_visual_ideas_by_concreteness(ideas)
        self.assertEqual(ranked[0][1], "holding handrail while stepping onto stair")

    def test_useless_words_are_removed_from_queries(self) -> None:
        query = broll_collector.clean_search_query("person people thing front body time day life way chair handrail")
        for word in ["person", "people", "thing", "front", "body", "time", "day", "life", "way"]:
            self.assertNotIn(word, query.split())
        self.assertIn("chair", query)
        self.assertIn("handrail", query)

    def test_llm_query_builder_falls_back_to_offline_mode(self) -> None:
        current = scene("S009B", "An older adult standing from a chair uses the legs and armrests.")
        offline = broll_collector.make_queries(
            "older adult",
            "standing from dining chair",
            "living room at home",
            "medium",
            scene=current,
            intent="routine",
            config={**broll_collector.DEFAULT_CONFIG, "query_builder_mode": "offline"},
        )
        llm_fallback = broll_collector.make_queries(
            "older adult",
            "standing from dining chair",
            "living room at home",
            "medium",
            scene=current,
            intent="routine",
            config={**broll_collector.DEFAULT_CONFIG, "query_builder_mode": "llm"},
        )
        self.assertEqual(llm_fallback, offline)

    def test_optional_scene_grouping_preserves_scene_ids_duration_and_narration(self) -> None:
        scenes = [
            scene("S101", "An older adult walks through the hallway.", index=1),
            scene("S102", "The same person reaches the kitchen counter.", index=2),
            scene("S103", "A simple framework appears on screen.", visual_mode="graphic_explainer", index=3),
        ]
        before = [(item.scene_id, item.duration, item.narration) for item in scenes]
        sequence_map = broll_collector.build_story_sequences(
            scenes,
            {**broll_collector.DEFAULT_CONFIG, "enable_llm_scene_grouping": True, "scene_group_chunk_size": 2},
        )
        after = [(item.scene_id, item.duration, item.narration) for item in scenes]
        self.assertEqual(after, before)
        self.assertEqual(set(sequence_map), {"S101", "S102", "S103"})

    def test_three_level_query_ladder_is_rich_medium_short(self) -> None:
        current = scene("S104", "An older adult climbing one stair using the handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        rich, medium, short = plan.searches[:3]
        self.assertIn("older adult", rich)
        self.assertIn("climbing", rich)
        self.assertIn("stair", rich)
        self.assertIn("older adult", medium)
        self.assertIn("climbing", medium)
        self.assertLessEqual(len(short.split()), 4)
        self.assertNotEqual(broll_collector.normalize_query(rich), broll_collector.normalize_query(medium))
        self.assertNotEqual(broll_collector.normalize_query(medium), broll_collector.normalize_query(short))

    def test_clip_validation_is_optional_and_after_preview_gate(self) -> None:
        current = scene("S105", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item = broll_collector.validate_candidate_clip(item, plan, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(item.clip_validation_status, "DISABLED")
        item = broll_collector.validate_candidate_clip(
            item,
            plan,
            {**broll_collector.DEFAULT_CONFIG, "enable_clip_validation": True, "enable_vision_validation": True},
        )
        self.assertEqual(item.clip_validation_status, "SKIPPED")
        self.assertIn("preview", item.clip_validation_note)

    def test_phash_does_not_replace_exact_duplicate_detection(self) -> None:
        current = scene("S106", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-99"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item.perceptual_hashes = ["ffffffffffffffff"]
        duplicate_index = {"pexels:px-99": {"scene_id": "S001"}, "phash:0000000000000000": {"scene_id": "S002"}}
        broll_collector.mark_duplicate(
            item,
            current,
            duplicate_index,
            {},
            {**broll_collector.DEFAULT_CONFIG, "enable_perceptual_hash": True},
        )
        self.assertEqual(item.duplicate_status, "DUPLICATE")
        self.assertIn("same source asset ID", item.duplicate_reason)

    def test_phash_near_duplicate_is_secondary_and_unique_candidate_preferred(self) -> None:
        current = scene("S107", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        near = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-near"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        near.perceptual_hashes = ["0000000000000001"]
        unique = broll_collector.validate_candidate_semantics(
            candidate("older woman walking on sidewalk", "older adult walking sidewalk", source_asset_id="px-unique"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        duplicate_index = {"phash:0000000000000000": {"scene_id": "S001"}}
        config = {**broll_collector.DEFAULT_CONFIG, "enable_perceptual_hash": True, "perceptual_hash_threshold": 2}
        selected, _ = broll_collector.choose_valid_candidate([near, unique], current, duplicate_index, {}, config)
        self.assertEqual(near.duplicate_status, "POSSIBLE_NEAR_DUPLICATE")
        self.assertEqual(selected.source_asset_id, "px-unique")

    def test_easter_clip_rejected_for_chair_rise_query(self) -> None:
        current = scene("S010", "An older adult standing from a dining chair at home shows chair-rise control.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        wrong = candidate("woman preparing for Easter celebration", "holiday party flowers")
        scored = broll_collector.validate_candidate_semantics(wrong, plan, current, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(scored.match_status, "REJECT")
        self.assertEqual(scored.hard_match_pass, "NO")

    def test_playing_cards_rejected_for_printed_routine_query(self) -> None:
        current = scene("S011", "An older adult following a printed home exercise routine at the kitchen table.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        wrong = candidate("senior playing cards with friends", "card game table")
        scored = broll_collector.validate_candidate_semantics(wrong, plan, current, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(scored.match_status, "REJECT")
        self.assertIn("required action", scored.rejection_reason)

    def test_trees_pathway_rejected_for_older_adult_walking_query(self) -> None:
        current = scene("S012", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        wrong = candidate("trees beside pathway with no people", "forest path landscape no people")
        scored = broll_collector.validate_candidate_semantics(wrong, plan, current, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(scored.match_status, "REJECT")
        self.assertIn("background-only", scored.rejection_reason)

    def test_same_source_asset_id_cannot_be_selected_twice(self) -> None:
        current = scene("S013", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        first = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-1"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        duplicate_index = {}
        creator_counts = {}
        selected, _ = broll_collector.choose_valid_candidate([first], current, duplicate_index, creator_counts, broll_collector.DEFAULT_CONFIG)
        self.assertIsNotNone(selected)
        second_scene = scene("S014", "An older adult walking on a quiet neighborhood sidewalk.", index=2)
        duplicate = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-1"),
            plan,
            second_scene,
            broll_collector.DEFAULT_CONFIG,
        )
        selected_again, _ = broll_collector.choose_valid_candidate([duplicate], second_scene, duplicate_index, creator_counts, broll_collector.DEFAULT_CONFIG)
        self.assertIsNone(selected_again)
        self.assertEqual(duplicate.duplicate_status, "DUPLICATE")

    def test_duplicate_url_variants_are_blocked(self) -> None:
        current = scene("S015", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        duplicate_index = {"https://cdn.example.com/video/1.mp4": {"scene_id": "S001"}}
        item = broll_collector.validate_candidate_semantics(
            candidate(
                "older senior walking on neighborhood sidewalk",
                "older adult walking sidewalk",
                source_asset_id="new-id",
                download_url="https://cdn.example.com/video/1.mp4?download=true&w=1920",
            ),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        broll_collector.mark_duplicate(item, current, duplicate_index, {}, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(item.duplicate_status, "DUPLICATE")
        self.assertEqual(item.duplicate_of_scene, "S001")

    def test_no_asset_below_threshold_is_selected(self) -> None:
        current = scene("S016", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        weak = broll_collector.validate_candidate_semantics(
            candidate("older adult standing outdoors", "senior outside"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        weak.relevance_score = 61
        weak.match_status = "WEAK_MATCH"
        weak.hard_match_pass = "YES"
        selected, reason = broll_collector.choose_valid_candidate([weak], current, {}, {}, broll_collector.DEFAULT_CONFIG)
        self.assertIsNone(selected)
        self.assertIn("no candidate", reason)

    def test_valid_fallback_when_no_good_match_exists(self) -> None:
        self.assertIn(
            broll_collector.fallback_for_mode("fullscreen_image", "low"),
            {"AI_IMAGE_RECOMMENDED", "AVATAR_RECOMMENDED", "GRAPHIC_RECOMMENDED", "MANUAL_SEARCH_REQUIRED"},
        )

    def test_download_retries_next_valid_candidate_after_failure(self) -> None:
        current = scene("S017", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        first = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-1", download_url="bad"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        second = broll_collector.validate_candidate_semantics(
            candidate("older woman walking on sidewalk", "older adult walking sidewalk", source_asset_id="px-2", download_url="good"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        attempts = []

        def fake_download(url, destination, retries=3):
            attempts.append(url)
            if url == "bad":
                raise RuntimeError("failed")

        old_download = broll_collector.download_file
        try:
            broll_collector.download_file = fake_download
            selected = None
            for item in [first, second]:
                try:
                    broll_collector.download_file(item.download_url, ROOT / "mock_clip.mp4")
                    selected = item
                    break
                except RuntimeError:
                    continue
            self.assertEqual(selected.source_asset_id, "px-2")
            self.assertEqual(attempts, ["bad", "good"])
        finally:
            broll_collector.download_file = old_download

    def test_manifest_columns_preserve_legacy_fields(self) -> None:
        columns = broll_collector.dedupe_columns(broll_collector.MANIFEST_COLUMNS)
        legacy = ["asset_id", "scene_id", "source", "search_query", "local_path", "original_url", "license", "creator", "duration", "resolution", "status", "notes"]
        self.assertEqual(columns[: len(legacy)], legacy)
        self.assertIn("source_asset_id", columns)
        self.assertIn("semantic_score", columns)

    def test_cli_help_passes(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "Tools" / "broll_collector.py"), "--help"], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--show-candidates", result.stdout)
        self.assertIn("--validate-only", result.stdout)
        self.assertIn("--fast-download", result.stdout)
        self.assertIn("--profile-scene", result.stdout)

    def test_preferred_video_file_chooses_1080p_over_4k(self) -> None:
        files = [
            {"link": "4k.mp4", "width": 3840, "height": 2160, "file_size": 900000000},
            {"link": "1080.mp4", "width": 1920, "height": 1080, "file_size": 90000000},
            {"link": "720.mp4", "width": 1280, "height": 720, "file_size": 50000000},
        ]
        chosen = broll_collector.choose_preferred_video_file(files, True)
        self.assertEqual(chosen["link"], "1080.mp4")

    def test_scene_with_existing_manifest_asset_is_skipped(self) -> None:
        rows = [
            {
                "scene_id": "S001",
                "source": "Pexels",
                "status": "MATCHED_DRY_RUN",
                "source_asset_id": "px-existing",
                "original_url": "https://example.com/existing",
                "download_url": "https://cdn.example.com/existing.mp4",
            }
        ]
        self.assertTrue(broll_collector.scene_has_valid_manifest_asset(rows, "S001"))
        self.assertFalse(broll_collector.scene_has_valid_manifest_asset(rows, "S002"))

    def test_download_file_defaults_are_fast_production_timeouts(self) -> None:
        import inspect

        signature = inspect.signature(broll_collector.download_file)
        self.assertEqual(signature.parameters["retries"].default, 2)
        self.assertEqual(signature.parameters["connect_timeout"].default, 10)
        self.assertEqual(signature.parameters["download_timeout"].default, 90)

    def test_fast_download_config_uses_small_pool_and_one_asset(self) -> None:
        config = {**broll_collector.DEFAULT_CONFIG, "candidate_pool_size": 15, "max_downloads_per_scene": 4}
        broll_collector.apply_fast_download_config(config)
        self.assertEqual(config["candidate_pool_size"], 3)
        self.assertEqual(config["max_downloads_per_scene"], 1)
        self.assertTrue(config["prefer_1080p_download"])

    def test_disabled_clip_and_phash_do_not_process(self) -> None:
        current, item = self.selectable_candidate("Pexels", "px-disabled-expensive")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_clip(item, plan, {**broll_collector.DEFAULT_CONFIG, "enable_clip_validation": False})
        self.assertEqual(item.clip_validation_status, "DISABLED")
        hashes = broll_collector.sampled_perceptual_hashes(ROOT / "missing.mp4", {**broll_collector.DEFAULT_CONFIG, "enable_perceptual_hash": False})
        self.assertEqual(hashes, [])

    def test_vision_validation_default_disabled_does_not_reject(self) -> None:
        current = scene("S018", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item = broll_collector.validate_candidate_vision(item, plan, current, broll_collector.DEFAULT_CONFIG)
        self.assertEqual(item.vision_validation_status, "DISABLED")
        self.assertNotEqual(item.match_status, "REJECT")

    def test_enabled_vision_validation_rejects_visual_mismatch(self) -> None:
        current = scene("S019", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        old_call = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = lambda preview, prompt, config: {
                "subject_exists": False,
                "action_exists": False,
                "age_group_matches": False,
                "setting_matches": True,
                "medical_context_matches": True,
                "reject": True,
                "note": "preview shows trees and no older adult",
            }
            item = broll_collector.validate_candidate_vision(
                item,
                plan,
                current,
                {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
            )
        finally:
            broll_collector.call_vision_model = old_call
        self.assertEqual(item.vision_validation_status, "FAILED")
        self.assertEqual(item.match_status, "REJECT")
        self.assertIn("trees", item.vision_validation_note)

    def assert_preview_rejects(self, narration: str, title: str, tags: str, result: dict[str, object], note_fragment: str) -> None:
        current = scene("S020", narration)
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate(title, tags),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        old_call = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = lambda preview, prompt, config: result
            item = broll_collector.validate_candidate_vision(
                item,
                plan,
                current,
                {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
            )
        finally:
            broll_collector.call_vision_model = old_call
        self.assertEqual(item.vision_validation_status, "FAILED")
        self.assertEqual(item.match_status, "REJECT")
        self.assertIn(note_fragment, item.vision_validation_note)

    def test_preview_validation_rejects_roof_for_stairs(self) -> None:
        self.assert_preview_rejects(
            "An older adult climbing one stair using a handrail.",
            "older adult climbing one stair using handrail",
            "older adult stairs handrail",
            {
                "subject_exists": False,
                "action_exists": False,
                "age_group_matches": False,
                "setting_matches": False,
                "medical_context_matches": False,
                "reject": True,
                "note": "preview shows roof ceiling shot, not stairs",
            },
            "roof",
        )

    def test_preview_validation_rejects_empty_road_for_walking(self) -> None:
        self.assert_preview_rejects(
            "An older adult walking on a quiet neighborhood sidewalk.",
            "older adult walking on sidewalk",
            "older adult walking sidewalk",
            {
                "subject_exists": False,
                "action_exists": False,
                "age_group_matches": False,
                "setting_matches": True,
                "medical_context_matches": False,
                "reject": True,
                "note": "preview shows empty road with no person walking",
            },
            "empty road",
        )

    def test_preview_validation_rejects_unrelated_home_activity_for_chair_rise(self) -> None:
        self.assert_preview_rejects(
            "An older adult standing from a dining chair at home shows chair-rise control.",
            "older adult standing from dining chair at home",
            "older adult chair rise home",
            {
                "subject_exists": True,
                "action_exists": False,
                "age_group_matches": True,
                "setting_matches": True,
                "medical_context_matches": False,
                "reject": True,
                "note": "preview shows person cooking, not a chair rise",
            },
            "cooking",
        )

    def test_preview_validation_rejects_sitting_for_balance(self) -> None:
        self.assert_preview_rejects(
            "An older adult practicing supported balance near a kitchen counter.",
            "older adult supported balance at kitchen counter",
            "older adult balance counter",
            {
                "subject_exists": True,
                "action_exists": False,
                "age_group_matches": True,
                "setting_matches": True,
                "medical_context_matches": False,
                "reject": True,
                "note": "preview shows person sitting, not balance practice",
            },
            "sitting",
        )

    def test_preview_rejection_blocks_video_download_and_tries_next_candidate(self) -> None:
        current = scene("S021", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        first = broll_collector.validate_candidate_semantics(
            candidate(
                "older senior walking on neighborhood sidewalk",
                "older adult walking sidewalk",
                source_asset_id="px-1",
                download_url="bad-video",
                preview_image="bad-preview",
            ),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        second = broll_collector.validate_candidate_semantics(
            candidate(
                "older woman walking on sidewalk",
                "older adult walking sidewalk",
                source_asset_id="px-2",
                download_url="good-video",
                preview_image="good-preview",
            ),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        video_downloads = []

        def fake_vision(preview, prompt, config):
            if preview == "bad-preview":
                return {
                    "subject_exists": False,
                    "action_exists": False,
                    "age_group_matches": False,
                    "setting_matches": True,
                    "medical_context_matches": False,
                    "reject": True,
                    "note": "preview shows empty street",
                }
            return {
                "subject_exists": True,
                "action_exists": True,
                "age_group_matches": True,
                "setting_matches": True,
                "medical_context_matches": True,
                "reject": False,
                "note": "preview matches older adult walking",
            }

        def fake_download(url, destination, retries=3):
            video_downloads.append(url)

        old_call = broll_collector.call_vision_model
        old_download = broll_collector.download_file
        try:
            broll_collector.call_vision_model = fake_vision
            broll_collector.download_file = fake_download
            selected = None
            config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "vision_validation_required": True}
            for item in [first, second]:
                if not broll_collector.candidate_preview_passes_before_download(item, plan, current, config):
                    continue
                broll_collector.download_file(item.download_url, ROOT / "mock_clip.mp4")
                selected = item
                break
        finally:
            broll_collector.call_vision_model = old_call
            broll_collector.download_file = old_download
        self.assertEqual(first.vision_validation_status, "FAILED")
        self.assertEqual(selected.source_asset_id, "px-2")
        self.assertEqual(video_downloads, ["good-video"])

    def validate_stair_preview(self, result: dict[str, object]):
        current = scene("S022", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult climbing one stair using handrail at home", "older adult stairs handrail stepping home"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        old_call = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = lambda preview, prompt, config: result
            return broll_collector.validate_candidate_vision(
                item,
                plan,
                current,
                {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
            )
        finally:
            broll_collector.call_vision_model = old_call

    def test_stairs_without_fully_visible_handrail_can_be_acceptable(self) -> None:
        item = self.validate_stair_preview(
            {
                "older_adult_visible": True,
                "stairs_or_step_visible": True,
                "stepping_action_visible": True,
                "handrail_or_support_visible": False,
                "home_or_interior_visible": False,
                "medical_safety_ok": True,
                "note": "older adult stepping upward on stairs; rail is cropped out",
            }
        )
        self.assertEqual(item.vision_validation_status, "ACCEPTABLE")
        self.assertEqual(item.vision_decision, "VISION_ACCEPTABLE")
        self.assertGreaterEqual(item.vision_best_frame_score, 70)

    def test_empty_staircase_fails_weighted_vision(self) -> None:
        item = self.validate_stair_preview(
            {
                "older_adult_visible": False,
                "stairs_or_step_visible": True,
                "stepping_action_visible": False,
                "handrail_or_support_visible": True,
                "home_or_interior_visible": True,
                "medical_safety_ok": True,
                "note": "empty staircase",
            }
        )
        self.assertEqual(item.vision_validation_status, "FAILED")
        self.assertIn("older adult", item.vision_rejection_reason)

    def test_younger_person_on_stairs_fails_demographic_requirement(self) -> None:
        item = self.validate_stair_preview(
            {
                "older_adult_visible": False,
                "subject_exists": True,
                "age_group_matches": False,
                "stairs_or_step_visible": True,
                "stepping_action_visible": True,
                "handrail_or_support_visible": True,
                "home_or_interior_visible": True,
                "medical_safety_ok": True,
                "note": "younger adult on stairs",
            }
        )
        self.assertEqual(item.vision_validation_status, "FAILED")
        self.assertIn("older adult", item.vision_rejection_reason)

    def test_older_adult_near_stairs_without_stepping_is_not_auto_selected(self) -> None:
        item = self.validate_stair_preview(
            {
                "older_adult_visible": True,
                "stairs_or_step_visible": True,
                "stepping_action_visible": False,
                "handrail_or_support_visible": True,
                "home_or_interior_visible": True,
                "medical_safety_ok": True,
                "note": "older adult standing near stairs but not stepping",
            }
        )
        self.assertEqual(item.vision_validation_status, "UNCERTAIN")
        self.assertLess(item.vision_best_frame_score, 70)

    def test_roof_or_ceiling_footage_fails_weighted_vision(self) -> None:
        item = self.validate_stair_preview(
            {
                "older_adult_visible": False,
                "stairs_or_step_visible": False,
                "stepping_action_visible": False,
                "handrail_or_support_visible": False,
                "home_or_interior_visible": False,
                "medical_safety_ok": True,
                "unrelated_activity": True,
                "note": "roof ceiling shot",
            }
        )
        self.assertEqual(item.vision_validation_status, "FAILED")
        self.assertEqual(item.vision_decision, "VISION_FAIL")

    def test_multiframe_validation_rescues_relevant_clip_after_bad_first_frame(self) -> None:
        current = scene("S023", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult climbing one stair using handrail at home", "older adult stairs handrail stepping home", preview_image="bad-frame"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item.raw = {"image": "good-frame"}
        calls = []

        def fake_vision(preview, prompt, config):
            calls.append(preview)
            if preview == "bad-frame":
                return {
                    "older_adult_visible": False,
                    "stairs_or_step_visible": False,
                    "stepping_action_visible": False,
                    "medical_safety_ok": True,
                    "note": "misleading first frame",
                }
            return {
                "older_adult_visible": True,
                "stairs_or_step_visible": True,
                "stepping_action_visible": True,
                "handrail_or_support_visible": False,
                "home_or_interior_visible": True,
                "medical_safety_ok": True,
                "note": "older adult stepping on stairs",
            }

        old_call = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = fake_vision
            item = broll_collector.validate_candidate_vision(
                item,
                plan,
                current,
                {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "vision_preview_frame_limit": 3},
            )
        finally:
            broll_collector.call_vision_model = old_call
        self.assertEqual(calls, ["bad-frame", "good-frame"])
        self.assertIn(item.vision_validation_status, {"PASSED", "ACCEPTABLE"})
        self.assertGreaterEqual(item.vision_best_frame_score, 70)

    def test_no_candidate_below_vision_70_is_auto_downloadable(self) -> None:
        current = scene("S024", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult climbing one stair using handrail at home", "older adult stairs handrail stepping home"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item.vision_validation_status = "UNCERTAIN"
        item.vision_decision = "VISION_UNCERTAIN"
        item.vision_best_frame_score = 69
        selected, _ = broll_collector.choose_valid_candidate(
            [item],
            current,
            {},
            {},
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertIsNone(selected)

    def vision_score_payload(self) -> dict[str, object]:
        return {
            "subject_score": 25,
            "action_score": 25,
            "setting_score": 30,
            "support_score": 15,
            "safety_score": 5,
            "best_frame_score": 100,
            "average_frame_score": 92,
            "decision": "VISION_PASS",
            "rejection_reason": "",
        }

    def parse_vision_text(self, text: str) -> dict[str, object]:
        return broll_collector.parsed_vision_response(text, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})

    def test_plain_valid_vision_json_parses(self) -> None:
        parsed = self.parse_vision_text(json.dumps(self.vision_score_payload()))
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["best_frame_score"], 100)
        self.assertEqual(parsed["_vision_parse_status"], "direct")

    def test_vision_json_inside_json_fence_parses(self) -> None:
        parsed = self.parse_vision_text("```json\n" + json.dumps(self.vision_score_payload()) + "\n```")
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_parse_status"], "code_fence")

    def test_vision_json_inside_generic_fence_parses(self) -> None:
        parsed = self.parse_vision_text("```\n" + json.dumps(self.vision_score_payload()) + "\n```")
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_parse_status"], "code_fence")

    def test_vision_json_with_prose_before_and_after_parses(self) -> None:
        parsed = self.parse_vision_text("Here is the result:\n" + json.dumps(self.vision_score_payload()) + "\nLooks good.")
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_parse_status"], "balanced_object")

    def test_single_item_vision_json_array_parses(self) -> None:
        parsed = self.parse_vision_text(json.dumps([self.vision_score_payload()]))
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_parse_status"], "direct")

    def test_json_encoded_vision_string_parses(self) -> None:
        parsed = self.parse_vision_text(json.dumps(json.dumps(self.vision_score_payload())))
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_parse_status"], "direct")

    def test_vision_numeric_percent_values_are_coerced(self) -> None:
        payload = self.vision_score_payload()
        payload["best_frame_score"] = "85%"
        payload["average_frame_score"] = "85.0"
        payload["overall_score"] = "85%"
        parsed = self.parse_vision_text(json.dumps(payload))
        self.assertEqual(parsed["best_frame_score"], 85)
        self.assertEqual(parsed["average_frame_score"], 85)

    def test_vision_missing_optional_field_still_parses(self) -> None:
        payload = self.vision_score_payload()
        payload.pop("support_score")
        parsed = self.parse_vision_text(json.dumps(payload))
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertNotEqual(parsed.get("status"), "ERROR")

    def test_invalid_vision_response_repairs_successfully(self) -> None:
        old_repair = broll_collector.request_vision_json_repair
        try:
            broll_collector.request_vision_json_repair = lambda raw, config: (json.dumps(self.vision_score_payload()), "")
            parsed = self.parse_vision_text("not json")
        finally:
            broll_collector.request_vision_json_repair = old_repair
        self.assertEqual(parsed["decision"], "VISION_PASS")
        self.assertEqual(parsed["_vision_repair_attempted"], "YES")
        self.assertEqual(parsed["_vision_repair_success"], "YES")

    def test_invalid_vision_response_after_repair_becomes_error(self) -> None:
        old_repair = broll_collector.request_vision_json_repair
        try:
            broll_collector.request_vision_json_repair = lambda raw, config: ("still not json", "")
            parsed = self.parse_vision_text("not json")
        finally:
            broll_collector.request_vision_json_repair = old_repair
        self.assertEqual(parsed["status"], "ERROR")
        self.assertEqual(parsed["decision"], "ERROR")
        self.assertEqual(parsed["_vision_repair_attempted"], "YES")
        self.assertEqual(parsed["_vision_repair_success"], "NO")
        self.assertIn("not parseable", parsed["note"])

    def test_existing_boolean_vision_response_remains_compatible(self) -> None:
        payload = {
            "older_adult_visible": True,
            "stairs_or_step_visible": True,
            "stepping_action_visible": True,
            "handrail_or_support_visible": False,
            "home_or_interior_visible": True,
            "medical_safety_ok": True,
            "note": "compatible response",
        }
        parsed = self.parse_vision_text(json.dumps(payload))
        self.assertTrue(parsed["older_adult_visible"])
        self.assertEqual(parsed["note"], "compatible response")

    def test_s006_style_wrapped_vision_json_does_not_reject_strong_candidate(self) -> None:
        current = scene("S006", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult climbing one stair using handrail home staircase", "older adult stairs handrail stepping home"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        old_call = broll_collector.call_vision_model
        try:
            wrapped = "```json\n" + json.dumps(self.vision_score_payload()) + "\n```"
            broll_collector.call_vision_model = lambda preview, prompt, config: broll_collector.parsed_vision_response(wrapped, config)
            item = broll_collector.validate_candidate_vision(
                item,
                plan,
                current,
                {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
            )
        finally:
            broll_collector.call_vision_model = old_call
        self.assertIn(item.vision_validation_status, {"PASSED", "ACCEPTABLE"})
        self.assertNotEqual(item.rejection_reason, "vision response was not parseable JSON")
        self.assertEqual(item.vision_parse_status, "code_fence")

    def selectable_candidate(self, source: str, source_asset_id: str, url: str = "https://example.com/video/1"):
        current = scene("S030", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate(
                "older senior walking on neighborhood sidewalk",
                "older adult walking sidewalk",
                source=source,
                source_asset_id=source_asset_id,
                url=url,
                download_url=f"{url}/download.mp4",
            ),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item.vision_validation_status = "PASSED"
        item.vision_decision = "VISION_PASS"
        item.vision_best_frame_score = 90
        item.vision_average_frame_score = 90
        return current, item

    def test_same_pexels_id_cannot_be_selected_twice_in_dry_run(self) -> None:
        duplicate_index = {}
        creator_counts = {}
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}
        first_scene, first = self.selectable_candidate("Pexels", "px-123")
        selected, _ = broll_collector.choose_valid_candidate([first], first_scene, duplicate_index, creator_counts, config)
        self.assertIsNotNone(selected)
        second_scene, second = self.selectable_candidate("Pexels", "px-123")
        selected_again, _ = broll_collector.choose_valid_candidate([second], second_scene, duplicate_index, creator_counts, config)
        self.assertIsNone(selected_again)
        self.assertEqual(second.duplicate_status, "DUPLICATE")
        self.assertEqual(second.duplicate_of_scene, first_scene.scene_id)

    def test_same_pixabay_id_cannot_be_selected_twice_in_dry_run(self) -> None:
        duplicate_index = {}
        creator_counts = {}
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}
        first_scene, first = self.selectable_candidate("Pixabay", "pb-123")
        selected, _ = broll_collector.choose_valid_candidate([first], first_scene, duplicate_index, creator_counts, config)
        self.assertIsNotNone(selected)
        second_scene, second = self.selectable_candidate("Pixabay", "pb-123")
        selected_again, _ = broll_collector.choose_valid_candidate([second], second_scene, duplicate_index, creator_counts, config)
        self.assertIsNone(selected_again)
        self.assertEqual(second.duplicate_status, "DUPLICATE")

    def test_same_source_url_cannot_be_selected_twice(self) -> None:
        duplicate_index = {}
        creator_counts = {}
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}
        first_scene, first = self.selectable_candidate("Pexels", "px-1", url="https://example.com/shared")
        selected, _ = broll_collector.choose_valid_candidate([first], first_scene, duplicate_index, creator_counts, config)
        self.assertIsNotNone(selected)
        second_scene, second = self.selectable_candidate("Pexels", "px-2", url="https://example.com/shared")
        selected_again, _ = broll_collector.choose_valid_candidate([second], second_scene, duplicate_index, creator_counts, config)
        self.assertIsNone(selected_again)
        self.assertEqual(second.duplicate_status, "DUPLICATE")

    def test_assets_are_reserved_before_download(self) -> None:
        duplicate_index = {}
        creator_counts = {}
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}
        current, item = self.selectable_candidate("Pexels", "px-reserved")
        selected, _ = broll_collector.choose_valid_candidate([item], current, duplicate_index, creator_counts, config)
        self.assertIsNotNone(selected)
        self.assertIn("asset:pexels:px-reserved", duplicate_index)
        self.assertIn("pexels:px-reserved", duplicate_index)

    def test_vision_enabled_cannot_select_disabled_candidate(self) -> None:
        current, item = self.selectable_candidate("Pexels", "px-disabled")
        item.vision_validation_status = "DISABLED"
        selected, _ = broll_collector.choose_valid_candidate([item], current, {}, {}, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})
        self.assertIsNone(selected)
        self.assertEqual(item.match_status, "REJECT")
        self.assertIn("DISABLED", item.rejection_reason)

    def test_missing_vision_provider_produces_error_and_no_selection(self) -> None:
        current = scene("S031", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", preview_image="bad-preview"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        old_call = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = lambda preview, prompt, config: {
                "status": "ERROR",
                "note": "missing OPENAI_API_KEY or preview image",
            }
            item = broll_collector.validate_candidate_vision(item, plan, current, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})
        finally:
            broll_collector.call_vision_model = old_call
        selected, _ = broll_collector.choose_valid_candidate([item], current, {}, {}, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})
        self.assertEqual(item.vision_validation_status, "ERROR")
        self.assertIsNone(selected)

    def test_missing_preview_image_sets_preview_unavailable_not_fail(self) -> None:
        current = scene("S032", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", preview_image=""),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item = broll_collector.validate_candidate_vision(item, plan, current, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})
        self.assertEqual(item.vision_validation_status, "PREVIEW_UNAVAILABLE")
        self.assertEqual(item.vision_decision, "PREVIEW_UNAVAILABLE")
        self.assertNotEqual(item.vision_decision, "VISION_FAIL")

    def test_provider_thumbnail_fallback_is_used_for_vision(self) -> None:
        item = candidate("older adult walking", "older adult walking", preview_image="")
        item.raw = {"thumbnail": "thumb-frame"}
        self.assertEqual(broll_collector.candidate_preview_images(item, broll_collector.DEFAULT_CONFIG), ["thumb-frame"])

    def test_keyframe_and_poster_fallbacks_are_used_for_vision(self) -> None:
        item = candidate("older adult walking", "older adult walking", preview_image="")
        item.raw = {"keyframe": "key-frame", "poster_frame": "poster-frame"}
        self.assertEqual(broll_collector.candidate_preview_images(item, {**broll_collector.DEFAULT_CONFIG, "vision_preview_frame_limit": 2}), ["key-frame", "poster-frame"])

    def test_high_semantic_preview_unavailable_becomes_manual_review_candidate(self) -> None:
        current = scene("S033", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", preview_image="", source_asset_id="px-previewless")
        item.relevance_score = 92
        item.match_status = "GOOD_MATCH"
        item.hard_match_pass = "YES"
        item.vision_validation_status = "PREVIEW_UNAVAILABLE"
        item.vision_validation_note = "no preview image, provider thumbnail, keyframe, or poster frame available"
        selected = broll_collector.best_manual_review_candidate(
            [item],
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertIs(selected, item)
        row = broll_collector.manifest_row_for(
            current,
            plan,
            item,
            "broll_S033",
            "",
            "MANUAL_REVIEW_REQUIRED",
            "preview unavailable",
            item,
            "VISION",
        )
        self.assertEqual(row["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertEqual(row["semantic_score"], "92")
        self.assertEqual(row["vision_validation_status"], "PREVIEW_UNAVAILABLE")

    def test_preview_unavailable_strong_semantic_downloads_with_review_flag(self) -> None:
        current = scene("S034", "An older adult walking on a quiet neighborhood sidewalk.")
        item = candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-previewless")
        item.relevance_score = 92
        item.match_status = "EXCELLENT_MATCH"
        item.hard_match_pass = "YES"
        item.duplicate_status = "UNIQUE"
        item.score_notes = "subject=25; action=25; setting=15; demographic=10; shot=10; narration=2; medical=5; hard_match=YES"
        item.vision_validation_status = "PREVIEW_UNAVAILABLE"
        item.vision_decision = "PREVIEW_UNAVAILABLE"
        item.vision_validation_note = "no preview image, provider thumbnail, keyframe, or poster frame available"
        selected, _ = broll_collector.choose_valid_candidate(
            [item],
            current,
            {},
            {},
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertIs(selected, item)
        self.assertTrue(broll_collector.candidate_preview_passes_before_download(item, shot_plan(["rich"]), current, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}))
        status, notes = broll_collector.successful_download_status_and_notes(item)
        self.assertEqual(status, "REVIEW_AFTER_DOWNLOAD")
        self.assertIn("preview", notes)

    def test_vision_fail_still_blocks_download(self) -> None:
        current = scene("S035", "An older adult walking on a quiet neighborhood sidewalk.")
        item = candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="px-fail")
        item.relevance_score = 95
        item.match_status = "EXCELLENT_MATCH"
        item.hard_match_pass = "YES"
        item.duplicate_status = "UNIQUE"
        item.vision_validation_status = "FAILED"
        item.vision_decision = "VISION_FAIL"
        item.vision_best_frame_score = 20
        item.vision_validation_note = "preview shows unrelated activity"
        selected, _ = broll_collector.choose_valid_candidate(
            [item],
            current,
            {},
            {},
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertIsNone(selected)
        self.assertFalse(broll_collector.candidate_preview_passes_before_download(item, shot_plan(["rich"]), current, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True}))

    def test_final_manifest_duplicate_audit_catches_conflicts(self) -> None:
        rows = [
            {
                "scene_id": "S001",
                "source": "Pexels",
                "status": "MATCHED_DRY_RUN",
                "source_asset_id": "dup-1",
                "original_url": "https://example.com/dup",
                "download_url": "https://cdn.example.com/dup.mp4",
                "duplicate_status": "UNIQUE",
                "vision_validation_status": "PASSED",
            },
            {
                "scene_id": "S002",
                "source": "Pexels",
                "status": "MATCHED_DRY_RUN",
                "source_asset_id": "dup-1",
                "original_url": "https://example.com/dup",
                "download_url": "https://cdn.example.com/dup.mp4",
                "duplicate_status": "UNIQUE",
                "vision_validation_status": "PASSED",
            },
        ]
        errors = broll_collector.validate_manifest_integrity(rows, {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True})
        self.assertTrue(any("selected duplicate asset key" in error for error in errors))
        self.assertTrue(any("duplicate_status UNIQUE conflicts" in error for error in errors))

    def test_fallback_manifest_preserves_best_rejected_candidate(self) -> None:
        current = scene("S040", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        rejected = candidate(
            "older adult climbing one stair using handrail",
            "older adult stairs handrail",
            source_asset_id="px-rejected",
            url="https://example.com/rejected",
        )
        rejected.relevance_score = 82
        rejected.hard_match_pass = "YES"
        rejected.match_status = "GOOD_MATCH"
        rejected.vision_validation_status = "FAILED"
        rejected.vision_best_frame_score = 42
        rejected.rejection_reason = "preview shows empty staircase"
        row = broll_collector.manifest_row_for(
            current,
            plan,
            None,
            "broll_S040",
            "",
            "MANUAL_SEARCH_REQUIRED",
            "fallback",
            rejected,
            "VISION",
        )
        self.assertEqual(row["status"], "MANUAL_SEARCH_REQUIRED")
        self.assertEqual(row["best_rejected_asset_id"], "px-rejected")
        self.assertEqual(row["best_rejected_url"], "https://example.com/rejected")
        self.assertEqual(row["best_rejected_semantic_score"], "82")
        self.assertEqual(row["best_rejected_vision_score"], "42")
        self.assertEqual(row["best_rejected_stage"], "VISION")

    def test_fallback_manifest_does_not_zero_semantic_when_rejected_candidate_exists(self) -> None:
        current = scene("S041", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        rejected = candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk")
        rejected.relevance_score = 78
        rejected.hard_match_pass = "YES"
        rejected.match_status = "GOOD_MATCH"
        row = broll_collector.manifest_row_for(current, plan, None, "broll_S041", "", "MANUAL_SEARCH_REQUIRED", "fallback", rejected, "VISION")
        self.assertEqual(row["semantic_score"], "78")
        self.assertEqual(row["relevance_score"], "78")

    def test_fallback_manifest_copies_vision_fields_when_candidate_reached_vision(self) -> None:
        current = scene("S042", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        rejected = candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk")
        rejected.relevance_score = 82
        rejected.hard_match_pass = "YES"
        rejected.match_status = "GOOD_MATCH"
        rejected.vision_validation_status = "UNCERTAIN"
        rejected.vision_best_frame_score = 61
        rejected.vision_average_frame_score = 55
        rejected.vision_decision = "VISION_UNCERTAIN"
        row = broll_collector.manifest_row_for(current, plan, None, "broll_S042", "", "MANUAL_SEARCH_REQUIRED", "fallback", rejected, "VISION")
        self.assertEqual(row["vision_validation_status"], "UNCERTAIN")
        self.assertEqual(row["vision_best_frame_score"], "61")
        self.assertEqual(row["vision_average_frame_score"], "55")
        self.assertEqual(row["vision_decision"], "VISION_UNCERTAIN")

    def test_candidate_diagnostics_record_rejection_stage(self) -> None:
        current = scene("S043", "An older adult climbing one stair using a handrail at home.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult climbing one stair using handrail", "older adult stairs handrail"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        item.vision_validation_status = "FAILED"
        item.vision_best_frame_score = 40
        item.vision_decision = "VISION_FAIL"
        item.rejection_reason = "preview mismatch"
        rows = broll_collector.candidate_diagnostic_rows(
            current,
            plan,
            [item],
            None,
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertEqual(rows[0]["rejection_stage"], "VISION")
        self.assertEqual(rows[0]["vision_status"], "FAILED")

    def test_candidate_diagnostics_stage_counts_are_accurate(self) -> None:
        current = scene("S044", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = broll_collector.plan_scene(current, 1, broll_collector.DEFAULT_CONFIG, [], ("SEQ-001", "1/1"))
        good = broll_collector.validate_candidate_semantics(
            candidate("older senior walking on neighborhood sidewalk", "older adult walking sidewalk", source_asset_id="good"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        good.vision_validation_status = "PASSED"
        good.vision_best_frame_score = 90
        good.vision_decision = "VISION_PASS"
        weak = broll_collector.validate_candidate_semantics(
            candidate("older senior sitting on neighborhood bench", "older adult sitting bench", source_asset_id="weak"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        counts = broll_collector.stage_counts_for(
            [good, weak],
            plan,
            current,
            {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True},
        )
        self.assertEqual(counts["provider_returned_count"], 2)
        self.assertEqual(counts["basic_filter_pass_count"], 2)
        self.assertEqual(counts["hard_match_pass_count"], 1)
        self.assertEqual(counts["vision_pass_count"], 1)
        self.assertEqual(counts["selectable_count"], 1)

    def test_manifest_columns_append_diagnostics_without_breaking_legacy_order(self) -> None:
        columns = broll_collector.dedupe_columns(broll_collector.MANIFEST_COLUMNS)
        legacy = ["asset_id", "scene_id", "source", "search_query", "local_path", "original_url", "license", "creator", "duration", "resolution", "status", "notes"]
        self.assertEqual(columns[: len(legacy)], legacy)
        self.assertIn("best_rejected_asset_id", columns)
        self.assertIn("best_rejected_reason", columns)

    def test_candidate_diagnostics_required_columns_exist(self) -> None:
        columns = broll_collector.dedupe_columns(broll_collector.CANDIDATE_DIAGNOSTIC_COLUMNS)
        for name in [
            "scene_id",
            "query_level",
            "search_query",
            "provider",
            "semantic_score",
            "hard_subject_pass",
            "hard_action_pass",
            "vision_status",
            "final_candidate_status",
            "rejection_stage",
            "provider_returned_count",
            "selectable_count",
        ]:
            self.assertIn(name, columns)

    def test_performance_profile_collects_timings_and_counts(self) -> None:
        profile = broll_collector.PerformanceProfile()
        profile.add_time("pexels_api", 1.25)
        profile.add_time("pexels_api", 0.75)
        profile.increment("total_api_requests")
        profile.increment("vision_requests", 2)
        self.assertEqual(profile.timings["pexels_api"], 2.0)
        self.assertEqual(profile.counts["total_api_requests"], 1)
        self.assertEqual(profile.counts["vision_requests"], 2)

    def run_search_with_mocks(self, plan, config, per_provider=5, vision_result=None, same_preview=False):
        current = scene("S900", "An older adult walking on a quiet neighborhood sidewalk.")
        calls = {"pexels": 0, "pixabay": 0, "vision": 0}

        def make_candidates(source, query):
            calls[source.lower()] += 1
            items = [
                candidate(
                    "older adult walking on sidewalk",
                    "older adult walking sidewalk",
                    source=source,
                    source_asset_id=f"{source}-{query}-{index}",
                    preview_image="data:image/jpeg;base64,shared" if same_preview else f"data:image/jpeg;base64,{source}{index}",
                )
                for index in range(per_provider)
            ]
            for item in items:
                item.query_used = query
            return items

        def fake_vision(preview, prompt, cfg):
            calls["vision"] += 1
            return vision_result or {
                "older_adult_visible": False,
                "stairs_or_step_visible": False,
                "stepping_action_visible": False,
                "medical_safety_ok": True,
                "reject": True,
                "note": "not a match",
            }

        old_pexels = broll_collector.search_pexels
        old_pixabay = broll_collector.search_pixabay
        old_vision = broll_collector.call_vision_model
        try:
            broll_collector.search_pexels = lambda query, api_key, orientation, limit: make_candidates("Pexels", query)
            broll_collector.search_pixabay = lambda query, api_key, orientation, limit: make_candidates("Pixabay", query)
            broll_collector.call_vision_model = fake_vision
            results = broll_collector.search_candidates(
                plan,
                current,
                config,
                ["pexels", "pixabay"],
                "pexels-key",
                "pixabay-key",
                {},
                {},
            )
        finally:
            broll_collector.search_pexels = old_pexels
            broll_collector.search_pixabay = old_pixabay
            broll_collector.call_vision_model = old_vision
        return results, calls

    def test_normal_mode_caps_vision_requests_at_six_per_scene(self) -> None:
        plan = shot_plan(["rich", "medium", "broad"])
        profile = broll_collector.PerformanceProfile()
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "_performance_profile": profile, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config)
        self.assertLessEqual(calls["vision"], 6)

    def test_profile_fast_caps_vision_requests_at_two(self) -> None:
        plan = shot_plan(["rich", "medium", "broad"])
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "_profile_fast": True, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config)
        self.assertLessEqual(calls["vision"], 2)

    def test_early_exit_stops_later_queries_after_excellent_candidate(self) -> None:
        plan = shot_plan(["rich", "medium"])
        pass_result = {
            "older_adult_visible": True,
            "stairs_or_step_visible": True,
            "stepping_action_visible": True,
            "handrail_or_support_visible": True,
            "home_or_interior_visible": True,
            "medical_safety_ok": True,
            "note": "excellent match",
        }
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config, per_provider=2, vision_result=pass_result)
        self.assertEqual(calls["pexels"], 1)
        self.assertEqual(calls["pixabay"], 0)

    def test_medium_runs_only_when_rich_fails(self) -> None:
        plan = shot_plan(["rich", "medium", "broad"])
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config, per_provider=1)
        self.assertGreaterEqual(calls["pexels"], 2)
        self.assertGreaterEqual(calls["pixabay"], 2)

    def test_broad_runs_only_when_medium_fails(self) -> None:
        plan = shot_plan(["rich", "medium", "broad"])
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config, per_provider=1)
        self.assertEqual(calls["pexels"], 3)
        self.assertEqual(calls["pixabay"], 3)

    def test_vision_cache_prevents_repeated_calls(self) -> None:
        current = scene("S901", "An older adult walking on a quiet neighborhood sidewalk.")
        plan = shot_plan(["rich"])
        item = broll_collector.validate_candidate_semantics(
            candidate("older adult walking on sidewalk", "older adult walking sidewalk", preview_image="same-preview"),
            plan,
            current,
            broll_collector.DEFAULT_CONFIG,
        )
        calls = {"vision": 0}

        def fake_vision(preview, prompt, config):
            calls["vision"] += 1
            return {
                "older_adult_visible": True,
                "action_exists": True,
                "age_group_matches": True,
                "setting_matches": True,
                "medical_safety_ok": True,
                "note": "cached match",
            }

        old_vision = broll_collector.call_vision_model
        try:
            broll_collector.call_vision_model = fake_vision
            config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "_vision_cache": {}}
            broll_collector.validate_candidate_vision(item, plan, current, config)
            again = broll_collector.validate_candidate_semantics(
                candidate("older adult walking on sidewalk", "older adult walking sidewalk", preview_image="same-preview"),
                plan,
                current,
                broll_collector.DEFAULT_CONFIG,
            )
            broll_collector.validate_candidate_vision(again, plan, current, config)
        finally:
            broll_collector.call_vision_model = old_vision
        self.assertEqual(calls["vision"], 1)

    def test_duplicate_previews_are_vision_checked_once(self) -> None:
        plan = shot_plan(["rich"])
        config = {**broll_collector.DEFAULT_CONFIG, "enable_vision_validation": True, "enable_vision_cache": False}
        _, calls = self.run_search_with_mocks(plan, config, per_provider=3, same_preview=True)
        self.assertEqual(calls["vision"], 1)

    def test_time_budget_can_stop_before_vision(self) -> None:
        plan = shot_plan(["rich"])
        config = {
            **broll_collector.DEFAULT_CONFIG,
            "enable_vision_validation": True,
            "_scene_started_at": 1.0,
            "scene_time_budget_sec": 0,
        }
        self.assertTrue(broll_collector.time_budget_exceeded(config))

    def test_profile_fast_cli_help_remains_compatible(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "Tools" / "broll_collector.py"), "--help"], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--profile-fast", result.stdout)


if __name__ == "__main__":
    unittest.main()
