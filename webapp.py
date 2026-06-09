"""Local JobScouting web app (Flask).

Run:  python main.py --web   (or just `python main.py`, the default)

One page: upload the CV (PDF/TXT), the model extracts the profile, you confirm
the fields, you launch the automation (Adzuna fetch + scoring). Progress arrives
in real time via SSE; at the end of the job the report is shown as HTML.

A thin layer over the existing functions (init_profile, scorer, adzuna, report,
profile_loader): no duplicated domain logic. 127.0.0.1 only, single-user.
"""

import io
import json
import os
import queue
import sys
import tempfile
import threading
import webbrowser

import markdown
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

import config
import init_profile
import main as main_mod
import profile_loader

app = Flask(__name__)

# State of a single job (local single-user: one automation at a time).
_job = {
    "thread": None,
    "queue": queue.Queue(),
    "status": "idle",   # idle | running | done | error
    "report_html": None,
    "error": None,
}
_job_lock = threading.Lock()
_DONE = "__DONE__"


class _QueueWriter(io.TextIOBase):
    """Stream that mirrors to `mirror` and enqueues lines for the SSE."""

    def __init__(self, q: queue.Queue, mirror):
        self._q = q
        self._mirror = mirror
        self._buf = ""

    def write(self, s: str) -> int:
        try:
            self._mirror.write(s)
        except Exception:
            pass
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._q.put(line)
        return len(s)

    def flush(self):
        try:
            self._mirror.flush()
        except Exception:
            pass


def _run_job(profile, path: str) -> None:
    """Runs the pipeline capturing stdout/stderr into the SSE queue."""
    q = _job["queue"]
    old_out, old_err = sys.stdout, sys.stderr
    writer = _QueueWriter(q, old_err)
    try:
        sys.stdout = writer
        sys.stderr = writer
        main_mod.run_pipeline(profile, path, echo_report=False)
        sys.stdout, sys.stderr = old_out, old_err
        with open(config.LATEST_REPORT_PATH, encoding="utf-8") as fh:
            md = fh.read()
        _job["report_html"] = markdown.markdown(
            md, extensions=["extra", "sane_lists", "nl2br"])
        _job["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - show the error in the page
        sys.stdout, sys.stderr = old_out, old_err
        _job["status"] = "error"
        _job["error"] = f"{type(exc).__name__}: {exc}"
        q.put(f"[error] {_job['error']}")
    finally:
        q.put(_DONE)


@app.get("/")
def index():
    countries = [{"code": c, "name": config.country_name(c)}
                 for c in config.REMOTE_COUNTRIES]
    factors = [{"key": k, "label": f["label"],
                "weight": f["weight"], "core": k in config.DEFAULT_FACTORS}
               for k, f in config.FACTORS.items()]
    return render_template("index.html",
                           backend=config.SCORER_BACKEND,
                           countries=countries,
                           factors=factors,
                           max_factors=config.MAX_RECOMMENDED_FACTORS,
                           default_top_n=config.DEFAULT_TOP_N)


@app.post("/extract")
def extract():
    """Upload CV -> extract profile fields. Returns prefilled JSON."""
    file = request.files.get("cv")
    if not file or not file.filename:
        return jsonify(error="No file uploaded."), 400
    language = (request.form.get("language") or "english").strip()

    suffix = os.path.splitext(file.filename)[1].lower() or ".pdf"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        file.save(tmp)
        try:
            cv_text = init_profile._read_cv_file(tmp)
        except Exception as exc:  # noqa: BLE001
            return jsonify(error=f"Failed to read CV: {exc}"), 400
        if not cv_text.strip():
            return jsonify(error="No extractable text in the CV "
                                 "(maybe a scan)."), 400
        try:
            data = init_profile._extract_profile(cv_text, language)
        except Exception as exc:  # noqa: BLE001
            return jsonify(error=f"Extraction failed: {exc}"), 502
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    kept, dropped = init_profile._filter_broad(data["keywords"])
    data["keywords"] = kept or data["keywords"]
    data["dropped_keywords"] = dropped
    return jsonify(data)


@app.post("/run")
def run():
    """Saves the profile from the confirmed fields and starts the pipeline in background."""
    with _job_lock:
        if _job["status"] == "running":
            return jsonify(error="An automation is already running."), 409

        missing = main_mod._missing_requirements()
        if missing:
            return jsonify(error="Missing prerequisites: " + "; ".join(missing)), 400

        d = request.get_json(force=True)
        name = (d.get("name") or "").strip()
        city = (d.get("city") or "").strip()
        if not name or not city:
            return jsonify(error="Name and city are required."), 400
        country = (d.get("country") or "it").strip().lower()
        language = (d.get("language") or "english").strip()
        remote = bool(d.get("remote", True))
        try:
            distance = int(d.get("distance", 50))
        except (TypeError, ValueError):
            distance = 50
        try:
            top_n = int(d.get("top_n", config.DEFAULT_TOP_N))
        except (TypeError, ValueError):
            top_n = config.DEFAULT_TOP_N
        top_n = max(1, top_n)
        keywords = [k.strip() for k in (d.get("keywords") or []) if str(k).strip()]
        extra = [k.strip() for k in (d.get("remote_extra_keywords") or [])
                 if str(k).strip()]
        if not keywords:
            return jsonify(error="At least one keyword is required."), 400

        # weights: {factor_key: relative value} on the active factors. Kept raw
        # here (positive floats only); the loader validates keys against the
        # catalog and auto-normalizes to 1.0.
        raw_w = d.get("weights") or {}
        weights = {}
        for k, v in raw_w.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                weights[k] = fv
        weights = weights or None

        remote_desc = ("also looking for full remote work (EU)" if remote
                       else "prefers on-site or hybrid near home")
        profile_text = ((d.get("profile_text") or "").rstrip()
                        + f"\n\nLocation and preferences: lives in {city}; {remote_desc}.")

        # Remote countries: only the selected ones (filtered to known); default all.
        if remote:
            chosen = [c.strip().lower() for c in (d.get("remote_countries") or [])]
            remote_countries = ([c for c in config.REMOTE_COUNTRIES if c in chosen]
                                if chosen else list(config.REMOTE_COUNTRIES))
        else:
            remote_countries = []
        toml_str = init_profile._render_toml(
            name=name, language=language, city=city, country=country,
            distance=distance, remote=remote, remote_countries=remote_countries,
            keywords=keywords, remote_extra_keywords=extra,
            profile_text=profile_text, weights=weights, top_n=top_n,
        )
        path = config.ACTIVE_PROFILE
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(toml_str)
        try:
            profile = profile_loader.load_profile(path)
        except profile_loader.ProfileError as exc:
            return jsonify(error=f"Generated profile is invalid: {exc}"), 500

        # reset job state and start thread
        _job.update(status="running", report_html=None, error=None,
                    queue=queue.Queue())
        _job["thread"] = threading.Thread(
            target=_run_job, args=(profile, path), daemon=True)
        _job["thread"].start()
    return jsonify(ok=True, profile=path)


@app.get("/progress")
def progress():
    """SSE stream of the log lines until the job finishes."""
    def gen():
        q = _job["queue"]
        while True:
            line = q.get()
            if line == _DONE:
                payload = {"status": _job["status"], "error": _job["error"]}
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                return
            yield f"data: {json.dumps(line)}\n\n"
    return Response(gen(), mimetype="text/event-stream")


@app.get("/report")
def report_html():
    return jsonify(html=_job["report_html"] or "",
                   status=_job["status"], error=_job["error"])


def serve(host: str = "127.0.0.1", port: int = 5000) -> None:
    load_dotenv()
    main_mod._force_utf8_io()
    url = f"http://{host}:{port}/"
    print(f"[web] JobScouting at {url}  (Ctrl+C to stop)", file=sys.stderr)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # threaded=True: SSE + requests in parallel. No reloader (job thread).
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    serve()
