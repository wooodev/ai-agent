from pathlib import Path

import pandas as pd
import pytest

from scripts.preprocess import TRIPS_COLUMNS, read_raw, to_trips

SAMPLE = Path(__file__).parent.parent / "data" / "sample" / "od_sample.csv"


@pytest.fixture
def raw():
    return read_raw(SAMPLE, encoding="utf-8")


def test_sample_keeps_every_departure_row(raw):
    trips = to_trips(raw)

    assert list(trips.columns) == TRIPS_COLUMNS
    assert len(trips) == 10
    assert trips["trips"].sum() == 12


def test_sample_first_row(raw):
    row = to_trips(raw).iloc[0]

    assert row["date"] == "2026-10-22"
    assert row["dow"] == "목"
    assert not row["is_weekend"]
    assert row["hour"] == 8
    assert row["slot"] == "0800"
    assert row["start_id"] == "ST-1005"
    assert row["end_id"] == "ST-1996"
    assert row["start_dong"] == "신정1동"
    assert row["end_dong"] == "목1동"


def test_blank_name_becomes_null(raw):
    row = to_trips(raw).iloc[9]

    assert row["start_id"] == "ST-1050"
    assert pd.isna(row["start_dong"])
    assert row["end_dong"] == "암사3동"


def test_arrival_rows_are_dropped(raw):
    arrivals = raw.assign(집계_기준="도착시간")

    trips = to_trips(pd.concat([raw, arrivals]))

    assert len(trips) == 10
    assert trips["trips"].sum() == 12


def test_end_id_x_becomes_null_and_keeps_trips(raw):
    raw.loc[0, ["종료_대여소_ID", "종료_대여소명"]] = ["X", ""]

    trips = to_trips(raw)

    assert pd.isna(trips.loc[0, "end_id"])
    assert pd.isna(trips.loc[0, "end_dong"])
    assert trips["trips"].sum() == 12


@pytest.mark.parametrize(
    "day, dow, is_weekend",
    [
        ("20261023", "금", False),
        ("20261024", "토", True),
        ("20261025", "일", True),
        ("20261026", "월", False),
    ],
)
def test_dow_and_weekend(raw, day, dow, is_weekend):
    trips = to_trips(raw.assign(기준_날짜=day))

    assert (trips["dow"] == dow).all()
    assert (trips["is_weekend"] == is_weekend).all()


def test_slot_keeps_leading_zero_and_hour_is_int(raw):
    trips = to_trips(raw.assign(기준_시간대="0005"))

    assert (trips["slot"] == "0005").all()
    assert (trips["hour"] == 0).all()
