import pytest

from core.gate import MAX_ROWS, GateError, check


def test_delete_is_rejected():
    with pytest.raises(GateError, match="SELECT"):
        check("DELETE FROM trips")


def test_two_selects_are_rejected():
    with pytest.raises(GateError, match="하나"):
        check("SELECT count(*) FROM trips; SELECT count(*) FROM trips")


def test_other_table_is_rejected():
    with pytest.raises(GateError, match="trips 테이블만"):
        check("SELECT * FROM pg_user")


def test_missing_limit_is_added():
    assert check("SELECT * FROM trips") == f"SELECT * FROM trips LIMIT {MAX_ROWS}"


def test_large_limit_is_capped():
    assert check("SELECT * FROM trips LIMIT 5000") == f"SELECT * FROM trips LIMIT {MAX_ROWS}"


def test_small_limit_and_trailing_semicolon_are_kept():
    assert check("SELECT * FROM trips LIMIT 3 OFFSET 6;") == "SELECT * FROM trips LIMIT 3 OFFSET 6"


def test_typical_question_passes():
    sql = """
        SELECT start_dong AS "동", sum(trips) AS "건수"
        FROM trips t
        WHERE NOT is_weekend AND hour = 8 AND start_dong LIKE '%동'
        GROUP BY start_dong
        ORDER BY "건수" DESC
        LIMIT 3
    """
    assert check(sql) == sql.rstrip()


def test_semicolon_inside_string_is_not_a_second_statement():
    assert check("SELECT count(*) FROM trips WHERE start_dong = 'a;b'").endswith("LIMIT 100")


@pytest.mark.parametrize(
    "sql",
    [
        "select * from trips; delete from trips",
        "SELECT * INTO copy_of_trips FROM trips",
        "SELECT * FROM trips FOR UPDATE",
        "WITH d AS (DELETE FROM trips RETURNING *) SELECT * FROM d",
        "SELECT 1 FROM trips -- 주석",
    ],
)
def test_writes_and_hidden_statements_are_rejected(sql):
    with pytest.raises(GateError):
        check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM trips, pg_user",
        "SELECT * FROM trips JOIN pg_catalog.pg_user ON true",
        'SELECT * FROM "pg_user"',
        "SELECT * FROM public.other",
        "SELECT * FROM trips WHERE end_id IN (SELECT usename FROM pg_user)",
        "SELECT * FROM trips UNION SELECT * FROM pg_user",
        "SELECT * FROM (pg_user CROSS JOIN trips)",
        "SELECT * FROM trips t, LATERAL (SELECT * FROM pg_user) u",
        "SELECT * FROM generate_series(1, 3)",
        "SELECT query_to_xml('select * from pg_user', true, true, '') FROM trips",
        "SELECT E'\\'' FROM pg_user",
    ],
)
def test_other_tables_and_functions_are_rejected(sql):
    with pytest.raises(GateError):
        check(sql)


def test_subquery_and_extract_from_trips_pass():
    sql = (
        "SELECT extract(dow FROM date), count(*) FROM "
        "(SELECT * FROM public.trips WHERE trips > 1) AS s GROUP BY 1"
    )
    assert check(sql) == f"{sql} LIMIT {MAX_ROWS}"


def test_parenthesized_join_of_trips_passes():
    sql = "SELECT count(*) FROM (trips a JOIN trips b USING (date)) WHERE a.hour = 8"
    assert check(sql) == f"{sql} LIMIT {MAX_ROWS}"


@pytest.mark.parametrize("sql", ["SELECT * FROM trips LIMIT ALL", "SELECT * FROM trips LIMIT 10 * 100"])
def test_unclear_limit_is_rejected(sql):
    with pytest.raises(GateError, match="LIMIT"):
        check(sql)
