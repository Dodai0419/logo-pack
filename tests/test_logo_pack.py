import glob
import os
import unittest
import xml.etree.ElementTree as ET

import logo_pack as lp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")
# tests/expected/ = output of logo-design-skill@7340903 scripts/export_variants.py
#   <name>.svg --mono "#0F7C80" --title "<Name> logo"


class VariantsMatchUpstream(unittest.TestCase):
    def test_examples_byte_identical(self):
        files = sorted(glob.glob(os.path.join(ROOT, "tests", "expected", "*.svg")))
        self.assertEqual(len(files), 18)
        for name in ("harbor", "fernly", "prism"):
            raw, root = lp.load_svg(os.path.join(EX, name + ".svg"))
            out = lp.variants(raw, root, raw, root, ["#0F7C80"], name.capitalize() + " logo")
            self.assertEqual(list(out), ["black", "white", "mono-0f7c80", "square", "favicon", "app-icon"])
            for suffix, svg in out.items():
                with open(os.path.join(ROOT, "tests", "expected", f"{name}-{suffix}.svg"), encoding="utf-8") as fh:
                    self.assertEqual(svg, fh.read(), f"{name}-{suffix}")

    def test_bbox_handles_transforms_arcs_and_relative_paths(self):
        root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(10 20) scale(2)">'
                             '<path d="m0 0 h10 v10 h-10 z"/><circle cx="20" cy="5" r="5"/></g>'
                             '<defs><rect width="999" height="999"/></defs></svg>')
        bb = lp.artwork_bbox(root)
        self.assertEqual([round(v, 6) for v in bb], [10.0, 20.0, 60.0, 40.0])

    def test_white_paint_note(self):
        self.assertTrue(lp.has_white_paint(lp.load_svg(os.path.join(EX, "harbor.svg"))[1]))
        self.assertFalse(lp.has_white_paint(lp.load_svg(os.path.join(EX, "harbor-cutout.svg"))[1]))


class Sheet(unittest.TestCase):
    def test_sheet_is_valid_svg_with_every_view(self):
        raw, root = lp.load_svg(os.path.join(EX, "fernly.svg"))
        out = lp.variants(raw, root, raw, root, ["#0F7C80"])
        svg = lp.sheet("Fernly", raw, root, out)
        doc = ET.fromstring(svg)
        images = [el for el in doc.iter() if el.tag.endswith("image")]
        # master + white + black + mono + 3 strips x 3 sizes
        self.assertEqual(len(images), 4 + 9)
        self.assertTrue(all(el.get("href").startswith("data:image/svg+xml;base64,") for el in images))
        self.assertIn("favicon 64 / 32 / 16 px", svg)

    def test_cli_writes_all_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lp.main([os.path.join(EX, "prism.svg"), "--out-dir", tmp, "--mono", "#0F7C80"]), 0)
            self.assertEqual(sorted(os.listdir(tmp)), sorted(f"prism-{k}.svg" for k in
                             ("black", "white", "mono-0f7c80", "square", "favicon", "app-icon", "sheet")))


if __name__ == "__main__":
    unittest.main()
