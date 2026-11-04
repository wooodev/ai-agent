import pytest
from pydantic import ValidationError

from core.assist import ToQuery, template_to_query, to_query
from core.db import run
from core.gate import check
from core.schema import TRIPS_SCHEMA, QueryPlan

# (질문, 해석 한 줄의 시작, SQL에 들어가야 할 조각들)
ANSWERABLE = [
    ("10월 22일 이용 건수는?", "이용 건수 합계", ["date IN ('2026-10-22')"]),
    ("10/24 성수1가1동 출발 건수", "이용 건수 합계", ["date IN ('2026-10-24')", "start_dong = '성수1가1동'"]),
    ("7~9시 서교동에서 출발한 건수", "이용 건수 합계", ["hour BETWEEN 7 AND 9", "start_dong = '서교동'"]),
    ("주말 저녁 7시대 출발이 가장 많은 동네 다섯 곳", "출발이 많은 동네 상위 5곳", ["is_weekend", "hour = 19", "LIMIT 5"]),
    ("도착이 가장 많은 동네는?", "도착이 많은 동네 상위 1곳", ["GROUP BY end_dong", "LIMIT 1"]),
    ("신촌동에서 가장 많이 가는 다른 동네 2곳", "도착이 많은 다른 동네", ["end_dong <> '신촌동'", "start_dong = '신촌동'"]),
    ("여의동으로 도착한 이용이 가장 많은 출발 동네는?", "출발이 많은 동네", ["end_dong = '여의동'", "GROUP BY start_dong"]),
    ("같은 대여소에 반납한 이용이 많은 동네 3곳", "같은 대여소에서", ["start_id = end_id", "LIMIT 3"]),
    ("날짜별 이용 건수", "날짜별", ["GROUP BY date"]),
    ("요일별 건수", "요일별", ["GROUP BY dow"]),
    ("금요일 시간대별 이용", "시각별", ["date IN ('2026-10-23')", "ORDER BY hour"]),
    ("평일 몇 시에 가장 많이 타나?", "출발 건수가 많은 시각", ["NOT is_weekend", "LIMIT 1"]),
    ("평일과 주말 하루 평균", "평일과 주말", ["count(DISTINCT date)"]),
]

UNANSWERABLE = [
    ("강남구 이용 건수", "구(區)"),
    ("ST-1005 대여소 이용", "대여소"),
    ("평균 이용 거리는?", "거리"),
    ("새벽에 몇 건?", "새벽"),
    ("10월 30일 건수", "데이터 기간"),
    ("화요일 건수", "화요일"),
    ("25시 건수", "시각"),
    ("날씨가 어때?", "템플릿"),
]


@pytest.mark.parametrize("question, interpretation, pieces", ANSWERABLE)
def test_template_is_chosen(question, interpretation, pieces):
    plan = to_query(question, TRIPS_SCHEMA)

    assert plan.answerable
    assert plan.interpretation.startswith(interpretation)
    for piece in pieces:
        assert piece in plan.sql
    check(plan.sql)  # 템플릿 SQL도 게이트를 지나야 한다


@pytest.mark.parametrize("question, reason", UNANSWERABLE)
def test_unanswerable(question, reason):
    plan = to_query(question, TRIPS_SCHEMA)

    assert not plan.answerable
    assert plan.sql is None
    assert reason in plan.reason


def test_interpretation_lists_the_weekdays():
    plan = to_query("평일 8시대 건수", TRIPS_SCHEMA)

    assert plan.interpretation == "이용 건수 합계(출발 기준), 평일 = 10/22·10/23·10/26, 08:00~08:59 출발"


def test_template_matches_to_query_protocol():
    implementation: ToQuery = template_to_query
    assert implementation("요일별 건수", TRIPS_SCHEMA).answerable


def test_query_plan_requires_sql_when_answerable():
    with pytest.raises(ValidationError):
        QueryPlan(answerable=True, interpretation="x")


def test_query_plan_requires_reason_when_unanswerable():
    with pytest.raises(ValidationError):
        QueryPlan(answerable=False, interpretation="x")


def test_query_plan_interpretation_is_one_line():
    with pytest.raises(ValidationError):
        QueryPlan(answerable=True, sql="SELECT 1", interpretation="첫 줄\n둘째 줄")


def test_template_results_from_db(reader_url):
    total = run(to_query("10월 22일 이용 건수는?", TRIPS_SCHEMA).sql, reader_url)
    by_date = run(to_query("날짜별 이용 건수", TRIPS_SCHEMA).sql, reader_url)

    assert total.rows == [(136513,)]
    assert len(by_date.rows) == 5
    assert sum(row[2] for row in by_date.rows) == 670935


@pytest.mark.parametrize("question", [q for q, _, _ in ANSWERABLE])
def test_every_template_runs_on_db(reader_url, question):
    result = run(to_query(question, TRIPS_SCHEMA).sql, reader_url)

    assert result.rows
