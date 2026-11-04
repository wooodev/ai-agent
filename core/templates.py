"""키워드로 자주 묻는 질문 템플릿 SQL 10개 중 하나를 고른다 (AI 자리의 기준선).

질문에서 날짜·요일·평일/주말·시각·동네를 뽑아 조건으로 붙이고, 키워드로 템플릿을 고른다.
뽑은 조건은 모두 해석 한 줄에 적는다. 못 고르거나 데이터로 답할 수 없으면 answerable=False.
"""

import re
from dataclasses import dataclass
from datetime import date

from core.schema import QueryPlan, Schema

DOW_NAMES = "월화수목금토일"

# 질문 단위는 행정동이다. 구는 대응표가 없어 답하지 않는다 (D-006)
GU_NAMES = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구",
    "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구",
    "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구",
]

# 시각 숫자 없이 쓰면 범위를 정할 수 없는 말
VAGUE_TIMES = ["새벽", "아침", "오전", "점심", "오후", "저녁", "밤", "출근", "퇴근"]
PM_WORDS = ["오후", "저녁", "밤"]

DATE_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일|(\d{1,2})/(\d{1,2})")
HOUR_RANGE_RE = re.compile(r"(\d{1,2})\s*시?\s*(?:~|-|부터)\s*(\d{1,2})\s*시")
HOUR_RE = re.compile(r"(\d{1,2})\s*시")
DONG_RE = re.compile(r"[가-힣]+[0-9]*(?:가[0-9]*)?동(?!네)")
NOT_DONGS = {"이동", "자동", "행동", "활동", "운동", "공동"}
TOP_N_RE = re.compile(r"(\d+)\s*(?:곳|개|위|군데)|상위\s*(\d+)")
KOREAN_COUNTS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
KOREAN_N_RE = re.compile(r"(다섯|한|두|세|네)\s*(?:곳|개|군데)")
TOP_WORDS = ["가장", "제일", "상위", "순위", "많은 곳", "바쁜", "붐비"]


class Unanswerable(Exception):
    def __init__(self, reason, interpretation):
        super().__init__(reason)
        self.reason = reason
        self.interpretation = interpretation


@dataclass
class Slots:
    """질문에서 뽑은 조건."""

    question: str
    schema: Schema
    dates: list[date]
    day_kind: str | None  # "평일", "주말", "평일·주말", None
    hours: tuple[int, int] | None
    start_dong: str | None
    end_dong: str | None
    top_n: int
    is_top: bool

    def has(self, *words):
        return any(word in self.question for word in words)


def match(question, schema):
    try:
        slots = _parse(question, schema)
    except Unanswerable as e:
        return QueryPlan(answerable=False, interpretation=e.interpretation, reason=e.reason)

    for template in TEMPLATES:
        built = template(slots)
        if built:
            description, sql = built
            notes = _filters(slots)[1]
            interpretation = ", ".join([description, *notes])
            return QueryPlan(answerable=True, sql=sql, interpretation=interpretation)

    return QueryPlan(
        answerable=False,
        interpretation="맞는 템플릿 없음",
        reason="자주 묻는 질문 템플릿 중 맞는 것을 찾지 못했다",
    )


def _parse(question, schema):
    for gu in GU_NAMES:
        if gu in question:
            raise Unanswerable("구(區) 정보가 없어 답할 수 없다. 데이터에는 행정동만 있다", f"{gu} 단위 질문")
    if "대여소" in question and "같은 대여소" not in question:
        raise Unanswerable("개별 대여소의 실제 이름을 알 수 없다. 데이터에는 ST- ID만 있다", "개별 대여소 질문")
    if re.search(r"거리|이용\s*시간|몇\s*분|소요", question):
        raise Unanswerable("이용 시간·거리는 정의를 확인하기 전이라 답하지 않는다", "이용 시간·거리 질문")

    weekday = "평일" in question
    weekend = "주말" in question
    day_kind = "평일·주말" if weekday and weekend else "평일" if weekday else "주말" if weekend else None

    dongs = [d for d in DONG_RE.findall(question) if d not in NOT_DONGS]
    start_dong, end_dong = _roles(question, dongs)

    return Slots(
        question=question,
        schema=schema,
        dates=_dates(question, schema),
        day_kind=day_kind,
        hours=_hours(question),
        start_dong=start_dong,
        end_dong=end_dong,
        top_n=_top_n(question),
        is_top=any(word in question for word in TOP_WORDS) or bool(TOP_N_RE.search(question)),
    )


def _dates(question, schema):
    available = schema.dates()
    period = f"{_md(schema.date_from)} ~ {_md(schema.date_to)}"
    found = []
    for m in DATE_RE.finditer(question):
        month, day = (int(x) for x in (m.group(1, 2) if m.group(1) else m.group(3, 4)))
        try:
            found.append(date(schema.date_from.year, month, day))
        except ValueError:
            raise Unanswerable(f"없는 날짜다: {m.group()}", f"{m.group()} 질문")
    for d in found:
        if d not in available:
            raise Unanswerable(f"데이터 기간은 {period}이다", f"{_md(d)} 질문")

    for i, name in enumerate(DOW_NAMES):
        if f"{name}요일" in question:
            same_dow = [d for d in available if d.weekday() == i]
            if not same_dow:
                raise Unanswerable(f"데이터 기간({period})에 {name}요일이 없다", f"{name}요일 질문")
            found.extend(same_dow)
    return sorted(set(found))


def _hours(question):
    m = HOUR_RANGE_RE.search(question)
    if m:
        hours = (int(m.group(1)), int(m.group(2)))
    else:
        m = HOUR_RE.search(question)
        if not m:
            vague = [word for word in VAGUE_TIMES if word in question]
            if vague:
                raise Unanswerable(
                    f"'{vague[0]}'이 몇 시부터 몇 시인지 정할 수 없다. 'N시대'나 'N~M시'로 물어 달라",
                    f"{vague[0]} 시간대 질문",
                )
            return None
        hours = (int(m.group(1)), int(m.group(1)))

    if any(word in question for word in PM_WORDS):
        hours = tuple(h + 12 if h < 12 else h for h in hours)
    if not all(0 <= h <= 23 for h in hours) or hours[0] > hours[1]:
        raise Unanswerable(f"시각을 이해하지 못했다: {m.group()}", f"{m.group()} 질문")
    return hours


def _roles(question, dongs):
    """동네가 출발 쪽인지 도착 쪽인지 조사로 가른다."""
    if not dongs:
        return None, None
    if len(dongs) >= 2:
        return dongs[0], dongs[1]
    dong = dongs[0]
    after = question[question.index(dong) + len(dong):]
    if after.startswith("에서"):
        return dong, None
    if after.startswith(("으로", "로", "까지", "에 도착")):
        return None, dong
    if "도착" in question and "출발" not in question:
        return None, dong
    return dong, None


def _top_n(question):
    m = TOP_N_RE.search(question)
    if m:
        return int(m.group(1) or m.group(2))
    m = KOREAN_N_RE.search(question)
    if m:
        return KOREAN_COUNTS[m.group(1)]
    return 1


def _md(d):
    return f"{d.month}/{d.day}"


def _filters(slots):
    """WHERE 조건과 해석 한 줄에 붙일 설명."""
    conditions, notes = [], []

    if slots.dates:
        listed = ", ".join(f"'{d.isoformat()}'" for d in slots.dates)
        conditions.append(f"date IN ({listed})")
        notes.append("날짜 = " + "·".join(f"{_md(d)}({DOW_NAMES[d.weekday()]})" for d in slots.dates))
    if slots.day_kind in ("평일", "주말"):
        weekend = slots.day_kind == "주말"
        conditions.append("is_weekend" if weekend else "NOT is_weekend")
        days = [d for d in slots.schema.dates() if (d.weekday() >= 5) == weekend]
        notes.append(f"{slots.day_kind} = " + "·".join(_md(d) for d in days))
    if slots.hours:
        first, last = slots.hours
        conditions.append(f"hour = {first}" if first == last else f"hour BETWEEN {first} AND {last}")
        notes.append(f"{first:02d}:00~{last:02d}:59 출발")
    if slots.start_dong:
        conditions.append(f"start_dong = '{slots.start_dong}'")
        notes.append(f"출발 동네 = {slots.start_dong}")
    if slots.end_dong:
        conditions.append(f"end_dong = '{slots.end_dong}'")
        notes.append(f"도착 동네 = {slots.end_dong}")
    return conditions, notes


def _where(slots, *extra):
    conditions = [*extra, *_filters(slots)[0]]
    return f" WHERE {' AND '.join(conditions)}" if conditions else ""


def _top_dongs(slots, column, description, *extra):
    sql = (
        f'SELECT {column} AS "동네", sum(trips) AS "건수" FROM trips'
        f"{_where(slots, f'{column} IS NOT NULL', *extra)}"
        f' GROUP BY {column} ORDER BY "건수" DESC LIMIT {slots.top_n}'
    )
    return f"{description} 상위 {slots.top_n}곳", sql


# 템플릿 10개. 위에서부터 먼저 맞는 것을 쓴다


def weekday_vs_weekend(slots):
    if slots.day_kind != "평일·주말":
        return None
    sql = (
        "SELECT CASE WHEN is_weekend THEN '주말' ELSE '평일' END AS \"구분\","
        ' sum(trips) AS "건수", count(DISTINCT date) AS "일수",'
        ' round(sum(trips)::numeric / count(DISTINCT date), 2) AS "하루 평균"'
        f' FROM trips{_where(slots)} GROUP BY is_weekend ORDER BY is_weekend'
    )
    return "평일과 주말의 이용 건수와 하루 평균", sql


def same_station_return(slots):
    if not slots.has("그대로 반납", "같은 대여소", "제자리", "빌린 곳"):
        return None
    return _top_dongs(slots, "start_dong", "같은 대여소에서 빌리고 반납한 건수가 많은 동네", "start_id = end_id")


def by_date(slots):
    if not slots.has("날짜별", "일별", "날마다", "매일"):
        return None
    sql = f'SELECT date AS "날짜", dow AS "요일", sum(trips) AS "건수" FROM trips{_where(slots)} GROUP BY date, dow ORDER BY date'
    return "날짜별 이용 건수", sql


def by_dow(slots):
    if not slots.has("요일별"):
        return None
    sql = f'SELECT dow AS "요일", sum(trips) AS "건수" FROM trips{_where(slots)} GROUP BY dow ORDER BY min(date)'
    return "요일별 이용 건수", sql


def by_hour(slots):
    if not slots.has("시간대별", "시각별", "몇 시"):
        return None
    head = f'SELECT hour AS "시", sum(trips) AS "건수" FROM trips{_where(slots)} GROUP BY hour'
    if slots.is_top:
        return f"출발 건수가 많은 시각 상위 {slots.top_n}개", f'{head} ORDER BY "건수" DESC LIMIT {slots.top_n}'
    return "시각별 출발 건수", f"{head} ORDER BY hour"


def destinations_from_dong(slots):
    if not (slots.is_top and slots.start_dong and not slots.end_dong):
        return None
    if not slots.has("도착", "가는", "간 ", "향"):
        return None
    if slots.has("다른"):
        return _top_dongs(slots, "end_dong", "도착이 많은 다른 동네", f"end_dong <> '{slots.start_dong}'")
    return _top_dongs(slots, "end_dong", "도착이 많은 동네")


def origins_to_dong(slots):
    if not (slots.is_top and slots.end_dong and not slots.start_dong):
        return None
    if slots.has("다른"):
        return _top_dongs(slots, "start_dong", "출발이 많은 다른 동네", f"start_dong <> '{slots.end_dong}'")
    return _top_dongs(slots, "start_dong", "출발이 많은 동네")


def top_end_dongs(slots):
    if not (slots.is_top and slots.has("동네", "어디", "어느 동") and slots.has("도착")):
        return None
    return _top_dongs(slots, "end_dong", "도착이 많은 동네")


def top_start_dongs(slots):
    if not (slots.is_top and slots.has("동네", "어디", "어느 동")):
        return None
    return _top_dongs(slots, "start_dong", "출발이 많은 동네")


def total_trips(slots):
    if not slots.has("건수", "몇 건", "이용량", "얼마나", "몇 번", "횟수"):
        return None
    return "이용 건수 합계(출발 기준)", f'SELECT sum(trips) AS "건수" FROM trips{_where(slots)}'


TEMPLATES = [
    weekday_vs_weekend,
    same_station_return,
    by_dow,  # "요일별"에 "일별"이 들어 있어 by_date보다 먼저 본다
    by_date,
    by_hour,
    destinations_from_dong,
    origins_to_dong,
    top_end_dongs,
    top_start_dongs,
    total_trips,
]
