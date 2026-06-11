"""
test_agent_intent_regression.py
Regression tests for:
  1. Intent classification and item splitting
  2. Qualifier penalty (false match prevention)
  3. Feedback blocklist (wrong matches get score 0)

Run with:  pytest BS/test_agent_intent_regression.py -v
"""

import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenv

anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules["anthropic"] = anthropic

supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules["supabase"] = supabase_module

from app.services.agent import (
    item_match_score,
    extract_shopping_list_items,
    normalize_understanding_payload,
    is_blocklisted,
    ITEM_QUALIFIER_WORDS,
)


# ─────────────────────────────────────────
# 1. Item splitting
# ─────────────────────────────────────────

class TestItemSplitting:
    def test_space_separated_spices(self):
        items = extract_shopping_list_items(
            "price for cinnamon stick saffron turmeric cardamom"
        )
        assert len(items) >= 3, f"Expected ≥3 items, got {items}"
        # Each major spice should appear in its own item
        joined = " ".join(items)
        for spice in ["saffron", "turmeric", "cardamom"]:
            assert spice in joined, f"Missing '{spice}' in split: {items}"

    def test_comma_separated_basics(self):
        items = extract_shopping_list_items("coconut oil, rice, dal")
        assert len(items) >= 3, f"Expected ≥3 items, got {items}"

    def test_newline_separated(self):
        items = extract_shopping_list_items("price table:\ncoconut oil\nrice\ndal\nonion")
        assert len(items) >= 3, f"Expected ≥3 items, got {items}"

    def test_compound_item_stays_together(self):
        items = extract_shopping_list_items("coconut oil, cinnamon stick, black pepper")
        joined = " ".join(items)
        assert "coconut oil" in joined or any("coconut" in i for i in items)
        assert "cinnamon" in joined

    def test_single_item_not_split(self):
        items = extract_shopping_list_items("price for coconut oil")
        assert len(items) <= 2, f"Single item should not be over-split: {items}"

    def test_classifier_payload_items_array(self):
        """normalize_understanding_payload should pass through an items array."""
        raw = {
            "intent": "item_price",
            "canonical_message": "best price for saffron, turmeric",
            "item_query": "saffron",
            "items": ["saffron", "turmeric", "cardamom"],
            "category": "",
            "is_receipt_question": True,
        }
        result = normalize_understanding_payload(raw)
        assert result["items"] == ["saffron", "turmeric", "cardamom"]

    def test_classifier_payload_seeds_items_from_item_query(self):
        """If no items array, items should be seeded from item_query."""
        raw = {
            "intent": "item_price",
            "canonical_message": "best price for cilantro",
            "item_query": "cilantro",
            "category": "",
            "is_receipt_question": True,
        }
        result = normalize_understanding_payload(raw)
        assert "cilantro" in result["items"]


# ─────────────────────────────────────────
# 2. Qualifier penalty — false match prevention
# ─────────────────────────────────────────

class TestQualifierPenalty:
    """
    The score for a false match must fall below STRICT_ITEM_MIN_SCORE (0.72)
    after the qualifier / asymmetric subset penalty is applied.
    """

    THRESHOLD = 0.72

    def _score(self, query: str, item: str) -> float:
        return item_match_score(query, item)

    # coconut oil → Oil Burner
    def test_coconut_oil_vs_oil_burner(self):
        score = self._score("coconut oil", "OIL BURNER 4OZ")
        assert score < self.THRESHOLD, \
            f"'coconut oil' should NOT match 'OIL BURNER 4OZ' (score={score:.3f})"

    # mushroom → mushroom gummies
    def test_mushroom_vs_mushroom_gummies(self):
        score = self._score("mushroom", "MUSHROOM GUMMIES 60CT")
        assert score < self.THRESHOLD, \
            f"'mushroom' should NOT match 'MUSHROOM GUMMIES 60CT' (score={score:.3f})"

    # rice → fried rice (prepared dish)
    def test_rice_vs_fried_rice(self):
        # raw "rice" should score lower against "FRIED RICE" because "fried" is a qualifier
        score_raw  = self._score("rice", "SONA MASOORI RICE 10LB")
        score_fried = self._score("rice", "FRIED RICE COMBO")
        assert score_raw > score_fried, \
            f"'rice' should score higher against raw rice than fried rice dish"

    # round → ground meat  (asymmetric subset: "round" ≠ token in "ground meat")
    def test_round_vs_ground_meat(self):
        score = self._score("round", "GROUND MEAT 1LB")
        assert score < self.THRESHOLD, \
            f"'round' should NOT match 'GROUND MEAT 1LB' (score={score:.3f})"

    # cilantro should still match CILANTRO receipts (no regression)
    def test_cilantro_positive(self):
        score = self._score("cilantro", "3 CILANTRO BUNCHES")
        assert score >= self.THRESHOLD, \
            f"'cilantro' should match '3 CILANTRO BUNCHES' (score={score:.3f})"

    # coconut oil should match actual coconut oil (no regression)
    def test_coconut_oil_positive(self):
        score = self._score("coconut oil", "COCONUT OIL 32OZ")
        assert score >= self.THRESHOLD, \
            f"'coconut oil' should match 'COCONUT OIL 32OZ' (score={score:.3f})"

    # mushroom should match plain mushroom receipt items
    def test_mushroom_positive(self):
        score = self._score("mushroom", "MUSHROOMS 8OZ")
        assert score >= self.THRESHOLD, \
            f"'mushroom' should match 'MUSHROOMS 8OZ' (score={score:.3f})"

    # qualifier words coverage — ensure qualifiers list is populated
    def test_qualifier_words_populated(self):
        assert len(ITEM_QUALIFIER_WORDS) >= 10, "ITEM_QUALIFIER_WORDS should have at least 10 entries"
        assert "gummies" in ITEM_QUALIFIER_WORDS
        assert "burner" in ITEM_QUALIFIER_WORDS


# ─────────────────────────────────────────
# 3. Feedback blocklist
# ─────────────────────────────────────────

class TestFeedbackBlocklist:
    def _make_blocklist(self, pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
        """Build a blocklist directly from (query_token, item_token) pairs."""
        return set(pairs)

    def test_blocklisted_pair_returns_true(self):
        bl = self._make_blocklist([("mushroom", "gummies")])
        assert is_blocklisted("mushroom", "MUSHROOM GUMMIES 60CT", bl)

    def test_non_blocklisted_pair_returns_false(self):
        bl = self._make_blocklist([("mushroom", "gummies")])
        assert not is_blocklisted("mushroom", "MUSHROOMS 8OZ", bl)

    def test_empty_blocklist_never_blocks(self):
        assert not is_blocklisted("coconut oil", "OIL BURNER 4OZ", set())

    def test_different_query_not_blocked(self):
        # Block mushroom→gummies, but coconut oil→gummies should still pass
        bl = self._make_blocklist([("mushroom", "gummies")])
        assert not is_blocklisted("coconut oil", "COCONUT GUMMIES", bl)

    def test_multiple_blocklist_entries(self):
        bl = self._make_blocklist([
            ("mushroom", "gummies"),
            ("coconut", "burner"),
        ])
        assert is_blocklisted("coconut oil", "OIL BURNER 4OZ COCONUT", bl)
        assert is_blocklisted("mushroom soup", "MUSHROOM GUMMIES", bl)
        assert not is_blocklisted("rice", "FRIED RICE", bl)

    def test_blocklist_case_insensitive(self):
        bl = self._make_blocklist([("mushroom", "gummies")])
        assert is_blocklisted("MUSHROOM", "Mushroom Gummies 60CT", bl)


# ─────────────────────────────────────────
# 4. Edge cases and regression guards
# ─────────────────────────────────────────

class TestEdgeCases:
    def test_empty_query_returns_zero(self):
        assert item_match_score("", "COCONUT OIL 32OZ") == 0.0

    def test_empty_item_returns_zero(self):
        assert item_match_score("coconut oil", "") == 0.0

    def test_exact_match_returns_one(self):
        assert item_match_score("coconut oil", "coconut oil") == 1.0

    def test_ocr_variant_pren_matches_prem(self):
        # receipt OCR often writes PREN instead of PREM
        score = item_match_score("rose pink prem", "2.00-GAL ROSE PINK PREN")
        assert score >= 0.72, f"OCR variant PREN should match PREM query (score={score:.3f})"

    def test_product_size_not_quantity(self):
        # 2.00-GAL is product size; it should not block a match on the product name
        score = item_match_score("rose pink", "2.00-GAL ROSE PINK PREM")
        assert score >= 0.60, f"Product size should not block name match (score={score:.3f})"

    def test_single_token_not_in_item_scores_zero(self):
        # "maggi" should not match "mango lassi"
        score = item_match_score("maggi", "MANGO LASSI")
        assert score < 0.72, f"'maggi' should not match 'MANGO LASSI' (score={score:.3f})"
