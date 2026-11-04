"""docker compose로 띄운 DB에 reader 계정으로 붙는 테스트. DB가 없으면 건너뛴다."""

import psycopg
import pytest

from core.db import run
from core.gate import GateError


def test_count_runs_as_reader(reader_url):
    result = run("SELECT current_user AS who, count(*) AS n FROM trips", reader_url)

    assert result.columns == ["who", "n"]
    assert result.rows == [("reader", 631210)]
    assert result.sql.endswith("LIMIT 100")


def test_rows_are_capped_and_percent_is_not_a_placeholder(reader_url):
    result = run("SELECT start_dong FROM trips WHERE start_dong LIKE '%동' LIMIT 1000", reader_url)

    assert len(result.rows) == 100


def test_delete_is_stopped_by_gate_before_db(reader_url):
    with pytest.raises(GateError):
        run("DELETE FROM trips", reader_url)


def test_reader_cannot_delete_even_without_gate(reader_url):
    with psycopg.connect(reader_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM trips")
