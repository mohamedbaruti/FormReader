"""Training the handwriting reader on your own forms (the Training page).

Separate from enrolment: staff upload photos of PAGE 1 only, the reader reads
them in the background, staff check each form and type EXACTLY what is written
(no rules, no lists). Each confirmed character becomes a training sample.

Folders (all under formreader/training_data/):
    forms/<id>/meta.json     one uploaded form: status, fields, what was read, what was typed
    forms/<id>/photo.*       the uploaded photo
    forms/<id>/cells/*.png   each written box (dark ink on white)
    forms/<id>/strips/*.png  picture of each field, shown to the person checking
    samples/<CHAR>/*.png     training samples (confirmed forms that are not test forms)
    candidate/               a newly trained model, before it is installed
    runs.json                history of trainings
Settings: app/training_settings.json.

Form status: queued -> reading -> ready -> confirmed / skipped, or problem (not page 1,
not a Form 1A, empty; "read anyway" is possible) or failed (could not be read).
Every Nth form (test_every) is a TEST form: checked like the others, never trained
on, used to compare a new model with the one in use.
"""
import datetime as dt
import glob
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict

import cv2
import numpy as np

from .cells import ALLOWED, is_single_stroke
from .recognizer import CLASSES, CharClassifier

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BASE_DIR = os.path.join(ROOT, "training_data")
FORMS_DIR = os.path.join(BASE_DIR, "forms")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
CANDIDATE_DIR = os.path.join(BASE_DIR, "candidate")
RUNS_PATH = os.path.join(BASE_DIR, "runs.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
MODEL_DIR = os.path.join(HERE, "model")
SETTINGS_PATH = os.path.join(HERE, "training_settings.json")
MODEL_FILES = ("char_cnn.npz", "char_mlp.npz")
TEXT_KINDS = ("alpha", "digit", "alnum", "date_d", "date_m", "date_y")
CHARS = list(CLASSES)        # 0-9 then A-Z
LOCK_TTL = 90                # seconds without a sign of life from the checking screen -> the form is free again
LOCK_IDLE_MINUTES = 10       # default: after this long without typing, another person may take the form over


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def key_of(text):
    """Characters that must match the written boxes one to one (spaces and / are not boxes)."""
    return re.sub(r"[\s/]", "", (text or "").upper())


def ink_from_sample(path):
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return None if g is None else ((g < 128) * 255).astype(np.uint8)


class FormLocked(Exception):
    """Someone else is checking this form. .info = who and since when."""
    def __init__(self, info):
        super().__init__(f"This form is being checked by {info['name']}.")
        self.info = info


class Trainer:
    def __init__(self, extractor, lock):
        self.extractor = extractor
        self.lock = lock                  # the server's "one reading at a time" lock
        self.q = queue.Queue()
        self.job = {"state": "idle"}      # the training run in progress
        self._job_lock = threading.Lock()
        # Who is checking which form, so two people never check the same form at once.
        # Kept in memory only: {fid: {"client", "name", "since", "seen", "active"}} (times = time.time()).
        # Restarting the reader frees every form; nothing about the forms themselves changes.
        self._locks = {}
        self._locks_lock = threading.Lock()
        os.makedirs(FORMS_DIR, exist_ok=True)
        threading.Thread(target=self._worker, daemon=True).start()
        for m in self._all_meta():        # forms left unfinished when the reader stopped
            if m["status"] in ("queued", "reading"):
                self.q.put(m["id"])

    # ------------------------------------------------------------------ settings & storage
    @staticmethod
    def settings():
        s = _read_json(SETTINGS_PATH, {})
        return {k: v for k, v in s.items() if not k.startswith("_")}

    def _dir(self, fid):
        if not re.fullmatch(r"[0-9a-f]{12}", fid or ""):
            raise KeyError(fid)
        return os.path.join(FORMS_DIR, fid)

    def meta(self, fid):
        m = _read_json(os.path.join(self._dir(fid), "meta.json"), None)
        if m is None:
            raise KeyError(fid)
        return m

    def _save(self, m):
        _write_json(os.path.join(self._dir(m["id"]), "meta.json"), m)

    def _all_meta(self):
        out = []
        for p in glob.glob(os.path.join(FORMS_DIR, "*", "meta.json")):
            m = _read_json(p, None)
            if m:
                out.append(m)
        return sorted(out, key=lambda m: m.get("seq", 0))

    # ------------------------------------------------------------------ upload & reading
    def add(self, filename, blob):
        st = _read_json(STATE_PATH, {"seq": 0})
        st["seq"] += 1
        _write_json(STATE_PATH, st)
        every = max(1, int(self.settings().get("test_every", 10)))
        fid = uuid.uuid4().hex[:12]
        d = os.path.join(FORMS_DIR, fid)
        os.makedirs(d)
        ext = ".pdf" if blob[:4] == b"%PDF" else (os.path.splitext(filename)[1].lower() or ".jpg")
        with open(os.path.join(d, "photo" + ext), "wb") as fh:
            fh.write(blob)
        m = {"id": fid, "seq": st["seq"], "filename": filename, "photo": "photo" + ext,
             "status": "queued", "test": (st["seq"] - 1) % every == 0, "uploaded_at": now(), "fields": []}
        self._save(m)
        self.q.put(fid)
        return m

    def retry(self, fid, force=True):
        m = self.meta(fid)
        m.update(status="queued", force=force, problem=None)
        self._save(m)
        self.q.put(fid)
        return m

    def _worker(self):
        while True:
            fid = self.q.get()
            try:
                self._read(fid)
            except KeyError:
                pass
            except Exception as e:           # never let one bad photo stop the queue
                try:
                    m = self.meta(fid)
                    m.update(status="failed", problem=f"Could not read this photo: {e}")
                    self._save(m)
                except Exception:
                    pass

    def _read(self, fid):
        m = self.meta(fid)
        if m["status"] not in ("queued",):
            return
        m["status"] = "reading"
        self._save(m)
        d = self._dir(fid)
        with open(os.path.join(d, m["photo"]), "rb") as fh:
            blob = fh.read()
        with self.lock:
            info = self.extractor.inspect(blob)
            problem = None
            if not info["recognised"]:
                problem = "This does not look like a page of Form 1A."
            elif info["page"] != 1:
                problem = f"This is page {info['page']} of the form. Only page 1 is used for training."
            elif info.get("blank"):
                problem = "No handwriting found: the form looks empty."
            if problem and not m.get("force"):
                m.update(status="problem", problem=problem)
                self._save(m)
                return
            form_id = info["form"] if info["recognised"] and info["page"] == 1 else None
            # plausible=False: no date limits and no lookup lists here, so the reading
            # shows what is really written (the Training page learns from it)
            result, layout, aligned, readings = self.extractor.run([blob], form_id, plausible=False)
        m.update(form=layout.id, form_title=layout.title, problem=None,
                 fields=self._fields(fid, layout, aligned, readings), status="ready", read_at=now())
        if not m["fields"]:
            m.update(status="problem", problem="No handwriting found in any box.")
        self._save(m)

    def _fields(self, fid, layout, aligned, readings):
        """Every page-1 text or date field with writing: picture, boxes, what was read."""
        d = self._dir(fid)
        os.makedirs(os.path.join(d, "cells"), exist_ok=True)
        os.makedirs(os.path.join(d, "strips"), exist_ok=True)
        out = []
        for sec in layout.sections:
            if sec["page"] != 0:
                continue
            for fm in sec["fields"]:
                name = fm["name"]
                entries = layout.groups.get(name, [])
                if not entries or entries[0]["type"] not in TEXT_KINDS or entries[0]["page"] != 0:
                    continue
                rows = readings.get(name, [])
                boxes = []
                for entry, row in zip(entries, rows):
                    for k, (mask, (ch, conf)) in enumerate(row):
                        if ch and mask is not None:
                            img = cv2.copyMakeBorder(255 - mask, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
                            fn = f"{name}_{len(boxes)}.png"
                            cv2.imwrite(os.path.join(d, "cells", fn), img)
                            kind = "digit" if entry["type"].startswith("date") else entry["type"]
                            boxes.append([fn, ch, round(float(conf), 1), kind])
                if not boxes:
                    continue                  # nothing written: nothing to learn
                # what was read, as on the paper: words with spaces, dates as DD/MM/YYYY
                parts = []
                for row in rows:
                    parts.append(re.sub(r"\s+", " ", "".join(ch if ch else " " for _, (ch, _) in row)).strip())
                is_date = entries[0]["type"].startswith("date")
                read = "/".join(p.replace(" ", "") for p in parts) if is_date else " ".join(p for p in parts if p)
                strip = layout.field_strip(aligned, name, height=56,
                                           max_boxes=layout.written_extent(readings, name))
                cv2.imwrite(os.path.join(d, "strips", name + ".png"), strip)
                out.append({"name": name, "label": fm.get("label"), "label_en": fm.get("label_en"),
                            "section": sec["id"], "type": "date" if is_date else entries[0]["type"],
                            "read": read, "boxes": boxes,
                            "unsure": any(b[2] < 90 for b in boxes)})
        return out

    # ------------------------------------------------------------------ checking
    def confirm(self, fid, values):
        """values: {field: text exactly as written}. Saves the training samples."""
        m = self.meta(fid)
        if m["status"] not in ("ready", "confirmed"):
            raise ValueError("This form is not ready to be checked.")
        self._remove_samples(fid)
        used_fields = 0
        for f in m["fields"]:
            typed = values.get(f["name"], f.get("typed", f["read"]))
            typed = " ".join(str(typed or "").upper().split())
            key = key_of(typed)
            n = len(f["boxes"])
            f["typed"] = typed
            if not key:
                f.update(used=False, reason="Left empty")
            elif len(key) != n:
                f.update(used=False, reason=f"{len(key)} characters typed, {n} boxes have writing")
            elif any(c not in CHARS for c in key):
                f.update(used=False, reason="Only letters A-Z and digits 0-9 can be learned")
            else:
                f.update(used=True, reason=None, truth=list(key))
                used_fields += 1
                if not m["test"]:
                    for (fn, _, _, _), ch in zip(f["boxes"], key):
                        dst = os.path.join(SAMPLES_DIR, ch)
                        os.makedirs(dst, exist_ok=True)
                        shutil.copy(os.path.join(self._dir(fid), "cells", fn),
                                    os.path.join(dst, f"{fid}_{fn}"))
        m.update(status="confirmed", confirmed_at=now(), fields_used=used_fields)
        self._save(m)
        return m

    def skip(self, fid):
        m = self.meta(fid)
        self._remove_samples(fid)
        m.update(status="skipped")
        self._save(m)
        return m

    def set_test(self, fid, test):
        m = self.meta(fid)
        m["test"] = bool(test)
        self._save(m)
        if m["status"] == "confirmed":            # move its samples in or out of training
            self.confirm(fid, {f["name"]: f.get("typed", f["read"]) for f in m["fields"]})
        return self.meta(fid)

    def delete(self, fid):
        d = self._dir(fid)
        self._remove_samples(fid)
        shutil.rmtree(d, ignore_errors=True)

    def _remove_samples(self, fid):
        for p in glob.glob(os.path.join(SAMPLES_DIR, "*", f"{fid}_*.png")):
            os.remove(p)

    # ------------------------------------------------------------------ one person per form
    def _idle_limit(self):
        return 60 * float(self.settings().get("lock_idle_minutes", LOCK_IDLE_MINUTES))

    def _fresh_lock(self, fid, t=None):
        """The lock on a form if its holder is still there (heard from in the last LOCK_TTL s)."""
        t = t or time.time()
        lk = self._locks.get(fid)
        if lk and t - lk["seen"] > LOCK_TTL:
            del self._locks[fid]                     # the screen was closed or the computer is off
            lk = None
        return lk

    def _lock_public(self, lk, client=None, t=None):
        t = t or time.time()
        idle = max(0, t - lk["active"])
        return {"name": lk["name"] or "Another staff member",
                "since": dt.datetime.fromtimestamp(lk["since"]).isoformat(timespec="seconds"),
                "idle_minutes": int(idle // 60), "mine": bool(client) and lk["client"] == client,
                "can_take_over": idle >= self._idle_limit()}

    def hold(self, fid, client, name="", idle=0, take=False):
        """Open a form for checking (and keep it open: the checking screen calls this every 30 s).
        Raises FormLocked when someone else has it, unless take=True and they have been idle
        longer than lock_idle_minutes."""
        if not client:
            raise ValueError("Missing staff id (X-Staff-Client).")
        self.meta(fid)                               # KeyError when the form does not exist
        t = time.time()
        with self._locks_lock:
            cur = self._fresh_lock(fid, t)
            if cur and cur["client"] != client:
                if not (take and t - cur["active"] >= self._idle_limit()):
                    raise FormLocked(self._lock_public(cur, client, t))
                cur = None                           # taken over
            idle = max(0.0, min(float(idle or 0), 24 * 3600))
            self._locks[fid] = {"client": client, "name": (name or "").strip()[:40],
                                "since": cur["since"] if cur else t, "seen": t, "active": t - idle}
            return self._lock_public(self._locks[fid], client, t)

    def release(self, fid, client):
        with self._locks_lock:
            lk = self._locks.get(fid)
            if lk and lk["client"] == client:
                del self._locks[fid]
        return {"unlocked": fid}

    def check_lock(self, fid, client):
        """Refuse a change to a form someone else is checking."""
        with self._locks_lock:
            lk = self._fresh_lock(fid)
            if lk and lk["client"] != client:
                raise FormLocked(self._lock_public(lk, client))

    def lock_of(self, fid, client=None):
        with self._locks_lock:
            lk = self._fresh_lock(fid)
            return self._lock_public(lk, client) if lk else None

    def next_form(self, client, name="", after=None):
        """The next form waiting to be checked that nobody else has open, opened for this person.
        Forms after `after` (by number) first, then from the start. None when there is none."""
        if not client:
            raise ValueError("Missing staff id (X-Staff-Client).")
        ready = [m for m in self._all_meta() if m["status"] == "ready" and m["id"] != after]
        seq = next((m["seq"] for m in self._all_meta() if m["id"] == after), 0) if after else 0
        ready.sort(key=lambda m: (m["seq"] <= seq, m["seq"]))
        for m in ready:
            try:
                self.hold(m["id"], client, name)
            except (FormLocked, KeyError):
                continue
            if after:
                self.release(after, client)
            return {"id": m["id"]}
        return {"id": None}

    def detail(self, fid):
        """One form for the checking screen, with its pictures as data URLs."""
        import base64
        m = self.meta(fid)
        d = self._dir(fid)
        for f in m["fields"]:
            p = os.path.join(d, "strips", f["name"] + ".png")
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    f["image"] = "data:image/png;base64," + base64.b64encode(fh.read()).decode()
        return m

    def photo_path(self, fid):
        m = self.meta(fid)
        return os.path.join(self._dir(fid), m["photo"])

    def forms(self, client=None):
        keep = ("id", "seq", "filename", "status", "test", "problem", "uploaded_at", "read_at",
                "confirmed_at", "fields_used", "form_title")
        out = []
        for m in self._all_meta():
            row = {k: m.get(k) for k in keep}
            row["fields"] = len(m.get("fields", []))
            row["unsure"] = sum(1 for f in m.get("fields", []) if f.get("unsure"))
            row["lock"] = self.lock_of(m["id"], client)
            out.append(row)
        return out

    # ------------------------------------------------------------------ statistics & advice
    def stats(self):
        cfg = self.settings()
        forms = self._all_meta()
        status = Counter(m["status"] for m in forms)
        samples = {c: len(glob.glob(os.path.join(SAMPLES_DIR, c, "*.png"))) for c in CHARS}
        seen, right = Counter(), Counter()
        confusions = defaultdict(Counter)          # true char -> {read as: count}
        fields_total = fields_used = 0
        not_used = Counter()
        test_forms = test_chars = 0
        for m in forms:
            if m["status"] != "confirmed":
                continue
            if m["test"]:
                test_forms += 1
            for f in m["fields"]:
                fields_total += 1
                if not f.get("used"):
                    not_used[f.get("reason") or "?"] += 1
                    continue
                fields_used += 1
                if m["test"]:
                    test_chars += len(f["boxes"])
                for (fn, pred, conf, kind), true in zip(f["boxes"], f["truth"]):
                    seen[true] += 1
                    if pred == true:
                        right[true] += 1
                    else:
                        confusions[true][pred] += 1
        per_char = []
        few, enough = cfg.get("few", 30), cfg.get("enough", 100)
        lo, ok, min_seen = cfg.get("accuracy_low", .85), cfg.get("accuracy_ok", .95), cfg.get("min_seen", 10)
        for c in CHARS:
            n, s = samples[c], seen[c]
            acc = right[c] / s if s else None
            level = "needs_more" if n < few else "moderate" if n < enough else "enough"
            reading = (None if acc is None or s < min_seen else
                       "often_misread" if acc < lo else "sometimes_misread" if acc < ok else "good")
            top = confusions[c].most_common(3)
            if reading == "often_misread" and level != "enough":
                advice = f"Often misread and few samples: collect more forms with {c}."
            elif reading == "often_misread":
                advice = (f"Still often misread with {n} samples: check that staff type exactly what is "
                          f"written; look at how {c} is written on the forms.")
            elif level == "needs_more":
                advice = f"Needs more samples ({n} of {few} at least)."
            elif reading == "sometimes_misread":
                advice = "Sometimes misread: more samples will help."
            elif level == "moderate":
                advice = f"Moderate: {enough - n} more samples to reach 'enough'."
            else:
                advice = "Enough samples."
            per_char.append({"char": c, "samples": n, "seen": s, "right": right[c],
                             "accuracy": round(acc, 4) if acc is not None else None,
                             "level": level, "reading": reading, "advice": advice,
                             "confused_with": [{"char": p, "count": k} for p, k in top]})
        pairs = sorted(((t, p, k) for t, cs in confusions.items() for p, k in cs.items()),
                       key=lambda x: -x[2])[:10]
        total_seen, total_right = sum(seen.values()), sum(right.values())
        runs = _read_json(RUNS_PATH, [])
        total_samples = sum(samples.values())
        last_total = runs[-1]["samples"] if runs else 0
        new_since = max(0, total_samples - last_total)

        # ---- advice, most useful first
        advice = []
        if self.missing_packages():
            advice.append({"level": "warn", "text": "Training needs extra packages: stop the reader, run "
                           "'pip install -r requirements-train.txt' in the formreader folder, and start it again."})
        cand = self.candidate()
        if cand and cand.get("better") and not cand.get("installed"):
            advice.append({"level": "action", "text": f"A newly trained model is ready: it reads the test forms "
                           f"{cand['new_accuracy']*100:.1f}% right against {cand['old_accuracy']*100:.1f}% now. Install it."})
        elif cand and cand.get("better") is False and not cand.get("installed"):
            advice.append({"level": "info", "text": "The last trained model was not better on the test forms; "
                           "keep the current one and collect more forms before training again."})
        if status["ready"]:
            advice.append({"level": "action", "text": f"{status['ready']} form{'s are' if status['ready'] != 1 else ' is'} "
                           "read and waiting to be checked."})
        if status["problem"]:
            advice.append({"level": "warn", "text": f"{status['problem']} photo{'s' if status['problem'] != 1 else ''} "
                           "could not be used (wrong page, not the form, or empty). See the list."})
        need = cfg.get("retrain_after", 500)
        if total_samples < cfg.get("min_samples_to_train", 200):
            advice.append({"level": "info", "text": f"{total_samples} characters collected; at least "
                           f"{cfg.get('min_samples_to_train', 200)} are needed before the first training."})
        elif new_since >= need:
            advice.append({"level": "action", "text": f"{new_since} new characters since the last training: train now."})
        else:
            advice.append({"level": "info", "text": f"{new_since} new characters since the last training; "
                           f"training is worth it from about {need}."})
        if test_forms < cfg.get("min_test_forms", 5):
            advice.append({"level": "warn", "text": f"Only {test_forms} checked test form{'s' if test_forms != 1 else ''}: at least "
                           f"{cfg.get('min_test_forms', 5)} are needed to compare models reliably "
                           f"(every {cfg.get('test_every', 10)}th form uploaded is a test form)."})
        weak = [p for p in per_char if p["reading"] == "often_misread"]
        if weak:
            advice.append({"level": "warn", "text": "Often misread: " + ", ".join(
                f"{p['char']} ({p['accuracy']*100:.0f}% right)" for p in sorted(weak, key=lambda p: p["accuracy"])[:6]) + "."})
        short = [p["char"] for p in sorted(per_char, key=lambda p: p["samples"]) if p["level"] == "needs_more"]
        if short:
            advice.append({"level": "info", "text": f"Fewest samples: {', '.join(short[:10])}. These come mostly "
                           "from names and places that use them: forms from many different people help."})
        if pairs:
            t, p, k = pairs[0]
            advice.append({"level": "info", "text": f"Most common mix-up: {t} read as {p} ({k} times). "
                           "Training on checked forms fixes this over time."})
        if fields_total >= 20 and (fields_total - fields_used) / fields_total > 0.2:
            advice.append({"level": "warn", "text": f"{fields_total - fields_used} of {fields_total} checked fields "
                           "were not used: type exactly one character for each written box."})
        return {
            "forms": {"total": len(forms), **{k: status.get(k, 0) for k in
                      ("queued", "reading", "ready", "confirmed", "skipped", "problem", "failed")},
                      "test": test_forms},
            "characters": {"samples": total_samples, "checked": total_seen, "read_right": total_right,
                           "accuracy": round(total_right / total_seen, 4) if total_seen else None,
                           "test_characters": test_chars, "new_since_training": new_since},
            "fields": {"checked": fields_total, "used": fields_used,
                       "not_used_reasons": dict(not_used.most_common())},
            "per_character": per_char,
            "confusions": [{"char": t, "read_as": p, "count": k} for t, p, k in pairs],
            "advice": advice,
            "runs": runs[::-1],
            "candidate": cand,
            "job": self.job_status(),
            "models": {f: dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(MODEL_DIR, f))).isoformat(timespec="minutes")
                       for f in MODEL_FILES if os.path.exists(os.path.join(MODEL_DIR, f))},
            "settings": cfg,
            "missing_packages": self.missing_packages(),
        }

    # ------------------------------------------------------------------ training
    def job_status(self):
        j = dict(self.job)
        if j.get("log_path") and os.path.exists(j["log_path"]):
            with open(j["log_path"], encoding="utf-8", errors="replace") as fh:
                j["log"] = fh.read().splitlines()[-12:]
        j.pop("log_path", None)
        return j

    @staticmethod
    def missing_packages():
        """Training needs scikit-learn (requirements-train.txt); reading does not."""
        import importlib.util
        return [p for p in ("sklearn",) if importlib.util.find_spec(p) is None]

    def start_training(self):
        with self._job_lock:
            if self.job.get("state") == "running":
                raise RuntimeError("A training is already running.")
            if self.missing_packages():
                raise ValueError("Training needs extra packages. Stop the reader, run "
                                 "pip install -r requirements-train.txt in the formreader folder, "
                                 "then start it again (python run.py).")
            cfg = self.settings()
            n = sum(len(glob.glob(os.path.join(SAMPLES_DIR, c, "*.png"))) for c in CHARS)
            if n < cfg.get("min_samples_to_train", 200):
                raise ValueError(f"Only {n} characters collected; at least "
                                 f"{cfg.get('min_samples_to_train', 200)} are needed.")
            shutil.rmtree(CANDIDATE_DIR, ignore_errors=True)
            os.makedirs(CANDIDATE_DIR)
            self.job = {"state": "running", "step": 0, "steps": 3, "step_name": "Starting",
                        "started_at": now(), "samples": n, "log_path": os.path.join(CANDIDATE_DIR, "training.log")}
        threading.Thread(target=self._train, args=(n,), daemon=True).start()
        return self.job_status()

    def _train(self, n):
        cfg = self.settings()
        py = sys.executable
        tools = os.path.join(ROOT, "tools")
        steps = [
            ("Training the stroke-shape model (about 5 minutes)",
             [py, os.path.join(tools, "train_classifier.py"), "--extra", SAMPLES_DIR,
              "--out", os.path.join(CANDIDATE_DIR, "char_mlp.npz")]),
            ("Training the main model (about 10-15 minutes)",
             [py, os.path.join(tools, "train_cnn.py"), "--extra", SAMPLES_DIR,
              "--epochs", str(cfg.get("cnn_epochs", 3)),
              "--init", os.path.join(MODEL_DIR, "char_cnn.npz"),
              "--out", os.path.join(CANDIDATE_DIR, "char_cnn.npz")]),
        ]
        log = self.job["log_path"]
        try:
            with open(log, "w", encoding="utf-8") as fh:
                for i, (title, cmd) in enumerate(steps, 1):
                    self.job.update(step=i, step_name=title)
                    fh.write(f"== {title}\n")
                    fh.flush()
                    rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
                    if rc != 0:
                        raise RuntimeError(f"{title} failed (see the log).")
            self.job.update(step=3, step_name="Comparing with the model in use on the test forms")
            report = self.evaluate()
            report.update(trained_at=now(), samples=n, installed=False,
                          seconds=round(time.time() - dt.datetime.fromisoformat(self.job["started_at"]).timestamp()))
            _write_json(os.path.join(CANDIDATE_DIR, "report.json"), report)
            runs = _read_json(RUNS_PATH, [])
            runs.append({k: report[k] for k in ("trained_at", "samples", "test_characters", "old_accuracy",
                                                "new_accuracy", "better", "installed", "seconds")})
            _write_json(RUNS_PATH, runs)
            self.job.update(state="done", finished_at=now())
        except Exception as e:
            self.job.update(state="failed", error=str(e), finished_at=now())

    def evaluate(self, candidate_dir=CANDIDATE_DIR):
        """Read every written box of the checked TEST forms with the model in use and with
        the new one; share of characters read right, overall and per character."""
        boxes = []
        for m in self._all_meta():
            if m["status"] != "confirmed" or not m["test"]:
                continue
            for f in m["fields"]:
                if f.get("used"):
                    for (fn, _, _, kind), true in zip(f["boxes"], f["truth"]):
                        boxes.append((os.path.join(self._dir(m["id"]), "cells", fn), kind, true))
        old = CharClassifier(os.path.join(MODEL_DIR, "char_mlp.npz"), os.path.join(MODEL_DIR, "char_cnn.npz"))
        new = CharClassifier(os.path.join(candidate_dir, "char_mlp.npz"), os.path.join(candidate_dir, "char_cnn.npz"))
        res = {"old": Counter(), "new": Counter()}
        per = defaultdict(lambda: {"seen": 0, "old": 0, "new": 0})
        for path, kind, true in boxes:
            ink = ink_from_sample(path)
            if ink is None:
                continue
            allowed = ALLOWED.get(kind, ALLOWED["alnum"])
            if is_single_stroke(ink):
                allowed = "".join(c for c in "I1" if c in allowed) or allowed
            per[true]["seen"] += 1
            for name, clf in (("old", old), ("new", new)):
                ch, _ = clf.pick(clf.probs(ink), allowed)
                ok = ch == true
                res[name]["right"] += ok
                per[true][name] += ok
        total = len(boxes)
        oa = res["old"]["right"] / total if total else None
        na = res["new"]["right"] / total if total else None
        return {"test_characters": total, "old_accuracy": oa, "new_accuracy": na,
                "better": (na > oa) if total else None,
                "per_character": {c: v for c, v in sorted(per.items())}}

    def candidate(self):
        r = _read_json(os.path.join(CANDIDATE_DIR, "report.json"), None)
        if r and all(os.path.exists(os.path.join(CANDIDATE_DIR, f)) for f in MODEL_FILES):
            r["files"] = list(MODEL_FILES)
            return r
        return None

    def candidate_file(self, name):
        if name not in MODEL_FILES or not self.candidate():
            raise KeyError(name)
        return os.path.join(CANDIDATE_DIR, name)

    def install(self):
        """Use the new model: the current pair is copied to app/model/backup-<date>/ first."""
        cand = self.candidate()
        if not cand:
            raise ValueError("No newly trained model to install.")
        backup = os.path.join(MODEL_DIR, "backup-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(backup)
        for f in MODEL_FILES:
            if os.path.exists(os.path.join(MODEL_DIR, f)):
                shutil.copy2(os.path.join(MODEL_DIR, f), backup)
        for f in MODEL_FILES:
            shutil.copy2(os.path.join(CANDIDATE_DIR, f), os.path.join(MODEL_DIR, f))
        from . import cells
        with self.lock:
            cells._classifier = None          # the next reading loads the new model
        cand["installed"] = True
        cand["installed_at"] = now()
        cand["backup"] = os.path.relpath(backup, ROOT)
        _write_json(os.path.join(CANDIDATE_DIR, "report.json"), {k: v for k, v in cand.items() if k != "files"})
        runs = _read_json(RUNS_PATH, [])
        if runs:
            runs[-1]["installed"] = True
            _write_json(RUNS_PATH, runs)
        return cand
