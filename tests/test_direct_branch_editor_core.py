from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EDITOR_DIR = ROOT / "experiments" / "branch_unit" / "direct_editor"
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))

core = importlib.import_module("editor_core")
app_module = importlib.import_module("app")


def _cubic(p0, p1, p2, p3):
    return {"p0": list(p0), "p1": list(p1), "p2": list(p2), "p3": list(p3)}


def test_loads_allowlisted_record_and_profile_exactly() -> None:
    bootstrap = core.load_source(4101)

    assert bootstrap["schema"] == core.SCHEMA
    assert len(bootstrap["branches"]) == 21
    assert {branch["level"] for branch in bootstrap["branches"]} == {1, 2, 3}
    assert bootstrap["topology"] == {
        "level_1": 7,
        "level_2": 12,
        "level_3": 2,
        "maximum_depth": 3,
    }
    assert bootstrap["canvas"]["active_repeat_x"] == [0.0, 256.0]
    assert bootstrap["backbone"]["locked"] is True
    assert len(bootstrap["backbone"]["points"]) == 81
    assert len(bootstrap["flowers"]) == 2
    assert all(len(branch["edited_cubics"]) in (1, 2) for branch in bootstrap["branches"])


def test_seed_and_arbitrary_session_paths_are_rejected() -> None:
    assert core.load_source(4102)["source"]["seed"] == 4102
    assert core.load_source(4103)["source"]["seed"] == 4103
    with pytest.raises(core.EditorValidationError, match="4101、4102、4103"):
        core.load_source(9999)
    with pytest.raises(core.EditorValidationError, match="session_id"):
        core.load_session("../record_4101")
    with pytest.raises(core.EditorValidationError, match="session_id"):
        core.load_session(r"..\record_4101")


def test_cubic_sampling_preserves_endpoints_and_segment_join() -> None:
    cubics = [
        _cubic((0, 0), (2, 0), (3, 1), (5, 1)),
        _cubic((5, 1), (7, 1), (8, 0), (10, 0)),
    ]
    points = core.sample_cubics(cubics, samples=8)

    assert points[0] == pytest.approx([0, 0])
    assert points[-1] == pytest.approx([10, 0])
    assert len(points) == 17
    assert core.cubic_point(cubics[0], 1.0) == pytest.approx(cubics[0]["p3"])


def test_nearest_arc_projection_and_mount_fraction() -> None:
    projection = core.project_point_to_polyline([5, 3], [[0, 0], [10, 0]])

    assert projection["point"] == pytest.approx([5, 0])
    assert projection["arc_length"] == pytest.approx(5)
    assert projection["fraction"] == pytest.approx(0.5)
    assert projection["tangent"] == pytest.approx([1, 0])
    assert projection["normal"] == pytest.approx([0, 1])
    assert projection["distance"] == pytest.approx(3)


def test_local_coordinates_map_into_new_parent_frame() -> None:
    old_frame = core.frame_at_fraction([[0, 0], [10, 0]], 0.5)
    new_frame = core.frame_at_fraction([[0, 0], [0, 10]], 0.5)
    local = core.local_coordinates([7, 3], old_frame)

    assert local == pytest.approx([2, 3])
    assert core.from_local_coordinates(local, new_frame) == pytest.approx([-3, 7])


def test_l1_l2_l3_descendants_follow_recursively() -> None:
    parent_old = [_cubic((0, 0), (3, 0), (7, 0), (10, 0))]
    parent_new = [_cubic((0, 0), (0, 3), (0, 7), (0, 10))]
    branches = {
        "l1": {
            "curve_id": "l1",
            "parent_id": "backbone",
            "level": 1,
            "mount_fraction": 0.5,
            "edited_cubics": parent_new,
        },
        "l2": {
            "curve_id": "l2",
            "parent_id": "l1",
            "level": 2,
            "mount_fraction": 0.5,
            "edited_cubics": [_cubic((5, 0), (5, 1), (5, 2), (5, 3))],
        },
        "l3": {
            "curve_id": "l3",
            "parent_id": "l2",
            "level": 3,
            "mount_fraction": 0.5,
            "edited_cubics": [_cubic((5, 1.5), (6, 1.5), (7, 1.5), (8, 1.5))],
        },
    }
    l2_before = copy.deepcopy(branches["l2"]["edited_cubics"])
    l3_before = copy.deepcopy(branches["l3"]["edited_cubics"])

    core.propagate_descendants(
        branches,
        "l1",
        core.sample_cubics(parent_old),
        core.sample_cubics(parent_new),
    )

    assert branches["l2"]["edited_cubics"][0]["p0"] == pytest.approx([0, 5], abs=1e-7)
    assert branches["l2"]["edited_cubics"] != l2_before
    assert branches["l3"]["edited_cubics"] != l3_before
    l3_root = branches["l3"]["edited_cubics"][0]["p0"]
    l2_points = core.sample_cubics(branches["l2"]["edited_cubics"])
    assert core.project_point_to_polyline(l3_root, l2_points)["distance"] < 1e-7


def test_initial_session_schema_validates_without_false_edits() -> None:
    session = core.validate_session(core.load_source())

    assert session["schema"] == core.SCHEMA
    assert session["edit_summary"]["modified_count"] == 0
    assert session["edit_summary"]["added_curve_ids"] == []
    assert session["edit_summary"]["deleted_curve_ids"] == []
    assert len(session["session_hash"]) == 64
    assert core.stable_hash(session) == session["session_hash"]


def test_illegal_parent_reference_is_rejected() -> None:
    payload = core.load_source()
    payload["branches"][0]["parent_id"] = "missing_parent"

    with pytest.raises(core.EditorValidationError, match="parent_id"):
        core.validate_session(payload)


def test_root_cannot_leave_its_parent() -> None:
    payload = core.load_source()
    payload["branches"][0]["edited_cubics"][0]["p0"] = [500.0, 500.0]

    with pytest.raises(core.EditorValidationError, match="根点离开父枝"):
        core.validate_session(payload)


def test_save_reload_hash_and_source_immutability(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "SESSION_ROOT", tmp_path / "sessions")
    before = core.file_sha256(core.RECORD_PATH)
    payload = core.load_source()
    branch = payload["branches"][0]
    old_points = core.sample_cubics(copy.deepcopy(branch["edited_cubics"]), 96)
    branch["edited_cubics"][0]["p3"][0] += 4.25
    branch["edited_cubics"][0]["p2"][0] += 4.25
    new_points = core.sample_cubics(branch["edited_cubics"], 96)
    core.propagate_descendants(
        core.branch_map(payload["branches"]),
        branch["curve_id"],
        old_points,
        new_points,
    )

    session_id, saved, directory = core.save_session(payload, session_id="pytest_replay")
    reloaded = core.load_session(session_id)

    assert directory == tmp_path / "sessions" / "pytest_replay"
    assert (directory / "session.json").is_file()
    assert (directory / "edited.svg").is_file()
    assert saved == reloaded
    assert saved["session_hash"] == reloaded["session_hash"]
    assert saved["branches"][0]["edited_cubics"] == reloaded["branches"][0]["edited_cubics"]
    assert saved["branches"][0]["mount_fraction"] == reloaded["branches"][0]["mount_fraction"]
    assert core.file_sha256(core.RECORD_PATH) == before


def test_failed_save_leaves_no_partial_directory(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    monkeypatch.setattr(core, "SESSION_ROOT", session_root)
    original_write = core._write_text

    def fail_on_svg(path: Path, content: str) -> None:
        if path.name == "edited.svg":
            raise OSError("simulated disk failure")
        original_write(path, content)

    monkeypatch.setattr(core, "_write_text", fail_on_svg)
    with pytest.raises(OSError, match="simulated"):
        core.save_session(core.load_source(), session_id="must_not_exist")

    assert not (session_root / "must_not_exist").exists()
    assert not list(session_root.glob(".tmp_direct_editor_*"))


def test_flask_api_rejects_non_allowlisted_access_and_replays(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "SESSION_ROOT", tmp_path / "sessions")
    client = app_module.create_app(4101).test_client()

    assert client.get("/").status_code == 200
    assert client.get("/api/bootstrap?seed=4102").status_code == 200
    assert client.get("/api/bootstrap?seed=9999").status_code == 400
    assert client.get("/api/sessions/not_here").status_code == 404
    bootstrap = client.get("/api/bootstrap?seed=4101").get_json()
    created = client.post("/api/sessions", json=bootstrap)
    assert created.status_code == 201
    metadata = created.get_json()
    loaded = client.get(f"/api/sessions/{metadata['session_id']}")
    assert loaded.status_code == 200
    assert loaded.get_json()["session_hash"] == metadata["session_hash"]
    index = client.get("/api/sessions?seed=4101")
    assert index.status_code == 200
    assert index.get_json()["aggregate"]["target_count"] == 1


def test_session_file_tampering_breaks_stable_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "SESSION_ROOT", tmp_path / "sessions")
    session_id, _, directory = core.save_session(core.load_source(), session_id="tamper_test")
    path = directory / "session.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["branches"][0]["edited_cubics"][0]["p1"][0] += 1
    path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(core.EditorValidationError, match="hash"):
        core.load_session(session_id)


def test_m3_direct_allowed_domains_save_and_reload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "SESSION_ROOT", tmp_path / "sessions")
    payload = core.load_source(4101)
    branch = payload["branches"][0]
    mount = branch["mount_fraction"]
    endpoint = branch["edited_cubics"][-1]["p3"]
    branch["constraints"]["root_mount_range"] = [mount - 0.01, mount + 0.02]
    branch["constraints"]["endpoint_region"] = {
        "type": "polygon",
        "classification": "allowed",
        "points": [
            [endpoint[0] - 6, endpoint[1] - 6],
            [endpoint[0] + 6, endpoint[1] - 6],
            [endpoint[0] + 6, endpoint[1] + 6],
            [endpoint[0] - 6, endpoint[1] + 6],
        ],
    }

    session_id, saved, _ = core.save_session(payload, session_id="m3_allowed")
    reloaded = core.load_session(session_id)

    assert reloaded == saved
    assert reloaded["branches"][0]["constraints"]["root_mount_range"] == pytest.approx(
        [mount - 0.01, mount + 0.02]
    )
    assert reloaded["branches"][0]["constraints"]["endpoint_region"]["classification"] == "allowed"


def test_m4_envelope_inference_intersection_and_forbidden_warning() -> None:
    payload = core.load_source(4101)
    branch = payload["branches"][0]
    branch["constraints"]["curve_envelope"] = {
        "boundary_a": [_cubic((0, 0), (3, 3), (7, 7), (10, 10))],
        "boundary_b": [_cubic((0, 10), (3, 7), (7, 3), (10, 0))],
    }
    root = branch["edited_cubics"][0]["p0"]
    payload["forbidden_regions"] = [
        {
            "region_id": "forbidden_test",
            "classification": "forbidden",
            "scope": "global",
            "target": None,
            "points": [
                [root[0] - 2, root[1] - 2],
                [root[0] + 2, root[1] - 2],
                [root[0] + 2, root[1] + 2],
                [root[0] - 2, root[1] + 2],
            ],
        }
    ]

    session = core.validate_session(payload)
    envelope = session["branches"][0]["constraints"]["curve_envelope"]
    warning_codes = {warning["code"] for warning in session["warnings"]}

    assert envelope["intersects"] is True
    assert len(envelope["polygon"]) == 130
    assert envelope["inferred"]["length_range"][0] > 0
    assert "curve_envelope_boundaries_intersect" in warning_codes
    assert "preferred_curve_enters_forbidden_region" in warning_codes


def test_m4_invalid_forbidden_scope_is_rejected() -> None:
    payload = core.load_source(4101)
    payload["forbidden_regions"] = [
        {
            "region_id": "bad_scope",
            "scope": "unit",
            "target": "secondary_1a_lat",
            "points": [[0, 0], [10, 0], [0, 10]],
        }
    ]
    with pytest.raises(core.EditorValidationError, match="Unit"):
        core.validate_session(payload)


def test_m5_add_delete_and_quantity_statuses() -> None:
    payload = core.load_source(4101)
    frame = core.frame_at_fraction(payload["backbone"]["points"], 0.15)
    root = frame["point"]
    tangent = frame["tangent"]
    endpoint = [root[0] + 24, root[1] - 30]
    payload["branches"].append(
        {
            "curve_id": "user_branch_pytest_added",
            "parent_id": "backbone",
            "level": 1,
            "role": "user_level_1",
            "kind": "user",
            "source": "user_drawn",
            "target_flower_id": None,
            "mount_fraction": 0.15,
            "original_mount_fraction": None,
            "width": 3.0,
            "status": "optional",
            "original_cubics": [],
            "edited_cubics": [
                _cubic(
                    root,
                    [root[0] + tangent[0] * 8, root[1] + tangent[1] * 8],
                    [endpoint[0] - 6, endpoint[1] + 6],
                    endpoint,
                )
            ],
            "constraints": {
                "root_mount_range": None,
                "endpoint_region": None,
                "curve_envelope": None,
            },
        }
    )
    deleted = {"primary_1_free", "secondary_1a_lat", "secondary_1b_lat"}
    payload["branches"] = [branch for branch in payload["branches"] if branch["curve_id"] not in deleted]

    session = core.validate_session(payload)

    assert session["edit_summary"]["added_curve_ids"] == ["user_branch_pytest_added"]
    assert set(session["edit_summary"]["deleted_curve_ids"]) == deleted
    added = next(branch for branch in session["branches"] if branch["curve_id"] == "user_branch_pytest_added")
    assert added["status"] == "optional"


def test_m5_orphan_after_parent_delete_is_rejected() -> None:
    payload = core.load_source(4101)
    payload["branches"] = [branch for branch in payload["branches"] if branch["curve_id"] != "primary_1_free"]
    with pytest.raises(core.EditorValidationError, match="不存在父枝"):
        core.validate_session(payload)


def test_m6_three_real_seeds_and_target_aggregate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "SESSION_ROOT", tmp_path / "sessions")
    sources = [core.load_source(seed) for seed in core.ALLOWED_SEEDS]
    assert len({source["source"]["source_geometry_hash"] for source in sources}) == 3
    for seed in core.ALLOWED_SEEDS:
        assert len(core.load_source(seed)["branches"]) == 21
    core.save_session(core.load_source(4101), session_id="seed4101_target_a")
    edited = core.load_source(4101)
    edited["branches"][0]["status"] = "optional"
    core.save_session(edited, session_id="seed4101_target_b")

    index = core.list_sessions(4101)
    assert index["aggregate"]["target_count"] == 2
    assert len(index["targets"]) == 2
    assert core.list_sessions(4102)["aggregate"]["target_count"] == 0


def test_legacy_m2_session_is_migrated_without_overwriting(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    monkeypatch.setattr(core, "SESSION_ROOT", session_root)
    session = core.validate_session(core.load_source(4101))
    for delta in session["edit_summary"]["curve_deltas"].values():
        delta.pop("constraints_changed")
        delta.pop("status_changed")
    session["session_hash"] = core.stable_hash(session)
    directory = session_root / "legacy_session"
    directory.mkdir(parents=True)
    path = directory / "session.json"
    path.write_text(json.dumps(session), encoding="utf-8")
    before = path.read_bytes()

    migrated = core.load_session("legacy_session")

    assert migrated["schema"] == core.SCHEMA
    assert "constraints_changed" in next(iter(migrated["edit_summary"]["curve_deltas"].values()))
    assert path.read_bytes() == before
