-- DART 주석 일괄다운로드 TSV를 그대로 받는 테이블.
-- 컬럼명은 TSV 헤더를 소문자로 옮긴 것이고, order/use는 예약어라 ord/use_로 바꿨다.
-- period(2026_HY 등)를 붙여 여러 보고서를 한 DB에 담는다.

CREATE TABLE IF NOT EXISTS sub (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    submission_datetime text,
    taxonomy_id text
);

CREATE TABLE IF NOT EXISTS role_ (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    taxonomy_id text,
    role_id     text,
    role_uri    text,
    role_nm_ko  text,
    role_nm_en  text
);

-- elmt.tsv는 CIK가 없다. 전 회사 택사노미의 합집합이라 period로만 구분한다.
CREATE TABLE IF NOT EXISTS elmt (
    period      text NOT NULL,
    element_id  text,
    taxonomy_id text,
    element_name text,
    data_type   text,
    substitution_group text,
    period_type text,
    balance     text,
    nillable    text,
    abstract    text
);

CREATE TABLE IF NOT EXISTS pre (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    role_id     text,
    element_id  text,
    taxonomy_id text,
    parent_element_id text,
    parent_taxonomy_id text,
    arcrole     text,
    ord         text,
    use_        text,
    priority    text,
    preferredlabel text
);

-- 정의 링크베이스. 한 주석 목차 안의 표마다 하위 목차(role-D822390a, b…)가 있고
-- 거기에 그 표의 축·멤버(하이퍼큐브)가 있다. 표시 링크베이스만으론 표끼리 멤버가 섞인다.
CREATE TABLE IF NOT EXISTS def (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    role_id     text,
    element_id  text,
    taxonomy_id text,
    parent_element_id text,
    parent_taxonomy_id text,
    arcrole     text,
    ord         text,
    use_        text,
    priority    text
);

CREATE TABLE IF NOT EXISTS lab (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    label_role_uri text,
    elmt_id     text,
    taxonomy_id text,
    lang        text,
    label       text
);

CREATE TABLE IF NOT EXISTS cntxt (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    context_id  text,
    axis_element_id text,
    axis_taxonomy_id text,
    member_element_id text,
    member_taxonomy_id text,
    dimension   text,
    period_start_date text,
    period_end_date text,
    period_instant text
);

CREATE TABLE IF NOT EXISTS val (
    period      text NOT NULL,
    cik         text NOT NULL,
    report_date text,
    element_id  text,
    taxonomy_id text,
    context_id  text,
    unit_id     text,
    decimals    text,
    value       text
);

-- OpenDART corpCode.xml (load_companies.py). 주석 TSV에는 한글 회사명이 없다.
-- ponytail: 수천 건이라 검색은 브라우저에서 한다. 서버 검색이 필요해지면 pg_trgm 인덱스(DB_GUIDE.md).
CREATE TABLE IF NOT EXISTS company (
    cik         text PRIMARY KEY,
    corp_name   text NOT NULL,
    corp_eng_name text,
    stock_code  text
);

-- load_notes.py가 적재 전에 이 파일을 다시 돌리므로(새 테이블 추가용) 전부 IF NOT EXISTS다.
-- 인덱스는 적재가 끝난 뒤 loader가 만든다. COPY 중에 인덱스가 있으면 몇 배 느려진다.
