# DART XBRL 주석 뷰어

금융감독원 OpenDART [주석 일괄다운로드](https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrlnote/main.do)
의 XBRL 주석 TSV 묶음을 Postgres에 적재하고, 회사 · 주석 목차별 **표시(presentation) 트리와 표**로
보여주는 웹 뷰어입니다. UI는 `reference-xbrl.invector.co`의 트리 뷰어 레이아웃을 참고했습니다.

## 구성

```
web (nginx)  →  /api/*  →  api (FastAPI)  →  db (Postgres 16)
   정적 HTML/JS              읽기 전용 조회        주석 택사노미
```

컨테이너 3개. 프론트엔드는 빌드 단계가 없는 정적 HTML + 바닐라 JS라 nginx가 그대로 서빙합니다.

## 실행

1. OpenDART에 로그인해 **주석 일괄다운로드 → 2026 반기보고서** zip을 받아 `data/`에 둡니다.
   (로그인이 필요해 자동 다운로드는 불가능합니다.)

2. ```bash
   docker compose up -d --build
   docker compose exec api python load_notes.py /data/2026_2Q_*.zip --period 2026_HY
   ```

3. http://localhost:8080 접속. 다른 장비에서 IP로 접근하려면 `HTTP_PORT=80 docker compose up -d`
   후 `http://<서버IP>/`.

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `HTTP_PORT` | `8080` | nginx가 호스트에 노출할 포트 |
| `POSTGRES_PASSWORD` | `xbrl` | DB 비밀번호 |

## 데이터

`data/`와 `*.zip`은 `.gitignore` 대상입니다. DART 원본 파일은 레포에 커밋하지 않습니다.
