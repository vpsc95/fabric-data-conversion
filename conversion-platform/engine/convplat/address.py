"""Deterministic US address parsing (the platform's first pass before any address service).

Splits a one-line street address into number, pre-direction, street name, suffix (USPS abbreviation),
post-direction and unit. It stands in for the SmartyStreets parse in the legacy process; in the target
architecture Azure Maps (or Smarty) verifies the parsed address, and only leftovers go to a person or
to the regional AI deployment.
"""
from __future__ import annotations

import re

SUFFIX = {  # USPS C1 street suffixes most common in the service area (full form -> abbreviation)
    "ALLEY": "ALY", "ALY": "ALY", "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE", "BEND": "BND", "BND": "BND",
    "BOULEVARD": "BLVD", "BLVD": "BLVD", "BRANCH": "BR", "BR": "BR", "CIRCLE": "CIR", "CIR": "CIR", "COURT": "CT",
    "CT": "CT", "COVE": "CV", "CV": "CV", "CREEK": "CRK", "CRK": "CRK", "CRESCENT": "CRES", "CRES": "CRES",
    "CROSSING": "XING", "XING": "XING", "DRIVE": "DR", "DR": "DR", "EXPRESSWAY": "EXPY", "EXPY": "EXPY",
    "FREEWAY": "FWY", "FWY": "FWY", "GLEN": "GLN", "GLN": "GLN", "GREEN": "GRN", "GRN": "GRN", "HIGHWAY": "HWY",
    "HWY": "HWY", "HILL": "HL", "HL": "HL", "HILLS": "HLS", "HLS": "HLS", "HOLLOW": "HOLW", "HOLW": "HOLW",
    "LANE": "LN", "LN": "LN", "LOOP": "LOOP", "PARK": "PARK", "PARKWAY": "PKWY", "PKWY": "PKWY", "PASS": "PASS",
    "PATH": "PATH", "PLACE": "PL", "PL": "PL", "PLAZA": "PLZ", "PLZ": "PLZ", "POINT": "PT", "PT": "PT",
    "RIDGE": "RDG", "RDG": "RDG", "ROAD": "RD", "RD": "RD", "ROW": "ROW", "RUN": "RUN", "SQUARE": "SQ", "SQ": "SQ",
    "STREET": "ST", "ST": "ST", "TERRACE": "TER", "TER": "TER", "TRACE": "TRCE", "TRCE": "TRCE", "TRAIL": "TRL",
    "TRL": "TRL", "VALLEY": "VLY", "VLY": "VLY", "VIEW": "VW", "VW": "VW", "WALK": "WALK", "WAY": "WAY",
}
DIRECTION = {"N": "N", "S": "S", "E": "E", "W": "W", "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW",
             "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE", "NORTHWEST": "NW",
             "SOUTHEAST": "SE", "SOUTHWEST": "SW"}
UNIT = {"APT", "UNIT", "STE", "SUITE", "LOT", "SPC", "SPACE", "BLDG", "TRLR", "RM", "FL", "MTR", "IRR"}
METER_TAG = re.compile(r"^\d+(MTR|IRR)$")          # SAMPLE service-address tags such as 1MTR / 1IRR


def parse_street(address: str) -> dict:
    out = {"number": "", "predir": "", "name": "", "suffix": "", "postdir": "", "unit": ""}
    t = address.upper().replace(",", " ").replace('"', " ").split()
    if not t:
        return out
    if re.match(r"^\d", t[0]):
        out["number"] = t.pop(0)
    for i, w in enumerate(t):
        if w in UNIT or w.startswith("#") or METER_TAG.match(w):
            out["unit"], t = " ".join(t[i:]), t[:i]
            break
    if len(t) > 1 and t[0] in DIRECTION:
        out["predir"] = DIRECTION[t.pop(0)]
    if len(t) > 1 and t[-1] in DIRECTION:
        out["postdir"] = DIRECTION[t.pop()]
    if len(t) > 1 and t[-1] in SUFFIX:
        out["suffix"] = SUFFIX[t.pop()]
    out["name"] = " ".join(t)
    return out
