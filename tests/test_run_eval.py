from decimal import Decimal

import pytest

from core.schema import QueryPlan
from eval.run_eval import UNANSWERABLE, evaluate_one, extract, same


def test_number_must_match_exactly():
    assert same(150343, extract(150343, [(150343,)]))
    assert not same(150343, extract(150343, [(300686,)]))
    assert not same(150343, extract(150343, []))


def test_decimal_and_float_compare_by_value():
    assert same(120633.5, Decimal("120633.50"))
    assert not same(143222.67, Decimal("143222.66"))


def test_single_name_is_first_cell_of_first_row():
    assert same("가양1동", extract("가양1동", [("가양1동", 27849), ("여의동", 1)]))


def test_list_must_match_in_order():
    expected = ["가양1동", "발산1동", "방화1동"]
    assert same(expected, extract(expected, [("가양1동", 3), ("발산1동", 2), ("방화1동", 1)]))
    assert not same(expected, extract(expected, [("발산1동", 3), ("가양1동", 2), ("방화1동", 1)]))
    assert not same(expected, extract(expected, [("가양1동", 3), ("발산1동", 2)]))


def test_dict_reads_last_cell_of_labeled_rows():
    expected = {"weekday": 143222.67, "weekend": 120633.5}
    rows = [("평일", 429668, 3, Decimal("143222.67")), ("주말", 241267, 2, Decimal("120633.50"))]
    assert same(expected, extract(expected, rows))
    assert not same(expected, extract(expected, rows[:1]))


@pytest.mark.parametrize(
    "expected, plan, ok",
    [
        (UNANSWERABLE, QueryPlan(answerable=False, interpretation="x", reason="y"), True),
        (150343, QueryPlan(answerable=False, interpretation="x", reason="y"), False),
    ],
)
def test_unanswerable_is_judged_by_answerable(expected, plan, ok):
    item = {"id": 1, "question": "q", "expected": expected}

    outcome = evaluate_one(item, lambda question, schema: plan, url=None)

    assert outcome.ok is ok


def test_gate_rejection_counts_as_wrong():
    item = {"id": 1, "question": "q", "expected": 1}
    plan = QueryPlan(answerable=True, sql="DELETE FROM trips", interpretation="x")

    outcome = evaluate_one(item, lambda question, schema: plan, url=None)

    assert not outcome.ok
    assert outcome.got.startswith("GateError")
