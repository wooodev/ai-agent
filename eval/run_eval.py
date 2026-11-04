"""golden.jsonl을 to_query → 게이트 → 실행으로 돌려 정답과 비교한다 (docs/proposal.md 7절).

저장소 루트에서 docker compose up 후 실행한다: python -m eval.run_eval

결과에서 답을 꺼내는 규칙:
- 숫자·문자 하나: 첫 행의 첫 칸
- 목록: 모든 행의 첫 칸, 순서까지 같아야 한다
- 사전 {"weekday": ..}: 첫 칸이 LABELS의 이름인 행의 마지막 칸
- "답할 수 없음": answerable=False이면 일치
숫자는 Decimal로 바꿔 정확히 같아야 한다.
"""

import argparse
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import dotenv_values

from core.assist import template_to_query
from core.db import run
from core.gate import GateError
from core.schema import TRIPS_SCHEMA

GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"
ENV_PATH = Path(__file__).parent.parent / ".env"
UNANSWERABLE = "답할 수 없음"
LABELS = {"weekday": "평일", "weekend": "주말"}


@dataclass
class Outcome:
    id: int
    question: str
    expected: object
    got: object
    ok: bool
    interpretation: str


def load_golden(path=GOLDEN_PATH):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def extract(expected, rows):
    """정답의 모양에 맞춰 결과 행에서 답을 꺼낸다."""
    if isinstance(expected, list):
        return [row[0] for row in rows]
    if isinstance(expected, dict):
        by_label = {row[0]: row[-1] for row in rows}
        return {key: by_label.get(label) for key, label in LABELS.items() if key in expected}
    return rows[0][0] if rows else None


def same(expected, got):
    if isinstance(expected, list):
        return isinstance(got, list) and len(got) == len(expected) and all(map(same, expected, got))
    if isinstance(expected, dict):
        return isinstance(got, dict) and got.keys() == expected.keys() and all(
            same(expected[key], got[key]) for key in expected
        )
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(got, (int, float, Decimal)) and not isinstance(got, bool) and (
            Decimal(str(expected)) == Decimal(str(got))
        )
    return expected == got


def evaluate_one(item, to_query, url):
    expected = item["expected"]
    plan = to_query(item["question"], TRIPS_SCHEMA)

    if not plan.answerable:
        got, ok = UNANSWERABLE, expected == UNANSWERABLE
    else:
        try:
            got = extract(expected, run(plan.sql, url).rows)
            ok = expected != UNANSWERABLE and same(expected, got)
        except (GateError, psycopg.Error) as e:  # 게이트 거부와 실행 오류는 모두 오답이다
            got, ok = f"{type(e).__name__}: {e}", False

    return Outcome(item["id"], item["question"], expected, got, ok, plan.interpretation)


def evaluate(to_query, url, golden=None):
    if golden is None:
        golden = load_golden()
    return [evaluate_one(item, to_query, url) for item in golden]


def default_url():
    """앱 컨테이너는 DATABASE_URL을 받는다. 호스트에서는 .env로 reader 주소를 만든다."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = dotenv_values(ENV_PATH)
    return f"postgresql://reader:{env['READER_PASSWORD']}@127.0.0.1:5432/{env['POSTGRES_DB']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=None, help="reader 접속 주소 (기본: DATABASE_URL 또는 .env)")
    args = parser.parse_args()

    outcomes = evaluate(template_to_query, args.url or default_url())
    for o in outcomes:
        mark = "O" if o.ok else "X"
        print(f"[{mark}] {o.id:>2}. {o.question}")
        print(f"       해석: {o.interpretation}")
        print(f"       정답: {o.expected} / 결과: {o.got}")
    print(f"\n템플릿: {len(outcomes)}건 중 {sum(o.ok for o in outcomes)}건")


if __name__ == "__main__":
    main()
