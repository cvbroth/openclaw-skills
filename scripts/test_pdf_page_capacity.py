"""Real HTTP PDF page boundary; enqueue stub prevents all recognition calls."""

import argparse
import http.client
import json
from pathlib import Path
import resource
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import fitz
from nas_filetools.standalone.config import load
from nas_filetools.standalone.http import Handler
from nas_filetools.standalone.tasks import Projects


def run(config, output):
    with tempfile.TemporaryDirectory(prefix="pdf-page-capacity-") as directory:
        root = Path(directory)
        settings = load(config)
        assert settings["service"]["max_pages"] == 1000
        assert settings["service"]["upload_bytes"] == 536870912
        fixtures = {}
        for pages in [1, 999, 1000, 1001]:
            path = root / f"synthetic-{pages}.pdf"
            with fitz.open() as doc:
                for _ in range(pages):
                    doc.new_page()
                doc.save(path)
            fixtures[pages] = path
        manager = Projects(root / "data", settings)
        manager.enqueue = lambda pid, *a, **k: {"project_id": pid, "task_id": "upload-only-test"}
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.manager = manager
        threading.Thread(target=server.serve_forever, daemon=True).start()
        results = []
        try:
            with (
                patch.object(
                    fitz.Document, "load_page", side_effect=AssertionError("upload must not load pages")
                ) as loaded,
                patch.object(
                    fitz.Page, "get_text", side_effect=AssertionError("upload must not extract text")
                ) as extracted,
                patch.object(
                    fitz.Page, "get_pixmap", side_effect=AssertionError("upload must not render")
                ) as rendered,
            ):
                for pages, path in fixtures.items():
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
                    start = time.monotonic()
                    try:
                        with path.open("rb") as stream:
                            connection.request(
                                "POST",
                                "/api/uploads?filename=synthetic.pdf&engine=local&pages=1",
                                stream,
                                {"Content-Length": str(path.stat().st_size)},
                            )
                            response = connection.getresponse()
                            data = json.loads(response.read())
                        record = {
                            "physical_pages": pages,
                            "bytes": path.stat().st_size,
                            "status": response.status,
                            "seconds": time.monotonic() - start,
                        }
                        if pages <= 1000:
                            assert response.status == 202, data
                            project = manager.get(data["project_id"])
                            assert project["source_info"] == {"kind": "pdf", "units": pages}
                            assert project["tasks"] == []
                            record["registered_pages"] = project["source_info"]["units"]
                        else:
                            assert response.status == 400 and "PAGE_LIMIT" in data["reason"], data
                            assert "1001" in data["reason"] and "1000" in data["reason"]
                            record["error"] = data
                        assert not list((manager.root / "uploads").iterdir())
                        results.append(record)
                    finally:
                        connection.close()
                result = {
                    "results": results,
                    "pdf_limit_inclusive": 1000,
                    "upload_bytes": settings["service"]["upload_bytes"],
                    "max_selected_pages": settings["conversion"]["max_selected_pages"],
                    "upload_page_load_calls": loaded.call_count,
                    "upload_text_extract_calls": extracted.call_count,
                    "upload_raster_calls": rendered.call_count,
                    "temporary_upload_files_remaining": 0,
                    "engine_calls": 0,
                    "conversion_verified": False,
                    "fixture": "synthetic blank-page PDFs; validation only",
                    "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                }
                target = Path(output)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps(result, ensure_ascii=False))
        finally:
            server.shutdown()
            server.server_close()
            manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.config, args.output)
