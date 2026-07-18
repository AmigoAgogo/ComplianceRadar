from __future__ import annotations

from pathlib import Path
import sys
from datetime import UTC, datetime

from flask import Flask, jsonify, render_template, request, send_file

from app.services.ai import DemoAIService
from app.services.ingestion import DemoIngestionService
from app.store import JsonStateStore, append_jsonl


def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def resolve_runtime_root(app_root: Path) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "runtime"
    return app_root / "data" / "runtime"


def create_app(data_dir: Path | None = None) -> Flask:
    repo_root = resolve_app_root()
    runtime_root = data_dir or resolve_runtime_root(repo_root)
    service = DemoIngestionService(
        store=JsonStateStore(runtime_root / "state.json"),
        seeds_path=repo_root / "data" / "seeds" / "sample_events.json",
        sources_path=repo_root / "data" / "sources" / "demo_sources.json",
    )
    ai_service = DemoAIService()
    service.ai_service = ai_service

    app = Flask(
        __name__,
        template_folder=str(repo_root / "templates"),
        static_folder=str(repo_root / "static"),
    )

    @app.before_request
    def handle_local_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return ("", 204)

    @app.after_request
    def add_local_cors_headers(response):
        origin = request.headers.get("Origin", "")
        if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", title="ComplianceRadar POC")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/dashboard")
    def get_dashboard():
        return jsonify(service.bootstrap())

    @app.get("/api/agent-config")
    def get_agent_config():
        return jsonify(service.get_agent_context())

    @app.get("/api/events")
    def get_events():
        return jsonify(
            service.list_events(
                date_from=request.args.get("from"),
                date_to=request.args.get("to"),
            )
        )

    @app.get("/api/sources")
    def get_sources():
        return jsonify(service.list_sources())

    @app.get("/api/sources/<source_id>/diagnostics")
    def source_diagnostics(source_id: str):
        try:
            return jsonify(service.diagnose_source(source_id))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/sources/discover")
    def discover_source():
        payload = request.get_json(force=True)
        try:
            source = service.discover_source(payload["query"])
            return jsonify({"source": source})
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/sources")
    def add_source():
        try:
            return jsonify(service.add_source(request.get_json(force=True)))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.put("/api/sources/<source_id>")
    def update_source(source_id: str):
        try:
            return jsonify(service.update_source(source_id, request.get_json(force=True)))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/sources/<source_id>/status/<status>")
    def update_source_status(source_id: str, status: str):
        try:
            return jsonify(service.update_source_status(source_id, status))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.delete("/api/sources/<source_id>")
    def delete_source(source_id: str):
        return jsonify(service.delete_source(source_id))

    @app.post("/api/sources/<source_id>/preview")
    def preview_source(source_id: str):
        try:
            return jsonify(service.preview_source(source_id))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.get("/api/sources/<source_id>/latest")
    def latest_source_signal(source_id: str):
        try:
            return jsonify(service.fetch_latest_source_signal(source_id))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.post("/api/sources/<source_id>/live-workflow")
    def run_live_workflow(source_id: str):
        payload = request.get_json(force=True)
        try:
            return jsonify(
                service.run_live_workflow(
                    source_id=source_id,
                    keywords=payload.get("keywords", []),
                    limit=int(payload.get("limit", 5)),
                )
            )
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.post("/api/url-workflow")
    def run_url_workflow():
        payload = request.get_json(force=True)
        try:
            return jsonify(
                service.run_url_workflow(
                    url=payload["url"],
                    keywords=payload.get("keywords", []),
                    limit=int(payload.get("limit", 5)),
                )
            )
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.post("/api/sources/<source_id>/direct-article-workflow")
    def run_direct_article_workflow(source_id: str):
        payload = request.get_json(force=True)
        try:
            return jsonify(
                service.run_direct_article_workflow(
                    source_id=source_id,
                    article_url=payload["article_url"],
                    keywords=payload.get("keywords", []),
                )
            )
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.get("/api/models")
    def get_models():
        return jsonify(service.get_models())

    @app.post("/api/models")
    def add_model():
        try:
            return jsonify(service.add_model(request.get_json(force=True)))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.post("/api/models/catalog")
    def model_catalog():
        payload = request.get_json(force=True)
        try:
            models = ai_service.fetch_model_catalog(
                provider=payload["provider"],
                base_url=payload["base_url"],
                api_key=payload["api_key"],
            )
            return jsonify({"models": models})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.put("/api/models/<name>")
    def update_model(name: str):
        try:
            return jsonify(service.update_model(name, request.get_json(force=True)))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.delete("/api/models/<name>")
    def delete_model(name: str):
        return jsonify(service.delete_model(name))

    @app.post("/api/models/<name>/test")
    def test_model(name: str):
        models = service.get_models()
        profile = next((item for item in models["profiles"] if item["name"] == name), None)
        if profile is None:
            return jsonify({"error": f"Unknown model: {name}"}), 404
        return jsonify(ai_service.test_connection(profile))

    @app.post("/api/models/current/<name>")
    def set_model(name: str):
        try:
            return jsonify(service.set_current_model(name))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/events/<event_id>/review")
    def review_event(event_id: str):
        payload = request.get_json(force=True)
        try:
            event = service.apply_review(
                event_id=event_id,
                reviewer=payload["reviewer"],
                status=payload["status"],
                note=payload["note"],
            )
            return jsonify(event)
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.delete("/api/events/<event_id>")
    def delete_event(event_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.delete_event(event_id, deleted_by=payload.get("deleted_by", "local-user")))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/ai/chat")
    def chat():
        payload = request.get_json(force=True)
        models = service.get_models()
        dashboard = service.bootstrap()
        try:
            opinion_id = f"ai-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
            result = ai_service.chat(
                prompt=payload["prompt"],
                context=payload.get("context", "dashboard"),
                models=models,
                dashboard=dashboard,
            )
            result["opinion_id"] = opinion_id
            append_jsonl(
                runtime_root / "ai_opinions" / "llm_runs.jsonl",
                {
                    "opinion_id": opinion_id,
                    "action": "created",
                    "generated_at": result.get("generated_at"),
                    "model": result.get("model"),
                    "prompt": payload["prompt"],
                    "context": payload.get("context", "dashboard"),
                    "context_event_count": result.get("context_event_count"),
                    "agent_file_count": result.get("agent_file_count"),
                    "answer": result.get("answer"),
                },
            )
            return jsonify(result)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502

    @app.put("/api/ai/opinions/<opinion_id>")
    def edit_ai_opinion(opinion_id: str):
        payload = request.get_json(force=True)
        answer = payload.get("answer", "")
        if not answer.strip():
            return jsonify({"error": "answer is required"}), 400
        record = {
            "opinion_id": opinion_id,
            "action": "edited",
            "edited_at": datetime.now(UTC).isoformat(),
            "edited_by": payload.get("edited_by", "local-user"),
            "answer": answer,
        }
        append_jsonl(runtime_root / "ai_opinions" / "llm_runs.jsonl", record)
        return jsonify(record)

    @app.post("/api/demo/reset")
    def reset_demo():
        return jsonify(service.reset())

    @app.post("/api/sources/sync")
    def sync_sources():
        payload = request.get_json(silent=True) or {}
        return jsonify(
            service.sync_sources(
                source_ids=payload.get("source_ids"),
                period=payload.get("period"),
            )
        )

    @app.post("/api/reports/export")
    def export_reports():
        payload = request.get_json(silent=True) or {}
        return jsonify(service.export_reports(module=payload.get("module", "dashboard")))

    @app.get("/api/reports/download/<kind>")
    def download_report(kind: str):
        module = request.args.get("module", "dashboard")
        exports = service.export_reports(module=module)
        path = exports.get(kind)
        if not path:
            return jsonify({"error": "unknown report kind"}), 404
        return send_file(path, as_attachment=True)

    return app


app = create_app()
