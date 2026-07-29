"""Local-only Flask entry point for the direct branch rule editor."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from typing import Any

from flask import Flask, jsonify, render_template, request

from editor_core import (
    ALLOWED_SEEDS,
    EditorError,
    EditorValidationError,
    SEED,
    load_session,
    load_source,
    list_sessions,
    save_session,
)


HOST = "127.0.0.1"
DEFAULT_PORT = 5127


def create_app(seed: int = SEED) -> Flask:
    if seed not in ALLOWED_SEEDS:
        raise EditorValidationError("只允许 seed 4101、4102、4103")
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(EDITOR_SEED=seed)
    app.json.ensure_ascii = False

    @app.get("/")
    def index() -> str:
        return render_template("editor.html", seed=seed)

    @app.get("/api/bootstrap")
    def bootstrap() -> Any:
        raw_seed = request.args.get("seed", str(seed))
        try:
            requested_seed = int(raw_seed)
        except ValueError:
            return jsonify({"error": "seed 必须是整数"}), 400
        try:
            return jsonify(load_source(requested_seed))
        except EditorValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except EditorError as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/api/sessions")
    def session_index() -> Any:
        raw_seed = request.args.get("seed", str(seed))
        try:
            requested_seed = int(raw_seed)
            return jsonify(list_sessions(requested_seed))
        except ValueError:
            return jsonify({"error": "seed 必须是整数"}), 400
        except EditorValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except EditorError as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/sessions")
    def create_session() -> Any:
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "请求体必须是 JSON"}), 400
        try:
            session_id, session, target = save_session(payload)
        except EditorValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except EditorError as exc:
            return jsonify({"error": str(exc)}), 409
        except OSError as exc:
            return jsonify({"error": f"保存失败且未保留半成品: {exc}"}), 500
        return (
            jsonify(
                {
                    "session_id": session_id,
                    "session_hash": session["session_hash"],
                    "session_url": f"/?session={session_id}",
                    "output_dir": str(target),
                }
            ),
            201,
        )

    @app.get("/api/sessions/<session_id>")
    def get_session(session_id: str) -> Any:
        try:
            return jsonify(load_session(session_id))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except EditorValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except EditorError as exc:
            return jsonify({"error": str(exc)}), 409

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="缠枝纹直接分支规则编辑器（M0-M6）")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.seed not in ALLOWED_SEEDS:
        raise SystemExit("只允许 --seed 4101、4102、4103")
    load_source(args.seed)
    url = f"http://{HOST}:{args.port}/"
    print(f"Direct Branch Rule Editor: {url}", flush=True)
    print("仅绑定 127.0.0.1；源 record 为只读。", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open_new(url)).start()
    create_app(args.seed).run(host=HOST, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
