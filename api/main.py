"""DART XBRL 주석 조회 API.

표시(presentation) 링크베이스로 트리를 만들고, 컨텍스트를 열·요소를 행으로 놓아
주석 표를 만든다.
"""
import os
import re
from collections import defaultdict

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

STD_LABEL = "http://www.xbrl.org/2003/role/label"
PERIOD_START = "http://www.xbrl.org/2003/role/periodStartLabel"
PERIOD_END = "http://www.xbrl.org/2003/role/periodEndLabel"

pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=8,
                      kwargs={"row_factory": dict_row}, open=False)

app = FastAPI(title="DART XBRL 주석 뷰어")


@app.on_event("startup")
def _open_pool():
    pool.open()


def q(sql, params=()):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@app.get("/api/periods")
def periods():
    return [r["period"] for r in q("SELECT DISTINCT period FROM sub ORDER BY period DESC")]


@app.get("/api/stats")
def stats():
    """대시보드 상단 요약 카드용 전체 적재 현황 (기간 무관)."""
    r = q("""
        SELECT count(*) AS report_count, count(DISTINCT cik) AS company_count,
               max(report_date) AS last_report_date
        FROM sub
    """)[0]
    d = r["last_report_date"]
    return r | {"last_report_date": f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else None}


@app.get("/api/companies")
def companies(period: str):
    # 한글명은 company(load_companies.py로 적재)에서, 없으면 XBRL의 영문 제출인명으로.
    return q("""
        SELECT s.cik AS corp_code, COALESCE(c.corp_name, v.value, s.cik) AS name, s.report_date,
               COALESCE(c.corp_eng_name, v.value) AS eng_name, c.stock_code
        FROM sub s
        LEFT JOIN company c ON c.cik = s.cik
        LEFT JOIN val v ON v.period = s.period AND v.cik = s.cik
                       AND v.element_id = 'dart-gcd_EntityRegistrantName'
        WHERE s.period = %s
        ORDER BY 2
    """, (period, ))


@app.get("/api/roles")
def roles(cik: str, period: str):
    """주석 목차. ROLE_NM_KO가 '[D822380] 25. 재무위험관리' 꼴인 것만 목차로 쓴다.

    대괄호가 없는 role-D822380a 같은 것들은 한 주석 안의 하위 표라서 목차에
    올리지 않는다.
    """
    return q("""
        SELECT DISTINCT role_id AS id, role_nm_ko AS ko, role_nm_en AS en
        FROM role_
        WHERE period = %s AND cik = %s AND role_nm_ko LIKE '[%%'
        ORDER BY 1
    """, (period, cik))


def _pre_rows(period, cik, role_id):
    """역할 하나의 표시 링크 아크.

    XBRL 링크베이스 override 규칙에 따라 (부모, 자식)이 같은 아크가 여러 개면
    PRIORITY가 가장 큰 것만 살리고, 그게 prohibited면 아크 자체를 뺀다. 같은 부모 밑 같은
    요소라도 preferredLabel이 다르면(변동표의 기초/기말 행) 다른 아크라서 키에 넣는다.
    이걸 안 하면 확장 택사노미가 덮어쓴 아크가 원본과 함께 두 번 나온다.
    """
    rows = q("""
        SELECT DISTINCT ON (p.parent_element_id, p.element_id, p.preferredlabel)
               p.element_id, p.parent_element_id, p.preferredlabel, p.use_,
               NULLIF(p.ord, '')::float AS ord,
               e.abstract, e.period_type, e.balance, e.data_type
        FROM pre p
        LEFT JOIN elmt e ON e.period = p.period AND e.element_id = p.element_id
        WHERE p.period = %s AND p.cik = %s AND p.role_id = %s
        ORDER BY p.parent_element_id, p.element_id, p.preferredlabel,
                 NULLIF(p.priority, '')::int DESC NULLS LAST
    """, (period, cik, role_id))
    return [r for r in rows if r["use_"] != "prohibited"]


def _arcs(rows):
    """(루트 목록, 부모 -> 자식 목록). 자식은 order 순으로 정렬한다."""
    roots, children = [], defaultdict(list)
    for r in rows:
        (children[r["parent_element_id"]] if r["parent_element_id"] else roots).append(r)
    for group in (roots, *children.values()):
        group.sort(key=lambda r: (r["ord"] is None, r["ord"] or 0))
    return roots, children


def build_tree(rows, label):
    """표시 아크를 중첩 트리로 만든다.

    같은 요소가 부모를 달리해 여러 번 나올 수 있으므로 아크마다 노드를 새로
    만든다. 노드 객체를 공유하면 서브트리가 중복으로 붙는다. path는 순환 방어용.
    """
    roots, children = _arcs(rows)

    def build(r, path):
        eid = r["element_id"]
        return {
            "element_id": eid,
            "korean_label": label(r, "ko"),
            "english_label": label(r, "en"),
            "abstract": r["abstract"] == "true",
            # XBRL 구조 및 속성 표용: 기본(표준) 라벨과 표시 라벨 역할, 요소 속성.
            "korean_std": label({**r, "preferredlabel": None}, "ko"),
            "english_std": label({**r, "preferredlabel": None}, "en"),
            "label_role": (r["preferredlabel"] or STD_LABEL).rsplit("/", 1)[-1],
            "data_type": r.get("data_type"),
            "period_type": r.get("period_type"),
            "balance": r.get("balance"),
            "children": [] if eid in path else
                        [build(c, path | {eid}) for c in children[eid]],
        }

    return [build(r, frozenset()) for r in roots]


def _labels(period, cik, element_ids):
    """(element_id, label_role_uri, lang) -> label"""
    if not element_ids:
        return {}
    rows = q("""
        SELECT elmt_id, label_role_uri, lang, label FROM lab
        WHERE period = %s AND cik = %s AND elmt_id = ANY(%s)
    """, (period, cik, list(element_ids)))
    return {(r["elmt_id"], r["label_role_uri"], r["lang"]): r["label"] for r in rows}


def _label_of(labels, element_id, preferred, lang="ko"):
    """preferredLabel(기초/기말 등)이 있으면 그걸, 없으면 표준 라벨을 쓴다."""
    for role in (preferred, STD_LABEL):
        if role and (hit := labels.get((element_id, role, lang))):
            return hit
    return element_id.split("_", 1)[-1]


@app.get("/api/tree/{cik}/{role_id:path}")
def tree(cik: str, role_id: str, period: str):
    rows = _pre_rows(period, cik, role_id)
    if not rows:
        raise HTTPException(404, "해당 주석 목차의 트리를 찾지 못했습니다.")
    labels = _labels(period, cik, {r["element_id"] for r in rows})
    return build_tree(rows, lambda r, lang: _label_of(
        labels, r["element_id"], r["preferredlabel"], lang))


def _context_periods(period, cik):
    """컨텍스트 ID -> 사람이 읽을 기간 문자열.

    cntxt.tsv에는 축·멤버가 붙은 컨텍스트만 있고 무차원 컨텍스트(CFY2026dHYA 등)는
    없다. 다만 기간은 ID의 접두어가 결정하므로, 차원 있는 컨텍스트에서 접두어별
    기간을 뽑아 무차원 쪽에도 그대로 적용한다.
    """
    rows = q("""
        SELECT DISTINCT split_part(context_id, '_', 1) AS pk,
               period_start_date, period_end_date, period_instant
        FROM cntxt WHERE period = %s AND cik = %s
    """, (period, cik))
    out = {}
    for r in rows:
        if r["period_instant"]:
            out[r["pk"]] = (r["period_instant"], r["period_instant"])
        elif r["period_end_date"]:
            out[r["pk"]] = (r["period_start_date"], r["period_end_date"])
    return out


def hypercube(rows):
    """축 -> 그 축 밑에 걸린 멤버 집합. 이 목차 표시 트리에 있는 차원만."""
    _, children = _arcs(rows)

    def under(eid, path):
        for c in children[eid]:
            m = c["element_id"]
            if m not in path:
                yield m
                yield from under(m, path | {m})

    return {r["element_id"]: set(under(r["element_id"], frozenset()))
            for r in rows if r["element_id"].endswith("Axis")}


def def_cubes(rows, role_id):
    """정의 링크베이스 아크 -> {[항목] 요소 ID: {축: 멤버 집합}}. 목차 자체의 큐브는 None 키.

    주석 목차 하나에 표가 여럿이면 표마다 하위 목차(role-D822390a, b…)가 있고, 거기서
    [표]에 hypercube-dimension으로 축이, 축 밑에 domain-member로 멤버가 걸린다.
    표시 트리는 같은 축 밑 멤버를 표끼리 합쳐 버려서, 이걸 봐야 표마다 열이 갈린다.
    """
    by_role = defaultdict(list)
    for r in rows:
        sub = r["role_id"][len(role_id):]
        if r["role_id"].startswith(role_id) and (sub == "" or sub.isalpha() and sub.islower()):
            by_role[sub].append(r)

    out = {}
    for sub, arcs in by_role.items():
        children = defaultdict(list)
        for a in arcs:
            children[a["parent_element_id"]].append(a["element_id"])

        def under(eid, path):
            for m in children[eid]:
                if m not in path:
                    yield m
                    yield from under(m, path | {m})

        cube = {a["element_id"]: set(under(a["element_id"], frozenset()))
                for a in arcs if (a["arcrole"] or "").endswith("hypercube-dimension")}
        for a in arcs:
            if a["element_id"].endswith("LineItems"):
                out[a["element_id"]] = cube
        if sub == "":
            out[None] = cube
    return out


def _def_cubes(period, cik, role_id):
    try:
        rows = q("""
            SELECT DISTINCT ON (role_id, parent_element_id, element_id)
                   role_id, element_id, parent_element_id, arcrole, use_
            FROM def
            WHERE period = %s AND cik = %s AND role_id LIKE %s
            ORDER BY role_id, parent_element_id, element_id,
                     NULLIF(priority, '')::int DESC NULLS LAST
        """, (period, cik, role_id + "%"))
    except psycopg.errors.UndefinedTable:
        return {}  # def.tsv를 아직 적재 안 한 DB. 표시 트리 기준 큐브로 대신한다.
    return def_cubes([r for r in rows if r["use_"] != "prohibited"], role_id)


def negate(cells):
    """negated*Label 행은 부호를 뒤집어 보여준다(감가상각비 등을 변동표에서 차감으로). XBRL 렌더링 규칙."""
    return {c: (v[1:] if v.startswith("-") else "-" + v) if re.fullmatch(r"-?\d+(\.\d+)?", v) and float(v) else v
            for c, v in cells.items()}


def missing_period_end(siblings):
    """기초 행만 있고 기말 행이 없는 요소에 기말 아크를 만들어 준다.

    DART pre.tsv는 (부모, 자식)이 같은 아크를 하나만 남겨서 변동표의 기초/기말 중
    기말 아크가 빠진다(같은 요소, preferredLabel만 다름). 값(val)은 그대로 있으니
    형제 끝에 기말 행을 붙인다. 원본 XBRL로 그리는 KOX 뷰어에는 이 행이 있다.
    """
    count = defaultdict(int)
    for c in siblings:
        count[c["element_id"]] += 1
    return [{**c, "preferredlabel": PERIOD_END} for c in siblings
            if c["preferredlabel"] == PERIOD_START and count[c["element_id"]] == 1]


def in_hypercube(dims, cube):
    """컨텍스트의 축·멤버가 전부 이 목차 트리에 있어야 이 목차의 값이다. 축이 없는 차원은 기본 멤버."""
    return all(d["member"] in cube.get(d["axis"], ()) for d in dims)


@app.get("/api/table/{cik}/{role_id:path}")
def table(cik: str, role_id: str, period: str, lang: str = "ko"):
    rows = _pre_rows(period, cik, role_id)
    if not rows:
        raise HTTPException(404, "해당 주석 목차의 표를 찾지 못했습니다.")

    element_ids = [r["element_id"] for r in rows]
    facts = q("""
        SELECT element_id, context_id, value, unit_id FROM val
        WHERE period = %s AND cik = %s AND element_id = ANY(%s)
    """, (period, cik, element_ids))
    if not facts:
        return {"roleTitle": role_id, "tables": [], "units": []}

    used = {f["context_id"] for f in facts}
    ctx_dims = defaultdict(list)
    for r in q("""
        SELECT context_id, axis_element_id, member_element_id FROM cntxt
        WHERE period = %s AND cik = %s AND context_id = ANY(%s)
    """, (period, cik, list(used))):
        ctx_dims[r["context_id"]].append(
            {"axis": r["axis_element_id"], "member": r["member_element_id"]})

    # 재고자산 같은 요소는 본문과 주석 양쪽에, 금융자산은 한 주석의 여러 표에 값이 있다.
    # 요소로만 값을 모으면 남의 컨텍스트가 섞여 열이 수십 개가 된다. 표([항목])마다 그 표의
    # 하이퍼큐브(정의 링크베이스, 없으면 표시 트리)에 맞는 컨텍스트만 쓴다.
    tree_cube = hypercube(rows)
    cubes = _def_cubes(period, cik, role_id)
    member_ids = {d["member"] for ds in ctx_dims.values() for d in ds}
    labels = _labels(period, cik, set(element_ids) | member_ids)
    periods_by_pk = _context_periods(period, cik)

    cells = defaultdict(dict)
    for f in facts:
        cells[f["element_id"]][f["context_id"]] = (f["value"], f["unit_id"])
    units = set()

    def cells_in(eid, cube):
        out = {}
        for ctx, (v, unit) in cells.get(eid, {}).items():
            if in_hypercube(ctx_dims.get(ctx, []), cube):
                out[ctx] = v
                if unit:
                    units.add(unit)
        return out

    def column(ctx):
        start, end = periods_by_pk.get(ctx.split("_", 1)[0], ("", ""))
        return {
            "contextId": ctx,
            "period": end if start == end else f"{start} ~ {end}",
            "members": [_label_of(labels, d["member"], None, lang) for d in ctx_dims.get(ctx, [])],
            "dims": ctx_dims.get(ctx, []),
            "_sort": (end or "", start or "", ctx),
        }

    # 하나의 주석 목차에 표가 여러 개 들어있다. 전부 한 표로 합치면 열이 수십 개인
    # 성긴 표가 되므로 [항목](LineItems)마다 표를 나눈다. 열은 그 표에 실제로 값이
    # 있는 컨텍스트만 쓴다.
    # KOX처럼 목차를 표시 순서대로 상자(표 또는 [항목] 밖 주석 문장)로 나눈다. [항목] 밖 행은
    # 그 자리에서 새 상자를 열어, 표 사이에 낀 각주가 맨 앞으로 몰리지 않게 한다.
    roots, children = _arcs(rows)
    lead = {"title": "", "elementId": None, "rows": [], "cube": cubes.get(None, tree_cube)}
    tables = []

    def box(group):
        if group is not lead:
            return group
        if not tables or tables[-1]["elementId"] is not None:
            tables.append({**lead, "rows": []})
        return tables[-1]

    def walk(r, depth, group, path):
        eid = r["element_id"]
        # 표/축/도메인/구성요소는 열을 정의하는 뼈대라 행으로 내보내지 않는다.
        if eid.endswith(("Table", "Axis", "Domain", "Member")):
            return
        label = _label_of(labels, eid, r["preferredlabel"], lang)
        if eid.endswith("LineItems"):
            group = {"title": label, "elementId": eid, "rows": [],
                     "cube": cubes.get(eid, cubes.get(None, tree_cube))}
            tables.append(group)
            depth = -1  # 자식이 0부터 시작하도록
        else:
            box(group)["rows"].append({
                "elementId": eid,
                "label": label,
                "depth": depth,
                "abstract": r["abstract"] == "true",
                "labelRole": r["preferredlabel"],  # 기초(periodStart)/기말 잔액 배치용
                "cells": negate(cells_in(eid, group["cube"])) if "negated" in (r["preferredlabel"] or "")
                         else cells_in(eid, group["cube"]),
            })
        if eid not in path:
            for c in children[eid]:
                walk(c, depth + 1, group, path | {eid})
            for c in missing_period_end(children[eid]):
                walk(c, depth + 1, group, path | {eid})

    for r in roots:
        walk(r, 0, lead, frozenset())

    out = []
    for t in tables:
        ctxs = {c for row in t["rows"] for c in row["cells"]}
        if not ctxs:
            continue
        cols = sorted((column(c) for c in ctxs), key=lambda c: c["_sort"], reverse=True)
        for c in cols:
            c.pop("_sort")
        out.append({"title": t["title"], "elementId": t["elementId"],
                    "columns": cols, "rows": t["rows"]})

    return {"roleTitle": role_id, "tables": out, "units": sorted(units)}
