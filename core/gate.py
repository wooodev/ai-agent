"""실행 전에 SQL을 거르는 게이트 (docs/architecture.md).

통과 조건: SQL 문장 하나, SELECT로 시작, 읽는 테이블은 trips뿐, LIMIT은 MAX_ROWS 이하.
판단이 애매한 문법은 통과시키지 않는다. 뒤에서 reader 계정과 읽기 전용 트랜잭션이 한 번 더 막는다.
"""

import re
from dataclasses import dataclass

TABLE = "trips"
MAX_ROWS = 100

TOKEN_RE = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<comment>--|/\*)
    | (?P<string>'(?:[^']|'')*')
    | (?P<quoted>"(?:[^"]|"")*")
    | (?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)
    | (?P<word>[^\W\d]\w*)
    | (?P<op>::|<=|>=|<>|!=|\|\||[-+*/%<>=(),.;])
    """,
    re.VERBOSE,
)

# SELECT 안에서도 쓰기·잠금·세션 변경이 되는 것까지 막는다 (SELECT INTO, FOR UPDATE, WITH ... DELETE)
FORBIDDEN = {
    "insert", "update", "delete", "merge", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "into", "call", "do", "set", "reset", "lock",
    "vacuum", "analyze", "explain", "with", "for", "fetch", "returning",
    "prepare", "execute", "listen", "notify", "begin", "commit", "rollback",
}

# 함수 호출은 이 목록만 허용한다. query_to_xml 같은 함수는 문자열 SQL로 다른 테이블을 읽는다
FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "round", "abs", "ceil", "floor",
    "coalesce", "nullif", "greatest", "least", "cast",
    "extract", "date_part", "date_trunc", "to_char",
    "lower", "upper", "length", "concat",
    "row_number", "rank", "dense_rank",
}

# 뒤에 오는 괄호가 함수 호출이 아니라 묶음·서브쿼리인 키워드
GROUPING_KEYWORDS = {
    "select", "from", "join", "lateral", "where", "having", "on", "using", "by",
    "in", "exists", "any", "all", "some", "not", "and", "or", "is", "as",
    "when", "then", "else", "case", "between", "like", "ilike",
    "over", "filter", "distinct", "union", "intersect", "except", "values",
}

# FROM 목록을 끝내는 키워드
FROM_END = {
    "where", "group", "having", "order", "limit", "offset", "window",
    "union", "intersect", "except",
}


class GateError(ValueError):
    """게이트를 통과하지 못한 SQL. 메시지가 거부 이유다."""


@dataclass
class Token:
    kind: str
    text: str
    start: int
    end: int

    @property
    def name(self):
        """식별자 이름. 따옴표 없는 이름은 PostgreSQL처럼 소문자로 접는다."""
        if self.kind == "quoted":
            return self.text[1:-1].replace('""', '"')
        return self.text.lower()

    def is_word(self, *names):
        return self.kind == "word" and self.name in names

    @property
    def is_identifier(self):
        return self.kind in ("word", "quoted")


def check(sql, max_rows=MAX_ROWS):
    """게이트를 통과한 SQL을 돌려준다. LIMIT이 없거나 크면 max_rows로 맞춘다."""
    tokens = _tokenize(sql)
    while tokens and tokens[-1].text == ";":
        tokens.pop()

    if not tokens:
        raise GateError("SQL이 비어 있다")
    if any(t.text == ";" for t in tokens):
        raise GateError("SQL 문장은 하나만 실행할 수 있다")
    if not tokens[0].is_word("select"):
        raise GateError("SELECT 문만 실행할 수 있다")

    forbidden = sorted({t.name for t in tokens if t.kind == "word"} & FORBIDDEN)
    if forbidden:
        raise GateError(f"쓸 수 없는 키워드: {', '.join(w.upper() for w in forbidden)}")

    _check_tables_and_functions(tokens)
    return _enforce_limit(sql[: tokens[-1].end], tokens, max_rows)


def _tokenize(sql):
    tokens = []
    pos = 0
    while pos < len(sql):
        match = TOKEN_RE.match(sql, pos)
        if not match:
            raise GateError(f"읽을 수 없는 문자: {sql[pos]!r}")
        kind = match.lastgroup
        if kind == "comment":
            raise GateError("주석은 쓸 수 없다")
        # E'...'처럼 접두사가 붙은 문자열은 따옴표 규칙이 달라 문자열 경계를 잘못 읽게 된다
        if kind == "string" and pos > 0 and re.match(r"\w", sql[pos - 1]):
            raise GateError("접두사가 붙은 문자열은 쓸 수 없다")
        if kind != "space":
            tokens.append(Token(kind, match.group(), pos, match.end()))
        pos = match.end()
    return tokens


def _check_tables_and_functions(tokens):
    parens = []  # 열린 괄호마다 "call" 또는 "group"
    in_from = [False]  # 괄호 깊이마다 FROM 목록 안에 있는지
    expect_table = False

    for i, token in enumerate(tokens):
        prev = tokens[i - 1] if i else None

        if expect_table and token.text != "(":
            expect_table = False
            if token.is_word("lateral"):
                expect_table = True
                continue
            if token.is_word("select", "values"):
                # 테이블 자리의 괄호가 서브쿼리였다. 안쪽 FROM은 따로 검사한다
                in_from[-1] = False
            else:
                _check_table(tokens, i)

        if token.text == "(":
            # 테이블 자리의 괄호는 (a JOIN b)일 수 있어 안쪽 첫 자리도 테이블 자리다
            table_position = expect_table
            is_call = (
                prev is not None
                and prev.is_identifier
                and not (prev.kind == "word" and prev.name in GROUPING_KEYWORDS)
            )
            if is_call and prev.name not in FUNCTIONS:
                raise GateError(f"쓸 수 없는 함수: {prev.text}")
            parens.append("call" if is_call else "group")
            in_from.append(table_position)
            expect_table = table_position
        elif token.text == ")":
            if not parens:
                raise GateError("괄호가 맞지 않는다")
            parens.pop()
            in_from.pop()
        elif token.is_word("from", "join"):
            # extract(hour FROM ...)의 FROM은 테이블 자리가 아니다
            if not (parens and parens[-1] == "call"):
                in_from[-1] = True
                expect_table = True
        elif token.kind == "word" and token.name in FROM_END:
            in_from[-1] = False
        elif token.text == "," and in_from[-1]:
            expect_table = True

    if parens:
        raise GateError("괄호가 맞지 않는다")
    if expect_table:
        raise GateError("FROM 뒤에 테이블이 없다")


def _check_table(tokens, i):
    """FROM·JOIN·쉼표 뒤의 테이블 자리에 trips(또는 public.trips)만 오게 한다."""
    j = i
    if tokens[i].is_word("public") and i + 1 < len(tokens) and tokens[i + 1].text == ".":
        j = i + 2
    table = tokens[j] if j < len(tokens) else None
    after = tokens[j + 1] if j + 1 < len(tokens) else None
    if (
        table is None
        or not table.is_identifier
        or table.name != TABLE
        or (after is not None and after.text in (".", "("))
    ):
        raise GateError(f"{TABLE} 테이블만 읽을 수 있다: {tokens[i].text}")


def _enforce_limit(body, tokens, max_rows):
    depth = 0
    limits = []
    for i, token in enumerate(tokens):
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif depth == 0 and token.is_word("limit"):
            limits.append(i)

    if not limits:
        return f"{body} LIMIT {max_rows}"
    if len(limits) > 1:
        raise GateError("LIMIT은 한 번만 쓸 수 있다")

    i = limits[0]
    count = tokens[i + 1] if i + 1 < len(tokens) else None
    after = tokens[i + 2] if i + 2 < len(tokens) else None
    if (
        count is None
        or not re.fullmatch(r"[0-9]+", count.text)
        or (after is not None and not after.is_word("offset"))
    ):
        raise GateError("LIMIT 뒤에는 정수 하나만 쓸 수 있다")
    if int(count.text) <= max_rows:
        return body
    return body[: count.start] + str(max_rows) + body[count.end :]
