#!/usr/bin/env python3
"""Shared helpers for parsing Physics GRE forms into structured items.

Furniture stripping, choice splitting, figure/math flags, and a keyword
topic classifier over the 9 PGRE content areas. Reads nothing on import.
"""
from __future__ import annotations

import re

# --- furniture that appears on ETS practice-book pages ---
FURNITURE_PATTERNS = [
    r"Unauthorized copying or reuse of\s*any part of this page is illegal\.?",
    r"Unauthorized copying or reuse of any part of this page is illegal\.?",
    r"GO ON TO THE NEXT PAGE\.?",
    r"SCRATCH ?WORK",
    r"NO TEST MATERIAL ON THIS PAGE",
    r"<<<PAGE\s*\d+>>>",
    r"PHYSICS TEST",
    r"Time\s*[—–-]\s*\d+\s*minutes",
    r"\b100 Questions\b",
    r"GRADUATE RECORD EXAMINATIONS",
    r"Copyright\b.*?reserved\.?",
    r"FORM GR\d{4}",
    # directions-header fragments (exact and OCR-garbled variants)
    r"Directions:.*",
    r"Select the one that is best.*",
    r"suggested answers or comple.*",
    r"incomplete statements?.*",
    r"corresponding space.*",
    r"in the corresponding.*",
    r"answer sheet\.?",
    r"\bpletions\b\.?",
    r"\bPHY\b",
    r"Time-\s*\S{0,4}",
]
FURNITURE_RE = re.compile("|".join(FURNITURE_PATTERNS), re.IGNORECASE)

DIRECTIONS_RE = re.compile(
    r"Directions:.*?fill in the corresponding space on the answer sheet\.",
    re.IGNORECASE | re.DOTALL,
)


def strip_furniture(text: str) -> str:
    text = DIRECTIONS_RE.sub(" ", text)
    text = FURNITURE_RE.sub(" ", text)
    out_lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"\d{1,3}", s):  # lone page number
            continue
        if re.fullmatch(r"[•®\W_]+", s):  # junk glyph lines
            continue
        out_lines.append(ln)
    return "\n".join(out_lines)


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_ws(s: str) -> str:
    s = _CTRL_RE.sub(" ", s)  # custom-font control glyphs (middot, etc.)
    return re.sub(r"\s+", " ", s).strip()


CHOICE_LABELS = ["A", "B", "C", "D", "E"]


def split_stem_choices(block: str):
    """Split a question block into (stem, {A..E}).

    Uses the first occurrence of each `(X)` marker and assigns each choice the
    text span up to the next marker BY POSITION. This handles both single-column
    choices (A,B,C,D,E in order) and two-column choice grids (which read
    A,D,B,E,C in text order, as in the REA prep book).

    Returns (stem, choices_dict, found_all_bool).
    """
    marks = []  # (pos, end, label)
    for lab in CHOICE_LABELS:
        m = re.search(r"\(%s\)" % lab, block)
        if m:
            marks.append((m.start(), m.end(), lab))
    if not marks:
        return clean_ws(block), {lab: "" for lab in CHOICE_LABELS}, False
    marks.sort()  # by position in text
    stem = clean_ws(block[: marks[0][0]])
    choices = {lab: "" for lab in CHOICE_LABELS}
    for i, (_start, end, lab) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(block)
        choices[lab] = clean_ws(block[end:nxt])
    found_all = len(marks) == 5
    return stem, choices, found_all


FIGURE_HINT_RE = re.compile(
    r"figure (above|below|shown)|shown (above|below)|as shown|the diagram|"
    r"the graph above|the graph below|figure\b|graph\b|circuit shown|"
    r"following (figures|diagrams|graphs)",
    re.IGNORECASE,
)


def figure_dependent(stem: str, choices: dict) -> bool:
    empties = sum(1 for v in choices.values() if not v.strip())
    if empties >= 2:  # figure-based choices
        return True
    if FIGURE_HINT_RE.search(stem):
        return True
    return False


def math_garbled(stem: str, choices: dict, fig: bool) -> bool:
    """Heuristic for lost math: dropped choices (not figure) or split fractions."""
    empties = sum(1 for v in choices.values() if not v.strip())
    if not fig and empties >= 1:  # a choice went missing without a figure reason
        return True
    joined = stem + " " + " ".join(choices.values())
    lone_digits = len(re.findall(r"(?<!\S)\d(?!\S)", joined))
    return lone_digits >= 4


# --- topic classifier over the 9 PGRE content areas ---
TOPIC_KEYWORDS = [
    ("Special Relativity", [
        "relativ", "lorentz", "time dilation", "length contraction", "rest mass",
        "space-time", "spacetime", "proper time", "four-vector", "muon", "gamma factor",
    ]),
    ("Quantum Mechanics", [
        "wave function", "wavefunction", "schrodinger", "schr\u00f6dinger", "eigenstate",
        "eigenvalue", "operator", "commutator", "hamiltonian", "hilbert", "spin",
        "hydrogen atom", "expectation value", "perturbation", "harmonic oscillator",
        "infinite well", "potential well", "barrier", "tunnel", "de broglie",
        "uncertainty", "hermitian", "bohr", "quantum",
    ]),
    ("Atomic Physics", [
        "electron configuration", "spectroscopic", "fine structure", "zeeman",
        "selection rule", "ionization", "energy level", "balmer", "lyman", "rydberg",
        "franck-hertz", "x-ray", "characteristic", "photoelectric", "atomic",
        "stern-gerlach", "orbital",
    ]),
    ("Thermodynamics and Statistical Mechanics", [
        "entropy", "carnot", "adiabatic", "isothermal", "thermal equilibrium",
        "partition function", "boltzmann", "fermi-dirac", "bose-einstein", "heat capacity",
        "specific heat", "ideal gas", "equipartition", "thermodynamic", "temperature",
        "efficiency", "engine", "reservoir", "statistical",
    ]),
    ("Optics and Wave Phenomena", [
        "lens", "mirror", "focal", "diffraction", "interference", "polariz",
        "refraction", "snell", "wavelength", "double slit", "grating", "telescope",
        "microscope", "thin film", "doppler", "standing wave", "beats", "resonance",
        "index of refraction", "optical", "image",
    ]),
    ("Electromagnetism", [
        "capacitor", "resistor", "inductor", "circuit", "magnetic field", "electric field",
        "charge", "current", "voltage", "gauss", "ampere", "faraday", "coulomb",
        "dielectric", "potential difference", "flux", "solenoid", "emf", "impedance",
        "electromagnetic", "conductor", "dipole", "biot", "lorentz force",
    ]),
    ("Classical Mechanics", [
        "pendulum", "orbit", "collision", "momentum", "kinetic energy", "potential energy",
        "friction", "torque", "angular momentum", "moment of inertia", "lagrangian",
        "oscillat", "spring", "projectile", "rotational", "rigid body", "gravitation",
        "kepler", "centripetal", "velocity", "acceleration", "newton", "mass",
    ]),
    ("Laboratory Methods", [
        "uncertainty", "precision", "accuracy", "standard deviation", "poisson",
        "error", "least squares", "counting statistics", "oscilloscope", "detector",
        "measurement", "significant figure", "instrument",
    ]),
    ("Specialized Topics", [
        "nucle", "quark", "lepton", "hadron", "half-life", "radioact", "decay",
        "binding energy", "cross section", "crystal", "lattice", "bravais", "semiconductor",
        "band gap", "superconduct", "condensed", "cosmolog", "hubble", "particle physics",
        "fission", "fusion", "isotope", "bragg", "phonon", "fermi energy",
    ]),
]


def guess_topic(text: str) -> str:
    low = text.lower()
    best = None
    best_score = 0
    for topic, kws in TOPIC_KEYWORDS:
        score = sum(low.count(kw) for kw in kws)
        if score > best_score:
            best_score = score
            best = topic
    return best or "Unclassified"
