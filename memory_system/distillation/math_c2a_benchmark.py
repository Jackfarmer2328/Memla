from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from ..ollama_client import ChatMessage, UniversalLLMClient


MATH_C2A_SYSTEM = """You are a constraint-transmutation analyst for algebra.
Solve the linear equation for x and return strict JSON only with this shape:
{
  "predicted_constraints": ["..."],
  "predicted_transmutations": ["..."],
  "next_equation": "...",
  "final_answer": "x = ...",
  "rationale": "short explanation"
}

Rules:
- Use only labels from the provided allowed constraint and transmutation vocabularies.
- Keep the reasoning abstract. Do not mention "teacher", "benchmark", or hidden labels.
- next_equation must be a valid linear-equation transformation or an empty string.
- final_answer must be a concrete answer for x.
- Do not include markdown fences.
"""

MATH_STEP_SYSTEM = """You are a math technician guided by constraint transmutation.
Return strict JSON only with this shape:
{
  "predicted_constraints": ["..."],
  "predicted_transmutations": ["..."],
  "next_equation": "...",
  "rationale": "short explanation"
}

Rules:
- Perform exactly one valid symbolic step from the current equation state.
- next_equation must be a full equation containing '='.
- Do not output a final answer unless x is already isolated in next_equation.
- Use only labels from the provided allowed constraint and transmutation vocabularies.
- Do not include markdown fences or extra prose.
"""

MATH_STEP_LABEL_SYSTEM = """You are a constraint-transmutation labeler for verified algebra steps.
Return strict JSON only with this shape:
{
  "predicted_constraints": ["..."],
  "predicted_transmutations": ["..."],
  "rationale": "short explanation"
}

Rules:
- The transition is already verified as mathematically valid.
- Label the constraint shape and the abstract trade represented by the step.
- Use only labels from the provided allowed constraint and transmutation vocabularies.
- Do not include markdown fences or extra prose.
"""

MATH_SELECT_SYSTEM = """You are a math move selector guided by constraint transmutation.
Return strict JSON only with this shape:
{
  "choice": "A"
}

Rules:
- Choose exactly one candidate move.
- Candidates are already mechanically generated and mathematically valid.
- Prefer the candidate that best advances isolation of x and matches any Memla guidance.
- Do not include markdown fences or extra prose.
"""

_SYM_X = sp.Symbol("x")
_SYM_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)
_TRADE_ADD = "Trade additive clutter for a cleaner equation by inverse operations"
_TRADE_COEFF = "Trade coefficient magnitude for isolated x by dividing both sides"
_TRADE_BILATERAL = "Trade bilateral variable terms for a one-sided coefficient difference"
_TRADE_SIGN = "Trade sign confusion for a stable positive isolation path"
_TRADE_DISTRIBUTION = "Trade nested structure for a flat equation by distributing or collapsing grouped terms"
_TRADE_DENOM = "Trade fractional obstruction for an integer-friendly equation by clearing denominators"

_STEP_OPCODE_DESCRIPTIONS = {
    "CLEAR_DENOMINATORS": "Multiply both sides by the given scalar to remove denominators.",
    "EXPAND": "Expand grouped terms into a flat equation.",
    "MOVE_X_LEFT": "Move the variable term from the right side to the left side.",
    "MOVE_X_RIGHT": "Move the variable term from the left side to the right side.",
    "SWAP_SIDES": "Swap sides so the variable expression is on the left.",
    "SUBTRACT_CONST": "Subtract the given constant from both sides.",
    "ADD_CONST": "Add the given constant to both sides.",
    "DIVIDE_BY_COEFF": "Divide both sides by the given coefficient.",
    "MULTIPLY_BY_NEG_ONE": "Multiply both sides by -1.",
}


@dataclass(frozen=True)
class MathC2ACase:
    case_id: str
    split: str
    prompt: str
    equation: str
    expected_answer: str
    expected_constraints: list[str]
    expected_transmutations: list[str]


def _normalize_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").strip().split())
        clean = re.sub(r"[.!?]+$", "", clean)
        if not clean:
            continue
        lowered = clean.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(clean)
    return out


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {item.lower() for item in predicted}
    expected_set = {item.lower() for item in expected}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        return {}
    clean = re.sub(r",(\s*[}\]])", r"\1", clean)
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if not match:
        return {}
    blob = re.sub(r",(\s*[}\]])", r"\1", match.group(0))
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _canonicalize_predictions(predicted: list[str], allowed: list[str]) -> list[str]:
    allowed_map = {item.lower(): item for item in _normalize_list(allowed)}
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in _normalize_list(predicted):
        mapped = allowed_map.get(raw.lower())
        if not mapped:
            continue
        lowered = mapped.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        canonical.append(mapped)
    return canonical


def _parse_linear_expression(expr: str) -> tuple[Fraction, Fraction] | None:
    clean = str(expr or "").replace(" ", "")
    if not clean:
        return None
    if clean[0] not in "+-":
        clean = "+" + clean
    terms = re.findall(r"[+-][^+-]+", clean)
    if not terms or "".join(terms) != clean:
        return None
    x_coef = Fraction(0)
    constant = Fraction(0)
    for term in terms:
        sign = -1 if term[0] == "-" else 1
        body = term[1:]
        if not body:
            return None
        if body.endswith("x"):
            coeff_text = body[:-1]
            if coeff_text == "":
                coeff = Fraction(1)
            else:
                try:
                    coeff = Fraction(coeff_text)
                except ValueError:
                    return None
            x_coef += sign * coeff
        else:
            try:
                constant += sign * Fraction(body)
            except ValueError:
                return None
    return x_coef, constant


def _parse_linear_equation(equation: str) -> tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]] | None:
    if "=" not in str(equation or ""):
        return None
    left, right = str(equation).split("=", 1)
    left_parsed = _parse_linear_expression(left)
    right_parsed = _parse_linear_expression(right)
    if not left_parsed or not right_parsed:
        return None
    return left_parsed, right_parsed


def _solve_linear_equation(equation: str) -> Fraction | None:
    parsed = _parse_linear_equation(equation)
    if not parsed:
        return None
    (left_x, left_const), (right_x, right_const) = parsed
    net_x = left_x - right_x
    net_const = right_const - left_const
    if net_x == 0:
        return None
    return net_const / net_x


def _is_equivalent_equation(base_equation: str, candidate_equation: str) -> bool:
    base_solution = _solve_linear_equation(base_equation)
    candidate_solution = _solve_linear_equation(candidate_equation)
    if base_solution is None or candidate_solution is None:
        return False
    return base_solution == candidate_solution


def _is_isolated_equation(equation: str) -> bool:
    parsed = _parse_linear_equation(equation)
    if not parsed:
        return False
    (left_x, left_const), (right_x, right_const) = parsed
    if left_const == 0 and left_x in {Fraction(1), Fraction(-1)} and right_x == 0:
        return True
    if right_const == 0 and right_x in {Fraction(1), Fraction(-1)} and left_x == 0:
        return True
    return False


def _parse_final_answer(answer: str) -> Fraction | None:
    clean = str(answer or "").strip()
    if not clean:
        return None
    number_pattern = r"[-+]?(?:\d+\.\d+|\d+/\d+|\d+)"
    match = re.search(rf"x\s*=\s*({number_pattern})", clean)
    if match:
        try:
            return Fraction(match.group(1))
        except ValueError:
            return None
    match = re.search(rf"({number_pattern})", clean)
    if not match:
        return None
    try:
        return Fraction(match.group(1))
    except ValueError:
        return None


def _fraction_to_string(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _parse_sympy_equation(equation: str) -> tuple[sp.Expr, sp.Expr] | None:
    clean = str(equation or "").strip()
    if clean.count("=") != 1:
        return None
    left_text, right_text = clean.split("=", 1)
    try:
        left_expr = parse_expr(
            left_text.replace("^", "**"),
            local_dict={"x": _SYM_X},
            transformations=_SYM_TRANSFORMS,
            evaluate=True,
        )
        right_expr = parse_expr(
            right_text.replace("^", "**"),
            local_dict={"x": _SYM_X},
            transformations=_SYM_TRANSFORMS,
            evaluate=True,
        )
    except Exception:
        return None
    return left_expr, right_expr


def _solve_sympy_equation(equation: str) -> Any | None:
    parsed = _parse_sympy_equation(equation)
    if not parsed:
        return None
    left_expr, right_expr = parsed
    try:
        solution = sp.solveset(sp.Eq(left_expr, right_expr), _SYM_X, domain=sp.S.Reals)
    except Exception:
        return None
    if isinstance(solution, sp.ConditionSet):
        return None
    return solution


def _sympy_solution_signature(solution: Any) -> tuple[str, ...] | None:
    if solution is None:
        return None
    if isinstance(solution, sp.FiniteSet):
        items = sorted(str(sp.nsimplify(item)) for item in solution)
        return tuple(items)
    return (str(solution),)


def _is_symbolically_equivalent_equation(base_equation: str, candidate_equation: str) -> bool:
    return _sympy_solution_signature(_solve_sympy_equation(base_equation)) == _sympy_solution_signature(
        _solve_sympy_equation(candidate_equation)
    )


def _is_symbolically_isolated_equation(equation: str) -> bool:
    parsed = _parse_sympy_equation(equation)
    if not parsed:
        return False
    left_expr, right_expr = parsed
    if sp.simplify(left_expr - _SYM_X) == 0 and not right_expr.has(_SYM_X):
        return True
    if sp.simplify(right_expr - _SYM_X) == 0 and not left_expr.has(_SYM_X):
        return True
    if sp.simplify(left_expr + _SYM_X) == 0 and not right_expr.has(_SYM_X):
        return True
    if sp.simplify(right_expr + _SYM_X) == 0 and not left_expr.has(_SYM_X):
        return True
    return False


def _derive_final_answer_from_equation(equation: str) -> Fraction | None:
    solution = _solve_sympy_equation(equation)
    if not isinstance(solution, sp.FiniteSet) or len(solution) != 1:
        return None
    item = sp.nsimplify(next(iter(solution)))
    if getattr(item, "is_real", False) is False:
        return None
    if getattr(item, "is_Rational", False):
        return Fraction(int(item.p), int(item.q))
    if getattr(item, "is_Integer", False):
        return Fraction(int(item), 1)
    return None


def _derive_case_features(equation: str) -> list[str]:
    clean = str(equation or "")
    if "=" not in clean:
        return []
    left_text, right_text = clean.split("=", 1)
    features: list[str] = []
    if re.search(r"[+-]\s*\d", clean) or re.search(r"\d+\s*[+-]", clean):
        features.append("inverse_operation_chain")
    if re.search(r"\d+\s*\*?\s*x", clean, flags=re.IGNORECASE) or "/" in clean:
        features.append("coefficient_normalization")
    if "(" in clean or ")" in clean:
        features.append("distribution_unwrap")
    if "/" in clean:
        features.append("denominator_clearing")
    if "x" in left_text.lower() and "x" in right_text.lower():
        features.append("variable_both_sides")
    if re.search(r"(^|[=\s(])-\s*\d*\s*\*?\s*x", clean, flags=re.IGNORECASE):
        features.append("sign_flip_management")
    if not features:
        features.extend(["inverse_operation_chain", "coefficient_normalization"])
    return _normalize_list(features)


def load_math_c2a_cases(path: str, *, split: str | None = None) -> list[MathC2ACase]:
    cases: list[MathC2ACase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        row_split = str(row.get("split") or "holdout")
        if split and row_split != split:
            continue
        cases.append(
            MathC2ACase(
                case_id=str(row.get("case_id") or ""),
                split=row_split,
                prompt=str(row.get("prompt") or ""),
                equation=str(row.get("equation") or ""),
                expected_answer=str(row.get("expected_answer") or ""),
                expected_constraints=_normalize_list(list(row.get("expected_constraints") or [])),
                expected_transmutations=_normalize_list(list(row.get("expected_transmutations") or [])),
            )
        )
    return cases


def _sympy_expr_to_text(expr: sp.Expr) -> str:
    return sp.sstr(sp.simplify(expr))


def _sympy_equation_to_text(left_expr: sp.Expr, right_expr: sp.Expr) -> str:
    return f"{_sympy_expr_to_text(left_expr)} = {_sympy_expr_to_text(right_expr)}"


def _scalar_denominator_lcm(left_expr: sp.Expr, right_expr: sp.Expr) -> int:
    denominators: list[int] = []
    for expr in (left_expr, right_expr):
        denom = sp.denom(sp.together(expr))
        if denom == 1:
            continue
        if getattr(denom, "free_symbols", set()):
            return 1
        if not getattr(denom, "is_Integer", False):
            return 1
        denominators.append(abs(int(denom)))
    if not denominators:
        return 1
    lcm = 1
    for value in denominators:
        lcm = sp.ilcm(lcm, value)
    return int(lcm)


def _linear_coeffs_from_sympy(left_expr: sp.Expr, right_expr: sp.Expr) -> tuple[sp.Expr, sp.Expr, sp.Expr, sp.Expr]:
    left_expanded = sp.expand(left_expr)
    right_expanded = sp.expand(right_expr)
    left_coeff = sp.expand(left_expanded.coeff(_SYM_X))
    right_coeff = sp.expand(right_expanded.coeff(_SYM_X))
    left_const = sp.expand(left_expanded.subs(_SYM_X, 0))
    right_const = sp.expand(right_expanded.subs(_SYM_X, 0))
    return left_coeff, left_const, right_coeff, right_const


def _build_symbolic_teacher_step_path(case: MathC2ACase, *, max_steps: int = 8) -> list[dict[str, Any]]:
    current_equation = case.equation
    steps: list[dict[str, Any]] = []

    for step_index in range(1, max_steps + 1):
        if _is_symbolically_isolated_equation(current_equation):
            break
        parsed = _parse_sympy_equation(current_equation)
        if not parsed:
            break
        left_expr, right_expr = parsed
        next_equation = ""
        step_constraints: list[str] = []
        step_transmutations: list[str] = []
        step_action = ""
        step_opcode = ""
        step_operand = ""

        denominator_lcm = _scalar_denominator_lcm(left_expr, right_expr)
        if denominator_lcm > 1:
            left_expr = sp.expand(left_expr * denominator_lcm)
            right_expr = sp.expand(right_expr * denominator_lcm)
            next_equation = _sympy_equation_to_text(left_expr, right_expr)
            step_constraints = ["denominator_clearing"]
            step_transmutations = [_TRADE_DENOM]
            step_action = f"Clear denominators by multiplying both sides by {denominator_lcm}."
            step_opcode = "CLEAR_DENOMINATORS"
            step_operand = str(denominator_lcm)
        else:
            expanded_left = sp.expand(left_expr)
            expanded_right = sp.expand(right_expr)
            if sp.simplify(expanded_left - left_expr) != 0 or sp.simplify(expanded_right - right_expr) != 0:
                next_equation = _sympy_equation_to_text(expanded_left, expanded_right)
                step_constraints = ["distribution_unwrap"]
                step_transmutations = [_TRADE_DISTRIBUTION]
                step_action = "Expand grouped terms to flatten the equation."
                step_opcode = "EXPAND"
            else:
                left_coeff, left_const, right_coeff, right_const = _linear_coeffs_from_sympy(left_expr, right_expr)
                if left_coeff != 0 and right_coeff != 0:
                    next_equation = _sympy_equation_to_text(
                        sp.expand(left_expr - right_coeff * _SYM_X),
                        sp.expand(right_expr - right_coeff * _SYM_X),
                    )
                    step_constraints = ["variable_both_sides"]
                    step_transmutations = [_TRADE_BILATERAL]
                    step_action = "Move the variable term from the right side to the left side."
                    step_opcode = "MOVE_X_LEFT"
                    step_operand = _sympy_expr_to_text(right_coeff)
                elif left_coeff == 0 and right_coeff != 0:
                    next_equation = _sympy_equation_to_text(right_expr, left_expr)
                    step_constraints = ["variable_both_sides"]
                    step_transmutations = [_TRADE_BILATERAL]
                    step_action = "Swap sides so the variable term is on the left."
                    step_opcode = "SWAP_SIDES"
                else:
                    variable_on_left = left_coeff != 0
                    variable_coeff = left_coeff if variable_on_left else right_coeff
                    variable_const = left_const if variable_on_left else right_const
                    if variable_const != 0:
                        shift_value = variable_const
                        next_equation = _sympy_equation_to_text(
                            sp.expand(left_expr - shift_value),
                            sp.expand(right_expr - shift_value),
                        )
                        step_constraints = ["inverse_operation_chain"]
                        step_transmutations = [_TRADE_ADD]
                        if shift_value > 0:
                            step_action = f"Subtract {_sympy_expr_to_text(shift_value)} from both sides."
                            step_opcode = "SUBTRACT_CONST"
                            step_operand = _sympy_expr_to_text(shift_value)
                        else:
                            step_action = f"Add {_sympy_expr_to_text(abs(shift_value))} to both sides."
                            step_opcode = "ADD_CONST"
                            step_operand = _sympy_expr_to_text(abs(shift_value))
                    elif variable_coeff not in {0, 1, -1}:
                        next_equation = _sympy_equation_to_text(
                            sp.simplify(left_expr / variable_coeff),
                            sp.simplify(right_expr / variable_coeff),
                        )
                        step_constraints = ["coefficient_normalization"]
                        step_transmutations = [_TRADE_COEFF]
                        step_action = f"Divide both sides by {_sympy_expr_to_text(variable_coeff)}."
                        step_opcode = "DIVIDE_BY_COEFF"
                        step_operand = _sympy_expr_to_text(variable_coeff)
                        if getattr(variable_coeff, "is_number", False) and variable_coeff.evalf() < 0:
                            step_constraints.append("sign_flip_management")
                            step_transmutations.append(_TRADE_SIGN)
                    elif variable_coeff == -1:
                        next_equation = _sympy_equation_to_text(
                            sp.expand(-left_expr),
                            sp.expand(-right_expr),
                        )
                        step_constraints = ["sign_flip_management"]
                        step_transmutations = [_TRADE_SIGN]
                        step_action = "Multiply both sides by -1."
                        step_opcode = "MULTIPLY_BY_NEG_ONE"
                        step_operand = "-1"

        normalized_next = " ".join(next_equation.split())
        if not normalized_next or normalized_next == " ".join(current_equation.split()):
            break
        steps.append(
            {
                "trace_id": f"{case.case_id}_step_{step_index}",
                "case_id": case.case_id,
                "step_index": step_index,
                "prompt": case.prompt,
                "current_equation": current_equation,
                "next_equation": next_equation,
                "features": _derive_case_features(current_equation),
                "teacher_action": step_action,
                "teacher_opcode": step_opcode,
                "teacher_operand": step_operand,
                "predicted_constraints": _normalize_list(step_constraints),
                "predicted_transmutations": _normalize_list(step_transmutations),
            }
        )
        current_equation = next_equation
    return steps


def capture_symbolic_teacher_math_traces(
    cases: list[MathC2ACase],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    case_traces: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []
    for case in cases:
        case_steps = _build_symbolic_teacher_step_path(case)
        step_traces.extend(case_steps)
        case_traces.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "equation": case.equation,
                "expected_answer": case.expected_answer,
                "features": _derive_case_features(case.equation),
                "predicted_constraints": case.expected_constraints,
                "predicted_transmutations": case.expected_transmutations,
                "final_answer": f"x = {case.expected_answer}",
                "answer_correct": True,
                "step_trace_ids": [step["trace_id"] for step in case_steps],
            }
        )
    return case_traces, step_traces


def _build_teacher_capture_prompt(
    case: MathC2ACase,
    *,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
) -> list[ChatMessage]:
    user_prompt = "\n".join(
        [
            f"Task: {case.prompt}",
            f"Equation: {case.equation}",
            "",
            "Allowed constraints:",
            *[f"- {item}" for item in allowed_constraints],
            "",
            "Allowed transmutations:",
            *[f"- {item}" for item in allowed_transmutations],
        ]
    )
    return [
        ChatMessage(role="system", content=MATH_C2A_SYSTEM),
        ChatMessage(role="user", content=user_prompt),
    ]


def _build_teacher_step_label_prompt(
    step: dict[str, Any],
    *,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
) -> list[ChatMessage]:
    user_prompt = "\n".join(
        [
            f"Task: {step.get('prompt') or ''}",
            f"Current equation: {step.get('current_equation') or ''}",
            f"Verified next equation: {step.get('next_equation') or ''}",
            "",
            "Allowed constraints:",
            *[f"- {item}" for item in allowed_constraints],
            "",
            "Allowed transmutations:",
            *[f"- {item}" for item in allowed_transmutations],
        ]
    )
    return [
        ChatMessage(role="system", content=MATH_STEP_LABEL_SYSTEM),
        ChatMessage(role="user", content=user_prompt),
    ]


def capture_teacher_math_traces(
    *,
    model: str,
    cases: list[MathC2ACase],
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> list[dict[str, Any]]:
    client = UniversalLLMClient.from_env()
    allowed_constraints = _normalize_list(sorted({item for case in cases for item in case.expected_constraints}))
    allowed_transmutations = _normalize_list(sorted({item for case in cases for item in case.expected_transmutations}))
    traces: list[dict[str, Any]] = []
    for case in cases:
        answer = client.chat(
            model=model,
            messages=_build_teacher_capture_prompt(
                case,
                allowed_constraints=allowed_constraints,
                allowed_transmutations=allowed_transmutations,
            ),
            temperature=temperature,
            num_ctx=num_ctx,
        ).strip()
        payload = _extract_json_object(answer)
        predicted_constraints = _canonicalize_predictions(
            list(payload.get("predicted_constraints") or []),
            allowed_constraints,
        )
        predicted_transmutations = _canonicalize_predictions(
            list(payload.get("predicted_transmutations") or []),
            allowed_transmutations,
        )
        final_answer = str(payload.get("final_answer") or "").strip()
        traces.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "equation": case.equation,
                "expected_answer": case.expected_answer,
                "features": _derive_case_features(case.equation),
                "predicted_constraints": predicted_constraints,
                "predicted_transmutations": predicted_transmutations,
                "final_answer": final_answer,
                "answer_correct": _parse_final_answer(final_answer) == Fraction(case.expected_answer),
                "raw_answer": answer,
            }
        )
    return traces


def capture_hybrid_teacher_math_traces(
    *,
    model: str,
    cases: list[MathC2ACase],
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    client = UniversalLLMClient.from_env()
    allowed_constraints = _normalize_list(sorted({item for case in cases for item in case.expected_constraints}))
    allowed_transmutations = _normalize_list(sorted({item for case in cases for item in case.expected_transmutations}))
    case_traces: list[dict[str, Any]] = []
    step_traces: list[dict[str, Any]] = []

    for case in cases:
        symbolic_steps = _build_symbolic_teacher_step_path(case)
        labeled_steps: list[dict[str, Any]] = []
        for step in symbolic_steps:
            raw_answer = client.chat(
                model=model,
                messages=_build_teacher_step_label_prompt(
                    step,
                    allowed_constraints=allowed_constraints,
                    allowed_transmutations=allowed_transmutations,
                ),
                temperature=temperature,
                num_ctx=num_ctx,
            ).strip()
            payload = _extract_json_object(raw_answer)
            predicted_constraints = _canonicalize_predictions(
                list(payload.get("predicted_constraints") or []),
                allowed_constraints,
            )
            predicted_transmutations = _canonicalize_predictions(
                list(payload.get("predicted_transmutations") or []),
                allowed_transmutations,
            )
            if not predicted_constraints:
                predicted_constraints = _canonicalize_predictions(
                    list(step.get("predicted_constraints") or []),
                    allowed_constraints,
                )
            if not predicted_transmutations:
                predicted_transmutations = _canonicalize_predictions(
                    list(step.get("predicted_transmutations") or []),
                    allowed_transmutations,
                )
            labeled_steps.append(
                {
                    **step,
                    "predicted_constraints": predicted_constraints,
                    "predicted_transmutations": predicted_transmutations,
                    "raw_label_answer": raw_answer,
                }
            )
        step_traces.extend(labeled_steps)
        case_traces.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "equation": case.equation,
                "expected_answer": case.expected_answer,
                "features": _derive_case_features(case.equation),
                "predicted_constraints": _normalize_list(
                    [item for step in labeled_steps for item in step.get("predicted_constraints") or []]
                ),
                "predicted_transmutations": _normalize_list(
                    [item for step in labeled_steps for item in step.get("predicted_transmutations") or []]
                ),
                "final_answer": f"x = {case.expected_answer}",
                "answer_correct": True,
                "step_trace_ids": [step["trace_id"] for step in labeled_steps],
            }
        )

    return case_traces, step_traces


def _retrieve_teacher_priors(
    case: MathC2ACase,
    teacher_traces: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    case_features = set(_derive_case_features(case.equation))
    case_prompt_tokens = set(re.findall(r"[a-z0-9]+", case.prompt.lower()))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for trace in teacher_traces:
        if str(trace.get("case_id") or "") == case.case_id:
            continue
        trace_features = set(_normalize_list(list(trace.get("features") or [])))
        trace_prompt_tokens = set(re.findall(r"[a-z0-9]+", str(trace.get("prompt") or "").lower()))
        score = (
            len(case_features & trace_features) * 1.4
            + len(case_prompt_tokens & trace_prompt_tokens) * 0.08
            + (0.25 if bool(trace.get("answer_correct")) else 0.0)
        )
        ranked.append((score, trace))
    ranked.sort(key=lambda item: (item[0], str(item[1].get("case_id") or "")), reverse=True)
    return [trace for _, trace in ranked[: max(int(top_k), 0)] if _ > 0 or top_k > 0]


def _retrieve_teacher_step_priors(
    *,
    case: MathC2ACase,
    current_equation: str,
    teacher_step_traces: list[dict[str, Any]],
    top_k: int = 1,
) -> list[dict[str, Any]]:
    case_features = set(_derive_case_features(current_equation))
    case_prompt_tokens = set(re.findall(r"[a-z0-9]+", case.prompt.lower()))
    equation_tokens = set(re.findall(r"[a-z0-9/]+", current_equation.lower()))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for trace in teacher_step_traces:
        trace_features = set(_normalize_list(list(trace.get("features") or [])))
        trace_prompt_tokens = set(re.findall(r"[a-z0-9]+", str(trace.get("prompt") or "").lower()))
        trace_equation_tokens = set(re.findall(r"[a-z0-9/]+", str(trace.get("current_equation") or "").lower()))
        score = (
            len(case_features & trace_features) * 1.5
            + len(case_prompt_tokens & trace_prompt_tokens) * 0.05
            + len(equation_tokens & trace_equation_tokens) * 0.12
        )
        ranked.append((score, trace))
    ranked.sort(key=lambda item: (item[0], str(item[1].get("trace_id") or "")), reverse=True)
    return [trace for score, trace in ranked[: max(int(top_k), 0)] if score > 0 or top_k > 0]


def _build_math_solver_messages(
    case: MathC2ACase,
    *,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
    teacher_priors: list[dict[str, Any]] | None = None,
    residual_constraints: list[str] | None = None,
    iteration: int = 1,
    previous_answer: str = "",
) -> list[ChatMessage]:
    user_parts = [
        f"Task: {case.prompt}",
        f"Equation: {case.equation}",
        "",
        "Allowed constraints:",
        *[f"- {item}" for item in allowed_constraints],
        "",
        "Allowed transmutations:",
        *[f"- {item}" for item in allowed_transmutations],
    ]
    normalized_priors = list(teacher_priors or [])
    if normalized_priors:
        user_parts.extend(["", "Memla teacher transmutation priors:"])
        for index, trace in enumerate(normalized_priors[:3], start=1):
            user_parts.extend(
                [
                    f"Example {index}:",
                    f"- Problem: {trace.get('prompt') or ''}",
                    f"- Equation: {trace.get('equation') or ''}",
                    f"- Teacher constraints: {', '.join(trace.get('predicted_constraints') or [])}",
                    f"- Teacher transmutations: {', '.join(trace.get('predicted_transmutations') or [])}",
                ]
            )
    if iteration > 1:
        user_parts.extend(
            [
                "",
                f"Retry iteration: {iteration}",
                "Your last answer did not validate. Repair the transmutation and answer using the residual constraints.",
            ]
        )
    normalized_residuals = _normalize_list(list(residual_constraints or []))
    if normalized_residuals:
        user_parts.extend(["", "Residual constraints from the verifier:", *[f"- {item}" for item in normalized_residuals]])
    if previous_answer.strip():
        user_parts.extend(["", "Previous attempt:", previous_answer.strip()])
    return [
        ChatMessage(role="system", content=MATH_C2A_SYSTEM),
        ChatMessage(role="user", content="\n".join(user_parts)),
    ]


def _build_math_step_solver_messages(
    case: MathC2ACase,
    *,
    current_equation: str,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
    teacher_priors: list[dict[str, Any]] | None = None,
    residual_constraints: list[str] | None = None,
    iteration: int = 1,
    previous_answer: str = "",
) -> list[ChatMessage]:
    user_parts = [
        f"Task: {case.prompt}",
        f"Original equation: {case.equation}",
        f"Current equation: {current_equation}",
        "",
        "Allowed constraints:",
        *[f"- {item}" for item in allowed_constraints],
        "",
        "Allowed transmutations:",
        *[f"- {item}" for item in allowed_transmutations],
    ]
    normalized_priors = list(teacher_priors or [])
    if normalized_priors:
        top_prior = normalized_priors[0]
        opcode = str(top_prior.get("teacher_opcode") or "").strip()
        operand = str(top_prior.get("teacher_operand") or "").strip()
        user_parts.extend(
            [
                "",
                "Memla next-step opcode:",
                f"- Similar state: {top_prior.get('current_equation') or top_prior.get('equation') or ''}",
                f"- Opcode: {opcode or 'APPLY_VERIFIED_STEP'}",
            ]
        )
        if operand:
            user_parts.append(f"- Operand: {operand}")
        if opcode:
            user_parts.append(f"- Opcode meaning: {_STEP_OPCODE_DESCRIPTIONS.get(opcode, 'Apply the verified symbolic move.')}")
        if top_prior.get("predicted_constraints"):
            user_parts.append(f"- Constraint shape: {', '.join(top_prior.get('predicted_constraints') or [])}")
        if top_prior.get("predicted_transmutations"):
            user_parts.append(f"- Why this move helps: {', '.join(top_prior.get('predicted_transmutations') or [])}")
    if iteration > 1:
        user_parts.extend(
            [
                "",
                f"Retry iteration: {iteration}",
                "Your last step did not validate or did not finish isolating x. Output a single corrected next equation.",
            ]
        )
    normalized_residuals = _normalize_list(list(residual_constraints or []))
    if normalized_residuals:
        user_parts.extend(["", "Residual constraints from the verifier:", *[f"- {item}" for item in normalized_residuals]])
    if previous_answer.strip():
        user_parts.extend(["", "Previous attempt:", previous_answer.strip()])
    return [
        ChatMessage(role="system", content=MATH_STEP_SYSTEM),
        ChatMessage(role="user", content="\n".join(user_parts)),
    ]


def _append_candidate_move(
    candidates: list[dict[str, Any]],
    *,
    opcode: str,
    operand: str,
    next_equation: str,
    constraints: list[str],
    transmutations: list[str],
) -> None:
    normalized_next = " ".join(str(next_equation or "").split())
    if not normalized_next:
        return
    if any(" ".join(str(item.get("next_equation") or "").split()) == normalized_next for item in candidates):
        return
    candidates.append(
        {
            "opcode": opcode,
            "operand": operand,
            "next_equation": normalized_next,
            "predicted_constraints": _normalize_list(constraints),
            "predicted_transmutations": _normalize_list(transmutations),
        }
    )


def _generate_candidate_moves(current_equation: str, *, max_candidates: int = 4) -> list[dict[str, Any]]:
    parsed = _parse_sympy_equation(current_equation)
    if not parsed:
        return []
    left_expr, right_expr = parsed
    candidates: list[dict[str, Any]] = []

    denominator_lcm = _scalar_denominator_lcm(left_expr, right_expr)
    if denominator_lcm > 1:
        _append_candidate_move(
            candidates,
            opcode="CLEAR_DENOMINATORS",
            operand=str(denominator_lcm),
            next_equation=_sympy_equation_to_text(sp.expand(left_expr * denominator_lcm), sp.expand(right_expr * denominator_lcm)),
            constraints=["denominator_clearing"],
            transmutations=[_TRADE_DENOM],
        )

    expanded_left = sp.expand(left_expr)
    expanded_right = sp.expand(right_expr)
    if sp.simplify(expanded_left - left_expr) != 0 or sp.simplify(expanded_right - right_expr) != 0:
        _append_candidate_move(
            candidates,
            opcode="EXPAND",
            operand="",
            next_equation=_sympy_equation_to_text(expanded_left, expanded_right),
            constraints=["distribution_unwrap"],
            transmutations=[_TRADE_DISTRIBUTION],
        )

    left_coeff, left_const, right_coeff, right_const = _linear_coeffs_from_sympy(left_expr, right_expr)
    if left_coeff != 0 and right_coeff != 0:
        _append_candidate_move(
            candidates,
            opcode="MOVE_X_LEFT",
            operand=_sympy_expr_to_text(right_coeff),
            next_equation=_sympy_equation_to_text(
                sp.expand(left_expr - right_coeff * _SYM_X),
                sp.expand(right_expr - right_coeff * _SYM_X),
            ),
            constraints=["variable_both_sides"],
            transmutations=[_TRADE_BILATERAL],
        )
        _append_candidate_move(
            candidates,
            opcode="MOVE_X_RIGHT",
            operand=_sympy_expr_to_text(left_coeff),
            next_equation=_sympy_equation_to_text(
                sp.expand(left_expr - left_coeff * _SYM_X),
                sp.expand(right_expr - left_coeff * _SYM_X),
            ),
            constraints=["variable_both_sides"],
            transmutations=[_TRADE_BILATERAL],
        )
    elif left_coeff == 0 and right_coeff != 0:
        _append_candidate_move(
            candidates,
            opcode="SWAP_SIDES",
            operand="",
            next_equation=_sympy_equation_to_text(right_expr, left_expr),
            constraints=["variable_both_sides"],
            transmutations=[_TRADE_BILATERAL],
        )

    variable_coeff = left_coeff if left_coeff != 0 else right_coeff
    variable_const = left_const if left_coeff != 0 else right_const
    if variable_coeff != 0 and variable_const != 0:
        shift_value = variable_const
        if shift_value > 0:
            opcode = "SUBTRACT_CONST"
            operand = _sympy_expr_to_text(shift_value)
        else:
            opcode = "ADD_CONST"
            operand = _sympy_expr_to_text(abs(shift_value))
        _append_candidate_move(
            candidates,
            opcode=opcode,
            operand=operand,
            next_equation=_sympy_equation_to_text(
                sp.expand(left_expr - shift_value),
                sp.expand(right_expr - shift_value),
            ),
            constraints=["inverse_operation_chain"],
            transmutations=[_TRADE_ADD],
        )
    if variable_coeff not in {0, 1, -1}:
        transmutations = [_TRADE_COEFF]
        constraints = ["coefficient_normalization"]
        if getattr(variable_coeff, "is_number", False) and variable_coeff.evalf() < 0:
            constraints.append("sign_flip_management")
            transmutations.append(_TRADE_SIGN)
        _append_candidate_move(
            candidates,
            opcode="DIVIDE_BY_COEFF",
            operand=_sympy_expr_to_text(variable_coeff),
            next_equation=_sympy_equation_to_text(
                sp.simplify(left_expr / variable_coeff),
                sp.simplify(right_expr / variable_coeff),
            ),
            constraints=constraints,
            transmutations=transmutations,
        )
    if variable_coeff == -1:
        _append_candidate_move(
            candidates,
            opcode="MULTIPLY_BY_NEG_ONE",
            operand="-1",
            next_equation=_sympy_equation_to_text(
                sp.expand(-left_expr),
                sp.expand(-right_expr),
            ),
            constraints=["sign_flip_management"],
            transmutations=[_TRADE_SIGN],
        )

    verified: list[dict[str, Any]] = []
    for candidate in candidates:
        next_equation = str(candidate.get("next_equation") or "")
        if not _is_symbolically_equivalent_equation(current_equation, next_equation):
            continue
        if " ".join(next_equation.split()) == " ".join(current_equation.split()):
            continue
        verified.append(candidate)
    return verified[: max(int(max_candidates), 1)]


def _extract_choice_letter(text: str) -> str:
    payload = _extract_json_object(text)
    choice = str(payload.get("choice") or "").strip().upper()
    if choice:
        return choice[:1]
    match = re.search(r"\b([A-Z])\b", str(text or "").upper())
    return match.group(1) if match else ""


def _find_correct_candidate_letters(
    candidates: list[dict[str, Any]],
    *,
    teacher_next_equation: str,
) -> list[str]:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    teacher_normalized = " ".join(str(teacher_next_equation or "").split())
    if not teacher_normalized:
        return []
    exact_matches: list[str] = []
    equivalent_matches: list[str] = []
    for index, candidate in enumerate(candidates):
        candidate_equation = " ".join(str(candidate.get("next_equation") or "").split())
        if not candidate_equation:
            continue
        if candidate_equation == teacher_normalized:
            exact_matches.append(letters[index])
        elif _is_symbolically_equivalent_equation(candidate_equation, teacher_normalized):
            equivalent_matches.append(letters[index])
    return exact_matches or equivalent_matches


def _rank_candidates_with_priors(
    candidates: list[dict[str, Any]],
    *,
    current_equation: str,
    teacher_priors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized_priors = list(teacher_priors or [])
    if not candidates:
        return list(candidates)
    top_prior = normalized_priors[0] if normalized_priors else {}
    preferred_opcode = str(top_prior.get("teacher_opcode") or "").strip()
    preferred_operand = str(top_prior.get("teacher_operand") or "").strip()
    preferred_constraints = set(_normalize_list(list(top_prior.get("predicted_constraints") or [])))
    preferred_transmutations = set(_normalize_list(list(top_prior.get("predicted_transmutations") or [])))
    current_features = set(_derive_case_features(current_equation))
    current_length = len(re.findall(r"[a-z0-9]+", current_equation.lower()))

    def _score(item: dict[str, Any]) -> tuple[float, str, str]:
        score = 0.0
        opcode = str(item.get("opcode") or "").strip()
        operand = str(item.get("operand") or "").strip()
        next_equation = str(item.get("next_equation") or "").strip()
        next_features = set(_derive_case_features(next_equation))
        next_length = len(re.findall(r"[a-z0-9]+", next_equation.lower()))

        if _is_symbolically_isolated_equation(next_equation) and _derive_final_answer_from_equation(next_equation) is not None:
            score += 6.0
        feature_reduction = len(current_features) - len(next_features)
        score += feature_reduction * 1.5
        for feature, weight in (
            ("variable_both_sides", 2.0),
            ("denominator_clearing", 1.8),
            ("distribution_unwrap", 1.2),
            ("inverse_operation_chain", 1.0),
            ("coefficient_normalization", 1.3),
            ("sign_flip_management", 0.8),
        ):
            if feature in current_features and feature not in next_features:
                score += weight
        if next_length < current_length:
            score += 0.3

        if preferred_opcode and opcode == preferred_opcode:
            score += 1.25
        if preferred_operand and operand == preferred_operand:
            score += 0.6
        score += 0.35 * len(preferred_constraints & set(_normalize_list(list(item.get("predicted_constraints") or []))))
        score += 0.35 * len(
            preferred_transmutations & set(_normalize_list(list(item.get("predicted_transmutations") or [])))
        )
        return (score, opcode, operand)

    return sorted(candidates, key=_score, reverse=True)


def _build_math_select_messages(
    case: MathC2ACase,
    *,
    current_equation: str,
    candidates: list[dict[str, Any]],
    teacher_priors: list[dict[str, Any]] | None = None,
    residual_constraints: list[str] | None = None,
    iteration: int = 1,
    previous_answer: str = "",
) -> list[ChatMessage]:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    user_parts = [
        f"Task: {case.prompt}",
        f"Original equation: {case.equation}",
        f"Current equation: {current_equation}",
        "",
        "Candidate next moves:",
    ]
    for index, candidate in enumerate(candidates):
        letter = letters[index]
        operand = str(candidate.get("operand") or "").strip()
        line = f"{letter}) {candidate.get('opcode')}"
        if operand:
            line += f"({operand})"
        line += f" -> {candidate.get('next_equation')}"
        user_parts.append(line)
    normalized_priors = list(teacher_priors or [])
    if normalized_priors:
        top_prior = normalized_priors[0]
        opcode = str(top_prior.get("teacher_opcode") or "").strip()
        operand = str(top_prior.get("teacher_operand") or "").strip()
        user_parts.extend(
            [
                "",
                "Memla guidance:",
                f"- Preferred opcode: {opcode or 'NONE'}",
            ]
        )
        if operand:
            user_parts.append(f"- Preferred operand: {operand}")
        if top_prior.get("predicted_constraints"):
            user_parts.append(f"- Constraint shape: {', '.join(top_prior.get('predicted_constraints') or [])}")
        if top_prior.get("predicted_transmutations"):
            user_parts.append(f"- Why this move helps: {', '.join(top_prior.get('predicted_transmutations') or [])}")
    if iteration > 1:
        user_parts.extend(
            [
                "",
                f"Retry iteration: {iteration}",
                "Your last selection did not validate or did not make progress. Choose the best next candidate now.",
            ]
        )
    normalized_residuals = _normalize_list(list(residual_constraints or []))
    if normalized_residuals:
        user_parts.extend(["", "Residual constraints from the verifier:", *[f"- {item}" for item in normalized_residuals]])
    if previous_answer.strip():
        user_parts.extend(["", "Previous attempt:", previous_answer.strip()])
    return [
        ChatMessage(role="system", content=MATH_SELECT_SYSTEM),
        ChatMessage(role="user", content="\n".join(user_parts)),
    ]


def _classify_math_residuals(
    *,
    equation: str,
    payload: dict[str, Any],
    expected_answer: Fraction,
) -> list[str]:
    residuals: list[str] = []
    if not payload:
        return ["invalid_math_json"]
    final_answer = _parse_final_answer(str(payload.get("final_answer") or ""))
    next_equation = str(payload.get("next_equation") or "").strip()
    if final_answer is None:
        residuals.append("missing_final_answer")
    elif final_answer != expected_answer:
        if not next_equation:
            residuals.append("incorrect_final_answer")
        elif not _parse_linear_equation(next_equation):
            residuals.append("invalid_equation_state")
        elif not _is_equivalent_equation(equation, next_equation):
            residuals.append("equivalence_error")
        elif not _is_isolated_equation(next_equation):
            residuals.append("not_isolated")
        else:
            residuals.append("arithmetic_error")
    return _normalize_list(residuals)


def _classify_math_step_residuals(
    *,
    current_equation: str,
    payload: dict[str, Any],
) -> list[str]:
    if not payload:
        return ["invalid_math_json"]
    next_equation = str(payload.get("next_equation") or "").strip()
    if not next_equation:
        return ["missing_next_equation"]
    if not _parse_sympy_equation(next_equation):
        return ["invalid_equation_state"]
    if not _is_symbolically_equivalent_equation(current_equation, next_equation):
        return ["equivalence_error"]
    if " ".join(next_equation.split()) == " ".join(str(current_equation or "").split()):
        return ["no_progress"]
    return []


def _evaluate_math_lane(
    *,
    client: UniversalLLMClient,
    model: str,
    case: MathC2ACase,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
    teacher_priors: list[dict[str, Any]] | None = None,
    max_iterations: int = 3,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    expected_answer = Fraction(case.expected_answer)
    residuals: list[str] = []
    previous_answer = ""
    attempts: list[dict[str, Any]] = []
    best_payload: dict[str, Any] = {}
    best_constraints: list[str] = []
    best_transmutations: list[str] = []
    best_answer_correct = False

    for iteration in range(1, max(int(max_iterations), 1) + 1):
        raw_answer = client.chat(
            model=model,
            messages=_build_math_solver_messages(
                case,
                allowed_constraints=allowed_constraints,
                allowed_transmutations=allowed_transmutations,
                teacher_priors=teacher_priors,
                residual_constraints=residuals,
                iteration=iteration,
                previous_answer=previous_answer,
            ),
            temperature=temperature,
            num_ctx=num_ctx,
        ).strip()
        payload = _extract_json_object(raw_answer)
        predicted_constraints = _canonicalize_predictions(
            list(payload.get("predicted_constraints") or []),
            allowed_constraints,
        )
        predicted_transmutations = _canonicalize_predictions(
            list(payload.get("predicted_transmutations") or []),
            allowed_transmutations,
        )
        parsed_final_answer = _parse_final_answer(str(payload.get("final_answer") or ""))
        answer_correct = parsed_final_answer == expected_answer
        residuals = _classify_math_residuals(
            equation=case.equation,
            payload=payload,
            expected_answer=expected_answer,
        )
        attempts.append(
            {
                "iteration": iteration,
                "predicted_constraints": predicted_constraints,
                "predicted_transmutations": predicted_transmutations,
                "next_equation": str(payload.get("next_equation") or "").strip(),
                "final_answer": str(payload.get("final_answer") or "").strip(),
                "answer_correct": bool(answer_correct),
                "residual_constraints": residuals,
                "raw_answer": raw_answer,
            }
        )
        if answer_correct:
            best_payload = payload
            best_constraints = predicted_constraints
            best_transmutations = predicted_transmutations
            best_answer_correct = True
            break
        if not best_payload:
            best_payload = payload
            best_constraints = predicted_constraints
            best_transmutations = predicted_transmutations
        previous_answer = raw_answer
        if attempts and len(attempts) >= 2:
            current_signature = (
                attempts[-1]["final_answer"],
                "|".join(attempts[-1]["residual_constraints"]),
            )
            prior_signature = (
                attempts[-2]["final_answer"],
                "|".join(attempts[-2]["residual_constraints"]),
            )
            if current_signature == prior_signature:
                break

    predicted_answer = _parse_final_answer(str(best_payload.get("final_answer") or ""))
    return {
        "predicted_constraints": best_constraints,
        "predicted_transmutations": best_transmutations,
        "predicted_final_answer": str(best_payload.get("final_answer") or "").strip(),
        "predicted_next_equation": str(best_payload.get("next_equation") or "").strip(),
        "answer_accuracy": 1.0 if (predicted_answer == expected_answer or best_answer_correct) else 0.0,
        "constraint_recall": round(_score_overlap(best_constraints, case.expected_constraints), 4),
        "transmutation_recall": round(_score_overlap(best_transmutations, case.expected_transmutations), 4),
        "iterations_used": len(attempts) or 1,
        "residual_constraints": list(attempts[-1]["residual_constraints"]) if attempts else [],
        "attempts": attempts,
    }


def _evaluate_math_step_lane(
    *,
    client: UniversalLLMClient,
    model: str,
    case: MathC2ACase,
    allowed_constraints: list[str],
    allowed_transmutations: list[str],
    teacher_priors: list[dict[str, Any]] | None = None,
    teacher_step_traces: list[dict[str, Any]] | None = None,
    max_iterations: int = 4,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    expected_answer = Fraction(case.expected_answer)
    current_equation = case.equation
    residuals = _derive_case_features(current_equation)
    previous_answer = ""
    attempts: list[dict[str, Any]] = []
    accumulated_constraints: list[str] = []
    accumulated_transmutations: list[str] = []
    solved = False

    for iteration in range(1, max(int(max_iterations), 1) + 1):
        equation_before = current_equation
        active_priors = (
            _retrieve_teacher_step_priors(
                case=case,
                current_equation=current_equation,
                teacher_step_traces=teacher_step_traces or [],
                top_k=1,
            )
            if teacher_step_traces
            else list(teacher_priors or [])
        )
        raw_answer = client.chat(
            model=model,
            messages=_build_math_step_solver_messages(
                case,
                current_equation=current_equation,
                allowed_constraints=allowed_constraints,
                allowed_transmutations=allowed_transmutations,
                teacher_priors=active_priors,
                residual_constraints=residuals,
                iteration=iteration,
                previous_answer=previous_answer,
            ),
            temperature=temperature,
            num_ctx=num_ctx,
        ).strip()
        payload = _extract_json_object(raw_answer)
        predicted_constraints = _canonicalize_predictions(
            list(payload.get("predicted_constraints") or []),
            allowed_constraints,
        )
        predicted_transmutations = _canonicalize_predictions(
            list(payload.get("predicted_transmutations") or []),
            allowed_transmutations,
        )
        accumulated_constraints = _normalize_list(accumulated_constraints + predicted_constraints)
        accumulated_transmutations = _normalize_list(accumulated_transmutations + predicted_transmutations)

        next_equation = str(payload.get("next_equation") or "").strip()
        step_residuals = _classify_math_step_residuals(
            current_equation=current_equation,
            payload=payload,
        )
        accepted_step = not step_residuals
        derived_answer: Fraction | None = None
        current_after = current_equation
        if accepted_step:
            current_after = next_equation
            current_equation = next_equation
            derived_answer = _derive_final_answer_from_equation(current_equation)
            if derived_answer == expected_answer and _is_symbolically_isolated_equation(current_equation):
                solved = True
                residuals = []
            else:
                residuals = _derive_case_features(current_equation)
        else:
            residuals = step_residuals

        attempts.append(
            {
                "iteration": iteration,
                "predicted_constraints": predicted_constraints,
                "predicted_transmutations": predicted_transmutations,
                "equation_before": equation_before,
                "next_equation": next_equation,
                "accepted_step": accepted_step,
                "equation_after": current_after,
                "derived_final_answer": f"x = {_fraction_to_string(derived_answer)}" if derived_answer is not None else "",
                "residual_constraints": residuals,
                "raw_answer": raw_answer,
            }
        )
        if solved:
            break
        previous_answer = raw_answer
        if len(attempts) >= 2:
            current_signature = (
                attempts[-1]["next_equation"],
                "|".join(attempts[-1]["residual_constraints"]),
            )
            prior_signature = (
                attempts[-2]["next_equation"],
                "|".join(attempts[-2]["residual_constraints"]),
            )
            if current_signature == prior_signature:
                break

    predicted_answer = _derive_final_answer_from_equation(current_equation)
    return {
        "predicted_constraints": accumulated_constraints,
        "predicted_transmutations": accumulated_transmutations,
        "predicted_final_answer": f"x = {_fraction_to_string(predicted_answer)}" if predicted_answer is not None else "",
        "predicted_next_equation": current_equation,
        "answer_accuracy": 1.0 if (predicted_answer == expected_answer and _is_symbolically_isolated_equation(current_equation)) else 0.0,
        "constraint_recall": round(_score_overlap(accumulated_constraints, case.expected_constraints), 4),
        "transmutation_recall": round(_score_overlap(accumulated_transmutations, case.expected_transmutations), 4),
        "iterations_used": len(attempts) or 1,
        "residual_constraints": list(attempts[-1]["residual_constraints"]) if attempts else [],
        "attempts": attempts,
    }


def _evaluate_math_select_lane(
    *,
    client: UniversalLLMClient,
    model: str,
    case: MathC2ACase,
    teacher_step_traces: list[dict[str, Any]] | None = None,
    max_iterations: int = 4,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    expected_answer = Fraction(case.expected_answer)
    current_equation = case.equation
    residuals = _derive_case_features(current_equation)
    previous_answer = ""
    attempts: list[dict[str, Any]] = []
    accumulated_constraints: list[str] = []
    accumulated_transmutations: list[str] = []
    solved = False
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for iteration in range(1, max(int(max_iterations), 1) + 1):
        equation_before = current_equation
        candidates = _generate_candidate_moves(current_equation)
        if not candidates:
            attempts.append(
                {
                    "iteration": iteration,
                    "selected_choice": "",
                    "selected_opcode": "",
                    "selected_equation": "",
                    "accepted_step": False,
                    "equation_before": equation_before,
                    "equation_after": equation_before,
                    "derived_final_answer": "",
                    "predicted_constraints": [],
                    "predicted_transmutations": [],
                    "residual_constraints": ["no_candidates"],
                    "raw_answer": "",
                }
            )
            break
        active_priors = (
            _retrieve_teacher_step_priors(
                case=case,
                current_equation=current_equation,
                teacher_step_traces=teacher_step_traces or [],
                top_k=1,
        )
        if teacher_step_traces
        else []
        )
        candidates = _rank_candidates_with_priors(
            candidates,
            current_equation=current_equation,
            teacher_priors=active_priors,
        )
        raw_answer = ""
        choice = ""
        if len(candidates) == 1:
            choice = "A"
            selected = candidates[0]
            raw_answer = '{"choice":"A","source":"auto_singleton"}'
        else:
            raw_answer = client.chat(
                model=model,
                messages=_build_math_select_messages(
                    case,
                    current_equation=current_equation,
                    candidates=candidates,
                    teacher_priors=active_priors,
                    residual_constraints=residuals,
                    iteration=iteration,
                    previous_answer=previous_answer,
                ),
                temperature=temperature,
                num_ctx=num_ctx,
            ).strip()
            choice = _extract_choice_letter(raw_answer)
            selected_index = letters.find(choice)
            selected = candidates[selected_index] if 0 <= selected_index < len(candidates) else None
        if not selected and active_priors and candidates:
            choice = "A"
            selected = candidates[0]
            raw_answer = raw_answer or '{"choice":"A","source":"memla_fallback"}'
        if not selected:
            residuals = ["invalid_choice"]
            attempts.append(
                {
                    "iteration": iteration,
                    "selected_choice": choice,
                    "selected_opcode": "",
                    "selected_equation": "",
                    "accepted_step": False,
                    "equation_before": equation_before,
                    "equation_after": equation_before,
                    "derived_final_answer": "",
                    "predicted_constraints": [],
                    "predicted_transmutations": [],
                    "residual_constraints": residuals,
                    "raw_answer": raw_answer,
                }
            )
            previous_answer = raw_answer
            continue

        predicted_constraints = _normalize_list(accumulated_constraints + list(selected.get("predicted_constraints") or []))
        predicted_transmutations = _normalize_list(
            accumulated_transmutations + list(selected.get("predicted_transmutations") or [])
        )
        accumulated_constraints = predicted_constraints
        accumulated_transmutations = predicted_transmutations

        current_equation = str(selected.get("next_equation") or "").strip()
        derived_answer = _derive_final_answer_from_equation(current_equation)
        if derived_answer == expected_answer and _is_symbolically_isolated_equation(current_equation):
            solved = True
            residuals = []
        else:
            residuals = _derive_case_features(current_equation)

        attempts.append(
            {
                "iteration": iteration,
                "selected_choice": choice,
                "selected_opcode": str(selected.get("opcode") or ""),
                "selected_equation": current_equation,
                "accepted_step": True,
                "equation_before": equation_before,
                "equation_after": current_equation,
                "derived_final_answer": f"x = {_fraction_to_string(derived_answer)}" if derived_answer is not None else "",
                "predicted_constraints": list(selected.get("predicted_constraints") or []),
                "predicted_transmutations": list(selected.get("predicted_transmutations") or []),
                "residual_constraints": residuals,
                "raw_answer": raw_answer,
            }
        )
        if solved:
            break
        previous_answer = raw_answer
        if len(attempts) >= 2:
            current_signature = (
                attempts[-1]["selected_choice"],
                attempts[-1]["equation_after"],
                "|".join(attempts[-1]["residual_constraints"]),
            )
            prior_signature = (
                attempts[-2]["selected_choice"],
                attempts[-2]["equation_after"],
                "|".join(attempts[-2]["residual_constraints"]),
            )
            if current_signature == prior_signature:
                break

    predicted_answer = _derive_final_answer_from_equation(current_equation)
    return {
        "predicted_constraints": accumulated_constraints,
        "predicted_transmutations": accumulated_transmutations,
        "predicted_final_answer": f"x = {_fraction_to_string(predicted_answer)}" if predicted_answer is not None else "",
        "predicted_next_equation": current_equation,
        "answer_accuracy": 1.0 if (predicted_answer == expected_answer and _is_symbolically_isolated_equation(current_equation)) else 0.0,
        "constraint_recall": round(_score_overlap(accumulated_constraints, case.expected_constraints), 4),
        "transmutation_recall": round(_score_overlap(accumulated_transmutations, case.expected_transmutations), 4),
        "iterations_used": len(attempts) or 1,
        "residual_constraints": list(attempts[-1]["residual_constraints"]) if attempts else [],
        "attempts": attempts,
    }


def _evaluate_math_rerank_lane(
    *,
    client: UniversalLLMClient,
    model: str,
    case: MathC2ACase,
    step_trace: dict[str, Any],
    teacher_step_traces: list[dict[str, Any]] | None = None,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    current_equation = str(step_trace.get("current_equation") or "").strip()
    teacher_next_equation = str(step_trace.get("next_equation") or "").strip()
    candidates = _generate_candidate_moves(current_equation)
    correct_choices = _find_correct_candidate_letters(
        candidates,
        teacher_next_equation=teacher_next_equation,
    )
    active_priors = (
        _retrieve_teacher_step_priors(
            case=case,
            current_equation=current_equation,
            teacher_step_traces=teacher_step_traces or [],
            top_k=1,
        )
        if teacher_step_traces
        else []
    )
    raw_answer = client.chat(
        model=model,
        messages=_build_math_select_messages(
            case,
            current_equation=current_equation,
            candidates=candidates,
            teacher_priors=active_priors,
            residual_constraints=[],
            iteration=1,
            previous_answer="",
        ),
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()
    choice = _extract_choice_letter(raw_answer)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    selected_index = letters.find(choice)
    selected = candidates[selected_index] if 0 <= selected_index < len(candidates) else None
    predicted_constraints = list(selected.get("predicted_constraints") or []) if selected else []
    predicted_transmutations = list(selected.get("predicted_transmutations") or []) if selected else []
    residuals: list[str]
    if not candidates:
        residuals = ["no_candidates"]
    elif not selected:
        residuals = ["invalid_choice"]
    elif choice not in correct_choices:
        residuals = ["teacher_mismatch"]
    else:
        residuals = []
    candidate_count = len(candidates)
    ambiguous = candidate_count >= 3
    return {
        "predicted_constraints": predicted_constraints,
        "predicted_transmutations": predicted_transmutations,
        "predicted_final_answer": "",
        "predicted_next_equation": str(selected.get("next_equation") or "").strip() if selected else "",
        "answer_accuracy": 1.0 if choice in correct_choices else 0.0,
        "choice_accuracy": 1.0 if choice in correct_choices else 0.0,
        "ambiguous_choice_accuracy": 1.0 if ambiguous and choice in correct_choices else 0.0,
        "ambiguous": ambiguous,
        "candidate_count": candidate_count,
        "selected_choice": choice,
        "correct_choices": correct_choices,
        "selected_opcode": str(selected.get("opcode") or "").strip() if selected else "",
        "constraint_recall": round(
            _score_overlap(predicted_constraints, list(step_trace.get("predicted_constraints") or [])),
            4,
        ),
        "transmutation_recall": round(
            _score_overlap(predicted_transmutations, list(step_trace.get("predicted_transmutations") or [])),
            4,
        ),
        "iterations_used": 1,
        "residual_constraints": residuals,
        "attempts": [
            {
                "iteration": 1,
                "selected_choice": choice,
                "correct_choices": correct_choices,
                "selected_opcode": str(selected.get("opcode") or "").strip() if selected else "",
                "selected_equation": str(selected.get("next_equation") or "").strip() if selected else "",
                "accepted_step": bool(choice in correct_choices),
                "equation_before": current_equation,
                "equation_after": str(selected.get("next_equation") or "").strip() if selected else current_equation,
                "predicted_constraints": predicted_constraints,
                "predicted_transmutations": predicted_transmutations,
                "residual_constraints": residuals,
                "raw_answer": raw_answer,
            }
        ],
    }


def run_math_c2a_teacher_student_benchmark(
    *,
    cases_path: str,
    teacher_model: str,
    student_models: list[str],
    temperature: float = 0.1,
    num_ctx: int | None = None,
    max_iterations: int = 3,
    top_k: int = 3,
    executor_mode: str = "oneshot",
    teacher_trace_source: str = "llm",
) -> dict[str, Any]:
    train_cases = load_math_c2a_cases(cases_path, split="train")
    holdout_cases = load_math_c2a_cases(cases_path, split="holdout")
    all_cases = train_cases + holdout_cases
    allowed_constraints = _normalize_list(sorted({item for case in all_cases for item in case.expected_constraints}))
    allowed_transmutations = _normalize_list(sorted({item for case in all_cases for item in case.expected_transmutations}))

    teacher_step_traces: list[dict[str, Any]] = []
    if teacher_trace_source == "sympy":
        teacher_traces, teacher_step_traces = capture_symbolic_teacher_math_traces(train_cases)
    elif teacher_trace_source == "hybrid":
        teacher_traces, teacher_step_traces = capture_hybrid_teacher_math_traces(
            model=teacher_model,
            cases=train_cases,
            temperature=temperature,
            num_ctx=num_ctx,
        )
    else:
        teacher_traces = capture_teacher_math_traces(
            model=teacher_model,
            cases=train_cases,
            temperature=temperature,
            num_ctx=num_ctx,
        )
    client = UniversalLLMClient.from_env()

    lanes: list[dict[str, Any]] = []
    lane_specs: list[tuple[str, str, str]] = [(f"{teacher_model}_raw", teacher_model, "raw")]
    for model in student_models:
        lane_specs.append((f"{model}_raw", model, "raw"))
        lane_specs.append((f"{model}_memla", model, "memla"))

    rows: list[dict[str, Any]] = []
    lane_results_accumulator: dict[str, list[dict[str, Any]]] = {lane_id: [] for lane_id, _, _ in lane_specs}

    if executor_mode == "stepwise_rerank":
        for case in holdout_cases:
            for step_trace in _build_symbolic_teacher_step_path(case):
                current_equation = str(step_trace.get("current_equation") or "").strip()
                candidates = _generate_candidate_moves(current_equation)
                row = {
                    "case_id": case.case_id,
                    "step_index": int(step_trace.get("step_index") or 0),
                    "prompt": case.prompt,
                    "equation": case.equation,
                    "current_equation": current_equation,
                    "teacher_next_equation": str(step_trace.get("next_equation") or "").strip(),
                    "expected_answer": case.expected_answer,
                    "expected_constraints": list(step_trace.get("predicted_constraints") or []),
                    "expected_transmutations": list(step_trace.get("predicted_transmutations") or []),
                    "teacher_priors": [
                        str(trace.get("trace_id") or trace.get("case_id") or "")
                        for trace in (
                            _retrieve_teacher_step_priors(
                                case=case,
                                current_equation=current_equation,
                                teacher_step_traces=teacher_step_traces,
                                top_k=top_k,
                            )
                            if teacher_step_traces
                            else []
                        )
                    ],
                    "candidate_count": len(candidates),
                    "correct_choices": _find_correct_candidate_letters(
                        candidates,
                        teacher_next_equation=str(step_trace.get("next_equation") or "").strip(),
                    ),
                    "lane_results": {},
                }
                for lane_id, model, mode in lane_specs:
                    result = _evaluate_math_rerank_lane(
                        client=client,
                        model=model,
                        case=case,
                        step_trace=step_trace,
                        teacher_step_traces=teacher_step_traces if mode == "memla" else None,
                        temperature=temperature,
                        num_ctx=num_ctx,
                    )
                    row["lane_results"][lane_id] = result
                    lane_results_accumulator[lane_id].append(result)
                rows.append(row)
    else:
        for case in holdout_cases:
            row = {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "equation": case.equation,
                "expected_answer": case.expected_answer,
                "expected_constraints": case.expected_constraints,
                "expected_transmutations": case.expected_transmutations,
                "teacher_priors": [
                    str(trace.get("trace_id") or trace.get("case_id") or "")
                    for trace in (
                        _retrieve_teacher_step_priors(case=case, current_equation=case.equation, teacher_step_traces=teacher_step_traces, top_k=top_k)
                        if executor_mode in {"stepwise", "stepwise_select"} and teacher_step_traces
                        else _retrieve_teacher_priors(case, teacher_traces, top_k=top_k)
                    )
                ],
                "lane_results": {},
            }
            for lane_id, model, mode in lane_specs:
                if mode == "memla":
                    if executor_mode == "stepwise" and teacher_step_traces:
                        priors = _retrieve_teacher_step_priors(
                            case=case,
                            current_equation=case.equation,
                            teacher_step_traces=teacher_step_traces,
                            top_k=top_k,
                        )
                    else:
                        priors = _retrieve_teacher_priors(case, teacher_traces, top_k=top_k)
                else:
                    priors = []
                if executor_mode == "stepwise":
                    result = _evaluate_math_step_lane(
                        client=client,
                        model=model,
                        case=case,
                        allowed_constraints=allowed_constraints,
                        allowed_transmutations=allowed_transmutations,
                        teacher_priors=priors,
                        teacher_step_traces=teacher_step_traces if mode == "memla" else None,
                        max_iterations=max_iterations,
                        temperature=temperature,
                        num_ctx=num_ctx,
                    )
                elif executor_mode == "stepwise_select":
                    result = _evaluate_math_select_lane(
                        client=client,
                        model=model,
                        case=case,
                        teacher_step_traces=teacher_step_traces if mode == "memla" else None,
                        max_iterations=max_iterations,
                        temperature=temperature,
                        num_ctx=num_ctx,
                    )
                else:
                    result = _evaluate_math_lane(
                        client=client,
                        model=model,
                        case=case,
                        allowed_constraints=allowed_constraints,
                        allowed_transmutations=allowed_transmutations,
                        teacher_priors=priors,
                        max_iterations=max_iterations,
                        temperature=temperature,
                        num_ctx=num_ctx,
                    )
                row["lane_results"][lane_id] = result
                lane_results_accumulator[lane_id].append(result)
            rows.append(row)

    for lane_id, model, mode in lane_specs:
        lane_rows = lane_results_accumulator[lane_id]
        count = max(len(lane_rows), 1)
        if executor_mode == "stepwise_rerank":
            ambiguous_rows = [item for item in lane_rows if item.get("ambiguous")]
            ambiguous_count = max(len(ambiguous_rows), 1)
            lanes.append(
                {
                    "lane_id": lane_id,
                    "model": model,
                    "mode": mode,
                    "avg_choice_accuracy": round(sum(item["choice_accuracy"] for item in lane_rows) / count, 4),
                    "avg_ambiguous_choice_accuracy": round(
                        sum(item["choice_accuracy"] for item in ambiguous_rows) / ambiguous_count,
                        4,
                    ),
                    "avg_constraint_recall": round(sum(item["constraint_recall"] for item in lane_rows) / count, 4),
                    "avg_transmutation_recall": round(sum(item["transmutation_recall"] for item in lane_rows) / count, 4),
                    "avg_candidate_count": round(sum(item["candidate_count"] for item in lane_rows) / count, 4),
                }
            )
        else:
            lanes.append(
                {
                    "lane_id": lane_id,
                    "model": model,
                    "mode": mode,
                    "avg_answer_accuracy": round(sum(item["answer_accuracy"] for item in lane_rows) / count, 4),
                    "avg_constraint_recall": round(sum(item["constraint_recall"] for item in lane_rows) / count, 4),
                    "avg_transmutation_recall": round(sum(item["transmutation_recall"] for item in lane_rows) / count, 4),
                    "avg_iterations_used": round(sum(item["iterations_used"] for item in lane_rows) / count, 4),
                }
            )

    return {
        "generated_ts": int(time.time()),
        "cases_path": cases_path,
        "teacher_model": teacher_model,
        "teacher_trace_source": teacher_trace_source,
        "student_models": student_models,
        "executor_mode": executor_mode,
        "train_cases": len(train_cases),
        "holdout_cases": len(holdout_cases),
        "allowed_constraints": allowed_constraints,
        "allowed_transmutations": allowed_transmutations,
        "teacher_traces": teacher_traces,
        "teacher_step_traces": teacher_step_traces,
        "lanes": lanes,
        "rows": rows,
    }


def render_math_c2a_teacher_student_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Math C2A Teacher-Student Benchmark",
        "",
        f"- Teacher model: `{report['teacher_model']}`",
        f"- Teacher trace source: `{report.get('teacher_trace_source', 'llm')}`",
        f"- Executor mode: `{report.get('executor_mode', 'oneshot')}`",
        f"- Train cases: `{report['train_cases']}`",
        f"- Holdout cases: `{report['holdout_cases']}`",
        "",
        "## Lanes",
        "",
    ]
    for lane in report.get("lanes") or []:
        if report.get("executor_mode") == "stepwise_rerank":
            lines.extend(
                [
                    f"### {lane['lane_id']}",
                    "",
                    f"- Avg choice accuracy: `{lane['avg_choice_accuracy']}`",
                    f"- Avg ambiguous-step choice accuracy: `{lane['avg_ambiguous_choice_accuracy']}`",
                    f"- Avg constraint recall: `{lane['avg_constraint_recall']}`",
                    f"- Avg transmutation recall: `{lane['avg_transmutation_recall']}`",
                    f"- Avg candidate count: `{lane['avg_candidate_count']}`",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"### {lane['lane_id']}",
                    "",
                    f"- Avg answer accuracy: `{lane['avg_answer_accuracy']}`",
                    f"- Avg constraint recall: `{lane['avg_constraint_recall']}`",
                    f"- Avg transmutation recall: `{lane['avg_transmutation_recall']}`",
                    f"- Avg iterations used: `{lane['avg_iterations_used']}`",
                    "",
                ]
            )
    for index, row in enumerate(report.get("rows") or [], start=1):
        if report.get("executor_mode") == "stepwise_rerank":
            lines.extend(
                [
                    f"## Holdout Step {index}",
                    "",
                    f"**Prompt**: {row['prompt']}",
                    "",
                    f"- Case id: `{row['case_id']}`",
                    f"- Step index: `{row.get('step_index', 0)}`",
                    f"- Original equation: `{row['equation']}`",
                    f"- Current equation: `{row.get('current_equation', '')}`",
                    f"- Teacher next equation: `{row.get('teacher_next_equation', '')}`",
                    f"- Candidate count: `{row.get('candidate_count', 0)}`",
                    f"- Correct choices: `{', '.join(row.get('correct_choices') or [])}`",
                    f"- Teacher prior case ids: `{', '.join(row['teacher_priors'])}`",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"## Holdout Case {index}",
                    "",
                    f"**Prompt**: {row['prompt']}",
                    "",
                    f"- Equation: `{row['equation']}`",
                    f"- Expected answer: `{row['expected_answer']}`",
                    f"- Teacher prior case ids: `{', '.join(row['teacher_priors'])}`",
                    "",
                ]
            )
        for lane in report.get("lanes") or []:
            lane_id = lane["lane_id"]
            result = row["lane_results"][lane_id]
            if report.get("executor_mode") == "stepwise_rerank":
                lines.extend(
                    [
                        f"### {lane_id}",
                        "",
                        f"- Selected choice: `{result.get('selected_choice', '')}`",
                        f"- Correct choices: `{', '.join(result.get('correct_choices') or [])}`",
                        f"- Selected opcode: `{result.get('selected_opcode', '')}`",
                        f"- Selected equation: `{result['predicted_next_equation']}`",
                        f"- Choice accuracy: `{result.get('choice_accuracy', 0.0)}`",
                        f"- Predicted constraints: `{', '.join(result['predicted_constraints'])}`",
                        f"- Constraint recall: `{result['constraint_recall']}`",
                        f"- Predicted transmutations: `{', '.join(result['predicted_transmutations'])}`",
                        f"- Transmutation recall: `{result['transmutation_recall']}`",
                        f"- Residual constraints: `{', '.join(result['residual_constraints'])}`",
                        "",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"### {lane_id}",
                        "",
                        f"- Predicted answer: `{result['predicted_final_answer']}`",
                        f"- Answer accuracy: `{result['answer_accuracy']}`",
                        f"- Predicted constraints: `{', '.join(result['predicted_constraints'])}`",
                        f"- Constraint recall: `{result['constraint_recall']}`",
                        f"- Predicted transmutations: `{', '.join(result['predicted_transmutations'])}`",
                        f"- Transmutation recall: `{result['transmutation_recall']}`",
                        f"- Residual constraints: `{', '.join(result['residual_constraints'])}`",
                        f"- Iterations used: `{result['iterations_used']}`",
                        "",
                    ]
                )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a teacher-student math C2A benchmark.")
    parser.add_argument("--cases", default="./distill/math_linear_c2a_v1.jsonl")
    parser.add_argument("--teacher_model", required=True)
    parser.add_argument("--student_models", default="qwen3.5:0.8b,qwen3.5:4b")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--max_iterations", type=int, default=3)
    parser.add_argument("--top_k", type=int, default=3)
    parser.add_argument("--executor_mode", choices=["oneshot", "stepwise", "stepwise_select", "stepwise_rerank"], default="oneshot")
    parser.add_argument("--teacher_trace_source", choices=["llm", "sympy", "hybrid"], default="llm")
    parser.add_argument("--out_dir", default="./distill/math_c2a_teacher_student")
    args = parser.parse_args(argv)

    report = run_math_c2a_teacher_student_benchmark(
        cases_path=args.cases,
        teacher_model=args.teacher_model,
        student_models=[item.strip() for item in str(args.student_models).split(",") if item.strip()],
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        max_iterations=args.max_iterations,
        top_k=args.top_k,
        executor_mode=args.executor_mode,
        teacher_trace_source=args.teacher_trace_source,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "math_c2a_teacher_student_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "math_c2a_teacher_student_report.md").write_text(
        render_math_c2a_teacher_student_markdown(report),
        encoding="utf-8",
    )
    (out_dir / "teacher_math_traces.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in report["teacher_traces"]),
        encoding="utf-8",
    )
    print(f"[math_c2a_benchmark] wrote benchmark artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
