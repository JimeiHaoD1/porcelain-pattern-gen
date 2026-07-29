from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chanzhi_sw.chanzhi_annotation_qa import audit_svg, main  # noqa: E402
from chanzhi_sw.chanzhi_svg_skeleton_io import _load_skeleton  # noqa: E402


def svg(body: str, family: str = "scroll_swollen") -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" data-terminal-family="{family}">
    {body}</svg>'''


BASE = '''
<path id="back" data-role="backbone" stroke="#0000ff" d="M0,50 L100,50"/>
<path id="left" data-role="unit_boundary" stroke="#000000" stroke-dasharray="3 2" d="M0 0 V100"/>
<path id="right" data-role="unit_boundary" stroke="#000000" stroke-dasharray="3 2" d="M100 0 V100"/>
'''


VALID_B = BASE + '''
<path id="p1" data-role="scroll_branch" data-generation="1" stroke="#ff9900" d="M20,50 L40,30"/>
<path id="p2" data-role="scroll_branch" data-generation="2" data-parent-id="p1" stroke="#00b7c7" d="M35,35 L50,20"/>
<path id="p3" data-role="scroll_branch" data-generation="3" data-parent-id="p2" stroke="#7a3db8" d="M47,23 L55,12"/>
<circle id="flower1" data-role="flower_anchor" stroke="#ff0000" cx="70" cy="35" r="5"/>
<path id="support" data-role="flower_support" data-parent-id="back" data-target-flower-id="flower1" stroke="#007800" d="M60,50 L70,40"/>
<path id="wrap" data-role="wrap_flower" data-parent-id="back" target_flower_id="flower1" stroke="#ffff00" d="M60,50 Q70,25 76,40"/>
'''


class AnnotationQaTests(unittest.TestCase):
    def write(self, text: str, directory: str, name: str = "sample.svg") -> Path:
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return path

    def codes(self, report: dict) -> set[str]:
        return {issue["code"] for issue in report["issues"]}

    def test_valid_profile_b_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(VALID_B), tmp))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["profile"], "scroll_swollen")

    def test_global_color_backbone_boundary_and_examples(self) -> None:
        body = '''
        <g data-example="true" transform="warp(2)"><path data-role="primary_branch" stroke="#123456" d="M0 0 L1 1"/></g>
        <path id="old" data-role="primary_branch" data-generation="1" stroke="#ff7800" d="M0 0 L1 1"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(svg(body, "leaf_bearing"), tmp)
            report = audit_svg(path)
            included = audit_svg(path, include_examples=True)
        self.assertTrue({"missing_backbone", "insufficient_unit_boundaries", "legacy_color"}.issubset(self.codes(report)))
        self.assertIn("example_objects_present", self.codes(report))
        self.assertNotIn("illegal_color", self.codes(report))
        self.assertNotIn("invalid_transform", self.codes(report))
        self.assertIn("illegal_color", self.codes(included))
        self.assertIn("invalid_transform", self.codes(included))

    def test_generation_parent_hierarchy_geometry_and_flower_target(self) -> None:
        body = BASE + '''
        <path id="p1" data-role="scroll_branch" stroke="#ff9900" d="M20 50 L40 30"/>
        <path id="wrong" data-role="scroll_branch" data-generation="1" stroke="#ff9900" d="M70 50 L80 30"/>
        <path id="p2" data-role="scroll_branch" data-generation="2" data-parent-id="back" stroke="#00b7c7" d="M5 5 L10 10"/>
        <path id="p3" data-role="scroll_branch" data-generation="3" stroke="#7a3db8" d="M10 10 L20 10"/>
        <path id="bad_generation" data-role="scroll_branch" data-generation="four" stroke="#00b7c7" d="M10 10 L20 10"/>
        <path id="support" data-role="flower_support" stroke="#007800" d="M1 1 L2 2"/>
        <path id="wrap" data-role="wrap_flower" data-target-flower-id="wrong" stroke="#ffff00" d="M1 1 L2 2"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(body), tmp), attachment_tolerance=2)
        codes = self.codes(report)
        self.assertTrue({"missing_generation", "invalid_generation", "wrong_parent_hierarchy", "missing_parent_id",
                         "missing_target_flower", "target_not_flower", "detached_branch_start"}.issubset(codes))

    def test_profile_a_and_b_color_misuse(self) -> None:
        a_body = BASE + '''
        <path id="p1" data-role="scroll_branch" data-generation="1" stroke="#ff9900" d="M20 50 L30 40"/>
        <path id="p2" data-role="scroll_branch" data-generation="2" data-parent-id="p1" stroke="#00b7c7" d="M25 45 L35 35"/>
        '''
        b_body = VALID_B + '<path id="leaf" data-role="leaf_guide" data-parent-id="p1" stroke="#00ff00" d="M30 40 L32 38"/>'
        with tempfile.TemporaryDirectory() as tmp:
            report_a = audit_svg(self.write(svg(a_body, "leaf_bearing"), tmp, "a.svg"))
            report_b = audit_svg(self.write(svg(b_body), tmp, "b.svg"))
        self.assertIn("profile_a_scroll_color_misuse", self.codes(report_a))
        self.assertIn("profile_b_leaf_color_misuse", self.codes(report_b))
        self.assertIn("wrong_parent_hierarchy", self.codes(report_b))

    def test_runtime_shape_and_arc_contract(self) -> None:
        body = BASE + '''
        <line id="line_branch" data-role="primary_branch" data-generation="1" data-terminal-family="leaf_bearing" stroke="#ff9900" x1="20" y1="50" x2="30" y2="40"/>
        <path id="arc_branch" data-role="primary_branch" data-generation="1" data-terminal-family="leaf_bearing" stroke="#ff9900" d="M40 50 A10 10 0 0 1 55 35"/>
        <path id="path_flower" data-role="flower_anchor" stroke="#ff0000" d="M50 20 L55 20"/>
        <circle id="circle_flower" data-role="flower_anchor" stroke="#ff0000" cx="70" cy="20" r="4"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(body, "leaf_bearing"), tmp))
        codes = self.codes(report)
        self.assertIn("unsupported_runtime_shape", codes)
        self.assertIn("runtime_unsupported_path", codes)
        unsupported_ids = {
            item["element_id"] for item in report["issues"]
            if item["code"] == "unsupported_runtime_shape"
        }
        self.assertEqual(unsupported_ids, {"line_branch", "path_flower"})

    def test_skew_transform_and_runtime_loader_contract(self) -> None:
        wrapped = f'<g transform="skewX(5) skewY(-3)">{VALID_B}</g>'
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(svg(wrapped), tmp, "contract.svg")
            report = audit_svg(path)
            width, height, paths, flowers = _load_skeleton(path, tile_width=100)
            invalid_count = audit_svg(self.write(svg(f'<g id="bad_transform" transform="skewX(1,2)">{VALID_B}</g>'), tmp, "invalid_count.svg"))
            invalid_name = audit_svg(self.write(svg(f'<g id="bad_name" transform="warp(2)">{VALID_B}</g>'), tmp, "invalid_name.svg"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual((width, height), (100, 100))
        self.assertEqual(len(paths), 8)
        self.assertEqual(len(flowers), 1)
        self.assertIn("invalid_transform", self.codes(invalid_count))
        self.assertIn("invalid_transform", self.codes(invalid_name))

    def test_repeat_boundaries_separate_and_backbone_spans_unit(self) -> None:
        short_backbone = BASE.replace('d="M0,50 L100,50"', 'd="M20,50 L80,50"')
        coincident = '''
        <path id="back" data-role="backbone" stroke="#0000ff" d="M0 50 L100 50"/>
        <path id="left" data-role="unit_boundary" stroke="#000000" stroke-dasharray="2 2" d="M0 0 V100"/>
        <path id="right" data-role="unit_boundary" stroke="#000000" stroke-dasharray="2 2" d="M0 0 V100"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            span_report = audit_svg(self.write(svg(short_backbone), tmp, "span.svg"))
            separation_report = audit_svg(self.write(svg(coincident), tmp, "separation.svg"))
        self.assertIn("backbone_does_not_span_unit", self.codes(span_report))
        self.assertIn("unit_boundaries_not_separated", self.codes(separation_report))

    def test_flower_branch_parent_attachment_and_terminal(self) -> None:
        body = BASE + '''
        <ellipse id="flower" data-role="flower_anchor" stroke="#ff0000" cx="70" cy="20" rx="4" ry="4"/>
        <path id="support" data-role="flower_support" data-parent-id="back" data-target-flower-id="flower" stroke="#007800" d="M10 10 L15 10"/>
        <path id="wrap" data-role="wrap_flower" data-target-flower-id="flower" stroke="#ffff00" d="M20 50 L25 45"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(body), tmp), attachment_tolerance=3, flower_tolerance=5)
        codes = self.codes(report)
        self.assertIn("detached_branch_start", codes)
        self.assertIn("flower_terminal_too_far", codes)
        self.assertIn("missing_parent_id", codes)

    def test_explicit_role_cannot_override_wrong_color(self) -> None:
        body = BASE + '''
        <path id="bad_backbone" data-role="backbone" stroke="#ff0000" d="M0 55 L100 55"/>
        <path id="bad_secondary_backbone" data-role="secondary_backbone" stroke="#0000ff" d="M0 60 L100 60"/>
        <path id="bad_primary" data-role="primary_branch" data-generation="1" data-terminal-family="leaf_bearing" stroke="#00b7c7" d="M10 50 L25 35"/>
        <path id="bad_scroll_1" data-role="scroll_branch" data-generation="1" data-terminal-family="scroll_swollen" stroke="#7a3db8" d="M60 50 L70 40"/>
        <path id="bad_scroll_2" data-role="scroll_branch" data-generation="2" data-parent-id="bad_scroll_1" data-terminal-family="scroll_swollen" stroke="#7a3db8" d="M65 45 L75 35"/>
        <path id="bad_scroll_3" data-role="scroll_branch" data-generation="3" data-parent-id="bad_scroll_2" data-terminal-family="scroll_swollen" stroke="#00b7c7" d="M70 40 L80 30"/>
        <path id="bad_leaf" data-role="leaf_guide" data-parent-id="bad_primary" data-terminal-family="leaf_bearing" stroke="#00b7c7" d="M20 40 L25 38"/>
        <ellipse id="flower" data-role="flower_anchor" stroke="#ff0000" cx="50" cy="25" rx="4" ry="4"/>
        <path id="bad_support" data-role="flower_support" data-parent-id="back" data-target-flower-id="flower" stroke="#ffff00" d="M40 50 L50 29"/>
        <path id="bad_wrap" data-role="wrap_flower" data-parent-id="back" data-target-flower-id="flower" stroke="#007800" d="M40 50 L55 28"/>
        <ellipse id="bad_flower" data-role="flower_anchor" stroke="#ff00ff" cx="35" cy="20" rx="3" ry="3"/>
        <line id="bad_boundary" data-role="unit_boundary" stroke="#0000ff" stroke-dasharray="2 2" x1="50" y1="0" x2="50" y2="100"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(body, "hybrid"), tmp))
        mismatch_ids = {
            issue["element_id"] for issue in report["issues"]
            if issue["code"] == "role_color_mismatch"
        }
        self.assertEqual(mismatch_ids, {
            "bad_backbone", "bad_secondary_backbone", "bad_primary",
            "bad_scroll_1", "bad_scroll_2", "bad_scroll_3", "bad_leaf",
            "bad_support", "bad_wrap", "bad_flower", "bad_boundary",
        })

    def test_legacy_role_colors_warn_but_remain_compatible(self) -> None:
        body = BASE + '''
        <path id="leaf_primary" data-role="primary_branch" data-generation="1" data-terminal-family="leaf_bearing" stroke="#ff7800" d="M10 50 L30 30"/>
        <path id="legacy_leaf" data-role="leaf_guide" data-parent-id="leaf_primary" data-terminal-family="leaf_bearing" stroke="#66cc66" d="M20 40 L25 35"/>
        <path id="scroll_primary" data-role="scroll_branch" data-generation="1" data-terminal-family="scroll_swollen" stroke="#ff7800" d="M60 50 L70 40"/>
        <path id="legacy_secondary" data-role="scroll_branch" data-generation="2" data-parent-id="scroll_primary" data-terminal-family="scroll_swollen" stroke="#00ffff" d="M65 45 L75 35"/>
        <ellipse id="flower" data-role="flower_anchor" stroke="#ff0000" cx="50" cy="20" rx="4" ry="4"/>
        <path id="legacy_wrap" data-role="wrap_flower" data-parent-id="back" data-target-flower-id="flower" stroke="#ffcc00" d="M40 50 L55 24"/>
        '''
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_svg(self.write(svg(body, "hybrid"), tmp))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["warnings"], 5)
        self.assertNotIn("role_color_mismatch", self.codes(report))

    def test_cli_json_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            valid = self.write(svg(VALID_B), tmp, "valid.svg")
            output = Path(tmp) / "report.json"
            self.assertEqual(main([str(valid), "-o", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "pass")
            bad = self.write(svg(""), tmp, "bad.svg")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main([str(bad), "--compact"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stream.getvalue())["status"], "fail")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main([str(Path(tmp)/"missing.svg"), "--compact"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stream.getvalue())["status"], "input_error")


if __name__ == "__main__":
    unittest.main()
