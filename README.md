# DART XBRL 주석 뷰어

금융감독원 OpenDART [주석 일괄다운로드](https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrlnote/main.do)
의 XBRL 주석 TSV 묶음을 Postgres에 적재하고, 회사 · 주석 목차별 **표시(presentation) 트리와 표**로
보여주는 웹 뷰어입니다. 대시보드 레이아웃(상단바 + 좌측 목차 트리 + 우측 표)에
"사업자 검색" 팝업으로 회사를 고르는 구조입니다.

## 구성

```
web (nginx :8080)  →  /api/*  →  api (FastAPI)  →  db (Postgres 16)
   정적 HTML/JS                    읽기 전용 조회       주석 택사노미
```

컨테이너 3개. 프론트엔드는 빌드 단계가 없는 정적 HTML + 바닐라 JS라 nginx가 그대로 서빙합니다.

## 프론트엔드 파일

프론트엔드는 `web/` 폴더의 파일 3개가 전부입니다. 프레임워크·npm·번들러 없이 파일 하나가 화면 전체입니다.

| 파일 | 역할 |
|---|---|
| `web/index.html` | 화면 전체. CSS(`<style>`), 마크업, JS(`<script>`)가 한 파일에 있습니다 |
| `web/nginx.conf` | `/`는 `index.html`을 서빙(`no-cache`), `/api/*`는 FastAPI(`api:8000`)로 프록시 |
| `web/check_note.cjs` | `index.html`의 표 렌더링 함수를 꺼내 돌리는 Node 자가 점검 (`node web/check_note.cjs`) |

`web/index.html` 안의 구성:

| 영역 | 마크업 | 담당 함수 | 호출 API |
|---|---|---|---|
| 상단바 (보고서 기간, 사업자 검색 버튼, 선택 회사) | `header.topbar` | `init`, `loadCompanies` | `/periods`, `/companies` |
| 통계 카드 (회사 수, 보고서 수, 기준일) | `.stats` | `loadStats` | `/stats` |
| 사업자 검색 팝업 | `#searchOverlay` | `openSearch`, `closeSearch`, `renderResults`, `selectCompany` | `/roles` |
| 좌측 목차 트리 (한글/영문 라벨 전환) | `#side`, `#toc` | `drawToc`, `groupOf` | |
| 우측 본문·주석 표 | `#pane` | `showRole`, `stmtCard`, `noteCard`, `gridTable`, `textBox`, `axisInfo`, `foldInstants` | `/tree/{회사}/{목차}`, `/table/{회사}/{목차}` |
| 우측 기초 정보 (D999xxx 보고서정보) | `#pane` | `showInfo`, `structTable` | `/table/...` |

공통 헬퍼: `api`(`/api` 호출 래퍼), `esc`(HTML 이스케이프), `cell`(숫자 서식), `periodName`(컨텍스트 → 기간 이름).

## 실행

1. OpenDART에 로그인해 **재무정보 다운로드 → 주석 일괄다운로드**에서 원하는 보고서 zip을
   받아 `data/`에 둡니다. (로그인이 필요해 자동 다운로드는 불가능합니다.)

2. ```bash
   docker compose up -d --build
   docker compose run --rm --entrypoint python api \
       load_notes.py /data/2026_2Q_20260912010317.zip --period 2026_HY
   ```

3. http://localhost:8080 접속.
   다른 장비에서 IP로 붙으려면 `HTTP_PORT=80 docker compose up -d` 후 `http://<서버IP>/`.

처음 설치하는 사람을 위한 화면별 캡처 없는 상세 순서와, 왜 PostgreSQL을
쓰는지·회사명 검색을 확장하려면 스키마를 어떻게 바꾸는지는 [DB_GUIDE.md](DB_GUIDE.md)에
정리했습니다.

`--period`는 화면 좌상단 드롭다운에 그대로 뜨는 라벨입니다. 여러 보고서를 각각 다른
`--period`로 적재하면 한 DB에서 같이 조회됩니다. 같은 `--period`로 다시 넣으면 덮어씁니다.

스모크 테스트로 앞쪽 회사만 넣으려면 `--max-cik 00130000` (약 330개사, 1분).

## 적재되는 것

zip 안 TSV 11개 중 트리와 표에 필요한 8개만 넣습니다.

| 파일 | 테이블 | 쓰임 |
|---|---|---|
| `sub.tsv` | `sub` | 제출 회사 (CIK = DART corp_code) |
| `role.tsv` | `role_` | 주석 목차. `[D822380] 25. 재무위험관리` |
| `pre.tsv` | `pre` | 표시 링크베이스 → 좌측 트리, 표의 행 순서 |
| `def.tsv` | `def` | 정의 링크베이스 → 주석 안 표마다의 축·멤버(열) |
| `elmt.tsv` | `elmt` | 요소 속성 (dataType, periodType, balance) |
| `lab.tsv` | `lab` | 한/영 라벨 |
| `cntxt.tsv` | `cntxt` | 컨텍스트(축·멤버·기간) → 표의 열 |
| `val.tsv` | `val` | 값 → 표의 셀 |

`cal` `txn` `txn-dts`는 계산 링크베이스와 DTS라 이 뷰어에서 안 씁니다.

이미 적재한 DB에 `def.tsv`만 추가하려면 (1GB, 1분 이내):
```bash
docker compose run --rm --entrypoint python api \
    load_notes.py /data/2026_2Q_20260912010317.zip --period 2026_HY --only def.tsv
```

## 구현하면서 걸린 것들

- **아크 override.** 확장 택사노미가 표준 택사노미의 아크를 덮어쓰면 `pre`에 같은
  (부모, 자식) 쌍이 두 번 들어옵니다. `PRIORITY`가 가장 큰 것만 남기고, 그게
  `prohibited`면 아크를 뺍니다. 안 하면 트리에 같은 가지가 두 번 납니다.
- **노드 공유 금지.** 같은 요소가 부모를 달리해 여러 번 나올 수 있어서 아크마다
  노드를 새로 만들어야 합니다. 객체를 공유하면 서브트리가 중복 전개됩니다
  (`test_tree.py`가 이걸 잡습니다).
- **무차원 컨텍스트.** `cntxt.tsv`에는 축·멤버가 붙은 컨텍스트만 있습니다. `CFY2026dHYA`
  같은 무차원 컨텍스트의 기간은, 차원 있는 컨텍스트에서 접두어별 기간을 뽑아 역산합니다.
- **표 쪼개기.** 주석 목차 하나에 표가 여러 개 들어있어 전부 한 표로 합치면 열이
  수십 개인 성긴 표가 됩니다. `[항목]`(LineItems)마다 표를 나누고, 열은 그 표에
  값이 실제로 있는 컨텍스트만 씁니다.

- **목차 묶기.** 목차 코드 `D` + 6자리 중 `D999xxx`는 보고서정보(기초 정보 한 페이지로 모음),
  `D2`~`D7`은 본문, `D8`은 주석이고 끝자리 `0`이 연결, `5`가 별도입니다.
- **표마다 하이퍼큐브로 값 거르기.** 재고자산 같은 요소는 본문과 주석 양쪽에, 금융자산은 한 주석의
  여러 표에 값이 있어 요소로만 모으면 남의 컨텍스트 열이 섞입니다. 주석 안 표마다 정의 링크베이스에
  하위 목차(`role-D822390a`, `b`…)가 있고 거기 그 표의 축·멤버가 있습니다. 컨텍스트의 축·멤버가
  전부 그 표의 하이퍼큐브에 있을 때만 그 표 값으로 씁니다. 표시 트리는 같은 축 밑 멤버를 표끼리
  합쳐 버려서 이걸로는 못 가릅니다(`def`가 없으면 그걸로 대신합니다).
- **기초/기말 잔액.** 현금흐름표·변동표의 기초/기말 행은 시점(instant) 값입니다. 기간 열이 있는
  표에선 `periodStartLabel`이면 시작 전날, 아니면 종료일 시점 값을 그 기간 열로 옮깁니다.

- **상자 단위 배치.** KOX 뷰어처럼 주석 목차를 표시 순서대로 상자로 나눕니다. 표 상자는
  [문장영역] → [개요] → [표]·축 / [항목]이고, [항목] 밖의 각주 문장은 표가 아니라 제목+본문 상자로
  그 자리에 둡니다.
- **빠진 기말 행 복원.** DART `pre.tsv`는 (부모, 자식)이 같은 아크를 하나만 남겨, 변동표에서 같은
  요소를 쓰는 기초/기말 중 기말 아크가 빠집니다(앞쪽 330개사 기준 기초 10,816 vs 기말 1,730).
  기말 짝이 없는 기초 행이 있으면 형제 끝에 기말(periodEndLabel) 행을 붙입니다. 값은 `val`에 있습니다.
- **negated 라벨.** `negatedLabel`·`negatedTerseLabel` 등이 붙은 행은 부호를 뒤집어 보여줍니다
  (변동표의 감가상각비, 현금흐름표의 유출 등).

## 알려진 한계

- **한글 회사명은 따로 적재합니다.** 주석 TSV에는 영문 제출인명(`dart-gcd_EntityRegistrantName`)만
  있습니다. OpenDART API 키로 고유번호 zip을 받아 `company` 테이블에 넣으면 한글명으로 검색됩니다.
  안 넣으면 영문명으로만 검색됩니다.
  ```bash
  curl -o data/corpCode.zip "https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=<API키>"
  docker compose run --rm --entrypoint python api load_companies.py /data/corpCode.zip
  ```
- 전체 텍스트 검색은 없습니다. 회사 검색은 브라우저에서 합니다.
- 인증이 없습니다. 사내망 밖에 IP로 열지 마세요.

## 테스트

```bash
docker compose run --rm --entrypoint python --no-deps api test_tree.py
node web/check_note.cjs   # 주석 표 머리글·셀 병합
```

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `HTTP_PORT` | `8080` | nginx가 호스트에 노출할 포트 |
| `POSTGRES_PASSWORD` | `xbrl` | DB 비밀번호 |

`data/`와 `*.zip`은 `.gitignore` 대상입니다. DART 원본 파일은 레포에 커밋하지 않습니다.
