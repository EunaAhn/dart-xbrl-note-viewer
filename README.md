# DART XBRL 주석 뷰어

금융감독원 OpenDART [주석 일괄다운로드](https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrlnote/main.do)
의 XBRL 주석 TSV 묶음을 Postgres에 적재하고, 회사 · 주석 목차별 **표시(presentation) 트리와 표**로
보여주는 웹 뷰어입니다. UI는 `reference-xbrl.invector.co`의 트리 뷰어 레이아웃을 참고했습니다.

## 구성

```
web (nginx :8080)  →  /api/*  →  api (FastAPI)  →  db (Postgres 16)
   정적 HTML/JS                    읽기 전용 조회       주석 택사노미
```

컨테이너 3개. 프론트엔드는 빌드 단계가 없는 정적 HTML + 바닐라 JS라 nginx가 그대로 서빙합니다.

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

`--period`는 화면 좌상단 드롭다운에 그대로 뜨는 라벨입니다. 여러 보고서를 각각 다른
`--period`로 적재하면 한 DB에서 같이 조회됩니다. 같은 `--period`로 다시 넣으면 덮어씁니다.

스모크 테스트로 앞쪽 회사만 넣으려면 `--max-cik 00130000` (약 330개사, 1분).

## 적재되는 것

zip 안 TSV 11개 중 트리와 표에 필요한 7개만 넣습니다.

| 파일 | 테이블 | 쓰임 |
|---|---|---|
| `sub.tsv` | `sub` | 제출 회사 (CIK = DART corp_code) |
| `role.tsv` | `role_` | 주석 목차. `[D822380] 25. 재무위험관리` |
| `pre.tsv` | `pre` | 표시 링크베이스 → 좌측 트리, 표의 행 순서 |
| `elmt.tsv` | `elmt` | 요소 속성 (dataType, periodType, balance) |
| `lab.tsv` | `lab` | 한/영 라벨 |
| `cntxt.tsv` | `cntxt` | 컨텍스트(축·멤버·기간) → 표의 열 |
| `val.tsv` | `val` | 값 → 표의 셀 |

`def` `cal` `txn` `txn-dts`는 정의·계산 링크베이스와 DTS라 이 뷰어에서 안 씁니다(2.2GB 절약).

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

## 알려진 한계

- **회사명이 영문입니다.** `sub.tsv`에 회사명이 없어 `dart-gcd_EntityRegistrantName`을
  씁니다. 한글명을 쓰려면 OpenDART API 키로 `corpCode.xml`을 받아 CIK에 조인해야 합니다.
  (일부 회사는 이 칸에 주소를 적어 낸 제출 오류가 있습니다.)
- 전체 텍스트 검색은 없습니다. 회사 검색은 브라우저 `<datalist>`로 클라이언트에서 합니다.
- 인증이 없습니다. 사내망 밖에 IP로 열지 마세요.

## 테스트

```bash
docker compose run --rm --entrypoint python --no-deps api test_tree.py
```

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `HTTP_PORT` | `8080` | nginx가 호스트에 노출할 포트 |
| `POSTGRES_PASSWORD` | `xbrl` | DB 비밀번호 |

`data/`와 `*.zip`은 `.gitignore` 대상입니다. DART 원본 파일은 레포에 커밋하지 않습니다.
