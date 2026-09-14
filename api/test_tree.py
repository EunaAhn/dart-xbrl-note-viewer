"""표시 트리 조립 검증. DB 없이 돈다.

    python test_tree.py

한 번 깨졌던 자리라서 남긴다. 같은 요소가 두 부모 밑에 걸릴 때 노드 객체를
공유하면 서브트리가 중복 전개된다.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql:///unused")

from main import _arcs, build_tree  # noqa: E402


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
