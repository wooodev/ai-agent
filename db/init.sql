-- DB 볼륨이 비어 있을 때 postgres 이미지가 psql로 한 번 실행한다.
-- 비밀번호는 db 서비스의 환경 변수에서 읽는다.

CREATE TABLE trips (
    date        DATE     NOT NULL,
    dow         TEXT     NOT NULL,
    is_weekend  BOOLEAN  NOT NULL,
    hour        SMALLINT NOT NULL,
    slot        TEXT     NOT NULL,
    start_id    TEXT     NOT NULL,
    end_id      TEXT,
    start_dong  TEXT,
    end_dong    TEXT,
    trips       INTEGER  NOT NULL
);

\getenv reader_password READER_PASSWORD
CREATE ROLE reader LOGIN PASSWORD :'reader_password';

-- PUBLIC 기본 권한으로 임시 테이블이나 객체를 만들지 못하게 막는다
REVOKE TEMPORARY ON DATABASE :"DBNAME" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT CONNECT ON DATABASE :"DBNAME" TO reader;
GRANT USAGE ON SCHEMA public TO reader;
GRANT SELECT ON trips TO reader;
