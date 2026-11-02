"""전처리 결과(trips.csv)를 PostgreSQL trips 테이블에 적재한다.

docker compose up 후 호스트에서 실행한다. 다시 실행하면 내용을 통째로 바꾼다.
"""

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

CSV_PATH = Path("data/processed/trips.csv")
COPY_SQL = "COPY trips FROM STDIN WITH (FORMAT csv, HEADER true)"
CHUNK_SIZE = 1024 * 1024


def load(conn, csv_path):
    """한 트랜잭션으로 바꾼다. 중간에 실패하면 기존 내용이 그대로 남는다."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("TRUNCATE trips")
        with cur.copy(COPY_SQL) as copy, open(csv_path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                copy.write(chunk)
        cur.execute("SELECT count(*) FROM trips")
        return cur.fetchone()[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    args = parser.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"{args.csv}가 없다. scripts/preprocess.py를 먼저 실행한다")

    load_dotenv()
    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conn:
        count = load(conn, args.csv)

    print(f"{args.csv} -> trips, {count:,}행")


if __name__ == "__main__":
    main()
