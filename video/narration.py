"""Step 1 of the explainer build: write the narration, synthesize it with the offline Windows voice,
and write work/timeline.json (scene id, text, start, duration). Numbers are read from the saved demo output."""
import json, pathlib, re, subprocess, wave

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = HERE / "work"
(WORK / "audio").mkdir(parents=True, exist_ok=True)

idx = (ROOT / "docs" / "indexing_demo.txt").read_text(encoding="utf-8")
ms = [float(x) for x in re.findall(r"([\d.]+) ms", idx)]
scan_ms, tree_ms = round(ms[0]), ms[1]

SCENES = [
    ("title", "This is HemoGrid, a blood bank database. The idea is simple: let the database enforce the rules, and keep the web page thin."),
    ("arch", "PostgreSQL is the system of record: donors, donations, blood units, requests and allocations. "
             "MongoDB holds the lab screening reports, whose fields differ for every donor. "
             "A small web app sits on top, and it only calls database functions."),
    ("er", "First, the E R diagram. Person is a superclass, specialised into donor, recipient and staff, because one person can play more than one role. "
           "A donor's phones and camps are multivalued, so each gets its own table. "
           "A donation is separated into blood units, and units are reserved for hospital requests through an allocation table, where a unit can appear only once."),
    ("norm", "Next, normalization. I wrote down the functional dependencies, then decomposed step by step. "
             "Shelf life depends only on the component, so it lives in its own table, and every table ends up in Boyce Codd normal form. "
             "If phones and camps shared a table, adding one phone number would force a row per camp. That multivalued dependency is why they are split, which gives fourth normal form. "
             "One redundancy is deliberate: a unit's blood group is copied once onto its label, and never changes."),
    ("sql", "Now the S Q L objects. A domain check rejects impossible blood groups. "
            "A trigger refuses a donation when the donor is under age, deferred, or inside the ninety or one hundred and twenty day gap. "
            "Another trigger fills in each unit's group, expiry date and barcode. A status trigger forbids illegal moves, such as expired back to available, and an audit trigger records every change. "
            "The allocate units function picks the patient's own group first, then the soonest expiry. "
            "Views feed the dashboard, and three roles get only the permissions they need."),
    ("index", f"Indexing. On four hundred thousand rows, the allocation lookup takes about {scan_ms} milliseconds as a full scan, "
              "but under a tenth of a millisecond with a partial, composite B plus tree on group, component and expiry. "
              "Barcode scans use a hash index, because they are always an exact match. For a date range, only the B plus tree helps, and the planner ignores the hash."),
    ("txn", "Transactions. One O negative unit is left, and two emergency requests arrive together. "
            "A naive read then write sees the unit as free in both, and only a unique constraint prevents a double booking. "
            "With for update skip locked, one request wins and the other stays open, with no error. "
            "At serializable isolation, one transaction is aborted and retried. Locking in opposite order causes a deadlock, which PostgreSQL detects. "
            "A rollback undoes everything, and a commit is flushed to the write ahead log: atomic, consistent, isolated and durable."),
    ("nosql", "NoSQL. Each screening report is a MongoDB document, and its questionnaire varies per donor. "
              "PostgreSQL decides pass or fail and creates the units, and the report is written afterwards, so a refusal leaves no orphan document. "
              "In C A P terms, unit status chooses consistency, while reports can tolerate delay."),
    ("close", "To sum up: constraints, triggers and functions enforce the rules. Indexes and locks give speed and safe concurrency. Roles limit access, and MongoDB holds the flexible reports. "
              "Thirteen database tests and thirteen interface flows cover it."),
]

PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Zira Desktop'); $s.Rate = 1; $s.Volume = 100
$items = Get-Content -Raw -Encoding UTF8 '%s' | ConvertFrom-Json
foreach ($i in $items) {
  $s.SetOutputToWaveFile("%s\$($i.id).wav")
  $s.Speak($i.text)
  $s.SetOutputToNull()
}
"""

(WORK / "narration.json").write_text(json.dumps([{"id": i, "text": t} for i, t in SCENES], indent=1), encoding="utf-8")
ps1 = WORK / "speak.ps1"
ps1.write_text(PS % (str(WORK / "narration.json"), str(WORK / "audio")), encoding="utf-8")
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)], check=True)

PAD_LEAD, PAD_TAIL = 0.5, 0.9           # air before/after each scene's narration
t, timeline = 0.0, []
for sid, text in SCENES:
    with wave.open(str(WORK / "audio" / f"{sid}.wav")) as w:
        dur = w.getnframes() / w.getframerate()
    total = PAD_LEAD + dur + PAD_TAIL
    timeline.append({"id": sid, "text": text, "start": round(t, 3), "narr_start": round(t + PAD_LEAD, 3), "narr_dur": round(dur, 3), "dur": round(total, 3)})
    t += total
(WORK / "timeline.json").write_text(json.dumps({"total": round(t, 3), "scenes": timeline, "scan_ms": scan_ms, "tree_ms": tree_ms}, indent=1), encoding="utf-8")
print(f"total {t:.1f}s")
for s in timeline:
    print(f"  {s['id']:<6} {s['start']:>6.1f}s  {s['dur']:>5.1f}s")
