"""data/raw/의 이용 기록 CSV를 trips 컬럼(docs/architecture.md)으로 바꾼다."""

import argparse
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/processed/trips.csv")
RAW_PATTERN = "tpss_bcycl_od_statnhm_*.csv"
RAW_ENCODING = "cp949"

# 두 기준을 합치면 건수가 2배가 된다 (D-003)
DEPARTURE = "출발시간"
DOW_NAMES = ["월", "화", "수", "목", "금", "토", "일"]
TRIPS_COLUMNS = [
    "date",
    "dow",
    "is_weekend",
    "hour",
    "slot",
    "start_id",
    "end_id",
    "start_dong",
    "end_dong",
    "trips",
]


def read_raw(path, encoding=RAW_ENCODING):
    # 시간대의 앞자리 0과 빈 값을 그대로 두려고 모두 문자열로 읽는다
    return pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=False)


def _dong(names):
    """행정동_번호_번호 꼴의 대여소명에서 행정동만 꺼낸다. 이름이 비면 NULL."""
    return names.str.split("_").str[0].replace("", pd.NA)


def to_trips(raw):
    rows = raw[raw["집계_기준"] == DEPARTURE]
    dates = pd.to_datetime(rows["기준_날짜"], format="%Y%m%d")
    slots = rows["기준_시간대"]
    end_ids = rows["종료_대여소_ID"]

    trips = pd.DataFrame(
        {
            "date": dates.dt.strftime("%Y-%m-%d"),
            "dow": dates.dt.dayofweek.map(lambda day: DOW_NAMES[day]),
            "is_weekend": dates.dt.dayofweek >= 5,
            "hour": slots.str[:2].astype(int),
            "slot": slots,
            "start_id": rows["시작_대여소_ID"],
            # 원본의 종료 ID 'X'는 대여소가 아니다. 건수는 살리고 ID만 NULL로 둔다
            "end_id": end_ids.where(end_ids.str.startswith("ST-")),
            "start_dong": _dong(rows["시작_대여소명"]),
            "end_dong": _dong(rows["종료_대여소명"]),
            "trips": rows["전체_건수"].astype(int),
        }
    )
    return trips[TRIPS_COLUMNS].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    paths = sorted(args.raw_dir.glob(RAW_PATTERN))
    if not paths:
        raise SystemExit(f"{args.raw_dir}에 {RAW_PATTERN} 파일이 없다")

    trips = pd.concat([to_trips(read_raw(path)) for path in paths], ignore_index=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    trips.to_csv(args.out, index=False, encoding="utf-8")

    print(f"파일 {len(paths)}개 -> {args.out}, {len(trips):,}행")
    for date, total in trips.groupby("date")["trips"].sum().items():
        print(f"{date}: {total:,}건")


if __name__ == "__main__":
    main()
