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
    test_complete_price_history_of_buying_eggs_does_not_create_buying_item,
    test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles,
    test_dangling_unit_tail_does_not_become_requested_item,
    test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up,
    test_general_advice_uses_general_knowledge,
    test_product_relationship_question_never_becomes_alias_training_data,
    test_product_relationship_routing_is_generic_not_item_specific,
    test_unknown_product_aliases_use_semantic_resolver_not_hardcoded_examples,
    test_should_buy_item_uses_receipt_history_without_current_price,
    test_contextual_retrieval_pipeline_trace_is_attached,
    test_multi_item_retrieval_pipeline_trace_is_attached,
    test_feedback_examples_boost_corrected_receipt_item_rank,
    test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets,
    test_multi_item_best_price_table_splits_requested_items,
    test_when_did_i_buy_mutton_answers_purchase_dates_not_price_table,
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
from test_agent_architecture_v2 import (
    test_intent_plan_preserves_raw_question_and_operation,
    test_prepared_plan_skips_second_interpretation,
    test_ttl_cache_reuses_data_without_request_wide_clear,
    test_workflow_passes_one_plan_into_execution,
)
from test_agent_canonical_events import (
    test_clear_known_item_query_skips_semantic_model_call,
    test_cross_source_line_index_differences_collapse_to_one_purchase,
    test_duplicate_candidates_do_not_push_other_dates_or_mutton_cuts_out,
    test_exact_match_skips_vector_network_call,
    test_empty_purchase_history_skips_vector_network_call,
    test_numeric_purchase_claim_is_corrected_to_canonical_event_count,
    test_ram_uses_the_mutton_goat_lamb_family,
    test_when_question_uses_canonical_pipeline_and_lists_all_dates,
)
from test_launch_readiness import (
    test_account_deletion_fails_closed_without_service_role,
    test_agent_guest_session_uses_same_strict_contract,
    test_date_filter_is_owner_scoped_and_uses_purchase_date,
    test_guest_session_rejects_shared_defaults,
    test_receipt_delete_refuses_unscoped_calls,
    test_scan_contract_includes_labeled_receipt_identifiers,
    test_unscoped_legacy_query_router_is_not_registered,
)


QUALITY_GATE_TESTS = [
    test_multi_item_best_price_table_splits_requested_items,
    test_pantry_request_keeps_round_and_does_not_match_ground_meat,
    test_spice_price_request_splits_adjacent_items,
    test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles,
    test_vegetable_include_request_excludes_candy_mushroom_match,
    test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets,
    test_dangling_unit_tail_does_not_become_requested_item,
    test_compare_multi_item_request_keeps_unknown_as_missing_row,
    test_complete_price_history_of_buying_eggs_does_not_create_buying_item,
    test_adaptive_recovery_dedupes_same_receipt_line,
    test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up,
    test_general_advice_uses_general_knowledge,
    test_product_relationship_routing_is_generic_not_item_specific,
    test_product_relationship_question_never_becomes_alias_training_data,
    test_unknown_product_aliases_use_semantic_resolver_not_hardcoded_examples,
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
    test_when_did_i_buy_mutton_answers_purchase_dates_not_price_table,
    test_intent_plan_preserves_raw_question_and_operation,
    test_prepared_plan_skips_second_interpretation,
    test_workflow_passes_one_plan_into_execution,
    test_ttl_cache_reuses_data_without_request_wide_clear,
    test_guest_session_rejects_shared_defaults,
    test_agent_guest_session_uses_same_strict_contract,
    test_receipt_delete_refuses_unscoped_calls,
    test_date_filter_is_owner_scoped_and_uses_purchase_date,
    test_unscoped_legacy_query_router_is_not_registered,
    test_account_deletion_fails_closed_without_service_role,
    test_scan_contract_includes_labeled_receipt_identifiers,
    test_cross_source_line_index_differences_collapse_to_one_purchase,
    test_duplicate_candidates_do_not_push_other_dates_or_mutton_cuts_out,
    test_ram_uses_the_mutton_goat_lamb_family,
    test_numeric_purchase_claim_is_corrected_to_canonical_event_count,
    test_clear_known_item_query_skips_semantic_model_call,
    test_exact_match_skips_vector_network_call,
    test_empty_purchase_history_skips_vector_network_call,
    test_when_question_uses_canonical_pipeline_and_lists_all_dates,
]


if __name__ == "__main__":
    setup_module()
    for test in QUALITY_GATE_TESTS:
        test()
    print(f"ReceiptAI quality gate passed: {len(QUALITY_GATE_TESTS)} checks.")
