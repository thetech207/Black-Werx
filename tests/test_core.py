import pytest

from blackwerx.core.model import Pattern, Stitch, StitchKind, Transform
from blackwerx.core.block import Block, BlockInstance, explode_instance
from blackwerx.core import symmetry, palette, svg_import
from blackwerx.core.project import save_project, load_project
from blackwerx.core.library import Library
import tempfile, os


def X(x, y, color="#000000"):
    return Stitch(StitchKind.X, (x, y), None, color)


def B(a, b, color="#000000"):
    return Stitch(StitchKind.BACK, a, b, color)


class TestStitch:
    def test_x_stitch(self):
        s = X(3, 4)
        assert s.kind is StitchKind.X
        assert s.key == ("x", (3, 4), None, "layer1", 0.0, 1.0)

    def test_backstitch_normalizes_endpoints(self):
        s = B((5, 5), (3, 3))
        assert s.a == (3, 3) and s.b == (5, 5)

    def test_x_rejects_two_endpoints(self):
        with pytest.raises(ValueError):
            Stitch(StitchKind.X, (0, 0), (1, 1), "#000")


class TestTransform:
    def test_identity(self):
        t = Transform.IDENTITY
        assert t.apply((3, 4)) == (3, 4)

    def test_rotation_90(self):
        t = Transform.from_semantic(0, 0, 90)
        assert t.apply((1, 0)) == (0, 1)
        assert t.apply((0, 1)) == (-1, 0)

    def test_rotation_270(self):
        t = Transform.from_semantic(0, 0, 270)
        assert t.apply((1, 0)) == (0, -1)

    def test_mirror(self):
        t = Transform.from_semantic(0, 0, 0, True, False)
        assert t.apply((3, 4)) == (-3, 4)

    def test_translate_then_rotate_composition(self):
        # apply rot90 then translate(10,0): p=(1,0) -> (0,1) -> (10,1)
        t = Transform.from_semantic(10, 0, 90)
        assert t.apply((1, 0)) == (10, 1)

    def test_compose(self):
        a = Transform.from_semantic(5, 0, 0)      # translate +5x
        b = Transform.from_semantic(0, 0, 90)     # rot90
        c = a.then(b)  # apply a then b
        # p=(1,0): a -> (6,0); b -> (0,6)
        assert c.apply((1, 0)) == (0, 6)

    def test_inverse(self):
        t = Transform.from_semantic(7, -3, 90, True, False)
        inv = t.inverse()
        for p in [(0, 0), (3, -2), (10, 10)]:
            assert inv.apply(t.apply(p)) == p

    def test_dict_roundtrip(self):
        t = Transform.from_semantic(3, 4, 180, True, True)
        assert Transform.from_dict(t.to_dict()) == t


class TestPattern:
    def test_add_remove(self):
        p = Pattern()
        p.add_stitch(X(1, 1))
        assert p.stitch_count() == 1
        p.remove_stitch(X(1, 1).key)
        assert p.stitch_count() == 0

    def test_stitches_in_rect(self):
        p = Pattern()
        p.add_stitch(X(0, 0)); p.add_stitch(X(5, 5)); p.add_stitch(B((0, 0), (2, 0)))
        got = p.stitches_in_rect(0, 0, 2, 1)
        assert len(got) == 2  # X(0,0) and the backstitch

    def test_project_roundtrip(self):
        p = Pattern(name="test", width=50, height=40)
        p.add_stitch(X(1, 2, "dmc:310"))
        p.add_stitch(B((0, 0), (3, 0), "#ff0000"))
        with tempfile.TemporaryDirectory() as d:
            path = save_project(p, os.path.join(d, "t.bwpx"))
            q = load_project(path)
        assert q.name == "test" and q.width == 50
        assert q.stitch_count() == 2
        colors = {s.color for s in q.stitches.values()}
        assert colors == {"dmc:310", "#ff0000"}


class TestBlock:
    def make_block(self):
        b = Block(id="b1", name="motif")
        b.stitches = [X(0, 0), X(1, 0), X(0, 1), X(1, 1)]
        return b

    def test_resolve_translation(self):
        b = self.make_block()
        inst = BlockInstance(uid="i1", block_id="b1", scope="project",
                             transform=Transform.translation(10, 20))
        out = inst.resolve({"b1": b}, {})
        pts = sorted(s.a for s in out)
        assert pts == [(10, 20), (10, 21), (11, 20), (11, 21)]

    def test_resolve_rotation(self):
        b = Block(id="b2", name="domino")
        b.stitches = [X(0, 0), X(1, 0)]
        inst = BlockInstance(uid="i2", block_id="b2", scope="project",
                             transform=Transform.from_semantic(0, 0, 90))
        out = inst.resolve({"b2": b}, {})
        pts = sorted(s.a for s in out)
        # cells (0,0),(1,0) span [0,2]x[0,1]; rot90 CCW -> [-1,0]x[0,2]
        assert pts == [(-1, 0), (-1, 1)]

    def test_nested_block(self):
        inner = Block(id="inner", name="dot")
        inner.stitches = [X(0, 0)]
        outer = Block(id="outer", name="pair")
        outer.instances = [
            BlockInstance(uid="n1", block_id="inner", scope="project",
                          transform=Transform.translation(0, 0)),
            BlockInstance(uid="n2", block_id="inner", scope="project",
                          transform=Transform.translation(5, 0)),
        ]
        p = Pattern()
        p.blocks = {"inner": inner, "outer": outer}
        inst = BlockInstance(uid="i3", block_id="outer", scope="project",
                             transform=Transform.translation(1, 1))
        stitches = inst.resolve(p.blocks, {})
        pts = sorted(s.a for s in stitches)
        # inner dot at local (0,0) and (5,0); outer placed at (1,1):
        # nested n1 at +0 -> (1,1); n2 at +5 -> (6,1)
        assert pts == [(1, 1), (6, 1)]

    def test_explode_flatten(self):
        b = self.make_block()
        p = Pattern()
        p.blocks["b1"] = b
        inst = BlockInstance(uid="i1", block_id="b1", scope="project",
                             transform=Transform.translation(3, 3))
        p.instances.append(inst)
        explode_instance(inst, p, "flatten", {})
        assert inst not in p.instances
        assert p.stitch_count() == 4
        assert (3, 3) in {s.a for s in p.stitches.values()}

    def test_explode_unlink_global_copies_block(self):
        g = self.make_block()
        lib = {"b1": g}
        p = Pattern()
        inst = BlockInstance(uid="i1", block_id="b1", scope="global",
                             transform=Transform.translation(0, 0))
        p.instances.append(inst)
        explode_instance(inst, p, "unlink", lib)
        assert inst.linked is False
        assert inst.scope == "project"
        assert inst.block_id in p.blocks
        assert inst.block_id != "b1"

    def test_recolor(self):
        b = Block(id="b3", name="x")
        b.stitches = [X(0, 0, "#ff0000")]
        inst = BlockInstance(uid="i9", block_id="b3", scope="project",
                             transform=Transform.IDENTITY,
                             recolor={"#ff0000": "#00ff00"})
        out = inst.resolve({"b3": b}, {})
        assert out[0].color == "#00ff00"


class TestSymmetry:
    def test_mirror_h(self):
        p_stitches = [X(1, 2)]
        out = symmetry.apply_symmetry(p_stitches, {"h"}, 10, 10)
        assert len(out) == 2
        xs = sorted(s.a[0] for s in out)
        assert xs == [1, 8]  # mirror of x=1 about cx=4.5 -> 8

    def test_no_axes(self):
        out = symmetry.apply_symmetry([X(1, 1)], set(), 10, 10)
        assert len(out) == 1


class TestPalette:
    def test_resolve_dmc(self):
        assert palette.resolve("dmc:310") == "#000000"

    def test_nearest_dmc(self):
        assert palette.nearest_dmc("#000000").startswith("dmc:")


class TestLibrary:
    def test_save_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lib.json")
            lib = Library(path)
            b = Block(id="bb", name="test")
            b.stitches = [X(0, 0)]
            lib.add(b)
            lib2 = Library(path)
            assert "bb" in lib2.blocks


class TestSvgImportUnit:
    """Unit-test the post-raster stages without Qt rendering."""

    def test_outline_square(self):
        covered = {(x, y) for x in range(3) for y in range(3)}
        st = svg_import.outline_stitches(covered, "#000")
        # 3x3 square boundary: 4 sides of 3 segments each
        assert len(st) == 4
        for s in st:
            assert s.kind is StitchKind.BACK

    def test_fill_stitches(self):
        covered = {(0, 0), (1, 0)}
        st = svg_import.fill_stitches(covered, {}, "mono", "#123456")
        assert len(st) == 2
        assert all(s.color == "#123456" for s in st)

    def test_despeckle(self):
        covered = {(0, 0), (5, 5), (1, 0)}
        out = svg_import._despeckle(covered, 1)
        assert (5, 5) not in out
        assert (0, 0) in out and (1, 0) in out
