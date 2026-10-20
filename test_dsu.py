import pytest
from dsu import DisjointSetUnion

def test_dsu_make_set_and_find():
    dsu=DisjointSetUnion()
    dsu.make_set(1)
    dsu.make_set(2)
    assert dsu.find(1) == 1
    assert dsu.find(2) == 2
    assert not dsu.connected(1, 2)

def test_dsu_union_and_connectivity():
    dsu=DisjointSetUnion()
    dsu.make_set(10)
    dsu.make_set(20)
    dsu.make_set(30)

    assert dsu.union(10, 20) is True
    assert dsu.connected(10, 20) is True
    assert dsu.connected(10, 30) is False

    # duplicate union should return false
    assert dsu.union(10, 20) is False

    dsu.union(20, 30)
    assert dsu.connected(10, 30) is True
    assert dsu.get_set_size(10) == 3

def test_dsu_path_compression():
    dsu=DisjointSetUnion()
    for i in range(1, 6):
        dsu.make_set(i)

    # 1-2-3-4-5 chain
    dsu.union(1, 2)
    dsu.union(2, 3)
    dsu.union(3, 4)
    dsu.union(4, 5)

    root=dsu.find(5)
    # verify direct pointer to root
    assert dsu.parent[5] == root
    assert dsu.parent[4] == root
    assert dsu.parent[3] == root

def test_dsu_group_overlap_conflict():
    dsu=DisjointSetUnion()
    dsu.union(1, 2)

    # student 1 is already taken
    valid,msg=dsu.can_form_group([1, 3, 4],max_group_size=4)
    assert valid is False
    assert "already part of an active confirmed group" in msg

    # new students should work
    valid2,_=dsu.can_form_group([3, 4, 5],max_group_size=4)
    assert valid2 is True

def test_dsu_rebuild_from_db():
    dsu=DisjointSetUnion()
    dsu.union(100, 200)
    assert dsu.connected(100, 200) is True

    # simulate group update
    active_groups=[
        {'member_ids': [300, 400, 500]}
    ]
    dsu.rebuild_from_db(active_groups)
    assert dsu.connected(100, 200) is False
    assert dsu.connected(300, 400) is True
    assert dsu.connected(400, 500) is True
    assert dsu.get_set_size(300) == 3
