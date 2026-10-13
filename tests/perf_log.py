"""Record performance measurements into docs/perf.md (between PERF markers)."""

import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "docs", "perf.json")
DOC = os.path.join(ROOT, "docs", "perf.md")


def record(name, value, unit, budget=None, note=""):
    data = {}
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as fh:
            data = json.load(fh)
    data[name] = {"value": float("{:.4g}".format(float(value))), "unit": unit, "budget": budget, "note": note,
                  "date": datetime.date.today().isoformat()}
    with open(STORE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    rows = ["| Measure | Result | Budget | Pass | Date | Note |", "| --- | --- | --- | --- | --- | --- |"]
    for k in sorted(data):
        d = data[k]
        ok = "" if d["budget"] is None else ("yes" if d["value"] <= d["budget"] else "NO")
        bud = "" if d["budget"] is None else "{} {}".format(d["budget"], d["unit"])
        rows.append("| {} | {:.4g} {} | {} | {} | {} | {} |".format(k, d["value"], d["unit"], bud, ok, d["date"],
                                                                  d["note"]))
    with open(DOC, encoding="utf-8") as fh:
        text = fh.read()
    a, b = text.index("<!-- PERF:BEGIN -->"), text.index("<!-- PERF:END -->")
    text = text[:a] + "<!-- PERF:BEGIN -->\n" + "\n".join(rows) + "\n" + text[b:]
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write(text)
