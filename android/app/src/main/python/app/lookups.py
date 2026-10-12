"""Official name lists from your lookup service (app/lookup_settings.json).

The service answers with JSON holding entries such as
    {"id": 5, "region": "TANGA", "postcode": "21", "active": true}
    {"id": 6, "district": "TANGA", "postcode": "2", "regionId": 5, "active": true}
    {"id": 6359, "ward": "KENDWA", "postcode": "21", "districtId": 143, "active": true}
The whole answer is searched for objects that have a list's key ("region",
"district", ...), so it does not matter how the service groups them. Inactive
entries are left out. regionId / districtId link each name to its parent.

Fields that belong together on the form (region, district, ward of one place)
form a group. Reading a group goes top-down: the region is matched first, then
the district only among that region's districts, then the ward among that
district's wards.

    lk = Lookups()
    lk.for_field("birth_district")  -> "district" (or None when that list is empty)
    lk.parent_field("birth_district") -> "birth_region"
    lk.match_fields({field: (raw_text, probs)}) -> {field: (name, how)}
    lk.check(data)                  -> problems: name not in the list / not in its region
"""
import datetime as dt
import difflib
import json
import os
import re
import threading
import time
import urllib.request

import numpy as np

from .recognizer import CLASSES

HERE = os.path.dirname(__file__)
SETTINGS_PATH = os.path.join(HERE, "lookup_settings.json")
CACHE_PATH = os.path.join(os.environ.get("FORMREADER_DATA_DIR") or os.path.join(HERE, "..", "data"),
                          "lookups_cache.json")

SURE_MARGIN = 1.1    # per box: a listed name this close to the raw reading is taken as sure
SKIP_PENALTY = 3.0   # cost of one box missed or added by the writer
GUESS_RATIO = 0.6    # spelling similarity needed (only used when no handwriting probabilities)
GUESS_MARGIN = 3.0   # per box: how much less likely than the raw reading a name may be to be pre-selected
FIRST_WORD_PENALTY = 0.3   # per box: matching on the first word only is a little less certain
PREFERRED_MARGIN = 4.0     # per box: the preferred name (TANZANIA) is accepted from much less clear writing


def _norm(s):
    return " ".join(str(s).upper().split())


def _collect(node, key, out):
    """All objects in the JSON that have `key` with a text value."""
    if isinstance(node, dict):
        v = node.get(key)
        if isinstance(v, str) and v.strip():
            if node.get("active", True) not in (False, 0, "false", "0"):
                out.append(node)
        for child in node.values():
            if isinstance(child, (dict, list)):
                _collect(child, key, out)
    elif isinstance(node, list):
        for child in node:
            _collect(child, key, out)


class Lookups:
    def __init__(self, settings_path=SETTINGS_PATH, cache_path=CACHE_PATH):
        with open(settings_path, encoding="utf-8") as fh:
            self.settings = json.load(fh)
        self.url = os.environ.get("FORMREADER_LOOKUP_URL") or self.settings.get("url", "")
        self.cache_path = os.path.abspath(cache_path)
        self.lists = self.settings.get("lists", {})
        # groups of fields that belong together: [{"region": "birth_region", "district": ...}]
        raw_groups = [{k: v for k, v in g.items() if not k.startswith("_")} for g in self.settings.get("groups", [])]
        self.groups = [{k: v for k, v in g.items() if k in self.lists} for g in raw_groups]
        # postcode fields filled from the chosen region + district + ward of the same group
        self.postcode_groups = [(g["postcode"], {k: v for k, v in g.items() if k in self.lists})
                                for g in raw_groups if g.get("postcode")]
        self.postcode_from = self.settings.get("postcode_from", ["region", "district", "ward"])
        # tick-box fields whose values come from lookup lists (sex, marital status...)
        self.choice_cfg = {k: v for k, v in self.settings.get("choices", {}).items() if not k.startswith("_")}
        self.choices = {}           # field -> [{"id", "code", "value", ...original fields}]
        self.field_list = {f: lst for g in self.groups for lst, f in g.items()}
        self.field_group = {f: g for g in self.groups for f in g.values()}
        self.entries = {}           # list name -> [{"id", "name", ...original fields}]
        self.status = {"source": None, "loaded_at": None, "error": None, "url": self.url}
        self._lock = threading.Lock()
        self._next_refresh = 0
        self.refresh()

    # ------------------------------------------------------------------ loading
    def _fetch(self):
        if re.match(r"^https?://", self.url, re.I):
            req = urllib.request.Request(self.url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.settings.get("timeout_seconds", 8)) as r:
                return json.loads(r.read().decode("utf-8"))
        with open(self.url, encoding="utf-8") as fh:        # a local JSON file
            return json.load(fh)

    @staticmethod
    def _branch(raw, sources):
        """The part of the answer to search: the first top-level key named in `sources`
        (e.g. "lookupRegions"), or the whole answer when none is there."""
        if isinstance(raw, dict) and sources:
            low = {k.lower(): k for k in raw}
            for s in sources:
                if s.lower() in low:
                    return raw[low[s.lower()]]
        return raw

    def _build(self, raw):
        out = {}
        for name, cfg in self.lists.items():
            key = cfg.get("key", name)
            pkey = cfg.get("parent_key")
            need = cfg.get("require", [])
            found = []
            _collect(self._branch(raw, cfg.get("source")), key, found)
            seen, items = set(), []
            for e in found:
                if any(k not in e for k in need):
                    continue
                n = _norm(e[key])
                pid = e.get(pkey) if pkey else None
                ident = ("id", e["id"]) if e.get("id") is not None else ("name", n, pid)
                if ident in seen:
                    continue
                seen.add(ident)
                # other spellings people write: the second name, and the part before a comma
                # ("TANZANIA, THE UNITED REPUBLIC" -> "TANZANIA")
                aliases = {n}
                for k in cfg.get("aliases_from", []):
                    if isinstance(e.get(k), str) and e[k].strip():
                        aliases.add(_norm(e[k]))
                for a in list(aliases):
                    if "," in a:
                        aliases.add(_norm(a.split(",")[0]))
                items.append({**{k: v for k, v in e.items() if k != key}, "name": n, "parent_id": pid,
                              "aliases": sorted(aliases)})
            items.sort(key=lambda e: e["name"])
            out[name] = items
        # entries without their own parent id belong to a fixed parent, e.g. every region
        # belongs to Tanzania (the only country with regions): "parent_default": {"code": "TZA"}
        for name, cfg in self.lists.items():
            dflt, parent = cfg.get("parent_default"), cfg.get("parent")
            if not dflt or not parent:
                continue
            pe = [e for e in out.get(parent, []) if all(str(e.get(k)) == str(v) for k, v in dflt.items())]
            for e in out.get(name, []):
                if e["parent_id"] is None and pe:
                    e["parent_id"] = pe[0].get("id")
        return out

    def _build_choices(self, raw):
        out = {}
        for field, cfg in self.choice_cfg.items():
            branch = self._branch(raw, cfg.get("source"))
            if branch is raw or not isinstance(branch, list):
                continue                     # this list is not in the answer: keep the form's own options
            vk = cfg.get("value", "description1")
            items = [{**e, "value": _norm(e[vk])} for e in branch
                     if isinstance(e, dict) and isinstance(e.get(vk), str)
                     and e.get("active", True) not in (False, 0, "false", "0")]
            if items:
                out[field] = sorted(items, key=lambda e: (e.get("id") is None, e.get("id") or 0))
        return out

    def refresh(self, force=False):
        """Load the lists from the service (or the saved copy). Cheap to call often."""
        if not force and time.time() < self._next_refresh:
            return
        with self._lock:
            self._next_refresh = time.time() + 60 * self.settings.get("refresh_minutes", 60)
            raw, source, error = None, None, None
            if self.url:
                try:
                    raw, source = self._fetch(), "service"
                    os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                    with open(self.cache_path, "w", encoding="utf-8") as fh:
                        json.dump({"saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                                   "url": self.url, "data": raw}, fh)
                except Exception as e:      # service down, wrong address, bad JSON...
                    error = f"{type(e).__name__}: {e}"
            if raw is None and os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path, encoding="utf-8") as fh:
                        raw, source = json.load(fh)["data"], "saved copy"
                except Exception:
                    pass
            if raw is None:
                if not self.entries:
                    self.status.update(source=None, error=error or "no lookup address set")
                    # try again soon instead of waiting the full refresh time
                    self._next_refresh = time.time() + 60
                return
            built = self._build(raw)
            if any(built.values()):
                self.entries = built
            choices = self._build_choices(raw)
            if choices:
                self.choices = choices
            self.status.update(source=source, error=error,
                               loaded_at=dt.datetime.now().isoformat(timespec="seconds"),
                               counts={**{k: len(v) for k, v in self.entries.items()},
                                       **{k: len(v) for k, v in self.choices.items()}})

    def refresh_soon(self):
        """Refresh in the background when due, so a slow service never delays a reading."""
        if time.time() >= self._next_refresh and not self._lock.locked():
            threading.Thread(target=self.refresh, daemon=True).start()

    # ------------------------------------------------------------------ use
    def for_field(self, field):
        name = self.field_list.get(field)
        return name if name and self.entries.get(name) else None

    def parent_field(self, field):
        """The field in the same group holding this field's parent (district -> region)."""
        lst, group = self.field_list.get(field), self.field_group.get(field, {})
        parent = self.lists.get(lst, {}).get("parent")
        while parent:                       # skip levels missing from the group or not loaded
            if parent in group and self.entries.get(parent):
                return group[parent]
            parent = self.lists.get(parent, {}).get("parent")
        return None

    def names(self, list_name, parent_ids=None):
        es = self.entries.get(list_name, [])
        if parent_ids is not None:
            es = [e for e in es if e["parent_id"] in parent_ids]
        return sorted({e["name"] for e in es})

    def ids(self, list_name, name, parent_ids=None):
        """Ids of the entries called `name` (under one of parent_ids, when given)."""
        es = [e for e in self.entries.get(list_name, []) if e["name"] == _norm(name)]
        if parent_ids is not None:
            within = [e for e in es if e["parent_id"] in parent_ids]
            es = within or es
        return {e.get("id") for e in es}

    def match(self, probs, raw_text, list_name, names=None):
        """Pick the listed name the handwriting most likely is.

        Every listed name is scored by how likely its letters are in the written
        boxes (the model's probabilities, average per box, one box missed or added
        allowed), both for the whole writing and for its first word only (people
        write "MBEYA MJINI" where the list has "MBEYA", or the other way round).
          'sure'  - the whole writing matches a name about as well as the raw reading
          'guess' - the closest name; shown pre-selected but marked "Please check"
          'none'  - nothing close; the user chooses
        names: the candidates (e.g. only the districts of the region); default all.
        """
        names = self.names(list_name) if names is None else names
        raw = _norm(raw_text or "")
        if not names or not raw:
            return None, "none"
        # every way a name may be written -> the name (aliases: "TANZANIA" -> "TANZANIA, THE UNITED REPUBLIC")
        alias_of = {}
        allowed = set(names)
        for e in self.entries.get(list_name, []):
            if e["name"] in allowed:
                for a in e.get("aliases", [e["name"]]):
                    alias_of.setdefault(a, e["name"])
        for nm in names:
            alias_of.setdefault(nm, nm)
        if raw in alias_of:
            return alias_of[raw], "sure"
        best = self._match_raw(probs, raw, list(alias_of))
        name, how = (alias_of[best[0]], best[1]) if best[0] else (None, best[1])
        # A preferred name (most people: TANZANIA) is taken whenever the writing looks
        # like it, unless another name is clearly written.
        pref = self.lists.get(list_name, {}).get("preferred")
        if pref and how != "sure":
            pe = [e for e in self.entries.get(list_name, []) if e["name"] in allowed
                  and all(str(e.get(k)) == str(v) for k, v in pref.items() if k not in ("alias", "similarity"))]
            if pe:
                alias = _norm(pref.get("alias") or pe[0]["name"])
                letters = raw.replace(" ", "")
                ratio = difflib.SequenceMatcher(None, letters, alias.replace(" ", "")).ratio()
                if ratio >= pref.get("similarity", 0.6):
                    return pe[0]["name"], ("sure" if ratio >= 0.85 else "guess")
                if probs and len(probs) == len(letters) and abs(len(alias.replace(" ", "")) - len(letters)) <= 1:
                    P = np.log(np.clip(np.array(probs), 1e-6, 1))
                    if _score(P, re.sub(r"[^A-Z0-9]", "", alias)) / len(P) >= P[:, 10:].max(axis=1).mean() - PREFERRED_MARGIN:
                        return pe[0]["name"], "guess"
        return name, how

    def _match_raw(self, probs, raw, names):
        """Best of `names` for the raw reading: (name or None, how)."""
        words = raw.split(" ")
        if not probs or len(probs) != len(raw.replace(" ", "")):
            close = difflib.get_close_matches(raw, names, n=1, cutoff=GUESS_RATIO)
            return (close[0], "guess") if close else (None, "none")
        P = np.log(np.clip(np.array(probs), 1e-6, 1))
        n0 = len(words[0])
        P0 = P[:n0]                                     # boxes of the first written word
        raw_avg = P[:, 10:].max(axis=1).mean()          # best letter in each box
        best, best_avg, best_full = None, -np.inf, False
        for name in names:
            letters = re.sub(r"[^A-Z0-9]", "", name)
            first = re.sub(r"[^A-Z0-9]", "", name.split(" ")[0])
            if any(c not in CLASSES for c in letters):
                continue
            if abs(len(letters) - len(P)) <= 1:
                avg = _score(P, letters) / len(P)
                if avg > best_avg:
                    best, best_avg, best_full = name, avg, True
            if (len(words) > 1 or " " in name) and abs(len(first) - n0) <= 1 and n0 >= 3:
                avg = _score(P0, first) / n0 - FIRST_WORD_PENALTY
                if " " in name and len(words) == 1:
                    avg -= FIRST_WORD_PENALTY           # writing has one word, name has more
                if avg > best_avg:
                    best, best_avg, best_full = name, avg, False
        if best is None:
            return None, "none"
        if best_full and best_avg >= raw_avg - SURE_MARGIN:
            return best, "sure"
        if best_avg >= raw_avg - GUESS_MARGIN:
            return best, "guess"
        return None, "none"

    def _levels(self, group):
        """The group's (list, field) pairs from the top (region) down, loaded lists only."""
        order, lst = [], [l for l in self.lists if not self.lists[l].get("parent")]
        while lst:
            cur = lst[0]
            order.append(cur)
            lst = [l for l in self.lists if self.lists[l].get("parent") == cur]
        return [(l, group[l]) for l in order if l in group and self.entries.get(l)]

    def match_fields(self, pending):
        """pending: {field: (raw_text, probs)} for every lookup field read.
        Matches each group top-down (district only among the region's districts...).
        A name found lower down fills an empty or unreadable parent (marked 'guess').
        Returns {field: (name or None, how)}."""
        out = {}
        for group in self.groups:
            levels = self._levels(group)
            chosen = {}                                  # list -> set of ids of the chosen name
            for lst, field in levels:
                if field not in pending:
                    continue
                raw, probs = pending[field]
                parent = self.lists[lst].get("parent")
                pids = chosen.get(parent)
                cands = self.names(lst, pids) if pids else None
                name, how = self.match(probs, raw, lst, cands)
                if pids and name is None and raw:        # not found under that parent: try all
                    name, how = self.match(probs, raw, lst)
                    p_field = group.get(parent)
                    if name and how == "sure" and out.get(p_field, (None, ""))[1] == "guess":
                        # the parent was only a guess and this name clearly says otherwise: take
                        # the parent of this name, if it is under the same grandparent
                        gp = self.lists[parent].get("parent")
                        par = [e for e in self.entries[parent] if e.get("id") in
                               {c["parent_id"] for c in self.entries[lst] if c["name"] == name}
                               and (not chosen.get(gp) or e["parent_id"] in chosen[gp])]
                        if len(par) == 1:
                            out[p_field] = (par[0]["name"], "guess")
                            chosen[parent] = {par[0].get("id")}
                            pids = chosen[parent]
                    how = "guess" if name else how
                out[field] = (name, how)
                if name:
                    chosen[lst] = self.ids(lst, name, pids)
                    # fill in parents left empty or not recognised, from this name
                    child_ids, child_lst = chosen[lst], lst
                    while self.lists[child_lst].get("parent"):
                        p_lst = self.lists[child_lst]["parent"]
                        p_field = group.get(p_lst)
                        if not p_field or not self.entries.get(p_lst) or p_field not in pending:
                            break
                        par = {e["parent_id"] for e in self.entries[child_lst] if e.get("id") in child_ids}
                        if out.get(p_field, (None,))[0] is None and len(par) == 1:
                            pe = [e for e in self.entries[p_lst] if e.get("id") in par]
                            if pe:
                                out[p_field] = (pe[0]["name"], "guess")
                                chosen[p_lst] = par
                        child_ids, child_lst = par, p_lst
        return out

    def check(self, data):
        """Problems with place names: [(field, message)]. A name must be in its list,
        and under the region / district chosen in the same group."""
        problems = []
        for group in self.groups:
            ids = {}
            for lst, field in self._levels(group):
                v = data.get(field)
                if not v:
                    continue
                v = _norm(v)
                parent = self.lists[lst].get("parent")
                if v not in self.names(lst):
                    problems.append((field, f"'{v}' is not in the official {lst} list. Choose it from the list."))
                    continue
                pids = ids.get(parent)
                if pids and v not in self.names(lst, pids):
                    p_field = group[parent]
                    problems.append((field, f"{lst.capitalize()} '{v}' is not in {parent} "
                                            f"'{_norm(data.get(p_field))}'. Choose a {lst} of that {parent}, "
                                            f"or correct the {parent}."))
                    continue
                ids[lst] = self.ids(lst, v, pids)
        for field in self.choices:
            v = data.get(field)
            if v and _norm(v) not in self.choice_options(field):
                problems.append((field, f"'{v}' is not one of the values in the lookup. Choose one of the buttons."))
        return problems

    # ------------------------------------------------------------------ postcodes
    def _chain(self, group, data, upto):
        """Entries chosen in a group, from the top down to list `upto`: {list: entry}
        (an empty level is skipped; an unknown name stops the chain)."""
        out, pids = {}, None
        for lst, field in self._levels(group):
            v = data.get(field)
            if not v:
                pids = None                   # e.g. no country written: regions are not narrowed
                continue
            es = [e for e in self.entries[lst] if e["name"] == _norm(v)]
            if pids is not None:
                es = [e for e in es if e["parent_id"] in pids] or es
            if not es:
                break
            out[lst] = es[0]
            pids = {e.get("id") for e in es}
            if lst == upto:
                break
        return out

    def postcode(self, group, data):
        """Region postcode + district postcode + ward postcode, e.g. 17 + 1 + 06 = 17106.
        None until all of them are chosen."""
        chain = self._chain(group, data, self.postcode_from[-1])
        parts = [chain.get(l, {}).get("postcode") for l in self.postcode_from]
        if any(p is None or str(p).strip() == "" for p in parts):
            return None
        return "".join(str(p).strip() for p in parts)

    def fill_postcodes(self, data):
        """Set every postcode field from its group's region, district and ward."""
        for field, group in self.postcode_groups:
            if field in data:
                data[field] = self.postcode(group, data)
        return data

    def postcode_parts(self, field):
        """The fields a postcode field is made from (for the portal)."""
        for f, group in self.postcode_groups:
            if f == field:
                return [group[l] for l in self.postcode_from if l in group]
        return None

    # ------------------------------------------------------------------ tick-box values from the lookup
    def choice_options(self, field):
        """Values offered for a tick-box field, in lookup order, without repeats
        (MARRIED appears once even though the lookup has it for men and for women)."""
        seen, out = set(), []
        for e in self.choices.get(field, []):
            if e["value"] not in seen:
                seen.add(e["value"])
                out.append(e["value"])
        return out

    def _choice_entry(self, field, value, data):
        """The lookup entry for a value, preferring the one for the applicant's sex
        (marital status codes differ for men and women)."""
        es = [e for e in self.choices.get(field, []) if e["value"] == _norm(value or "")]
        flt = self.choice_cfg.get(field, {}).get("depends_on")      # {"field": "sex", "key": "gender"}
        if flt and len(es) > 1:
            dep = self._choice_entry(flt["field"], data.get(flt["field"]), data)
            if dep:
                es = [e for e in es if str(e.get(flt["key"])) == str(dep.get("id"))] or es
        return es[0] if es else None

    def map_choices(self, data):
        """Tick boxes read from the form ('male', 'self_employed') -> lookup values ('MALE',
        'SELF-EMPLOYED'). Returns the fields that need checking (two boxes ticked, or a box
        with no matching value in the lookup)."""
        unsure = []
        letters = lambda t: re.sub(r"[^A-Z0-9]", "", str(t).upper())
        for field, cfg in self.choice_cfg.items():
            if field not in self.choices or field not in data:
                continue
            v = data.get(field)
            if not v:
                continue
            if "," in str(v):                       # two boxes ticked: the user chooses
                data[field] = None
                unsure.append(field)
                continue
            wanted = cfg.get("boxes", {}).get(v)
            es = self.choices[field]
            hit = None
            if wanted:
                codes = [str(w) for w in (wanted if isinstance(wanted, list) else [wanted])]
                cands = [e for e in es if str(e.get("code")) in codes or letters(e["value"]) in map(letters, codes)]
                flt = cfg.get("depends_on")
                if flt and len(cands) > 1:
                    dep = self._choice_entry(flt["field"], data.get(flt["field"]), data)
                    if dep:
                        cands = [e for e in cands if str(e.get(flt["key"])) == str(dep.get("id"))] or cands
                hit = cands[0] if cands else None
            if hit is None:                         # same letters: self_employed = SELF-EMPLOYED
                hit = next((e for e in es if letters(e["value"]) == letters(v)), None)
            if hit is None:
                hit = next((e for e in es if letters(e["value"]).startswith(letters(v)[:5])), None)
            if hit is None:
                data[field] = None
                unsure.append(field)
            else:
                data[field] = hit["value"]
        return unsure

    def lookup_ids(self, data):
        """Ids in your lookup of every value chosen from a list ({"sex": 2, "birth_district": 6, ...}),
        to send on to your own system. Marital status uses the id for the applicant's sex."""
        ids = {}
        for group in self.groups:
            chain = self._chain(group, data, None)
            for lst, e in chain.items():
                ids[group[lst]] = e.get("id")
        for field in self.choices:
            e = self._choice_entry(field, data.get(field), data)
            if e:
                ids[field] = e.get("id")
        return ids

    def public(self):
        """For GET /api/lookups and the portal: the lists (id, name, parent id), which
        field uses which list, each field's parent field, and where the lists came from."""
        return {"lists": self.compact(),
                "fields": {f: n for f, n in self.field_list.items() if self.entries.get(n)},
                "parents": {f: self.parent_field(f) for f in self.field_list if self.parent_field(f)},
                "postcodes": {f: self.postcode_parts(f) for f, _ in self.postcode_groups},
                "choices": {f: self.choice_options(f) for f in self.choices},
                "status": self.status}

    def compact(self):
        return {k: [{"id": e.get("id"), "name": e["name"], "parent_id": e["parent_id"],
                     "postcode": e.get("postcode")} for e in v]
                for k, v in self.entries.items() if v}


def _score(P, letters):
    idx = [CLASSES.index(ch) for ch in letters]
    n, m = len(P), len(idx)
    if n == m:
        return P[np.arange(n), idx].sum()
    if n == m + 1:
        return max(np.delete(P, k, 0)[np.arange(m), idx].sum() for k in range(n)) - SKIP_PENALTY
    if n + 1 == m:
        return max(P[np.arange(n), idx[:k] + idx[k + 1:]].sum() for k in range(m)) - SKIP_PENALTY
    return -np.inf
