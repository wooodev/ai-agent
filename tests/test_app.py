import pytest
from fastapi.testclient import TestClient

from app.main import _answer, app

client = TestClient(app)


@pytest.fixture
def db_env(reader_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", reader_url)


def test_index_page_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "따릉이 물어보기" in response.text


def test_unanswerable_needs_no_db():
    response = client.post("/ask", json={"question": "마포구에서 출발한 이용 건수는?"})

    body = response.json()
    assert response.status_code == 200
    assert body["answerable"] is False
    assert body["answer"] == "답할 수 없음"
    assert "구(區)" in body["reason"]
    assert body["sql"] is None


def test_empty_question_is_rejected():
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_question_runs_template(db_env):
    response = client.post("/ask", json={"question": "평일 아침 8시대에 출발이 가장 많은 동네 3곳은?"})

    body = response.json()
    assert response.status_code == 200
    assert body["answer"] == "가양1동(1,741), 발산1동(902), 방화1동(851)"
    assert body["interpretation"].endswith("08:00~08:59 출발")
    assert body["columns"] == ["동네", "건수"]
    assert body["rows"][0] == ["가양1동", 1741]
    assert body["edited"] is False


def test_edited_sql_is_rerun_through_gate(db_env):
    sql = (
        'SELECT start_dong AS "동네", sum(trips) AS "건수" FROM trips '
        "WHERE NOT is_weekend AND hour BETWEEN 7 AND 9 AND start_dong IS NOT NULL "
        'GROUP BY start_dong ORDER BY "건수" DESC LIMIT 3'
    )
    response = client.post(
        "/ask",
        json={"question": "평일 아침에 가장 바쁜 동네 3곳은?", "sql": sql, "interpretation": "아침 = 07:00~09:59"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["edited"] is True
    assert body["interpretation"] == "아침 = 07:00~09:59"
    assert [row[0] for row in body["rows"]] == ["가양1동", "발산1동", "방화1동"]


def test_edited_sql_rejected_by_gate():
    response = client.post("/ask", json={"question": "q", "sql": "DELETE FROM trips"})

    assert response.status_code == 400
    assert "게이트" in response.json()["detail"]


def test_edited_sql_error_is_reported(db_env):
    response = client.post("/ask", json={"question": "q", "sql": "SELECT no_such_column FROM trips"})

    assert response.status_code == 400
    assert "SQL 실행 오류" in response.json()["detail"]


def test_decimal_and_date_are_json_numbers_and_strings(db_env):
    by_date = client.post("/ask", json={"question": "날짜별 이용 건수"}).json()
    averages = client.post("/ask", json={"question": "평일과 주말 하루 평균"}).json()

    assert by_date["rows"][0] == ["2026-10-22", "목", 136513]
    assert averages["rows"][0][-1] == 143222.67


def test_answer_summary():
    assert _answer(["건수"], [[150343]]) == "150,343"
    assert _answer(["동네", "건수"], []) == "결과 없음"
    assert _answer(["시"], [[h] for h in range(7)]) == "0, 1, 2, 3, 4 외 2행"
