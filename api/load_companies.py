#!/usr/bin/env python3
"""OpenDART 고유번호 파일(corpCode.xml)을 company 테이블에 넣는다. 한글 회사명 검색용.

    python load_companies.py /data/corpCode.zip

파일은 https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=<API키> 로 받은 zip
그대로, 또는 그 안의 CORPCODE.xml을 줘도 된다. 매번 전체를 갈아끼운다.
"""
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

import psycopg


def rows(path):
    fh = zipfile.ZipFile(path).open("CORPCODE.xml") if zipfile.is_zipfile(path) else open(path, "rb")
    with fh:
        for e in ET.parse(fh).getroot().iter("list"):
            get = lambda tag: (e.findtext(tag) or "").strip() or None
            yield get("corp_code"), get("corp_name"), get("corp_eng_name"), get("stock_code")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data = [r for r in rows(sys.argv[1]) if r[0] and r[1]]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE company")
        with cur.copy("COPY company (cik, corp_name, corp_eng_name, stock_code) FROM STDIN") as cp:
            for r in data:
                cp.write_row(r)
    print(f"회사 {len(data)}건 적재")


if __name__ == "__main__":
    main()
