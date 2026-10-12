"""Flask web application and JSON API: scanned PDF or photo(s) of Form 1A in, JSON out.

Routes
  GET  /                          built-in upload + review page
  POST /api/extract               multipart field "file": one PDF, or photos in page order
                                  (page 1 first). ?form=<id> skips edition detection,
                                  ?review=1 adds field pictures, sections and a job id
  POST /api/inspect               one photo: which edition and page it is, is anything written
  POST /api/validate              {"data": {...}}: logic checks (app/validation_rules.json)
  GET  /api/rules                 the logic-check settings currently in force
  GET  /api/lookups               official name lists (districts...) from the lookup service
  POST /api/lookups/refresh       load them again now (app/lookup_settings.json)
  POST /api/jobs/<id>/confirm     {"data": {...}, "sections_confirmed": ["A", ...]}
                                  saves the record (no training samples: see the Training page);
                                  refused (422) while a logic check of severity "error" fails
  GET  /api/enrolments            saved records (newest first): ?q=<text>&limit=&offset=
  GET  /api/enrolments/<id>       one saved record
  GET  /api/stats                 numbers and breakdowns for the dashboard
  GET  /api/training              Training page dashboard: samples, accuracy per character, advice
       /api/training/...          upload page-1 photos, check them, train, install (app/training.py)
  GET  /api/health                status, form editions, model files

Set FORMREADER_ALLOW_ORIGIN to the address of another web app (for example the
Next.js frontend, http://localhost:3000) to let a browser call this API directly.
Default "*" allows any origin; this API is meant to run on a private network.
"""
import base64
import datetime as dt
import json
import os
import re
import shutil
import threading
import time
import uuid
from urllib.parse import unquote
from collections import Counter

import cv2
from flask import Flask, abort, jsonify, render_template, request, send_file

from .extractor import FormExtractor, label_for
from .imaging import IMAGE_TYPES
from .lookups import Lookups
from .training import SAMPLES_DIR, FormLocked, Trainer
from . import store
from .validation import has_errors, load_rules, validate

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# where uploads and saved records go (FORMREADER_DATA_DIR: the phone app keeps them in its own storage)
DATA_DIR = os.environ.get("FORMREADER_DATA_DIR") or os.path.join(BASE, "data")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")          # temporary per-upload files
OUTPUT_DIR = os.path.join(DATA_DIR, "output")      # confirmed JSON records
MODEL_DIR = os.path.join(BASE, "app", "model")
JOB_TTL_DAYS = 7
MAX_UPLOAD_MB = 40
ALLOW_ORIGIN = os.environ.get("FORMREADER_ALLOW_ORIGIN", "*")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.json.sort_keys = False  # keep the form's field order in JSON output

lookups = Lookups()            # official district (and later region, ward...) names
extractor = FormExtractor(lookups=lookups)
_lock = threading.Lock()  # one extraction at a time keeps memory low on an 8 GB machine
# the Training page (reads page-1 photos in the background); not in the phone app (FORMREADER_NO_TRAINING=1)
trainer = None if os.environ.get("FORMREADER_NO_TRAINING") else Trainer(extractor, _lock)


@app.before_request
def _no_training():
    if trainer is None and request.path.startswith("/api/training"):
        return jsonify(error="Reader Training is not available in this version."), 404


def _warm_up():
    """Prepare the second matching method (SIFT points of every reference page and its other
    looks) in the background, so the first photo after starting is not slow. Page by page,
    under the reading lock, so a photo being checked is never held up for long."""
    for lay in extractor.layouts:
        for al in lay.aligners:
            with _lock:
                try:
                    al._sift_reference()
                except Exception:
                    app.logger.exception("preparing the second matching method failed")


threading.Thread(target=_warm_up, daemon=True).start()


@app.after_request
def _cors(resp):
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = ALLOW_ORIGIN
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Staff-Client, X-Staff-Name"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def _preflight(_):
    return ("", 204)


def _png_data_url(img):
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _endorse_summary(e):
    """What was found in the signature / stamp boxes, without pictures, for the saved record."""
    if not e:
        return None
    return {i["id"]: {"numbers": i.get("numbers"), "stamp": i["stamp"], "writing": i["writing"],
                      "missing": i["missing"]} for i in e.get("items", [])}


def _cleanup_old_jobs():
    if not os.path.isdir(JOBS_DIR):
        return
    cutoff = time.time() - JOB_TTL_DAYS * 86400
    for d in os.listdir(JOBS_DIR):
        p = os.path.join(JOBS_DIR, d)
        if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
            shutil.rmtree(p, ignore_errors=True)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    models = {}
    for f in ("char_cnn.npz", "char_mlp.npz"):
        p = os.path.join(MODEL_DIR, f)
        if os.path.exists(p):
            models[f] = dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="minutes")
    return {"status": "ok", "version": "6",
            "forms": [{"id": l.id, "title": l.title, "pages": l.n_pages,
                       "fields": len([g for g in l.groups.values() if g[0]["type"] != "image"])}
                      for l in extractor.layouts],
            "models": models, "lookups": lookups.status,
            "database": {"path": os.path.relpath(store.DB_PATH, BASE), "records": store.count()}}


@app.post("/api/inspect")
def inspect():
    """Quick look at ONE photo before reading: which edition, which page, empty or not.
    It never rejects a photo; the app shows what it found and the user decides."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file uploaded. Send one photo in a form field named 'file'."), 400
    blob = f.read()
    if not (blob[:4] == b"%PDF" or f.filename.lower().endswith(IMAGE_TYPES)):
        return jsonify(error=f"{f.filename}: please upload a photo (JPG or PNG) or a PDF."), 400
    try:
        with _lock:
            return jsonify(extractor.inspect(blob))
    except ValueError as e:
        return jsonify(error=str(e)), 422
    except Exception as e:
        app.logger.exception("inspect failed")
        return jsonify(error=f"Could not open this file: {e}"), 500


@app.post("/api/validate")
def validate_route():
    body = request.get_json(silent=True) or {}
    data = body.get("data")
    if not isinstance(data, dict):
        return jsonify(error="Send the record as {\"data\": {...}}."), 400
    issues = validate(data, lookups=lookups)
    return jsonify(issues=issues, errors=sum(i["severity"] == "error" for i in issues),
                   warnings=sum(i["severity"] == "warning" for i in issues))


@app.get("/api/rules")
def rules_route():
    return jsonify(load_rules())


@app.get("/api/lookups")
def lookups_route():
    lookups.refresh_soon()
    return jsonify(lookups.public())


@app.post("/api/lookups/refresh")
def lookups_refresh():
    lookups.refresh(force=True)
    return jsonify(lookups.status)


@app.post("/api/extract")
def extract():
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        return jsonify(error="No file uploaded. Send a PDF or photo(s) in a form field named 'file'."), 400
    blobs = [f.read() for f in files]
    for f, b in zip(files, blobs):
        if not (b[:4] == b"%PDF" or f.filename.lower().endswith(IMAGE_TYPES)):
            return jsonify(error=f"{f.filename}: please upload a PDF or a photo (JPG or PNG)."), 400
    form_id = request.args.get("form") or None
    if form_id and form_id not in extractor.by_id:
        return jsonify(error=f"Unknown form '{form_id}'."), 400
    name = ", ".join(f.filename for f in files)
    lookups.refresh_soon()
    try:
        with _lock:
            result, layout, aligned, readings = extractor.run(blobs, form_id)
    except ValueError as e:
        return jsonify(error=str(e)), 422
    except Exception as e:  # corrupt file etc.
        app.logger.exception("extraction failed")
        return jsonify(error=f"Could not read this file: {e}"), 500

    # A complete form has every page (page 1 AND page 2): refuse a partial upload.
    missing = result.pop("pages_missing", [])
    if missing and request.args.get("allow_missing_pages") != "1":
        return jsonify(error=f"This form has {layout.n_pages} pages but only {layout.n_pages - len(missing)} "
                             f"{'was' if layout.n_pages - len(missing) == 1 else 'were'} uploaded. "
                             f"Upload the photo of page {', '.join(map(str, missing))} as well."), 422
    # Enrolment values from the lookup: tick boxes -> lookup values (MALE, SELF-EMPLOYED...),
    # postcodes filled in from the chosen region + district + ward.
    data = result["data"]
    postcode_written = {f: data.get(f) for f, _ in lookups.postcode_groups}
    for f in lookups.map_choices(data):
        if f not in result["needs_review"]:
            result["needs_review"].append(f)
    if lookups.entries.get("region"):
        lookups.fill_postcodes(data)
        result["needs_review"] = [f for f in result["needs_review"] if f not in postcode_written]
    result["issues"] = validate(data, lookups=lookups)
    matches = result.pop("lookup_matches", {})
    if lookups.field_list and not any(lookups.entries.values()):
        result["warnings"].append(f"The region, district and ward lists could not be loaded from {lookups.url} "
                                  f"({lookups.status.get('error')}). These fields are typed in by hand.")

    if request.args.get("review") != "1":
        return jsonify(result)

    # Review mode: keep the handwriting of every filled box so corrections can train the model.
    _cleanup_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(os.path.join(job_dir, "cells"))
    cells_meta, by_name = {}, {}
    for fname, entries in layout.groups.items():
        kind = entries[0]["type"]
        field = {"name": fname, "label": label_for(fname), "type": kind,
                 "value": result["data"].get(fname),
                 "flagged": fname in result["needs_review"],
                 "page": entries[0]["page"],
                 "image": _png_data_url(layout.field_strip(
                     aligned, fname, height=120 if kind == "image" else 56,
                     max_boxes=layout.written_extent(readings, fname) if kind in ("alpha", "digit", "alnum") else None,
                     pad_left=230 if kind == "check" else None))}
        if kind == "check":
            # values from the lookup when it has them (MALE / FEMALE...), else the form's own
            field["options"] = lookups.choice_options(fname) or [e["value"] for e in entries]
        if fname in postcode_written and lookups.entries.get("region"):
            field["postcode_parts"] = lookups.postcode_parts(fname)   # filled in, not typed
            field["read_as"] = postcode_written[fname]
        list_name = lookups.for_field(fname)
        if list_name:                       # chosen from the official list (dropdown)
            field["lookup"] = list_name
            field["parent_field"] = lookups.parent_field(fname)
            field.update(matches.get(fname, {}))
        # (no handwriting is kept from enrolments for training: see the Training page)
        by_name[fname] = field
    fields = [f for f in by_name.values() if f["type"] != "image"]   # flat list (built-in page)

    # Grouped like the paper form: pages -> sections -> fields (used by the Next.js app)
    pages = []
    for p in range(layout.n_pages):
        secs = []
        for sec in layout.sections:
            if sec["page"] != p:
                continue
            items = []
            for meta_f in sec["fields"]:
                f = dict(by_name[meta_f["name"]], label=meta_f["label"], label_en=meta_f["label_en"])
                flag = meta_f.get("attached_flag")
                if flag:
                    f["attached"] = {"name": flag, "value": by_name[flag]["value"],
                                     "image": by_name[flag]["image"]}
                items.append(f)
            secs.append({"id": sec["id"], "title": sec["title"], "subtitle": sec["subtitle"],
                         "page": p, "fields": items})
        pages.append({"index": p, "supplied": aligned[p] is not None, "sections": secs})
    with open(os.path.join(job_dir, "meta.json"), "w") as fh:
        json.dump({"filename": name, "form": layout.id, "created": time.time(),
                   "needs_review": result["needs_review"],
                   "predicted": result["data"], "cells": cells_meta,
                   "endorsements": _endorse_summary(result.get("endorsements"))}, fh)
    result.update(job_id=job_id, fields=fields, pages=pages, page_count=layout.n_pages, filename=name,
                  lookups=lookups.compact())
    return jsonify(result)


@app.post("/api/jobs/<job_id>/confirm")
def confirm(job_id):
    if not job_id.isalnum():
        abort(404)
    job_dir = os.path.join(JOBS_DIR, job_id)
    meta_path = os.path.join(job_dir, "meta.json")
    if not os.path.exists(meta_path):
        return jsonify(error="This upload has expired. Please upload the file again."), 404
    body = request.get_json(silent=True) or {}
    data = body.get("data")
    if not isinstance(data, dict):
        return jsonify(error="Send the corrected record as {\"data\": {...}}."), 400
    with open(meta_path) as fh:
        meta = json.load(fh)

    # Only keep known fields, in form order; clean text the same way as extraction does.
    layout = extractor.by_id.get(meta.get("form"), extractor.layouts[0])
    final = {}
    for name, entries in layout.groups.items():
        kind = entries[0]["type"]
        if kind == "image":
            continue
        v = data.get(name, meta["predicted"].get(name))
        if kind == "flag":
            v = bool(v)
        elif isinstance(v, str):
            v = " ".join(v.split())
            if kind != "check":  # handwritten fields are block capitals
                v = v.upper()
            v = v or None
        final[name] = v

    # Postcodes always follow the chosen region, district and ward (they cannot be typed).
    if lookups.entries.get("region"):
        lookups.fill_postcodes(final)

    # Logic checks (app/validation_rules.json): errors must be corrected before saving.
    issues = validate(final, lookups=lookups)
    if has_errors(issues):
        return jsonify(error="Some values break the form's rules. Correct them before saving.",
                       issues=issues), 422

    # Enrolment does not collect training samples: the saved values are the correct record
    # (official place names, corrected spellings), not always what is written. Training is
    # done on the Training page (app/training.py), where staff type exactly what is written.

    # How much did the reviewer have to change? (for the dashboard)
    pred = meta["predicted"]
    chars_total = chars_fixed = fields_fixed = 0
    for name, v in final.items():
        p = pred.get(name)
        if v != p:
            fields_fixed += 1
        if isinstance(v, str) and layout.groups[name][0]["type"] not in ("check", "flag"):
            a, b = v.replace(" ", ""), (p or "").replace(" ", "")
            chars_total += len(a)
            chars_fixed += sum(x != y for x, y in zip(a, b)) + max(0, len(a) - len(b))

    record = {
        "id": job_id, "form": layout.id, "form_title": layout.title,
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_files": meta.get("filename"),
        "sections_confirmed": [str(x) for x in body.get("sections_confirmed", [])],
        "review": {"fields_flagged": len(meta.get("needs_review", [])), "fields_corrected": fields_fixed,
                   "characters_total": chars_total, "characters_corrected": chars_fixed},
        "data": final,
        # ids in your lookup of every value chosen from a list (sex, marital status, country,
        # region, district, ward...), to pass on to your own system
        "lookup_ids": lookups.lookup_ids(final),
        # signatures and stamps found on page 2 when it was read (app/endorsements.py)
        "endorsements": meta.get("endorsements"),
    }
    store.save(record)                     # the database (app/store.py)...
    os.makedirs(OUTPUT_DIR, exist_ok=True)   # ...and a plain JSON copy, as before
    out_path = os.path.join(OUTPUT_DIR, f"{job_id}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    shutil.rmtree(os.path.join(job_dir, "cells"), ignore_errors=True)
    return jsonify(id=job_id, data=final,
                   saved_to=f"{os.path.relpath(store.DB_PATH, BASE)} (copy: {os.path.relpath(out_path, BASE)})",
                   training_samples_added=0, characters_corrected=chars_fixed,
                   fields_corrected=fields_fixed)


# ---------------------------------------------------------------- saved records
def _normalise(fn, r):
    """A record as read from data/output/<fn> (records saved by an older version are only the data)."""
    if "data" not in r:
        r = {"id": fn[:-5], "form": r.pop("form", None), "data": r,
             "saved_at": dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(OUTPUT_DIR, fn)))
             .isoformat(timespec="seconds")}
    r.setdefault("id", fn[:-5])
    return r


# saved enrolments live in the SQLite database data/enrolments.db (app/store.py); records saved
# as JSON files by an earlier version are added to it once, here
store.import_folder(OUTPUT_DIR, _normalise)


def _load_records():
    return store.all_records()


def _summary(r):
    d = r.get("data", {})
    name = " ".join(x for x in (d.get("first_name"), d.get("middle_name"), d.get("last_name")) if x)
    return {"id": r["id"], "name": name or "(no name)", "sex": d.get("sex"),
            "date_of_birth": d.get("date_of_birth"),
            "region": d.get("residence_region") or d.get("birth_region"),
            "phone_number": d.get("phone_number"), "form": r.get("form"),
            "saved_at": r.get("saved_at"), "fields_corrected": r.get("review", {}).get("fields_corrected")}


@app.get("/api/enrolments")
def enrolments():
    q = (request.args.get("q") or "").strip().upper()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    rows = [_summary(r) for r in _load_records()]
    if q:
        rows = [x for x in rows if q in " ".join(str(v) for v in x.values() if v).upper()]
    return jsonify(total=len(rows), items=rows[offset:offset + limit])


@app.get("/api/enrolments/<rid>")
def enrolment(rid):
    if not rid.isalnum():
        abort(404)
    r = store.get(rid)
    if r is None:
        return jsonify(error="Record not found."), 404
    return jsonify(r)


def _age(dob, today):
    try:
        d, m, y = (int(x) for x in dob.split("/"))
        born = dt.date(y, m, d)
    except (ValueError, AttributeError):
        return None
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 <= age < 120 else None


def _key(v):
    """Same key for old and new values: 'male' and 'MALE', 'self_employed' and 'SELF-EMPLOYED'."""
    return re.sub(r"[^a-z0-9]+", "_", str(v).lower()).strip("_") if v else "unknown"


@app.get("/api/stats")
def stats():
    recs = _load_records()
    today = dt.date.today()
    days = int(request.args.get("days", 30))
    per_day = Counter()
    sex, marital, employment, region, edition, ages = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    chars_total = chars_fixed = fields_fixed = flagged = reviewed = 0
    bands = [(0, 17, "0-17"), (18, 25, "18-25"), (26, 35, "26-35"), (36, 45, "36-45"),
             (46, 60, "46-60"), (61, 200, "61+")]
    for r in recs:
        d = r.get("data", {})
        try:
            day = dt.date.fromisoformat((r.get("saved_at") or "")[:10])
            per_day[day] += 1
        except ValueError:
            pass
        sex[_key(d.get("sex"))] += 1
        marital[_key(d.get("marital_status"))] += 1
        employment[_key(d.get("employment_status"))] += 1
        region[d.get("residence_region") or d.get("birth_region") or "unknown"] += 1
        edition[r.get("form") or "unknown"] += 1
        a = _age(d.get("date_of_birth"), today)
        if a is not None:
            ages[next(lbl for lo, hi, lbl in bands if lo <= a <= hi)] += 1
        rv = r.get("review")
        if rv:
            reviewed += 1
            chars_total += rv.get("characters_total", 0)
            chars_fixed += rv.get("characters_corrected", 0)
            fields_fixed += rv.get("fields_corrected", 0)
            flagged += rv.get("fields_flagged", 0)
    series = [{"date": (today - dt.timedelta(days=i)).isoformat(),
               "count": per_day.get(today - dt.timedelta(days=i), 0)} for i in range(days - 1, -1, -1)]
    week = sum(x["count"] for x in series[-7:])
    prev_week = sum(per_day.get(today - dt.timedelta(days=i), 0) for i in range(7, 14))
    titles = {l.id: l.title for l in extractor.layouts}
    samples = sum(len(fs) for _, _, fs in os.walk(SAMPLES_DIR)) if os.path.isdir(SAMPLES_DIR) else 0
    return jsonify(
        total=len(recs), today=per_day.get(today, 0), this_week=week, previous_week=prev_week,
        per_day=series,
        sex=dict(sex), marital_status=dict(marital), employment_status=dict(employment),
        regions=dict(region.most_common(8)),
        age_bands={lbl: ages.get(lbl, 0) for _, _, lbl in bands},
        editions={titles.get(k, k): v for k, v in edition.items()},
        accuracy={"reviewed_records": reviewed, "characters_total": chars_total,
                  "characters_corrected": chars_fixed,
                  "auto_read_rate": round(1 - chars_fixed / chars_total, 4) if chars_total else None,
                  "fields_corrected_per_form": round(fields_fixed / reviewed, 2) if reviewed else None,
                  "fields_flagged_per_form": round(flagged / reviewed, 2) if reviewed else None},
        training_samples=samples,
        recent=[_summary(r) for r in recs[:8]])


# ---------------------------------------------------------------- Training page (app/training.py)
@app.get("/api/training")
def training_stats():
    return jsonify(trainer.stats())


def _staff():
    """Who is calling: a random id per browser tab and the name typed on the Training page
    (sent by the portal as X-Staff-Client / X-Staff-Name). Used to keep one person per form."""
    return (request.headers.get("X-Staff-Client", "")[:64],
            unquote(request.headers.get("X-Staff-Name", ""))[:40])


@app.get("/api/training/forms")
def training_forms():
    return jsonify(items=trainer.forms(_staff()[0]))


@app.post("/api/training/forms")
def training_upload():
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        return jsonify(error="No file uploaded. Send photos of page 1 in a form field named 'file'."), 400
    added, refused = [], []
    for f in files:
        blob = f.read()
        if not (blob[:4] == b"%PDF" or f.filename.lower().endswith(IMAGE_TYPES)):
            refused.append(f"{f.filename}: not a photo (JPG or PNG)")
            continue
        added.append(trainer.add(f.filename, blob)["id"])
    return jsonify(added=len(added), ids=added, refused=refused)


def _tform(fid, fn):
    try:
        return jsonify(fn(fid))
    except KeyError:
        return jsonify(error="This training form does not exist (any more)."), 404
    except FormLocked as e:
        return jsonify(error=str(e), lock=e.info), 423
    except ValueError as e:
        return jsonify(error=str(e)), 409


def _mine(fn):
    """Run fn(fid) only if nobody else is checking the form."""
    def run(fid):
        trainer.check_lock(fid, _staff()[0])
        return fn(fid)
    return run


@app.get("/api/training/forms/<fid>")
def training_form(fid):
    return _tform(fid, trainer.detail)


@app.get("/api/training/forms/<fid>/photo")
def training_photo(fid):
    try:
        return send_file(trainer.photo_path(fid))
    except KeyError:
        abort(404)


@app.post("/api/training/forms/<fid>/confirm")
def training_confirm(fid):
    values = (request.get_json(silent=True) or {}).get("values") or {}
    return _tform(fid, _mine(lambda i: trainer.confirm(i, values)))


@app.post("/api/training/forms/<fid>/lock")
def training_lock(fid):
    """Open a form for checking; the checking screen repeats this every 30 s while it is open.
    423 when someone else has it open (with their name)."""
    body = request.get_json(silent=True) or {}
    client, name = _staff()
    return _tform(fid, lambda i: trainer.hold(i, client, name, body.get("idle_seconds", 0), bool(body.get("take_over"))))


@app.post("/api/training/forms/<fid>/unlock")
def training_unlock(fid):
    return _tform(fid, lambda i: trainer.release(i, _staff()[0]))


@app.post("/api/training/next")
def training_next():
    """Open the next form waiting to be checked that nobody else has open."""
    body = request.get_json(silent=True) or {}
    client, name = _staff()
    try:
        return jsonify(trainer.next_form(client, name, body.get("after")))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.post("/api/training/forms/<fid>/skip")
def training_skip(fid):
    return _tform(fid, _mine(trainer.skip))


@app.post("/api/training/forms/<fid>/retry")
def training_retry(fid):
    return _tform(fid, _mine(trainer.retry))


@app.post("/api/training/forms/<fid>/test")
def training_set_test(fid):
    test = bool((request.get_json(silent=True) or {}).get("test"))
    return _tform(fid, lambda i: trainer.set_test(i, test))


@app.delete("/api/training/forms/<fid>")
def training_delete(fid):
    return _tform(fid, _mine(lambda i: (trainer.delete(i), trainer.release(i, _staff()[0]), {"deleted": i})[2]))


@app.post("/api/training/train")
def training_train():
    try:
        return jsonify(trainer.start_training())
    except (RuntimeError, ValueError) as e:
        return jsonify(error=str(e)), 409


@app.post("/api/training/install")
def training_install():
    try:
        return jsonify(trainer.install())
    except ValueError as e:
        return jsonify(error=str(e)), 409


@app.get("/api/training/candidate/<name>")
def training_candidate_file(name):
    try:
        return send_file(trainer.candidate_file(name), as_attachment=True, download_name=name)
    except KeyError:
        abort(404)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error=f"File is larger than {MAX_UPLOAD_MB} MB."), 413
