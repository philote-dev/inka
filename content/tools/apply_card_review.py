"""Apply Frank's card-review verdicts from REVIEW-CARDS-reviewed.md.

DROP moves the file to content/gold/dropped/ (duplicates). FIX applies the
specific correction Frank asked for (patched below). KEEP just marks verified.
Every kept card gets verification.status = verified with Frank and the date.

Run:
    python content/tools/apply_card_review.py
"""

from __future__ import annotations

import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
CARDS = os.path.join(CONTENT, "gold", "cards")
DROPPED = os.path.join(CONTENT, "gold", "dropped")
SHEET = os.path.join(CONTENT, "gold", "REVIEW-CARDS-reviewed.md")
TODAY = "2026-07-05"


def facts(*claims: str) -> list[dict]:
    return [{"claim": c, "must_hold": True} for c in claims]


# Per-card corrections, from Frank's notes.
PATCHES: dict[str, dict] = {
    "gold-card-0011": {
        "back": "Coulomb's constant, \\( k = \\dfrac{1}{4\\pi\\epsilon_0} \\).",
        "fact_assertions": facts(
            "The proportionality constant in Coulomb's law is Coulomb's constant \\( k = 1/(4\\pi\\epsilon_0) \\); "
            "\\( \\epsilon_0 \\) is the vacuum permittivity, not the constant itself."),
    },
    "gold-card-0020": {
        "blueprint_area": "mechanics",
        "topic": {"category": "mechanics", "subtopic": "dynamics_energy"},
    },
    "gold-card-0021": {
        "back": "The source states \\( h_0 \\geq \\hbar \\); more generally a phase-space cell has a size of order "
                "\\( \\hbar \\) (or \\( h \\), by convention) per conjugate coordinate-momentum pair.",
        "fact_assertions": facts(
            "A phase-space cell has size of order \\( \\hbar \\) per conjugate pair; the exact constant is "
            "convention-dependent (the source uses \\( h_0 \\geq \\hbar \\))."),
    },
    "gold-card-0024": {
        "back": "\\( [J_x, J_y] = i\\hbar J_z \\), with cyclic permutations \\( [J_y, J_z] = i\\hbar J_x \\) "
                "and \\( [J_z, J_x] = i\\hbar J_y \\).",
        "fact_assertions": facts(
            "The total angular momentum components satisfy \\( [J_x, J_y] = i\\hbar J_z \\) and cyclic permutations."),
    },
    "gold-card-0026": {
        "card_kind": "conceptual",
        "back": "To first order it is proportional to \\( \\langle \\mathbf{S}\\cdot\\mathbf{L} \\rangle = "
                "\\tfrac{\\hbar^2}{2}\\,[\\,j(j+1) - l(l+1) - s(s+1)\\,] \\) times the radial expectation "
                "\\( \\langle 1/r^3 \\rangle \\); with \\( s = 1/2 \\) the angular factor is \\( j(j+1) - l(l+1) - 3/4 \\).",
        "fact_assertions": facts(
            "The first-order spin-orbit shift is proportional to \\( \\langle \\mathbf{S}\\cdot\\mathbf{L} \\rangle \\) "
            "and to \\( \\langle 1/r^3 \\rangle \\).",
            "For \\( s = 1/2 \\) the angular factor is \\( j(j+1) - l(l+1) - 3/4 \\)."),
        "_remove": ["computational", "solution_decomposition"],
    },
    "gold-card-0030": {
        "back": "Classical mechanics is used for translational (continuous phase-space) motion as far as possible, "
                "while internal degrees of freedom often require a quantum treatment.",
        "fact_assertions": facts(
            "The classical approach treats translational motion classically; internal motions often require a "
            "quantum treatment."),
    },
    "gold-card-0032": {
        "back": "13.6 eV (the energy to remove the electron from the \\( n=1 \\) ground state to the ionization limit).",
        "fact_assertions": facts(
            "The ionization energy of hydrogen from the \\( n=1 \\) Bohr orbit is 13.6 eV."),
    },
    "gold-card-0040": {
        "back": "It becomes partially polarized, with the component parallel to the reflecting surface favored; "
                "at Brewster's angle it is completely polarized.",
        "fact_assertions": facts(
            "Unpolarized light reflected from a surface is partially polarized (the component parallel to the "
            "surface is favored), and completely polarized at Brewster's angle."),
    },
    "gold-card-0042": {"_section": "5.4 Length Contraction"},
    "gold-card-0043": {"_section": "5.2 Relativity of Simultaneity and Time Intervals"},
    "gold-card-0049": {
        "back": "The rock-salt structure: two interpenetrating face-centered-cubic (FCC) sublattices, one of "
                "Na\\(^+\\) and one of Cl\\(^-\\).",
        "fact_assertions": facts(
            "NaCl has the rock-salt structure: two interpenetrating FCC sublattices, one Na, one Cl."),
    },
    "gold-card-0050": {
        "back": "About 13.8 billion years.",
        "fact_assertions": facts(
            "The universe is approximately 13.8 billion years old in current cosmological models."),
    },
}


def parse_sheet() -> dict[str, dict]:
    txt = open(SHEET, encoding="utf-8").read()
    out: dict[str, dict] = {}
    for b in re.split(r"^### \d+\. `", txt, flags=re.M)[1:]:
        iid = re.match(r"([^`]+)`", b).group(1)
        vm = re.search(r"DROP\)\s*:\s*(.*?)\s*-?\s*Notes\s*:", b, flags=re.S)
        verdict = (vm.group(1).strip() if vm else "")
        nm = re.search(r"Notes\s*:\s*(.*?)(?:\n---|\Z)", b, flags=re.S)
        note = (nm.group(1).strip() if nm else "")
        if note in ("---", "-"):
            note = ""
        out[iid] = {"verdict": verdict, "note": note}
    return out


def apply_patch(item: dict, patch: dict) -> None:
    for k, v in patch.items():
        if k.startswith("_"):
            continue
        item[k] = v
    if "_section" in patch:
        item["provenance"]["source_ref"]["section"] = patch["_section"]
    for rm in patch.get("_remove", []):
        item.pop(rm, None)


def main() -> None:
    verdicts = parse_sheet()
    os.makedirs(DROPPED, exist_ok=True)
    kept = fixed = dropped = 0
    drop_log = ["", "## Dropped cards (Frank review, 2026-07-05)", ""]

    for name in sorted(os.listdir(CARDS)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CARDS, name)
        item = json.load(open(path, encoding="utf-8"))
        iid = item["id"]
        rec = verdicts.get(iid, {"verdict": "KEEP", "note": ""})
        up = rec["verdict"].upper()

        if up.startswith("DROP"):
            shutil.move(path, os.path.join(DROPPED, name))
            drop_log.append(f"- `{iid}`: {rec['note'] or 'no reason given'}")
            dropped += 1
            continue

        v = item.setdefault("verification", {})
        v["status"] = "verified"
        v["verified_by"] = "Frank"
        v["verified_at"] = TODAY
        if rec["note"]:
            v["frank_note"] = rec["note"]
        if iid in PATCHES:
            apply_patch(item, PATCHES[iid])
            v["adjudication"] = "Corrected per Frank's review."
            fixed += 1
        else:
            kept += 1
        json.dump(item, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    with open(os.path.join(DROPPED, "DROP-LOG.md"), "a", encoding="utf-8") as fh:
        fh.write("\n".join(drop_log) + "\n")

    print(f"kept: {kept}   fixed: {fixed}   dropped: {dropped}   remaining: {kept + fixed}")
    missing = [i for i in PATCHES if not os.path.exists(os.path.join(CARDS, i + ".json"))]
    if missing:
        print("WARNING: patch target missing:", missing)


if __name__ == "__main__":
    main()
