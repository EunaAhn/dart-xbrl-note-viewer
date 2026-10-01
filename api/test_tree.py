"""표시 트리 조립 검증. DB 없이 돈다.

    python test_tree.py

한 번 깨졌던 자리라서 남긴다. 같은 요소가 두 부모 밑에 걸릴 때 노드 객체를
공유하면 서브트리가 중복 전개된다.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql:///unused")

from main import PERIOD_END, PERIOD_START, _arcs, build_tree, def_cubes, hypercube, in_hypercube, missing_period_end, negate  # noqa: E402


def arc(eid, parent=None, ord=None, abstract="false"):
    return {"element_id": eid, "parent_element_id": parent, "ord": ord,
            "abstract": abstract, "preferredlabel": None, "use_": "optional"}


def labels(r, lang):
    return r["element_id"]


def names(nodes):
    return [(n["element_id"], names(n["children"])) for n in nodes]


def test_order():
    roots, children = _arcs([arc("R"), arc("b", "R", 2.0), arc("a", "R", 1.0)])
    assert [r["element_id"] for r in roots] == ["R"]
    assert [c["element_id"] for c in children["R"]] == ["a", "b"]


def test_shared_element_is_not_shared_between_parents():
    # X가 A와 B 양쪽 자식이다. 노드를 공유하면 X 밑에 자식이 두 번 쌓인다.
    tree = build_tree([
        arc("R"), arc("A", "R", 1.0), arc("B", "R", 2.0),
        arc("X", "A", 1.0), arc("X", "B", 1.0), arc("leaf", "X", 1.0),
    ], labels)
    assert names(tree) == [("R", [
        ("A", [("X", [("leaf", [])])]),
        ("B", [("X", [("leaf", [])])]),
    ])], names(tree)


def test_cycle_does_not_hang():
    tree = build_tree([arc("R"), arc("A", "R", 1.0), arc("R", "A", 1.0)], labels)
    assert names(tree) == [("R", [("A", [("R", [])])])], names(tree)


def test_abstract_flag():
    tree = build_tree([arc("R", abstract="true")], labels)
    assert tree[0]["abstract"] is True


def test_hypercube_drops_foreign_contexts():
    # 본문 트리엔 연결/별도 축 밑에 연결 멤버만 있다. 별도 컨텍스트, 트리에 없는 축(부문)이
    # 붙은 컨텍스트는 이 목차 값이 아니다.
    cube = hypercube([arc("T"), arc("CSAxis", "T", 1.0), arc("CSDomain", "CSAxis", 1.0),
                      arc("Cons", "CSDomain", 1.0), arc("Items", "T", 2.0)])
    d = lambda *ps: [{"axis": a, "member": m} for a, m in ps]
    assert in_hypercube(d(("CSAxis", "Cons")), cube)
    assert in_hypercube([], cube)
    assert not in_hypercube(d(("CSAxis", "Sep")), cube)
    assert not in_hypercube(d(("CSAxis", "Cons"), ("SegAxis", "DS")), cube)


def test_def_cubes_split_tables_in_one_role():
    # D822390a/b 두 표가 같은 축을 쓰지만 멤버가 다르다. 표시 트리에선 합쳐지므로
    # 정의 링크베이스의 하위 목차로 표마다 가른다. D8223900 같은 다른 목차는 무시.
    def d(role, eid, parent=None, arcrole="domain-member"):
        return {"role_id": role, "element_id": eid, "parent_element_id": parent,
                "arcrole": "http://xbrl.org/int/dim/arcrole/" + arcrole}
    cubes = def_cubes([
        d("R", "CSTable", "Text", "all"), d("R", "CSAxis", "CSTable", "hypercube-dimension"),
        d("R", "Cons", "CSAxis"),
        d("Ra", "ATable", "AAbs", "all"), d("Ra", "CatAxis", "ATable", "hypercube-dimension"),
        d("Ra", "OCI", "CatAxis"), d("Ra", "ALineItems", "AAbs"),
        d("Rb", "BTable", "BAbs", "all"), d("Rb", "CatAxis", "BTable", "hypercube-dimension"),
        d("Rb", "FVPL", "CatAxis"), d("Rb", "Debt", "FVPL"), d("Rb", "BLineItems", "BAbs"),
        d("R0", "XAxis", "XTable", "hypercube-dimension"), d("R0", "XLineItems", "XAbs"),
    ], "R")
    assert cubes[None] == {"CSAxis": {"Cons"}}
    assert cubes["ALineItems"] == {"CatAxis": {"OCI"}}
    assert cubes["BLineItems"] == {"CatAxis": {"FVPL", "Debt"}}
    assert "XLineItems" not in cubes


def test_missing_period_end_row_is_added():
    start = arc("PPE", "Items", 1.0) | {"preferredlabel": PERIOD_START}
    end = arc("Cash", "Items", 3.0) | {"preferredlabel": PERIOD_END}
    cash_start = arc("Cash", "Items", 1.0) | {"preferredlabel": PERIOD_START}
    added = missing_period_end([start, arc("Add", "Items", 2.0), cash_start, end])
    assert [(a["element_id"], a["preferredlabel"]) for a in added] == [("PPE", PERIOD_END)]


def test_negate():
    assert negate({"a": "5", "b": "-3", "c": "0", "d": "텍스트"}) == {"a": "-5", "b": "3", "c": "0", "d": "텍스트"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
