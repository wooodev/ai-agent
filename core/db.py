"""게이트를 지난 SQL만 reader 계정으로 실행한다.

DATABASE_URL은 reader 계정이어야 한다 (docker-compose.yml의 app 서비스가 받는 값).
"""

import os
from dataclasses import dataclass

import psycopg

from core.gate import MAX_ROWS, check

STATEMENT_TIMEOUT_MS = 5000


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple]


def run(sql, url=None, max_rows=MAX_ROWS):
    """게이트에서 거부되면 GateError, 실행 중 실패하면 psycopg.Error가 난다."""
    checked = check(sql, max_rows)
    with psycopg.connect(
        url or os.environ["DATABASE_URL"],
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    ) as conn:
        # reader 권한과 별도로 트랜잭션도 읽기 전용으로 연다
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(checked)
            columns = [column.name for column in cur.description]
            return QueryResult(checked, columns, cur.fetchall())
