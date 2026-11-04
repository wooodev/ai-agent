"""AI 자리: 질문 한 줄을 QueryPlan으로 바꾼다 (docs/proposal.md 4절).

v0.2는 템플릿 매칭이, v0.5는 모델이 같은 시그니처로 이 자리를 채운다.
어느 쪽이든 나온 SQL은 core.db.run을 거쳐 게이트를 지난다.
"""

from typing import Protocol

from core import templates
from core.schema import TRIPS_SCHEMA, QueryPlan, Schema


class ToQuery(Protocol):
    def __call__(self, question: str, schema: Schema) -> QueryPlan: ...


def template_to_query(question: str, schema: Schema = TRIPS_SCHEMA) -> QueryPlan:
    """키워드로 템플릿을 고른다. 못 고르면 answerable=False."""
    return templates.match(question, schema)


to_query: ToQuery = template_to_query
