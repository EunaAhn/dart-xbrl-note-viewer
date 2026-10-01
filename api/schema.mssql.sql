-- DART 주석 일괄다운로드 TSV를 그대로 받는 테이블 (SQL Server용).
-- 컬럼명은 TSV 헤더를 소문자로 옮긴 것이고, order/use는 예약어라 ord/use_로 바꿨다.
-- period(2026_HY 등)를 붙여 여러 보고서를 한 DB에 담는다.
--
-- period·cik는 NVARCHAR(20)로 짧게 잡아 인덱스 키에 넣고, 그 밖의 값(label, value,
-- element_id 등)은 DART 확장 택사노미에서 길이가 수백~1400자까지 나와
-- SQL Server 인덱스 키 한도(1700바이트)를 넘길 수 있으므로 NVARCHAR(MAX)로 두고
-- 인덱스 키에서 뺐다. elmt만 예외: cik가 없어 period 하나로는 좁혀지지 않고
-- 테이블 자체가 (회사 수와 무관하게) 한 period에 수백만 행이라 element_id를
-- 반드시 인덱스에 넣어야 한다. 실측 최대 780자, (period 20 + element_id N)*2 <= 1700
-- 한도 안에서 800으로 여유를 뒀다
-- (그 이상 긴 element_id가 나오면 INSERT가 "index row size" 에러로 막히는데,
-- 그때는 ix_elmt를 period 전용으로 좁히고 로더가 애플리케이션에서 필터링하게
-- 바꿔야 한다 — 회사별 조회와 달리 elmt는 그 우회가 못 먹는다는 뜻).

CREATE TABLE sub (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    submission_datetime NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX)
);

CREATE TABLE role_ (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX),
    role_id     NVARCHAR(MAX),
    role_uri    NVARCHAR(MAX),
    role_nm_ko  NVARCHAR(MAX),
    role_nm_en  NVARCHAR(MAX)
);

-- elmt.tsv는 CIK가 없다. 전 회사 택사노미의 합집합이라 period로만 구분한다.
CREATE TABLE elmt (
    period      NVARCHAR(20) NOT NULL,
    element_id  NVARCHAR(800),
    taxonomy_id NVARCHAR(MAX),
    element_name NVARCHAR(MAX),
    data_type   NVARCHAR(MAX),
    substitution_group NVARCHAR(MAX),
    period_type NVARCHAR(MAX),
    balance     NVARCHAR(MAX),
    nillable    NVARCHAR(MAX),
    abstract    NVARCHAR(MAX)
);

CREATE TABLE pre (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    role_id     NVARCHAR(MAX),
    element_id  NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX),
    parent_element_id NVARCHAR(MAX),
    parent_taxonomy_id NVARCHAR(MAX),
    arcrole     NVARCHAR(MAX),
    ord         NVARCHAR(MAX),
    use_        NVARCHAR(MAX),
    priority    NVARCHAR(MAX),
    preferredlabel NVARCHAR(MAX)
);

-- 정의 링크베이스. 주석 안 표마다(role-D822390a, b…) 그 표의 축·멤버가 있다.
CREATE TABLE def (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    role_id     NVARCHAR(MAX),
    element_id  NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX),
    parent_element_id NVARCHAR(MAX),
    parent_taxonomy_id NVARCHAR(MAX),
    arcrole     NVARCHAR(MAX),
    ord         NVARCHAR(MAX),
    use_        NVARCHAR(MAX),
    priority    NVARCHAR(MAX)
);

CREATE TABLE lab (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    label_role_uri NVARCHAR(MAX),
    elmt_id     NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX),
    lang        NVARCHAR(MAX),
    label       NVARCHAR(MAX)
);

CREATE TABLE cntxt (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    context_id  NVARCHAR(MAX),
    axis_element_id NVARCHAR(MAX),
    axis_taxonomy_id NVARCHAR(MAX),
    member_element_id NVARCHAR(MAX),
    member_taxonomy_id NVARCHAR(MAX),
    dimension   NVARCHAR(MAX),
    period_start_date NVARCHAR(MAX),
    period_end_date NVARCHAR(MAX),
    period_instant NVARCHAR(MAX)
);

CREATE TABLE val (
    period      NVARCHAR(20) NOT NULL,
    cik         NVARCHAR(20) NOT NULL,
    report_date NVARCHAR(MAX),
    element_id  NVARCHAR(MAX),
    taxonomy_id NVARCHAR(MAX),
    context_id  NVARCHAR(MAX),
    unit_id     NVARCHAR(MAX),
    decimals    NVARCHAR(MAX),
    value       NVARCHAR(MAX)
);

-- 인덱스는 적재 후 loader가 만든다. 대량 INSERT 중에 인덱스가 있으면 훨씬
-- 느려진다. sub/role_/pre/lab/cntxt/val은 회사(period, cik) 단위 조회만 하고
-- 그 조각이 많아야 수만 행이라(api/main.py 참고) element_id·context_id까지
-- 인덱스에 넣지 않아도 충분히 빠르다. elmt만 전체가 수백만 행이라 element_id를
-- 반드시 포함해야 한다.
