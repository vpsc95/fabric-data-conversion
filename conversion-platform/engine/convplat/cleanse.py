"""Deterministic cleansing proposals for gate 2.

The module reads gold staging rows (and selected silver columns where the received text is needed),
writes proposal rows to run.CleanseProposal, and never updates gold tables. Console/reporting helpers
return counts only; before/after values stay inside the conversion database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import sqlio
from .specs import ClientSpecs

STATE_TO_CODE = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}
STATE_CODES = set(STATE_TO_CODE.values())

STREET_SUFFIX = {
    "ALLEY": "ALY", "ANNEX": "ANX", "AVENUE": "AVE", "BOULEVARD": "BLVD", "CIRCLE": "CIR",
    "COURT": "CT", "DRIVE": "DR", "EXPRESSWAY": "EXPY", "HIGHWAY": "HWY", "LANE": "LN",
    "PARKWAY": "PKWY", "PLACE": "PL", "ROAD": "RD", "SQUARE": "SQ", "STREET": "ST", "TERRACE": "TER",
    "TRAIL": "TRL", "TURNPIKE": "TPKE", "WAY": "WAY",
}

CARE_OF_RE = re.compile(r"\b(C/O|C\\O|CARE\s+OF|ATTN:?|ATTENTION:?)\b", re.IGNORECASE)
MULTI_PERSON_RE = re.compile(r"\s(&|\bAND\b|/)\s", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-']+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
EXT_RE = re.compile(r"\b(EXT\.?|EXTENSION|X)\s*\d+\b", re.IGNORECASE)
NON_DIGIT_RE = re.compile(r"\D+")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Proposal:
    module: str
    row_id: int
    record_key: str
    field: str
    rule_id: str
    before: str
    after: str
    confidence: float
    band: str
    reason: str


def compact_spaces(value: str) -> str:
    return SPACE_RE.sub(" ", (value or "").strip())


def first_token_before_legacy_break(value: str) -> str:
    text = (value or "").strip()
    points = [p for p in (text.find(" "), text.find(",")) if p >= 0]
    return text[:min(points)] if points else text


def digits(value: str) -> str:
    return NON_DIGIT_RE.sub("", value or "")


def band(confidence: float, threshold: float) -> str:
    return "high" if confidence >= threshold else "low"


def add(out: list[Proposal], module: str, row_id: int, record_key: str, field: str, rule_id: str,
        before: str | None, after: str | None, confidence: float, threshold: float, reason: str) -> None:
    before_s = "" if before is None else str(before)
    after_s = "" if after is None else str(after)
    if before_s == after_s and not rule_id.endswith("_REVIEW"):
        return
    out.append(Proposal(module, int(row_id), record_key or "", field, rule_id, before_s[:400], after_s[:400],
                        min(confidence, 0.99), band(confidence, threshold), reason[:400]))


def propose_phone(out: list[Proposal], row: dict, field: str, source_field: str, threshold: float) -> None:
    raw = row.get(source_field) or ""
    if not raw.strip():
        return
    legacy_part = first_token_before_legacy_break(raw)
    all_digits = digits(raw)
    legacy_digits = digits(legacy_part)
    if EXT_RE.search(raw) or (len(all_digits) > 10 and all_digits[:10] == legacy_digits[:10]):
        after = all_digits[:10] if len(all_digits) >= 10 else legacy_digits
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], field, "CLN_PHONE_EXTENSION_REVIEW", raw, after,
            0.75, threshold, "Phone includes extension or extra text; analyst/client review required.")
    elif len(legacy_digits) == 10 and legacy_digits != (row.get(field) or ""):
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], field, "CLN_PHONE_10_DIGIT", raw, legacy_digits,
            0.95, threshold, "Legacy-truncated phone can be normalized to digits-only ten-digit form.")
    elif legacy_digits and len(legacy_digits) != 10:
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], field, "CLN_PHONE_REVIEW", raw, legacy_digits,
            0.65, threshold, "Phone does not produce a ten-digit value after deterministic cleanup.")


def propose_email(out: list[Proposal], row: dict, threshold: float) -> None:
    before = row.get("Email") or ""
    if not before.strip():
        return
    after = before.strip().lower()
    if EMAIL_RE.match(after):
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], "Email", "CLN_EMAIL_TRIM_LOWER", before, after,
            0.96, threshold, "Email has deterministic trim/lower-case cleanup.")
    else:
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], "Email", "CLN_EMAIL_INVALID_REVIEW", before, after,
            0.60, threshold, "Email syntax is invalid; client review required.")


def propose_names(out: list[Proposal], row: dict, threshold: float) -> None:
    for field in ("FirstName", "MiddleName", "LastName"):
        before = row.get(field) or ""
        if not before.strip():
            continue
        normalized = compact_spaces(before)
        if MULTI_PERSON_RE.search(normalized):
            add(out, "UMRM0101", row["RowId"], row["RecordKey"], field, "CLN_NAME_MULTI_PERSON_REVIEW",
                before, normalized, 0.70, threshold, "Name appears to contain more than one person; client review required.")
        elif normalized != before:
            add(out, "UMRM0101", row["RowId"], row["RecordKey"], field, "CLN_NAME_EXTRA_SPACES", before,
                normalized, 0.95, threshold, "Name has leading, trailing or repeated spaces.")


def propose_customer_address(out: list[Proposal], row: dict, threshold: float) -> None:
    contact = compact_spaces(row.get("ContactPerson") or "")
    for field in ("ADDRESS1", "ADDRESS2", "ADDRESS3"):
        before = row.get(field) or ""
        if CARE_OF_RE.search(before or ""):
            address_part = compact_spaces(CARE_OF_RE.sub("", before).replace(":", " "))
            after = address_part if address_part else contact
            add(out, "UMRM0111", row["RowId"], row["RecordKey"], field, "CLN_ADDRESS_CARE_OF_REVIEW",
                before, after, 0.78, threshold, "Care-of or attention text belongs in ContactPerson; client review required.")


def normalize_state(value: str) -> tuple[str, str, float] | None:
    text = compact_spaces(value).upper().replace(".", "")
    if not text:
        return None
    if text in STATE_TO_CODE:
        return STATE_TO_CODE[text], "CLN_STATE_FULL_NAME", 0.97
    if text in STATE_CODES:
        return None
    if len(text) > 2:
        return text[:2], "CLN_STATE_UNKNOWN_REVIEW", 0.55
    return None


def propose_state_zip(out: list[Proposal], row: dict, module: str, fields: Iterable[str], threshold: float) -> None:
    for field in fields:
        before = row.get(field) or ""
        norm = normalize_state(before)
        if norm:
            after, rule, conf = norm
            reason = "Full state name can be converted to USPS two-letter code." if rule.endswith("FULL_NAME") else "State code is not recognized; review required."
            add(out, module, row["RowId"], row["RecordKey"], field, rule, before, after, conf, threshold, reason)
    zip_field = "Zip" if module == "UMRM0101" else "SZip"
    before = row.get(zip_field) or ""
    z = digits(before)
    if len(z) == 9 and "-" not in before:
        add(out, module, row["RowId"], row["RecordKey"], zip_field, "CLN_ZIP_PLUS4", before, z[:5] + "-" + z[5:],
            0.96, threshold, "Nine-digit ZIP can be formatted as ZIP+4.")
    elif len(z) == 4:
        add(out, module, row["RowId"], row["RecordKey"], zip_field, "CLN_ZIP_LEADING_ZERO_REVIEW", before, "0" + z,
            0.80, threshold, "Four-digit ZIP may need a leading zero; client review required.")


def propose_alternate_id(out: list[Proposal], row: dict, threshold: float) -> None:
    dl = compact_spaces(row.get("DRIVERSLICENSE") or "")
    st = compact_spaces(row.get("DLST") or "")
    if not dl or not st:
        return
    norm = normalize_state(st)
    if norm:
        state, rule, conf = norm
        rule_id = "CLN_ALTERNATEID_DL_STATE" if rule == "CLN_STATE_FULL_NAME" else "CLN_ALTERNATEID_DL_STATE_REVIEW"
        reason = "Driver licence state can use USPS two-letter code." if conf >= threshold else "Driver licence state needs review."
        add(out, "UMRM0101", row["RowId"], row["RecordKey"], "AlternateID", rule_id,
            row.get("AlternateID") or "", (dl + " " + state).strip(), conf, threshold, reason)


def propose_street_suffix(out: list[Proposal], row: dict, threshold: float) -> None:
    before = row.get("SStreetType") or ""
    key = compact_spaces(before).upper().replace(".", "")
    after = STREET_SUFFIX.get(key)
    if after and after != before:
        add(out, "UM00600", row["RowId"], row["RecordKey"], "SStreetType", "CLN_STREET_SUFFIX_USPS", before,
            after, 0.94, threshold, "Parsed service-address suffix can be standardized to USPS abbreviation.")


def collect(cn, client: str, take: str, threshold: float = 0.90) -> list[Proposal]:
    proposals: list[Proposal] = []
    customers = sqlio.query(cn, """
        SELECT g.RowId, g.RecordKey, g.FirstName, g.MiddleName, g.LastName, g.ADDRESS1, g.ADDRESS2, g.ADDRESS3,
               g.City, g.[STATE], g.Zip, g.Phone1, g.Phone2, g.Phone3, g.Email, g.ContactPerson, g.AlternateID,
               s.PHONENUMBER, s.HOMENUMBER, s.CELLNUMBER, s.DRIVERSLICENSE, s.DLST
        FROM gold.UM_Customer g
        JOIN slv.Customers s ON s.TakeId = g.TakeId AND s.SourceRow = g.SourceRow
        WHERE g.ClientId = ? AND g.TakeId = ?
        """, client, take)
    for row in customers:
        propose_phone(proposals, row, "Phone1", "PHONENUMBER", threshold)
        propose_phone(proposals, row, "Phone2", "HOMENUMBER", threshold)
        propose_phone(proposals, row, "Phone3", "CELLNUMBER", threshold)
        propose_email(proposals, row, threshold)
        propose_names(proposals, row, threshold)
        propose_customer_address(proposals, row, threshold)
        propose_state_zip(proposals, row, "UMRM0101", ("STATE",), threshold)
        propose_alternate_id(proposals, row, threshold)

    locations = sqlio.query(cn, """
        SELECT RowId, RecordKey, SStreetType, SState, SZip
        FROM gold.UM_Location
        WHERE ClientId = ? AND TakeId = ?
        """, client, take)
    for row in locations:
        propose_street_suffix(proposals, row, threshold)
        propose_state_zip(proposals, row, "UM00600", ("SState",), threshold)
    return proposals


def _proposal_key(p: Proposal) -> tuple[str, int, str, str]:
    return (p.module, p.row_id, p.field, p.rule_id)


def apply(cn, client: str, take: str, proposals: list[Proposal]) -> int:
    """Replace pending proposals for the take, preserving decided rows and not duplicating their keys."""
    cur = cn.cursor()
    decided = {
        (r[0], int(r[1]), r[2], r[3])
        for r in cur.execute("""
            SELECT Module, RowId, Field, RuleId
            FROM run.CleanseProposal
            WHERE ClientId = ? AND TakeId = ? AND Status <> 'pending'
            """, client, take).fetchall()
    }
    cur.execute("DELETE run.CleanseProposal WHERE ClientId = ? AND TakeId = ? AND Status = 'pending'", client, take)
    rows = [p for p in proposals if _proposal_key(p) not in decided]
    if not rows:
        return 0
    cur.fast_executemany = True
    cur.executemany("""
        INSERT run.CleanseProposal (ClientId, TakeId, Module, RowId, RecordKey, Field, RuleId,
                                    BeforeValue, AfterValue, Confidence, Band, Reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [(client, take, p.module, p.row_id, p.record_key, p.field, p.rule_id, p.before, p.after,
                p.confidence, p.band, p.reason) for p in rows])
    return len(rows)


def run(cn, client: str, take: str, threshold: float = 0.90) -> dict:
    proposals = collect(cn, client, take, threshold)
    inserted = apply(cn, client, take, proposals)
    return {"generated": len(proposals), "inserted_pending": inserted, "summary": summary(cn, client, take)}


def summary(cn, client: str, take: str) -> list[dict]:
    return sqlio.query(cn, """
        SELECT Module, RuleId, Band, COUNT_BIG(*) AS Proposals,
               SUM(CASE WHEN Status = 'approved' THEN 1 ELSE 0 END) AS Approved,
               SUM(CASE WHEN Status = 'rejected' THEN 1 ELSE 0 END) AS Rejected,
               SUM(CASE WHEN Status = 'pending' THEN 1 ELSE 0 END) AS Pending
        FROM run.CleanseProposal
        WHERE ClientId = ? AND TakeId = ?
        GROUP BY Module, RuleId, Band
        ORDER BY Module, RuleId, Band
        """, client, take)


def gate2_evidence(cn, client: str, take: str) -> dict:
    row = sqlio.query(cn, """
        SELECT COUNT_BIG(*) AS proposals,
               SUM(CASE WHEN Band = 'high' THEN 1 ELSE 0 END) AS high,
               SUM(CASE WHEN Band = 'low' THEN 1 ELSE 0 END) AS low,
               SUM(CASE WHEN Band = 'low' AND Status = 'pending' THEN 1 ELSE 0 END) AS pending_low
        FROM run.CleanseProposal
        WHERE ClientId = ? AND TakeId = ?
        """, client, take)[0]
    return {"what": "Review low-confidence deterministic cleansing proposals before any rule is promoted.",
            "proposals": int(row["proposals"] or 0), "high": int(row["high"] or 0),
            "low": int(row["low"] or 0), "pending_low": int(row["pending_low"] or 0)}


def client_take(client_dir: str | Path, take: str) -> tuple[str, str]:
    specs = ClientSpecs(client_dir, take)
    return specs.client, specs.take_id
