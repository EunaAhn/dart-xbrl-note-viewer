#!/usr/bin/env python3
"""DART 주석 일괄다운로드 zip을 Postgres에 적재한다.

zip 안의 TSV를 풀지 않고 스트리밍해서 COPY로 밀어넣는다. 8.6GB를 디스크에
두 번 쓰지 않으려는 것이다.

    python load_notes.py /data/2026_2Q_20260912010317.zip --period 2026_HY
    python load_notes.py ... --max-cik 00200000   # 앞쪽 회사만, 스모크 테스트용
"""
import argparse
import os
import re
import sys
import time
import zipfile

import psycopg

# TSV 파일 -> (테이블, period를 뺀 컬럼 목록). TSV 헤더 순서와 반드시 같아야 한다.
# def/cal/txn/txn-dts는 트리와 표를 그리는 데 쓰지 않아 넣지 않는다.
TABLES = {
    "sub.tsv": ("sub", ["cik", "report_date", "submission_datetime", "taxonomy_id"]),
    "role.tsv": ("role_", ["cik", "report_date", "taxonomy_id", "role_id", "role_uri",
                           "role_nm_ko", "role_nm_en"]),
    "elmt.tsv": ("elmt", ["element_id", "taxonomy_id", "element_name", "data_type",
                          "substitution_group", "period_type", "balance", "nillable",
                          "abstract"]),
    "pre.tsv": ("pre", ["cik", "report_date", "role_id", "element_id", "taxonomy_id",
                        "parent_element_id", "parent_taxonomy_id", "arcrole", "ord",
                        "use_", "priority", "preferredlabel"]),
    "lab.tsv": ("lab", ["cik", "report_date", "label_role_uri", "elmt_id", "taxonomy_id",
                        "lang", "label"]),
    "cntxt.tsv": ("cntxt", ["cik", "report_date", "context_id", "axis_element_id",
                            "axis_taxonomy_id", "member_element_id", "member_taxonomy_id",
                            "dimension", "period_start_date", "period_end_date",
                            "period_instant"]),
    "val.tsv": ("val", ["cik", "report_date", "element_id", "taxonomy_id", "context_id",
                        "unit_id", "decimals", "value"]),
}

# 적재가 끝난 뒤 만드는 인덱스. COPY 도중에 인덱스가 있으면 몇 배 느려진다.
INDEXES = [
    "CREATE INDEX ON sub (period, cik)",
    "CREATE INDEX ON role_ (period, cik, role_id)",
    "CREATE INDEX ON elmt (period, element_id)",
    "CREATE INDEX ON pre (period, cik, role_id)",
    "CREATE INDEX ON lab (period, cik, elmt_id)",
    "CREATE INDEX ON cntxt (period, cik, context_id)",
    "CREATE INDEX ON val (period, cik, element_id)",
    "CREATE INDEX ON val (period, cik, context_id)",
]

CHUNK = 8 << 20


def blocks(fh, max_cik):
    """TSV 본문을 바이트 덩어리로 내보낸다. 헤더 한 줄은 버린다.

    max_cik이 있으면 각 줄의 첫 필드(CIK)를 보고 그 이상이 나오면 끊는다.
    파일이 CIK 오름차순이라 조기 종료가 가능하다. elmt.tsv는 CIK 컬럼이
    없으므로 호출부에서 max_cik을 넘기지 않는다.
    """
    fh.readline()  # header
    if max_cik is None:
        while chunk := fh.read(CHUNK):
            yield chunk
        return

    bound = max_cik.encode()
    tail = b""
    while chunk := fh.read(CHUNK):
        tail += chunk
        tail, _, rest = tail.rpartition(b"\n")
        if not tail:
            tail = rest
            continue
        keep = []
        for line in tail.split(b"\n"):
            if line[: line.find(b"\t")] >= bound:
                yield b"\n".join(keep) + b"\n" if keep else b""
                return
            keep.append(line)
        yield b"\n".join(keep) + b"\n"
        tail = rest


def load(conn, zf, name, period, max_cik):
    table, cols = TABLES[name]
    # period는 COPY 대상에서 빼고 기본값으로 채운다. 줄마다 파이썬으로
    # 컬럼을 붙이는 것보다 훨씬 빠르다.
    with conn.cursor() as cur:
        # ALTER TABLE은 placeholder를 못 받아 리터럴로 박는다. period는 main()에서
        # [A-Za-z0-9_]로 검증하므로 문자열 조립이 안전하다.
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN period SET DEFAULT '{period}'")
        cur.execute(f"DELETE FROM {table} WHERE period = %s", (period,))
        collist = ", ".join(cols)
        # QUOTE/ESCAPE를 데이터에 없는 바이트로 두어 따옴표·역슬래시를 글자 그대로 받는다.
        sql = (f"COPY {table} ({collist}) FROM STDIN "
               f"WITH (FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01', ESCAPE E'\\x01')")
        t0, n = time.time(), 0
        with cur.copy(sql) as cp, zf.open(name) as fh:
            for chunk in blocks(fh, max_cik):
                cp.write(chunk)
                n += len(chunk)
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN period DROP DEFAULT")
    conn.commit()
    print(f"  {name:12} -> {table:6} {n/1e6:8.1f} MB  {time.time()-t0:6.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip_path")
    ap.add_argument("--period", required=True, help="예: 2026_HY")
    ap.add_argument("--max-cik", help="이 CIK 이상은 건너뛴다 (스모크 테스트용)")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args()

    if not args.dsn:
        sys.exit("DATABASE_URL이 없습니다.")
    if not re.fullmatch(r"\w+", args.period):
        sys.exit("--period는 영숫자와 밑줄만 쓸 수 있습니다.")

    with psycopg.connect(args.dsn) as conn, zipfile.ZipFile(args.zip_path) as zf:
        missing = [n for n in TABLES if n not in zf.namelist()]
        if missing:
            sys.exit(f"zip에 없는 파일: {missing}")

        print(f"적재 시작: {args.period}", flush=True)
        for name in TABLES:
            # elmt.tsv에는 CIK 컬럼이 없어 회사 기준으로 자를 수 없다.
            load(conn, zf, name, args.period, None if name == "elmt.tsv" else args.max_cik)

        print("인덱스 생성 중...", flush=True)
        with conn.cursor() as cur:
            for stmt in INDEXES:
                t0 = time.time()
                cur.execute(stmt)
                print(f"  {stmt.split('ON ')[1]:32} {time.time()-t0:6.1f}s", flush=True)
            cur.execute("ANALYZE")
        conn.commit()
    print("완료", flush=True)


if __name__ == "__main__":
    main()
