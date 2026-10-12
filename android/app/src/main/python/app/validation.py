"""Logic checks on an enrolment (the values read from the form, after the user's
corrections). All limits come from app/validation_rules.json.

    issues = validate(data)            # list of problems, empty if all is well

Each problem is a dict:
    {"rule": "phone_number", "fields": ["phone_number"], "severity": "error",
     "message": "Phone number must have exactly 10 digits (it has 9)."}

"fields" lists every field the problem concerns, so the user interface can show
it next to each of them (e.g. middle name AND father's first name).
"""
import datetime as dt
import json
import os
import re

RULES_PATH = os.path.join(os.path.dirname(__file__), "validation_rules.json")


def load_rules(path=RULES_PATH):
    """Read the rules file each time, so edits apply without restarting."""
    with open(path, encoding="utf-8") as fh:
        rules = json.load(fh)
    return {k: v for k, v in rules.items() if not k.startswith("_") and isinstance(v, dict)}


def _year(date_value):
    """Year (int) from 'DD/MM/YYYY' or a plain 'YYYY'; None if missing or not 4 digits."""
    if not date_value or not isinstance(date_value, str):
        return None
    part = date_value.split("/")[-1].strip()
    return int(part) if re.fullmatch(r"\d{4}", part) else None


def _name(v):
    return re.sub(r"\s+", " ", v).strip().upper() if isinstance(v, str) else ""


def _issue(rule, cfg, fields, message):
    return {"rule": rule, "fields": fields, "severity": cfg.get("severity", "error"), "message": message}


def validate(data, rules=None, lookups=None):
    """lookups: the official name lists (app/lookups.py), for the 'from the list' check."""
    rules = load_rules() if rules is None else rules
    this_year = dt.date.today().year
    out = []
    on = lambda key: rules.get(key, {}).get("enabled", False)
    birth = _year(data.get("date_of_birth"))

    # Item 5: year of birth within the allowed range
    if on("applicant_birth_year"):
        cfg = rules["applicant_birth_year"]
        lo = cfg.get("min_year") or 1900
        hi = cfg.get("max_year") or this_year
        if birth is None:
            out.append(_issue("applicant_birth_year", cfg, ["date_of_birth"],
                              "Enter the date of birth with a 4-digit year (DD/MM/YYYY)."))
        elif not lo <= birth <= hi:
            out.append(_issue("applicant_birth_year", cfg, ["date_of_birth"],
                              f"Year of birth must be between {lo} and {hi} (it is {birth})."))

    # Item 7: phone number has exactly N digits
    if on("phone_number"):
        cfg = rules["phone_number"]
        n = int(cfg.get("digits", 10))
        phone = (data.get("phone_number") or "").replace(" ", "")
        if not phone:
            if cfg.get("required", True):
                out.append(_issue("phone_number", cfg, ["phone_number"], f"Enter the phone number ({n} digits)."))
        elif not phone.isdigit():
            out.append(_issue("phone_number", cfg, ["phone_number"], "Phone number must contain digits only."))
        elif len(phone) != n:
            out.append(_issue("phone_number", cfg, ["phone_number"],
                              f"Phone number must have exactly {n} digits (it has {len(phone)})."))

    # Items 10 and 11: employed -> employer's name required
    if on("employer_name_when_employed"):
        cfg = rules["employer_name_when_employed"]
        status = data.get("employment_status") or ""
        letters = lambda t: re.sub(r"[^A-Z0-9]", "", str(t).upper())   # employed = EMPLOYED
        wanted = {letters(w) for w in cfg.get("statuses", ["employed"])}
        if any(letters(s) in wanted for s in str(status).split(",")) and not _name(data.get("employer_name")):
            out.append(_issue("employer_name_when_employed", cfg, ["employer_name", "employment_status"],
                              "'Employed' is ticked, so the employer's name (item 11) must be filled in."))

    # Item 14: primary school completed a sensible number of years after birth
    if on("primary_school_completion_year"):
        cfg = rules["primary_school_completion_year"]
        raw = (data.get("primary_school_completion_year") or "").replace(" ", "")
        if raw:
            done = int(raw) if re.fullmatch(r"\d{4}", raw) else None
            gap = int(cfg.get("min_years_after_birth", 10))
            if done is None:
                out.append(_issue("primary_school_completion_year", cfg, ["primary_school_completion_year"],
                                  "Year primary school was completed must be a 4-digit year."))
            elif cfg.get("not_after_this_year", True) and done > this_year:
                out.append(_issue("primary_school_completion_year", cfg, ["primary_school_completion_year"],
                                  f"Year primary school was completed ({done}) is in the future."))
            elif birth is not None and done - birth < gap:
                out.append(_issue("primary_school_completion_year", cfg,
                                  ["primary_school_completion_year", "date_of_birth"],
                                  (f"Primary school completed in {done}, before the year of birth ({birth})."
                                   if done < birth else
                                   f"Primary school completed in {done}, only {done - birth} years after birth "
                                   f"({birth}); it must be at least {gap} years.")))

    # Item 2 = item 15: middle name is the father's first name
    if on("middle_name_is_father_first_name"):
        cfg = rules["middle_name_is_father_first_name"]
        mid, father = _name(data.get("middle_name")), _name(data.get("father_first_name"))
        if (mid or father) and mid != father:
            out.append(_issue("middle_name_is_father_first_name", cfg, ["middle_name", "father_first_name"],
                              f"Middle name (item 2) must be the father's first name (item 15): "
                              f"'{mid or '(empty)'}' and '{father or '(empty)'}' differ."))

    # Items 19 and 24: parents old enough compared with the applicant
    for key, field, who in (("father_birth_year", "father_date_of_birth", "Father"),
                            ("mother_birth_year", "mother_date_of_birth", "Mother")):
        if not on(key):
            continue
        cfg = rules[key]
        py = _year(data.get(field))
        if data.get(field) and py is None:
            out.append(_issue(key, cfg, [field], f"{who}'s date of birth needs a 4-digit year (DD/MM/YYYY)."))
            continue
        if py is None or birth is None:
            continue
        gap = int(cfg.get("min_years_older_than_applicant", 15))
        if birth - py < gap:
            out.append(_issue(key, cfg, [field, "date_of_birth"],
                              f"{who} born in {py} is only {birth - py} years older than the applicant "
                              f"(born {birth}); must be at least {gap} years older." if birth >= py else
                              f"{who} born in {py}, after the applicant (born {birth})."))
    # Region, district, ward (and village) fields: a name from the official list, and under the
    # region / district chosen in the same section (app/lookups.py, app/lookup_settings.json)
    if on("names_from_official_list") and lookups is not None:
        cfg = rules["names_from_official_list"]
        for field, message in lookups.check(data):
            out.append(_issue("names_from_official_list", cfg, [field], message))
    return out


def has_errors(issues):
    return any(i["severity"] == "error" for i in issues)
