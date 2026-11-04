"""POST /ask 하나와 정적 화면 한 장 (docs/proposal.md 6절).

질문만 오면 to_query로 QueryPlan을 만든다. 사람이 고친 sql이 함께 오면 to_query를 건너뛰고
그 SQL을 실행한다. 어느 쪽이든 실행은 core.db.run을 거쳐 게이트와 reader 계정을 지난다.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.assist import to_query
from core.db import run
from core.gate import GateError
from core.schema import TRIPS_SCHEMA, QueryPlan

WEB_DIR = Path(__file__).parent.parent / "web"
ANSWER_ROWS = 5


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=200)
    sql: str | None = Field(default=None, description="사람이 고친 SQL. 있으면 이 SQL을 다시 실행한다")
    interpretation: str | None = Field(default=None, description="사람이 고친 해석")


class AskResponse(BaseModel):
    question: str
    answerable: bool
    answer: str
    interpretation: str
    reason: str = ""
    sql: str | None = None
    edited: bool = False
    columns: list[str] = []
    rows: list[list] = []


app = FastAPI(title="따릉이 물어보기")


@app.post("/ask")
def ask(request: AskRequest) -> AskResponse:
    edited = request.sql is not None
    if edited:
        interpretation = " ".join((request.interpretation or "사람이 고친 SQL").split())
        plan = QueryPlan(answerable=True, sql=request.sql, interpretation=interpretation)
    else:
        plan = to_query(request.question, TRIPS_SCHEMA)

    if not plan.answerable:
        return AskResponse(
            question=request.question,
            answerable=False,
            answer="답할 수 없음",
            interpretation=plan.interpretation,
            reason=plan.reason,
        )

    try:
        result = run(plan.sql)
    except GateError as e:
        raise HTTPException(400, f"게이트에서 거부했다: {e}")
    except psycopg.errors.QueryCanceled:
        raise HTTPException(400, "실행 시간이 너무 길어 중단했다")
    except psycopg.OperationalError:
        raise HTTPException(503, "DB에 접속할 수 없다")
    except psycopg.Error as e:
        raise HTTPException(400, f"SQL 실행 오류: {str(e).splitlines()[0]}")

    rows = [[_cell(value) for value in row] for row in result.rows]
    return AskResponse(
        question=request.question,
        answerable=True,
        answer=_answer(result.columns, rows),
        interpretation=plan.interpretation,
        sql=result.sql,
        edited=edited,
        columns=result.columns,
        rows=rows,
    )


def _cell(value):
    """JSON으로 보낼 수 있게 바꾼다. Decimal은 문자열이 되지 않게 숫자로 둔다."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _format(value):
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _answer(columns, rows):
    """결과표를 한 줄로 줄인다. 값 하나면 그 값, 아니면 첫 칸(마지막 칸) 목록."""
    if not rows:
        return "결과 없음"
    if len(rows) == 1 and len(columns) == 1:
        return _format(rows[0][0])
    if len(columns) == 1:
        parts = [_format(row[0]) for row in rows[:ANSWER_ROWS]]
    else:
        parts = [f"{_format(row[0])}({_format(row[-1])})" for row in rows[:ANSWER_ROWS]]
    rest = len(rows) - ANSWER_ROWS
    return ", ".join(parts) + (f" 외 {rest}행" if rest > 0 else "")


# API 경로보다 뒤에 둔다. / 에서 web/index.html을 준다
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
