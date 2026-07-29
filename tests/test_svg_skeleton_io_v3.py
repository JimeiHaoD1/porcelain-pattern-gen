from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from chanzhi_sw import chanzhi_svg_skeleton_io as svg_io  # noqa: E402


def _write_svg(tmp_path: Path, body: str) -> Path:
    svg_path = tmp_path / "annotation.svg"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 304">{body}</svg>',
        encoding="utf-8",
    )
    return svg_path


def _features_by_id(
    svg_path: Path,
    *,
    include_examples: bool = False,
) -> dict[str, svg_io.PathFeature]:
    _, _, paths, _ = svg_io._load_skeleton(
        svg_path,
        tile_width=256,
        include_examples=include_examples,
    )
    return {feature.element_id: feature for feature in paths if feature.element_id is not None}


def test_nested_v3_scroll_layers_inherit_group_metadata(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        """
        <g data-terminal-family="scroll_swollen">
          <path id="branch-1" d="M 10 20 L 100 40"
                style="stroke:#FF9900;stroke-width:6px"
                data-role="scroll_branch" data-generation="1" />
          <path id="branch-2" d="M 80 35 L 130 80"
                stroke="rgb(0, 183, 199)" stroke-width="4"
                data-generation="2" data-parent-id="branch-1" />
          <g data-generation="3" data-parent-id="branch-2"
             style="stroke:#7A3DB8;stroke-width:3px">
            <path id="branch-3" d="M 125 78 L 150 105" />
          </g>
        </g>
        """,
    )

    width, height, paths, flowers = svg_io._load_skeleton(svg_path, tile_width=256)

    assert (width, height) == (512, 304)
    assert flowers == []
    assert [path.element_id for path in paths] == ["branch-1", "branch-2", "branch-3"]
    assert [path.role for path in paths] == ["scroll_branch"] * 3
    assert [path.terminal_family for path in paths] == ["scroll_swollen"] * 3
    assert [path.generation for path in paths] == [1, 2, 3]
    assert [path.parent_id for path in paths] == [None, "branch-1", "branch-2"]
    assert [path.stroke for path in paths] == ["#ff9900", "#00b7c7", "#7a3db8"]
    assert [path.stroke_width for path in paths] == [6.0, 4.0, 3.0]


def test_metadata_priority_is_role_then_family_then_generation_then_color(tmp_path: Path) -> None:
    features = _features_by_id(
        _write_svg(
            tmp_path,
            """
            <path id="role-wins" d="M 0 10 L 30 10" stroke="#ff9900"
                  data-role="backbone" data-terminal-family="scroll_swollen"
                  data-generation="2" data-parent-id="declared-parent" />
            <path id="family-wins" d="M 40 10 L 70 10" stroke="#00b7c7"
                  data-terminal-family="leaf_bearing" data-generation="2" />
            <path id="generation-wins" d="M 80 10 L 110 10" stroke="#ff9900"
                  data-generation="2" />
            <path id="explicit-primary" d="M 120 10 L 150 10" stroke="#7a3db8"
                  data-role="primary_branch" data-generation="3" />
            <path id="semantic-only" d="M 160 10 L 190 10"
                  data-role="leaf_guide" data-terminal-family="leaf_bearing"
                  data-parent-id="explicit-primary" />
            <path id="role-blocks-color-fallback" d="M 200 10 L 230 10"
                  data-role="backbone" stroke="#7a3db8" />
            """,
        )
    )

    assert features["role-wins"].role == "backbone"
    assert features["role-wins"].terminal_family == "scroll_swollen"
    assert features["role-wins"].generation == 2
    assert features["role-wins"].parent_id == "declared-parent"

    assert features["family-wins"].role == "primary_branch"
    assert features["family-wins"].terminal_family == "leaf_bearing"
    assert features["family-wins"].generation == 2

    assert features["generation-wins"].role == "scroll_branch"
    assert features["generation-wins"].generation == 2
    assert features["explicit-primary"].role == "primary_branch"
    assert features["explicit-primary"].generation == 3
    assert features["semantic-only"].role == "leaf_guide"
    assert features["semantic-only"].stroke == ""
    assert features["semantic-only"].parent_id == "explicit-primary"
    assert features["role-blocks-color-fallback"].role == "backbone"
    assert features["role-blocks-color-fallback"].generation is None
    assert features["role-blocks-color-fallback"].terminal_family == "unknown"


def test_v3_colors_and_legacy_colors_remain_compatible(tmp_path: Path) -> None:
    features = _features_by_id(
        _write_svg(
            tmp_path,
            """
            <path id="backbone" d="M 0 20 L 20 20" stroke="#00F" />
            <path id="old-orange" d="M 20 20 L 40 20" stroke="#FF7800" />
            <path id="new-orange" d="M 40 20 L 60 20" stroke="#FF9900" />
            <path id="cyan" d="M 60 20 L 80 20" stroke="#00B7C7" />
            <path id="purple" d="M 80 20 L 100 20" stroke="#7A3DB8" />
            <path id="new-green" d="M 100 20 L 120 20" stroke="#00FF00" />
            <path id="old-green" d="M 120 20 L 140 20" stroke="#66CC66" />
            <path id="old-structural" d="M 140 20 L 160 20" stroke="#007800" />
            <path id="wrap" d="M 160 20 L 180 20" stroke="#FFFF00" />
            <path id="boundary" d="M 256 0 V 304"
                  style="stroke:#000;stroke-dasharray:5,5" />
            """,
        )
    )

    assert features["backbone"].role == "backbone"
    assert features["old-orange"].role == "primary_branch"
    assert features["new-orange"].role == "primary_branch"
    assert features["old-orange"].generation == 1
    assert features["new-orange"].generation == 1
    assert features["old-orange"].terminal_family == "unknown"
    assert features["new-orange"].terminal_family == "unknown"

    assert features["cyan"].role == "scroll_branch"
    assert features["cyan"].generation == 2
    assert features["cyan"].terminal_family == "scroll_swollen"
    assert features["purple"].role == "scroll_branch"
    assert features["purple"].generation == 3
    assert features["purple"].terminal_family == "scroll_swollen"

    assert features["new-green"].role == "leaf_guide"
    assert features["old-green"].role == "leaf_guide"
    assert features["new-green"].legacy_ambiguous_terminal is True
    assert features["old-green"].legacy_ambiguous_terminal is True
    assert features["old-structural"].role == "structural_branch"
    assert features["wrap"].role == "wrap_flower"
    assert features["boundary"].role == "unit_boundary"


def test_qa_accepted_legacy_cyan_and_yellow_are_not_dropped(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        """
        <path id="legacy-secondary" d="M 10 20 L 80 40" stroke="#00FFFF" />
        <path id="legacy-wrap" d="M 90 20 C 110 0 140 0 160 20"
              style="stroke:#FFCC00;fill:none" />
        """,
    )

    _, _, paths, flowers = svg_io._load_skeleton(svg_path, tile_width=256)
    features = {feature.element_id: feature for feature in paths}

    assert flowers == []
    assert len(paths) == 2
    secondary = features["legacy-secondary"]
    assert secondary.stroke == "#00ffff"
    assert secondary.role == "scroll_branch"
    assert secondary.generation == 2
    assert secondary.terminal_family == "scroll_swollen"
    legacy_wrap = features["legacy-wrap"]
    assert legacy_wrap.stroke == "#ffcc00"
    assert legacy_wrap.role == "wrap_flower"
    assert legacy_wrap.generation is None


def test_flower_anchor_role_overrides_stroke_and_supports_circle(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        """
        <ellipse id="legacy-flower" cx="40" cy="60" rx="12" ry="8"
                 style="stroke:rgb(255, 0, 0)" />
        <circle id="semantic-flower" cx="300" cy="70" r="10"
                stroke="#0000ff" data-role="flower_anchor" />
        <circle id="not-a-flower" cx="100" cy="70" r="10"
                stroke="#ff0000" data-role="backbone" />
        """,
    )

    _, _, _, flowers = svg_io._load_skeleton(svg_path, tile_width=256)

    assert [flower.element_id for flower in flowers] == ["legacy-flower", "semantic-flower"]
    assert (flowers[0].rx, flowers[0].ry, flowers[0].unit) == (12.0, 8.0, 0)
    assert (flowers[1].rx, flowers[1].ry, flowers[1].unit) == (10.0, 10.0, 1)


def test_path_feature_old_positional_constructor_stays_valid() -> None:
    feature = svg_io.PathFeature(
        "backbone",
        "#0000ff",
        "M 0 0 L 1 1",
        [(0.0, 0.0), (1.0, 1.0)],
        0,
        0,
    )

    assert feature.role == "backbone"
    assert feature.element_id is None
    assert feature.terminal_family == "unknown"
    assert feature.generation is None
    assert feature.parent_id is None
    assert feature.target_flower_id is None


def test_target_flower_aliases_normalize_and_override_group_value(tmp_path: Path) -> None:
    features = _features_by_id(
        _write_svg(
            tmp_path,
            """
            <g data-target-flower-id="#group-flower">
              <path id="inherited" d="M 0 10 L 20 10" stroke="#007800"
                    data-role="flower_support" />
              <path id="data-underscore" d="M 20 10 L 40 10" stroke="#007800"
                    data-role="flower_support" data-target_flower_id="#flower-a" />
              <path id="plain-underscore" d="M 40 10 L 60 10" stroke="#ffff00"
                    data-role="wrap_flower" target_flower_id=" #flower-b " />
              <path id="plain-hyphen" d="M 60 10 L 80 10" stroke="#ffff00"
                    data-role="wrap_flower" target-flower-id="#flower-c" />
            </g>
            """,
        )
    )

    assert features["inherited"].target_flower_id == "group-flower"
    assert features["data-underscore"].target_flower_id == "flower-a"
    assert features["plain-underscore"].target_flower_id == "flower-b"
    assert features["plain-hyphen"].target_flower_id == "flower-c"


def test_real_v3_template_flower_branches_reference_anchor() -> None:
    template = PROJECT_ROOT / "data" / "annotation_templates" / "chanzhi_annotation_v3_template.svg"
    _, _, default_paths, default_flowers = svg_io._load_skeleton(template, tile_width=256)
    features = _features_by_id(template, include_examples=True)

    assert default_paths == []
    assert default_flowers == []
    assert features["flower_support_001"].target_flower_id == "flower_anchor_001"
    assert features["wrap_flower_001"].target_flower_id == "flower_anchor_001"


def test_example_objects_and_inherited_example_groups_are_opt_in(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        """
        <g data-example="true">
          <path id="group-example" d="M 0 10 L 20 10" stroke="#0000ff" />
          <ellipse id="group-example-flower" cx="10" cy="30" rx="4" ry="3"
                   stroke="#ff0000" />
        </g>
        <path id="object-example" d="M 20 10 L 40 10" stroke="#ff9900"
              data-example="yes" />
        <path id="formal-path" d="M 40 10 L 60 10" stroke="#0000ff" />
        <ellipse id="formal-flower" cx="50" cy="30" rx="4" ry="3"
                 stroke="#ff0000" />
        """,
    )

    _, _, formal_paths, formal_flowers = svg_io._load_skeleton(svg_path, tile_width=256)
    _, _, all_paths, all_flowers = svg_io._load_skeleton(
        svg_path,
        tile_width=256,
        include_examples=True,
    )

    assert [path.element_id for path in formal_paths] == ["formal-path"]
    assert [flower.element_id for flower in formal_flowers] == ["formal-flower"]
    assert [path.element_id for path in all_paths] == [
        "group-example",
        "object-example",
        "formal-path",
    ]
    assert [flower.element_id for flower in all_flowers] == [
        "group-example-flower",
        "formal-flower",
    ]


def test_compound_multi_subpath_annotation_is_rejected(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        '<path id="compound" d="M 0 0 L 20 0 M 40 0 L 60 0" stroke="#0000ff" />',
    )

    with pytest.raises(
        ValueError,
        match=r"compound SVG path contains 2 subpaths; split it into separate <path> elements",
    ):
        svg_io._load_skeleton(svg_path, tile_width=256)


def test_parent_child_and_path_transforms_are_applied(tmp_path: Path) -> None:
    features = _features_by_id(
        _write_svg(
            tmp_path,
            """
            <g transform="translate(10 20)">
              <g transform="scale(2 3)">
                <path id="nested" d="M 1 2 L 3 4" stroke="#0000ff" />
              </g>
            </g>
            <path id="own-rotate" d="M 1 0 L 2 0" stroke="#0000ff"
                  transform="rotate(90)" />
            <path id="own-matrix" d="M 1 2 L 3 4" stroke="#0000ff"
                  transform="matrix(2 0 0 3 5 7)" />
            <path id="own-skew-x" d="M 0 2 L 1 2" stroke="#0000ff"
                  transform="skewX(45)" />
            <path id="own-skew-y" d="M 2 0 L 2 1" stroke="#0000ff"
                  transform="skewY(45)" />
            """,
        )
    )

    assert features["nested"].points[0] == pytest.approx((12.0, 26.0))
    assert features["nested"].points[1] == pytest.approx((16.0, 32.0))
    assert features["own-rotate"].points[0] == pytest.approx((0.0, 1.0), abs=1e-9)
    assert features["own-rotate"].points[1] == pytest.approx((0.0, 2.0), abs=1e-9)
    assert features["own-matrix"].points[0] == pytest.approx((7.0, 13.0))
    assert features["own-matrix"].points[1] == pytest.approx((11.0, 19.0))
    assert features["own-skew-x"].points[0] == pytest.approx((2.0, 2.0), abs=1e-9)
    assert features["own-skew-x"].points[1] == pytest.approx((3.0, 2.0), abs=1e-9)
    assert features["own-skew-y"].points[0] == pytest.approx((2.0, 2.0), abs=1e-9)
    assert features["own-skew-y"].points[1] == pytest.approx((2.0, 3.0), abs=1e-9)

    transform = svg_io._parse_transform("translate(10 20) scale(2 3)")
    assert svg_io._apply_transform(transform, (1.0, 2.0)) == pytest.approx((12.0, 26.0))


def test_ellipse_and_circle_receive_inherited_and_local_transforms(tmp_path: Path) -> None:
    svg_path = _write_svg(
        tmp_path,
        """
        <g transform="translate(100 50)">
          <g transform="rotate(90)">
            <ellipse id="transformed-ellipse" data-role="flower_anchor"
                     cx="10" cy="20" rx="4" ry="2" transform="scale(2 3)" />
          </g>
        </g>
        <circle id="transformed-circle" data-role="flower_anchor"
                cx="1" cy="2" r="4" transform="matrix(2 0 0 3 5 7)" />
        """,
    )

    _, _, _, flowers = svg_io._load_skeleton(svg_path, tile_width=256)
    by_id = {flower.element_id: flower for flower in flowers}

    ellipse = by_id["transformed-ellipse"]
    assert (ellipse.cx, ellipse.cy) == pytest.approx((40.0, 70.0), abs=1e-9)
    assert (ellipse.rx, ellipse.ry) == pytest.approx((6.0, 8.0), abs=1e-9)

    circle = by_id["transformed-circle"]
    assert (circle.cx, circle.cy) == pytest.approx((7.0, 13.0))
    assert (circle.rx, circle.ry) == pytest.approx((8.0, 12.0))


def test_quadratic_and_smooth_path_commands_are_sampled() -> None:
    quadratic = svg_io._parse_svg_path("M 0 0 Q 10 20 20 0 T 40 0")
    assert quadratic[0] == pytest.approx((0.0, 0.0))
    assert quadratic[28] == pytest.approx((20.0, 0.0))
    assert quadratic[42] == pytest.approx((30.0, -10.0))
    assert quadratic[-1] == pytest.approx((40.0, 0.0))

    cubic = svg_io._parse_svg_path("M 0 0 C 10 0 10 10 20 10 S 30 20 40 10")
    assert cubic[28] == pytest.approx((20.0, 10.0))
    assert cubic[42] == pytest.approx((30.0, 13.75))
    assert cubic[-1] == pytest.approx((40.0, 10.0))

    relative = svg_io._parse_svg_path("m 1 1 q 10 20 20 0 t 20 0")
    assert relative[-1] == pytest.approx((41.0, 1.0))


def test_arc_command_fails_with_an_actionable_error() -> None:
    with pytest.raises(ValueError, match=r"unsupported SVG path command 'A'.*M/L/H/V/C/S/Q/T/Z"):
        svg_io._parse_svg_path("M 0 0 A 10 10 0 0 1 20 20")
