"""ReceiptAI permanent quality gate.

Run this before deploying agent changes:
    python test_agent_quality_gate.py

It covers the failure classes that repeatedly caused bad answers:
- exclusion clauses becoming fake requested items
- non-food/supplement rows matching grocery items
- descriptors like round/cut becoming standalone products
- multi-item splitting and adaptive recovery
- feedback rank adjustments
"""

from test_agent_rag_regression import (
    setup_module,
    test_adaptive_recovery_dedupes_same_receipt_line,
    test_compare_multi_item_request_keeps_unknown_as_missing_row,
    test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles,
    test_dangling_unit_tail_does_not_become_requested_item,
    test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up,
    test_general_advice_is_scoped_to_receipt_memory,
    test_should_buy_item_uses_receipt_history_without_current_price,
    test_contextual_retrieval_pipeline_trace_is_attached,
    test_multi_item_retrieval_pipeline_trace_is_attached,
    test_feedback_examples_boost_corrected_receipt_item_rank,
    test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets,
    test_multi_item_best_price_table_splits_requested_items,
    test_pantry_request_keeps_round_and_does_not_match_ground_meat,
    test_round_is_not_corrected_to_ground_meat,
    test_spice_price_request_splits_adjacent_items,
    test_vegetable_include_request_excludes_candy_mushroom_match,
)
from test_agent_fuzz_queries import (
    test_adversarial_multi_item_noise_does_not_leak_rows,
    test_adversarial_single_item_noise_does_not_create_fake_items,
    test_generated_answer_cards_keep_requested_items_clean,
    test_generated_clean_multi_item_queries_extract_expected_items,
    test_high_confidence_semantic_understanding_overrides_local_single_item,
    test_low_confidence_semantic_understanding_does_not_override_local_single_item,
    test_uncertain_generated_queries_route_to_claude_correction,
)
from test_agent_wide_scenarios import test_frequent_items_phrases_route_to_repeat_summary


QUALITY_GATE_TESTS = [
    test_multi_item_best_price_table_splits_requested_items,
    test_pantry_request_keeps_round_and_does_not_match_ground_meat,
    test_spice_price_request_splits_adjacent_items,
    test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles,
    test_vegetable_include_request_excludes_candy_mushroom_match,
    test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets,
    test_dangling_unit_tail_does_not_become_requested_item,
    test_compare_multi_item_request_keeps_unknown_as_missing_row,
    test_adaptive_recovery_dedupes_same_receipt_line,
    test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up,
    test_general_advice_is_scoped_to_receipt_memory,
    test_should_buy_item_uses_receipt_history_without_current_price,
    test_contextual_retrieval_pipeline_trace_is_attached,
    test_multi_item_retrieval_pipeline_trace_is_attached,
    test_feedback_examples_boost_corrected_receipt_item_rank,
    test_round_is_not_corrected_to_ground_meat,
    test_generated_clean_multi_item_queries_extract_expected_items,
    test_adversarial_single_item_noise_does_not_create_fake_items,
    test_adversarial_multi_item_noise_does_not_leak_rows,
    test_high_confidence_semantic_understanding_overrides_local_single_item,
    test_low_confidence_semantic_understanding_does_not_override_local_single_item,
    test_generated_answer_cards_keep_requested_items_clean,
    test_uncertain_generated_queries_route_to_claude_correction,
    test_frequent_items_phrases_route_to_repeat_summary,
]


if __name__ == "__main__":
    setup_module()
    for test in QUALITY_GATE_TESTS:
        test()
    print(f"ReceiptAI quality gate passed: {len(QUALITY_GATE_TESTS)} checks.")
