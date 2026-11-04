"""to_query가 주고받는 모양: 입력 Schema와 출력 QueryPlan (docs/proposal.md 4절)."""

from datetime import date, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator


class Column(BaseModel):
    name: str
    type: str
    description: str


class Schema(BaseModel):
    """질문을 SQL로 바꿀 때 코드가 넣어 주는 테이블 정보와 데이터 기간."""

    table: str
    columns: list[Column]
    date_from: date
    date_to: date

    def dates(self):
        days = (self.date_to - self.date_from).days
        return [self.date_from + timedelta(days=i) for i in range(days + 1)]


class QueryPlan(BaseModel):
    sql: str | None = Field(default=None, description="실행할 SELECT 한 문장. 답할 수 없으면 비운다")
    interpretation: str = Field(description="질문을 어떻게 해석했는지 한 줄")
    answerable: bool
    reason: str = Field(default="", description="답할 수 없을 때 그 이유")

    @field_validator("interpretation")
    @classmethod
    def _one_line(cls, value):
        if "\n" in value:
            raise ValueError("interpretation은 한 줄이어야 한다")
        return value

    @model_validator(mode="after")
    def _sql_matches_answerable(self):
        if self.answerable and not self.sql:
            raise ValueError("답할 수 있으면 sql이 있어야 한다")
        if not self.answerable and (self.sql or not self.reason):
            raise ValueError("답할 수 없으면 sql 없이 reason을 적는다")
        return self


# docs/architecture.md의 trips 테이블
TRIPS_SCHEMA = Schema(
    table="trips",
    columns=[
        Column(name="date", type="date", description="날짜 (2026-10-22 ~ 10-26)"),
        Column(name="dow", type="text", description="요일 (목, 금, 토, 일, 월)"),
        Column(name="is_weekend", type="boolean", description="토·일이면 true"),
        Column(name="hour", type="smallint", description="출발 시각의 시 (0 ~ 23)"),
        Column(name="slot", type="text", description="5분 단위 출발 시각 (HHMM)"),
        Column(name="start_id", type="text", description="출발 대여소 ID (ST-xxxx)"),
        Column(name="end_id", type="text", description="도착 대여소 ID (ST-xxxx). 원본에 없으면 NULL"),
        Column(name="start_dong", type="text", description="출발 대여소의 행정동. 이름이 비면 NULL"),
        Column(name="end_dong", type="text", description="도착 대여소의 행정동. 이름이 비면 NULL"),
        Column(name="trips", type="integer", description="이용 건수 (출발 기준 한 번씩)"),
    ],
    date_from=date(2026, 10, 22),
    date_to=date(2026, 10, 26),
)
