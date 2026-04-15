from __future__ import annotations

from fractions import Fraction

from memory_system.distillation.math_c2a_benchmark import (
    _build_symbolic_teacher_step_path,
    _classify_math_residuals,
    _classify_math_step_residuals,
    _derive_case_features,
    _derive_final_answer_from_equation,
    _extract_choice_letter,
    _extract_json_object,
    _find_correct_candidate_letters,
    _generate_candidate_moves,
    _is_equivalent_equation,
    _is_isolated_equation,
    _is_symbolically_equivalent_equation,
    _is_symbolically_isolated_equation,
    _parse_final_answer,
    _parse_linear_equation,
    _rank_candidates_with_priors,
    _retrieve_teacher_priors,
    _retrieve_teacher_step_priors,
    _solve_linear_equation,
    MathC2ACase,
)


def test_parse_linear_equation_handles_variable_on_both_sides() -> None:
    parsed = _parse_linear_equation("7x + 3 = 3x - 9")
    assert parsed is not None
    (left_x, left_const), (right_x, right_const) = parsed
    assert left_x == Fraction(7)
    assert left_const == Fraction(3)
    assert right_x == Fraction(3)
    assert right_const == Fraction(-9)


def test_solve_linear_equation_returns_exact_fraction() -> None:
    assert _solve_linear_equation("14 - 3x = 2") == Fraction(4)
    assert _solve_linear_equation("-2x - 8 = 10") == Fraction(-9)


def test_parse_final_answer_accepts_assignment_or_number() -> None:
    assert _parse_final_answer("x = -7") == Fraction(-7)
    assert _parse_final_answer("-9") == Fraction(-9)
    assert _parse_final_answer("x = 4.25") == Fraction(17, 4)


def test_equivalence_and_isolation_checks_work() -> None:
    assert _is_equivalent_equation("6x + 1 = 2x + 17", "4x = 16") is True
    assert _is_equivalent_equation("6x + 1 = 2x + 17", "4x = 15") is False
    assert _is_isolated_equation("x = 4") is True
    assert _is_isolated_equation("-x = -4") is True
    assert _is_isolated_equation("4x = 16") is False
    assert _is_symbolically_equivalent_equation("2*(x - 5) + 3 = (x + 1)/2", "4*x - 14 = x + 1") is True
    assert _is_symbolically_isolated_equation("x = 5") is True
    assert _is_symbolically_isolated_equation("3x = 15") is False
    assert _derive_final_answer_from_equation("x = 5/2") == Fraction(5, 2)


def test_classify_math_residuals_distinguishes_error_types() -> None:
    expected = Fraction(4)

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={},
        expected_answer=expected,
    ) == ["invalid_math_json"]

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={"final_answer": "x = 5", "next_equation": "4x = 16"},
        expected_answer=expected,
    ) == ["not_isolated"]

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={"final_answer": "x = 5", "next_equation": "4x = 15"},
        expected_answer=expected,
    ) == ["equivalence_error"]

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={"final_answer": "x = 5", "next_equation": "x = 4"},
        expected_answer=expected,
    ) == ["arithmetic_error"]

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={"final_answer": "x = 5", "next_equation": "6x = 18"},
        expected_answer=expected,
    ) == ["equivalence_error"]

    assert _classify_math_residuals(
        equation="6x + 1 = 2x + 17",
        payload={"final_answer": "", "next_equation": "4x = 16"},
        expected_answer=expected,
    ) == ["missing_final_answer"]


def test_derive_case_features_marks_variable_both_sides_and_signs() -> None:
    assert _derive_case_features("3x + 5 = 20") == [
        "inverse_operation_chain",
        "coefficient_normalization",
    ]
    assert _derive_case_features("-6x + 9 = 3x - 18") == [
        "inverse_operation_chain",
        "coefficient_normalization",
        "variable_both_sides",
        "sign_flip_management",
    ]
    assert _derive_case_features("(3x + 9)/4 = (x - 1)/2") == [
        "inverse_operation_chain",
        "coefficient_normalization",
        "distribution_unwrap",
        "denominator_clearing",
        "variable_both_sides",
    ]


def test_classify_math_step_residuals_checks_equivalence_and_progress() -> None:
    assert _classify_math_step_residuals(current_equation="2*(x + 3) = 14", payload={}) == ["invalid_math_json"]
    assert _classify_math_step_residuals(
        current_equation="2*(x + 3) = 14",
        payload={"next_equation": ""},
    ) == ["missing_next_equation"]
    assert _classify_math_step_residuals(
        current_equation="2*(x + 3) = 14",
        payload={"next_equation": "2*(x + 3) = 14"},
    ) == ["no_progress"]
    assert _classify_math_step_residuals(
        current_equation="2*(x + 3) = 14",
        payload={"next_equation": "2x + 6 = 15"},
    ) == ["equivalence_error"]
    assert _classify_math_step_residuals(
        current_equation="2*(x + 3) = 14",
        payload={"next_equation": "2x + 6 = 14"},
    ) == []


def test_generate_candidate_moves_produces_verified_options() -> None:
    candidates = _generate_candidate_moves("(5x - 10)/3 = x + 2")
    assert candidates
    assert any(item["opcode"] == "CLEAR_DENOMINATORS" for item in candidates)
    assert all("=" in item["next_equation"] for item in candidates)


def test_extract_choice_letter_handles_json_or_plain_letter() -> None:
    assert _extract_choice_letter('{"choice":"B"}') == "B"
    assert _extract_choice_letter("C") == "C"


def test_find_correct_candidate_letters_matches_teacher_equation() -> None:
    candidates = _generate_candidate_moves("(5x - 10)/3 = x + 2")
    matches = _find_correct_candidate_letters(
        candidates,
        teacher_next_equation="5*x - 10 = 3*x + 6",
    )
    assert matches == ["A"]


def test_rank_candidates_with_priors_prefers_matching_opcode() -> None:
    candidates = _generate_candidate_moves("(5x - 10)/3 = x + 2")
    ranked = _rank_candidates_with_priors(
        candidates,
        current_equation="(5x - 10)/3 = x + 2",
        teacher_priors=[
            {
                "teacher_opcode": "CLEAR_DENOMINATORS",
                "teacher_operand": "3",
                "predicted_constraints": ["denominator_clearing"],
                "predicted_transmutations": [
                    "Trade fractional obstruction for an integer-friendly equation by clearing denominators."
                ],
            }
        ],
    )
    assert ranked[0]["opcode"] == "CLEAR_DENOMINATORS"


def test_retrieve_teacher_priors_prefers_matching_feature_shape() -> None:
    case = MathC2ACase(
        case_id="holdout_01",
        split="holdout",
        prompt="Solve for x: 6x + 1 = 2x + 17",
        equation="6x + 1 = 2x + 17",
        expected_answer="4",
        expected_constraints=[
            "inverse_operation_chain",
            "coefficient_normalization",
            "variable_both_sides",
        ],
        expected_transmutations=[
            "Trade additive clutter for a cleaner equation by inverse operations.",
            "Trade coefficient magnitude for isolated x by dividing both sides.",
            "Trade bilateral variable terms for a one-sided coefficient difference.",
        ],
    )
    traces = [
        {
            "case_id": "train_a",
            "prompt": "Solve for x: 7x + 3 = 3x - 9",
            "equation": "7x + 3 = 3x - 9",
            "features": [
                "inverse_operation_chain",
                "coefficient_normalization",
                "variable_both_sides",
            ],
            "predicted_constraints": ["variable_both_sides"],
            "predicted_transmutations": ["Trade bilateral variable terms for a one-sided coefficient difference."],
            "answer_correct": True,
        },
        {
            "case_id": "train_b",
            "prompt": "Solve for x: 3x + 5 = 20",
            "equation": "3x + 5 = 20",
            "features": [
                "inverse_operation_chain",
                "coefficient_normalization",
            ],
            "predicted_constraints": ["inverse_operation_chain"],
            "predicted_transmutations": ["Trade additive clutter for a cleaner equation by inverse operations."],
            "answer_correct": True,
        },
    ]

    priors = _retrieve_teacher_priors(case, traces, top_k=1)

    assert priors[0]["case_id"] == "train_a"


def test_extract_json_object_handles_partial_wrapping() -> None:
    payload = _extract_json_object(
        'Answer: {"predicted_constraints":["inverse_operation_chain"],"predicted_transmutations":["Trade additive clutter for a cleaner equation by inverse operations."],"next_equation":"x = 5","final_answer":"x = 5"}'
    )
    assert payload["final_answer"] == "x = 5"


def test_build_symbolic_teacher_step_path_generates_verified_progression() -> None:
    case = MathC2ACase(
        case_id="holdout_sym",
        split="holdout",
        prompt="Solve for x: 2*(x - 5) + 3 = (x + 1)/2",
        equation="2*(x - 5) + 3 = (x + 1)/2",
        expected_answer="5",
        expected_constraints=[
            "inverse_operation_chain",
            "coefficient_normalization",
            "distribution_unwrap",
            "denominator_clearing",
            "variable_both_sides",
        ],
        expected_transmutations=[
            "Trade additive clutter for a cleaner equation by inverse operations.",
            "Trade coefficient magnitude for isolated x by dividing both sides.",
            "Trade nested structure for a flat equation by distributing or collapsing grouped terms.",
            "Trade fractional obstruction for an integer-friendly equation by clearing denominators.",
            "Trade bilateral variable terms for a one-sided coefficient difference.",
        ],
    )
    steps = _build_symbolic_teacher_step_path(case)
    assert steps
    assert steps[0]["predicted_constraints"]
    assert steps[-1]["next_equation"]
    assert steps[0]["teacher_action"]
    assert steps[0]["teacher_opcode"]
    assert "teacher_operand" in steps[0]


def test_retrieve_teacher_step_priors_prefers_matching_current_state() -> None:
    case = MathC2ACase(
        case_id="holdout_step",
        split="holdout",
        prompt="Solve for x: (5x - 10)/3 = x + 2",
        equation="(5x - 10)/3 = x + 2",
        expected_answer="8",
        expected_constraints=["denominator_clearing", "variable_both_sides"],
        expected_transmutations=[
            "Trade fractional obstruction for an integer-friendly equation by clearing denominators.",
            "Trade bilateral variable terms for a one-sided coefficient difference.",
        ],
    )
    priors = _retrieve_teacher_step_priors(
        case=case,
        current_equation="(5x - 10)/3 = x + 2",
        teacher_step_traces=[
            {
                "trace_id": "a",
                "prompt": "Solve for x: (5x - 10)/3 = x + 2",
                "current_equation": "(5x - 10)/3 = x + 2",
                "teacher_action": "Clear denominators by multiplying both sides by 3.",
                "teacher_opcode": "CLEAR_DENOMINATORS",
                "teacher_operand": "3",
                "features": ["denominator_clearing", "variable_both_sides"],
                "predicted_constraints": ["denominator_clearing"],
                "predicted_transmutations": ["Trade fractional obstruction for an integer-friendly equation by clearing denominators."],
            },
            {
                "trace_id": "b",
                "prompt": "Solve for x: 3*(2x + 1) - 4 = 5x + 9",
                "current_equation": "3*(2x + 1) - 4 = 5x + 9",
                "teacher_action": "Expand grouped terms to flatten the equation.",
                "teacher_opcode": "EXPAND",
                "teacher_operand": "",
                "features": ["distribution_unwrap", "variable_both_sides"],
                "predicted_constraints": ["distribution_unwrap"],
                "predicted_transmutations": ["Trade nested structure for a flat equation by distributing or collapsing grouped terms."],
            },
        ],
        top_k=1,
    )
    assert priors[0]["trace_id"] == "a"
    assert priors[0]["teacher_opcode"] == "CLEAR_DENOMINATORS"
