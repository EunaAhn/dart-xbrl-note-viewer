"""DART XBRL 주석 조회 API.

표시(presentation) 링크베이스로 트리를 만들고, 컨텍스트를 열·요소를 행으로 놓아
주석 표를 만든다.
"""
import os
from collections import defaultdict

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

STD_LABEL = "http://www.xbrl.org/2003/role/label"

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


@app.get("/api/companies")
def companies(period: str):
    return q("""
        SELECT s.cik AS corp_code, COALESCE(v.value, s.cik) AS name
        FROM sub s
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
    PRIORITY가 가장 큰 것만 살리고, 그게 prohibited면 아크 자체를 뺀다.
    이걸 안 하면 확장 택사노미가 덮어쓴 아크가 원본과 함께 두 번 나온다.
    """
    rows = q("""
        SELECT DISTINCT ON (p.parent_element_id, p.element_id)
               p.element_id, p.parent_element_id, p.preferredlabel, p.use_,
               NULLIF(p.ord, '')::float AS ord,
               e.abstract, e.period_type, e.balance, e.data_type
        FROM pre p
        LEFT JOIN elmt e ON e.period = p.period AND e.element_id = p.element_id
        WHERE p.period = %s AND p.cik = %s AND p.role_id = %s
        ORDER BY p.parent_element_id, p.element_id,
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


@app.get("/api/table/{cik}/{role_id:path}")
def table(cik: str, role_id: str, period: str):
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
    ctx_members = defaultdict(list)
    for r in q("""
        SELECT context_id, member_element_id FROM cntxt
        WHERE period = %s AND cik = %s AND context_id = ANY(%s)
    """, (period, cik, list(used))):
        ctx_members[r["context_id"]].append(r["member_element_id"])

    member_ids = {m for ms in ctx_members.values() for m in ms}
    labels = _labels(period, cik, set(element_ids) | member_ids)
    periods_by_pk = _context_periods(period, cik)

    cells = defaultdict(dict)
    units = set()
    for f in facts:
        cells[f["element_id"]][f["context_id"]] = f["value"]
        if f["unit_id"]:
            units.add(f["unit_id"])

    def column(ctx):
        start, end = periods_by_pk.get(ctx.split("_", 1)[0], ("", ""))
        return {
            "contextId": ctx,
            "period": end if start == end else f"{start} ~ {end}",
            "members": [_label_of(labels, m, None) for m in ctx_members.get(ctx, [])],
            "_sort": (end or "", start or "", ctx),
        }

    # 하나의 주석 목차에 표가 여러 개 들어있다. 전부 한 표로 합치면 열이 수십 개인
    # 성긴 표가 되므로 [항목](LineItems)마다 표를 나눈다. 열은 그 표에 실제로 값이
    # 있는 컨텍스트만 쓴다.
    roots, children = _arcs(rows)
    lead = {"title": "", "rows": []}
    tables = [lead]

    def walk(r, depth, group, path):
        eid = r["element_id"]
        # 표/축/도메인/구성요소는 열을 정의하는 뼈대라 행으로 내보내지 않는다.
        if eid.endswith(("Table", "Axis", "Domain", "Member")):
            return
        label = _label_of(labels, eid, r["preferredlabel"])
        if eid.endswith("LineItems"):
            group = {"title": label, "rows": []}
            tables.append(group)
            depth = -1  # 자식이 0부터 시작하도록
        else:
            group["rows"].append({
                "elementId": eid,
                "label": label,
                "depth": depth,
                "abstract": r["abstract"] == "true",
                "cells": cells.get(eid, {}),
            })
        if eid not in path:
            for c in children[eid]:
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
        out.append({"title": t["title"], "columns": cols, "rows": t["rows"]})

    return {"roleTitle": role_id, "tables": out, "units": sorted(units)}


@app.get("/api/element/{cik}/{element_id:path}")
def element(cik: str, element_id: str, period: str):
    rows = q("""
        SELECT element_id, element_name, taxonomy_id, data_type, substitution_group,
               period_type, balance, nillable, abstract
        FROM elmt WHERE period = %s AND element_id = %s LIMIT 1
    """, (period, element_id))
    if not rows:
        raise HTTPException(404, "요소를 찾지 못했습니다.")
    labels = _labels(period, cik, {element_id})
    return rows[0] | {
        "korean_label": _label_of(labels, element_id, None, "ko"),
        "english_label": _label_of(labels, element_id, None, "en"),
    }
