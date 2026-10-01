# DB 선택 가이드 & 처음 설치하는 법

이 프로젝트는 "회사마다 자기 컴퓨터에 깃허브 코드를 받아 자기 DB에 데이터를 넣고
혼자 쓴다"는 전제로 만들어져 있습니다. 서버 한 대를 여럿이 공유하는 구조가
아니라, **각자 로컬(또는 사내 PC)에서 완전히 독립된 스택 하나씩**을 띄웁니다.
그래서 DB도 "가볍게 설치되고, 이 프로젝트의 조회 패턴에 잘 맞는 것"이 기준입니다.

## 1. 왜 PostgreSQL인가

| 후보 | 이 프로젝트에 맞는가 |
|---|---|
| **PostgreSQL** (채택) | 됨. `ANY(array)` 배치 조회, `COPY`로 8GB급 TSV를 수 분 내 적재, `DISTINCT ON` 같은 표시-링크베이스 중복 제거에 딱 맞는 문법을 제공. Docker 한 줄로 뜨고 회사 PC 한 대 분량 리소스로 충분. |
| SQLite | 파일 하나라 배포는 더 쉽지만, `COPY` 같은 대량 적재 경로가 없어 8GB TSV 적재가 훨씬 느리고, 동시 쓰기·복잡한 배열 조회(`ANY`)가 약함. 표 하나 조회에 여러 조인이 필요한 이 구조엔 안 맞음. |
| MySQL/MariaDB | 가능은 하지만 배열 파라미터(`ANY(%s)`)나 `DISTINCT ON`이 없어 지금 API 코드(`api/main.py`)를 상당 부분 다시 짜야 함. 얻는 이득이 없음. |
| DuckDB | 분석 쿼리는 빠르지만 동시 다중 커넥션 API 서버(psycopg_pool) 용도가 아니라 "붙여서 조회하는 웹앱" 그림과 안 맞음. |
| MongoDB | 이 데이터는 회사·기간·요소·컨텍스트가 서로 강하게 관계된 정형 데이터라 조인이 핵심. 문서형 DB로 가면 트리·표 조립 로직을 다 애플리케이션 레벨로 옮겨야 해서 오히려 복잡해짐. |

결론: **바꿀 이유가 없다.** 이미 `docker-compose.yml`에 있는 `postgres:16-alpine`을
그대로 씁니다. 설치도 `docker compose up` 한 줄, 회사 컴퓨터 한 대 감당 못 할 사양이
아닙니다.

## 2. 스키마 설계 — 조회에 맞춘 이유

`api/schema.sql`의 7개 테이블은 이미 "표 하나를 그리는 데 필요한 조회"를 기준으로
쪼개져 있습니다. 핵심 설계 포인트:

- **모든 테이블에 `period` 컬럼.** 여러 보고서(분기·반기·연간)를 한 DB에 같이
  적재하고, `WHERE period = %s`로만 갈라 봅니다. 보고서마다 DB를 새로 만들 필요가
  없습니다.
- **조회 키는 항상 `(period, cik, ...)` 순서.** 실제 API 코드도 항상 이 순서로
  `WHERE`를 겁니다. 그래서 인덱스도 이 순서로 만듭니다 (`load_notes.py`의
  `INDEXES` 참고). 인덱스 컬럼 순서가 조회 조건 순서와 다르면 인덱스를 못 탑니다.
- **인덱스는 적재 후 생성.** `COPY`로 수백만 행을 넣을 때 인덱스가 미리 있으면
  몇 배 느려집니다. `load_notes.py`가 적재 → `ANALYZE` 순서를 지키는 이유입니다.
- **`val`(값) 테이블에 인덱스 2개**: `(period, cik, element_id)`와
  `(period, cik, context_id)`. 트리 클릭 시 "이 요소의 값"과 "이 표의 컨텍스트
  전체" 양쪽으로 다 조회하기 때문에 각각 필요합니다.

### 지금 당장은 안 넣은 것 (회사명 검색용 `company` 테이블)

팝업 "사업자 검색"은 지금 `/api/companies`가 돌려주는 목록(회사당 한 줄, 보통
수천 건)을 브라우저 메모리에서 필터링합니다. 이 규모에서는 DB 인덱스가 필요
없습니다 — 굳이 넣으면 안 쓰는 인덱스만 하나 늘어납니다 (YAGNI).

다만 아래 두 가지가 **실제로 문제가 되면** 이렇게 확장하세요:

1. **회사명이 영문이라 검색이 불편하다** → OpenDART API 키로 `corpCode.xml`을
   받아 다음 테이블을 추가하고 `sub.cik`에 조인:

   ```sql
   CREATE TABLE company (
       cik         text PRIMARY KEY,   -- corp_code
       corp_name   text NOT NULL,      -- 한글명
       corp_eng_name text,
       stock_code  text
   );
   CREATE INDEX company_name_trgm ON company USING gin (corp_name gin_trgm_ops);
   ```
   (`CREATE EXTENSION pg_trgm;` 먼저 필요) — 이러면 `ILIKE '%삼성%'` 같은 부분
   일치 검색도 인덱스를 탑니다. `/api/companies`가 `sub`와 `company`를 조인하도록
   한 줄만 고치면 됩니다.

2. **회사 수가 수만 건으로 늘어나 브라우저 필터링이 느려진다** → 팝업 입력을
   `/api/companies?q=검색어`로 서버 조회하게 바꾸고, 위 트라이그램 인덱스로
   받쳐줍니다.

지금 규모(회사당 한 페이지 응답, 클라이언트 필터)에서는 둘 다 불필요합니다.

## 3. 처음 쓰는 사람이 사이트를 열기까지

회사 컴퓨터에서 처음부터 끝까지 따라 하는 순서입니다. 터미널(명령 프롬프트)
사용이 처음이어도 그대로 복사해서 붙여넣으면 됩니다.

### 준비물

1. **Docker Desktop** 설치: <https://www.docker.com/products/docker-desktop/>
   에서 Windows/Mac용을 받아 설치하고 실행합니다. (설치 후 재부팅을 요구할 수
   있습니다.) 실행되면 작업표시줄/메뉴바에 고래 아이콘이 뜹니다 — 이게 켜져
   있어야 아래 명령이 동작합니다.
2. **DART 주석 일괄다운로드 zip**: <https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrlnote/main.do>
   에 로그인 후 원하는 보고서(예: 2026년 반기)의 zip을 내려받습니다. (로그인이
   필요해 자동화가 안 되는 유일한 수동 단계입니다.)

### 설치 단계

1. **코드 받기.** GitHub 저장소 페이지에서 `Code → Download ZIP`으로 받아
   원하는 폴더에 풀거나, 터미널에서:
   ```bash
   git clone <이 저장소 URL>
   cd dart-xbrl-note-viewer
   ```
2. **DART zip을 `data/` 폴더에 넣기.** 1번에서 받은 zip 파일을
   `dart-xbrl-note-viewer/data/` 안에 그대로 복사합니다. (`data/` 폴더가 없으면
   만듭니다.)
3. **컨테이너 띄우기** (DB + API + 웹서버 3개가 한 번에 뜹니다):
   ```bash
   docker compose up -d --build
   ```
   처음 실행이면 이미지를 내려받느라 몇 분 걸립니다.
4. **zip을 DB에 적재** (zip 파일명은 실제로 받은 이름으로 바꾸세요):
   ```bash
   docker compose run --rm --entrypoint python api \
       load_notes.py /data/2026_2Q_20260912010317.zip --period 2026_HY
   ```
   보고서 하나 적재에 수 분~수십 분 걸립니다(진행 로그가 파일별로 뜹니다).
   빠르게 동작만 확인하고 싶으면 `--max-cik 00130000`을 붙여 앞쪽 330개사만
   넣어보세요(약 1분).
5. **브라우저 열기.** <http://localhost:8080> 접속. 상단에서 기간을 고르고
   "🔍 사업자 검색" 버튼으로 회사를 찾으면 왼쪽에 주석 목차, 오른쪽에 표가
   뜹니다.

### 다른 사람 컴퓨터에서도 그대로

각 팀원이 위 1~5단계를 자기 컴퓨터에서 그대로 반복하면, 각자 자기 PC 안에서
완전히 독립된 Postgres에 데이터가 들어가고 자기 브라우저로만 조회합니다. 서버
한 대를 공유하지 않으므로 DB 계정이나 방화벽 설정을 조율할 필요가 없습니다 —
그만큼 "내 데이터가 남의 PC에 노출될 걱정"도 없습니다.

### 자주 막히는 지점

- `docker compose up`이 "Cannot connect to the Docker daemon"라고 하면 Docker
  Desktop이 꺼져 있는 것입니다. 아이콘을 눌러 실행부터 하세요.
- 적재 명령에서 `zip에 없는 파일: [...]`이 뜨면 DART에서 받은 zip이 아니거나
  손상된 것입니다. 다시 받으세요.
- 포트 8080이 이미 쓰이고 있다면 `HTTP_PORT=8081 docker compose up -d`처럼
  다른 포트를 지정하세요.
- 다시 시작할 땐 `docker compose up -d`만 실행하면 됩니다(데이터는 Docker
  볼륨에 남아 있어 재적재가 필요 없습니다). 데이터를 완전히 지우고 싶을 때만
  `docker compose down -v`를 씁니다.
