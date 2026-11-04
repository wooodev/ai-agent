from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values

ENV_PATH = Path(__file__).parent.parent / ".env"


@pytest.fixture(scope="session")
def reader_url():
    """docker compose로 띄운 DB의 reader 접속 주소. DB가 없으면 테스트를 건너뛴다."""
    env = dotenv_values(ENV_PATH)
    if not env.get("READER_PASSWORD"):
        pytest.skip(".env가 없다")
    url = f"postgresql://reader:{env['READER_PASSWORD']}@127.0.0.1:5432/{env['POSTGRES_DB']}"
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("DB에 접속할 수 없다 (docker compose up 필요)")
    return url
