"""Core analysis engine for smart client intake.

Parses intake forms, runs conflict checks against existing clients,
classifies matters, estimates fees, and drafts engagement letters.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date
from io import StringIO

from dotenv import load_dotenv

from models import (
    ConflictHit,
    ConflictResult,
    ConflictSeverity,
    EngagementDraft,
    FeeEstimate,
    FeeStructure,
    IntakeData,
    IntakeReport,
    MatterClassification,
    MatterType,
)
from prompts import (
    CONFLICT_ANALYSIS_PROMPT,
    ENGAGEMENT_LETTER_PROMPT,
    INTAKE_EXTRACTION_PROMPT,
    MATTER_CLASSIFICATION_PROMPT,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Fee schedule defaults (used when no CSV is provided or as fallback)
# ---------------------------------------------------------------------------

DEFAULT_FEE_SCHEDULE: dict[str, dict] = {
    "Personal Injury": {
        "structure": FeeStructure.CONTINGENCY,
        "contingency_pct": 33.3,
        "range_low": 0,
        "range_high": 0,
        "retainer": 0,
        "hourly_rate": 0,
        "est_hours": 0,
    },
    "Family Law": {
        "structure": FeeStructure.RETAINER,
        "contingency_pct": 0,
        "range_low": 3000,
        "range_high": 15000,
        "retainer": 5000,
        "hourly_rate": 350,
        "est_hours": 20,
    },
    "Real Estate": {
        "structure": FeeStructure.FLAT_FEE,
        "contingency_pct": 0,
        "range_low": 1500,
        "range_high": 5000,
        "retainer": 0,
        "hourly_rate": 0,
        "est_hours": 0,
    },
    "Commercial Litigation": {
        "structure": FeeStructure.HOURLY,
        "contingency_pct": 0,
        "range_low": 10000,
        "range_high": 75000,
        "retainer": 10000,
        "hourly_rate": 400,
        "est_hours": 50,
    },
    "Estate/Probate": {
        "structure": FeeStructure.FLAT_FEE,
        "contingency_pct": 0,
        "range_low": 2000,
        "range_high": 8000,
        "retainer": 0,
        "hourly_rate": 300,
        "est_hours": 10,
    },
    "Immigration": {
        "structure": FeeStructure.FLAT_FEE,
        "contingency_pct": 0,
        "range_low": 2500,
        "range_high": 10000,
        "retainer": 2500,
        "hourly_rate": 0,
        "est_hours": 0,
    },
    "Criminal Defense": {
        "structure": FeeStructure.FLAT_FEE,
        "contingency_pct": 0,
        "range_low": 3000,
        "range_high": 25000,
        "retainer": 5000,
        "hourly_rate": 350,
        "est_hours": 15,
    },
    "Employment": {
        "structure": FeeStructure.HYBRID,
        "contingency_pct": 25.0,
        "range_low": 5000,
        "range_high": 30000,
        "retainer": 3000,
        "hourly_rate": 350,
        "est_hours": 25,
    },
    "Bankruptcy": {
        "structure": FeeStructure.FLAT_FEE,
        "contingency_pct": 0,
        "range_low": 1500,
        "range_high": 8000,
        "retainer": 0,
        "hourly_rate": 0,
        "est_hours": 0,
    },
    "General": {
        "structure": FeeStructure.HOURLY,
        "contingency_pct": 0,
        "range_low": 2000,
        "range_high": 10000,
        "retainer": 2500,
        "hourly_rate": 300,
        "est_hours": 15,
    },
}


def _get_claude_client():
    """Get an Anthropic client if API key is available."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-your"):
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def _call_claude(client, system_prompt: str, user_message: str) -> dict | None:
    """Call Claude and parse the JSON response."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Intake form parsing
# ---------------------------------------------------------------------------


def parse_intake_text(text: str) -> IntakeData:
    """Parse a text intake form into structured IntakeData.

    Uses Claude if available, otherwise falls back to keyword extraction.
    """
    client = _get_claude_client()
    if client:
        result = _call_claude(client, INTAKE_EXTRACTION_PROMPT, text)
        if result:
            # Normalize date field
            if "date_of_inquiry" in result:
                try:
                    result["date_of_inquiry"] = date.fromisoformat(
                        result["date_of_inquiry"]
                    )
                except (ValueError, TypeError):
                    result["date_of_inquiry"] = date.today()
            return IntakeData(**result)

    # Fallback: keyword-based extraction
    return _extract_intake_heuristic(text)


def _extract_intake_heuristic(text: str) -> IntakeData:
    """Extract intake data using pattern matching (no AI)."""
    lines = text.strip().split("\n")
    data: dict[str, str] = {}

    field_map = {
        "name": "client_name",
        "full name": "client_name",
        "client name": "client_name",
        "email": "client_email",
        "e-mail": "client_email",
        "phone": "client_phone",
        "telephone": "client_phone",
        "cell": "client_phone",
        "mobile": "client_phone",
        "address": "client_address",
        "date": "date_of_inquiry",
        "date of inquiry": "date_of_inquiry",
        "matter": "matter_description",
        "description": "matter_description",
        "legal issue": "matter_description",
        "describe your situation": "matter_description",
        "nature of case": "matter_description",
        "brief description": "matter_description",
        "opposing party": "opposing_party",
        "other party": "opposing_party",
        "adverse party": "opposing_party",
        "defendant": "opposing_party",
        "plaintiff": "opposing_party",
        "opposing counsel": "opposing_counsel",
        "opposing attorney": "opposing_counsel",
        "incident date": "incident_date",
        "date of incident": "incident_date",
        "when did this occur": "incident_date",
        "urgency": "urgency",
        "how urgent": "urgency",
        "priority": "urgency",
        "referral": "referral_source",
        "how did you hear": "referral_source",
        "referred by": "referral_source",
        "prior attorney": "prior_representation",
        "previous attorney": "prior_representation",
        "prior representation": "prior_representation",
        "previous counsel": "prior_representation",
        "notes": "additional_notes",
        "additional": "additional_notes",
        "anything else": "additional_notes",
        "comments": "additional_notes",
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Try "Field: Value" pattern
        if ":" in line:
            key, _, value = line.partition(":")
            key_clean = key.strip().lower().rstrip("*").strip()
            value = value.strip()
            if value:
                for pattern, field in field_map.items():
                    if pattern in key_clean:
                        if field not in data or not data[field]:
                            data[field] = value
                        elif field == "matter_description":
                            data[field] += " " + value
                        break

    # Handle multi-line descriptions: if matter_description is short, look for
    # paragraph blocks after description-like headers
    if len(data.get("matter_description", "")) < 20:
        capture = False
        desc_lines = []
        for line in lines:
            stripped = line.strip().lower()
            if any(
                k in stripped
                for k in [
                    "describe your situation",
                    "brief description",
                    "nature of case",
                    "legal issue",
                ]
            ):
                capture = True
                # Check if there's inline content after the colon
                if ":" in line:
                    _, _, inline = line.partition(":")
                    if inline.strip():
                        desc_lines.append(inline.strip())
                continue
            if capture:
                if (
                    stripped
                    and ":" in stripped
                    and any(k in stripped for k in field_map)
                ):
                    break  # Hit next field
                if stripped:
                    desc_lines.append(line.strip())
        if desc_lines:
            data["matter_description"] = " ".join(desc_lines)

    return IntakeData(
        client_name=data.get("client_name", "Unknown"),
        client_email=data.get("client_email", ""),
        client_phone=data.get("client_phone", ""),
        client_address=data.get("client_address", ""),
        matter_description=data.get("matter_description", ""),
        opposing_party=data.get("opposing_party", ""),
        opposing_counsel=data.get("opposing_counsel", ""),
        incident_date=data.get("incident_date", ""),
        urgency=data.get("urgency", "routine"),
        referral_source=data.get("referral_source", ""),
        prior_representation=data.get("prior_representation", ""),
        additional_notes=data.get("additional_notes", ""),
    )


# ---------------------------------------------------------------------------
# Conflict checking
# ---------------------------------------------------------------------------


def load_existing_clients(csv_text: str) -> list[dict]:
    """Load existing client list from CSV text."""
    reader = csv.DictReader(StringIO(csv_text))
    return [row for row in reader]


def check_conflicts(
    intake: IntakeData,
    existing_clients: list[dict],
) -> ConflictResult:
    """Check for conflicts of interest against existing client list.

    Uses Claude if available for nuanced analysis, otherwise uses string matching.
    """
    client = _get_claude_client()
    if client and existing_clients:
        clients_text = "\n".join(
            f"- {c.get('client_name', '')} | Matter: {c.get('matter', '')} | "
            f"Opposing: {c.get('opposing_party', '')} | Status: {c.get('status', '')}"
            for c in existing_clients
        )
        user_msg = (
            f"NEW CLIENT INTAKE:\n"
            f"Name: {intake.client_name}\n"
            f"Matter: {intake.matter_description}\n"
            f"Opposing Party: {intake.opposing_party}\n"
            f"Opposing Counsel: {intake.opposing_counsel}\n\n"
            f"EXISTING CLIENT LIST:\n{clients_text}"
        )
        result = _call_claude(client, CONFLICT_ANALYSIS_PROMPT, user_msg)
        if result:
            hits = [
                ConflictHit(
                    existing_client=h.get("existing_client", ""),
                    existing_matter=h.get("existing_matter", ""),
                    match_type=h.get("match_type", ""),
                    match_detail=h.get("match_detail", ""),
                    severity=ConflictSeverity(h.get("severity", "clear")),
                )
                for h in result.get("hits", [])
            ]
            return ConflictResult(
                has_conflict=result.get("has_conflict", False),
                severity=ConflictSeverity(result.get("severity", "clear")),
                hits=hits,
                summary=result.get("summary", ""),
                recommendation=result.get("recommendation", ""),
            )

    # Fallback: simple string matching
    return _check_conflicts_heuristic(intake, existing_clients)


def _check_conflicts_heuristic(
    intake: IntakeData,
    existing_clients: list[dict],
) -> ConflictResult:
    """Check conflicts using simple name matching."""
    hits: list[ConflictHit] = []
    new_name = intake.client_name.lower().strip()
    new_opposing = intake.opposing_party.lower().strip()

    for client in existing_clients:
        client_name = client.get("client_name", "").lower().strip()
        opposing = client.get("opposing_party", "").lower().strip()
        matter = client.get("matter", "")
        status = client.get("status", "").lower()

        # Direct conflict: new client's opposing party is an existing client
        if new_opposing and _name_match(new_opposing, client_name):
            hits.append(
                ConflictHit(
                    existing_client=client.get("client_name", ""),
                    existing_matter=matter,
                    match_type="opposing_party",
                    match_detail=(
                        f"New client's opposing party '{intake.opposing_party}' "
                        f"matches existing client '{client.get('client_name', '')}'"
                    ),
                    severity=ConflictSeverity.CONFLICT,
                )
            )

        # Reverse conflict: new client is an opposing party in existing matter
        if new_name and _name_match(new_name, opposing):
            hits.append(
                ConflictHit(
                    existing_client=client.get("client_name", ""),
                    existing_matter=matter,
                    match_type="related_party",
                    match_detail=(
                        f"New client '{intake.client_name}' appears as opposing party "
                        f"in existing matter '{matter}'"
                    ),
                    severity=ConflictSeverity.CONFLICT,
                )
            )

        # Same client, different matter (informational)
        if new_name and _name_match(new_name, client_name):
            hits.append(
                ConflictHit(
                    existing_client=client.get("client_name", ""),
                    existing_matter=matter,
                    match_type="client_name",
                    match_detail=(
                        f"New client '{intake.client_name}' matches existing client "
                        f"'{client.get('client_name', '')}' -- may be returning client"
                    ),
                    severity=ConflictSeverity.CLEAR,
                )
            )

    # Determine overall severity
    if any(h.severity == ConflictSeverity.CONFLICT for h in hits):
        overall = ConflictSeverity.CONFLICT
        has_conflict = True
        recommendation = (
            "STOP -- conflict of interest detected. Do not proceed with representation "
            "until reviewed by the ethics partner."
        )
    elif any(h.severity == ConflictSeverity.POTENTIAL for h in hits):
        overall = ConflictSeverity.POTENTIAL
        has_conflict = True
        recommendation = (
            "Potential conflict identified. Requires partner review before proceeding."
        )
    else:
        overall = ConflictSeverity.CLEAR
        has_conflict = False
        recommendation = "No conflicts found. Safe to proceed with representation."

    conflict_count = sum(1 for h in hits if h.severity != ConflictSeverity.CLEAR)
    summary = (
        f"Found {conflict_count} potential conflict(s) across {len(existing_clients)} "
        f"existing clients."
        if conflict_count > 0
        else f"No conflicts found across {len(existing_clients)} existing clients."
    )

    return ConflictResult(
        has_conflict=has_conflict,
        severity=overall,
        hits=hits,
        summary=summary,
        recommendation=recommendation,
    )


def _name_match(name1: str, name2: str) -> bool:
    """Check if two names match (case-insensitive, handles partial matches)."""
    if not name1 or not name2:
        return False
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if n1 == n2:
        return True
    # Check if last names match
    parts1 = n1.split()
    parts2 = n2.split()
    if parts1 and parts2 and parts1[-1] == parts2[-1] and len(parts1[-1]) > 2:
        # Same last name -- check if first name/initial also matches
        if len(parts1) > 1 and len(parts2) > 1:
            if parts1[0] == parts2[0] or parts1[0][0] == parts2[0][0]:
                return True
    # Check containment for business names
    if len(n1) > 5 and n1 in n2:
        return True
    if len(n2) > 5 and n2 in n1:
        return True
    return False


# ---------------------------------------------------------------------------
# Matter classification
# ---------------------------------------------------------------------------


def classify_matter(intake: IntakeData) -> MatterClassification:
    """Classify the legal matter type and assess complexity.

    Uses Claude if available, otherwise uses keyword matching.
    """
    client = _get_claude_client()
    if client:
        user_msg = (
            f"CLIENT: {intake.client_name}\n"
            f"MATTER DESCRIPTION: {intake.matter_description}\n"
            f"OPPOSING PARTY: {intake.opposing_party}\n"
            f"INCIDENT DATE: {intake.incident_date}\n"
            f"URGENCY: {intake.urgency}\n"
            f"ADDITIONAL NOTES: {intake.additional_notes}"
        )
        result = _call_claude(client, MATTER_CLASSIFICATION_PROMPT, user_msg)
        if result:
            try:
                mt = MatterType(result.get("matter_type", "General"))
            except ValueError:
                mt = MatterType.GENERAL
            return MatterClassification(
                matter_type=mt,
                sub_category=result.get("sub_category", ""),
                jurisdiction=result.get("jurisdiction", ""),
                statute_of_limitations=result.get("statute_of_limitations", ""),
                complexity_score=min(
                    max(int(result.get("complexity_score", 5)), 1), 10
                ),
                complexity_factors=result.get("complexity_factors", []),
                key_issues=result.get("key_issues", []),
                recommended_practice_group=result.get("recommended_practice_group", ""),
            )

    # Fallback: keyword matching
    return _classify_heuristic(intake)


def _classify_heuristic(intake: IntakeData) -> MatterClassification:
    """Classify matter using keyword analysis."""
    desc = (intake.matter_description + " " + intake.additional_notes).lower()

    keyword_map: dict[MatterType, list[str]] = {
        MatterType.PERSONAL_INJURY: [
            "injury",
            "accident",
            "slip",
            "fall",
            "car accident",
            "medical malpractice",
            "negligence",
            "hurt",
            "pain",
            "damage",
            "collision",
            "broken",
        ],
        MatterType.FAMILY_LAW: [
            "divorce",
            "custody",
            "child support",
            "alimony",
            "separation",
            "visitation",
            "prenup",
            "prenuptial",
            "adoption",
            "guardianship",
            "family court",
            "domestic",
        ],
        MatterType.REAL_ESTATE: [
            "property",
            "real estate",
            "house",
            "closing",
            "deed",
            "title",
            "mortgage",
            "zoning",
            "landlord",
            "tenant",
            "lease",
            "eviction",
            "condo",
            "co-op",
            "boundary",
        ],
        MatterType.COMMERCIAL_LITIGATION: [
            "breach of contract",
            "business dispute",
            "partnership",
            "fraud",
            "corporate",
            "shareholder",
            "commercial",
            "breach",
            "contract dispute",
            "non-compete",
            "trade secret",
        ],
        MatterType.ESTATE_PLANNING: [
            "will",
            "trust",
            "estate",
            "probate",
            "inheritance",
            "executor",
            "beneficiary",
            "power of attorney",
            "living will",
            "testament",
        ],
        MatterType.IMMIGRATION: [
            "immigration",
            "visa",
            "green card",
            "citizenship",
            "deportation",
            "asylum",
            "work permit",
            "naturalization",
            "uscis",
            "i-130",
        ],
        MatterType.CRIMINAL_DEFENSE: [
            "criminal",
            "arrest",
            "dui",
            "dwi",
            "felony",
            "misdemeanor",
            "charges",
            "plea",
            "bail",
            "indictment",
            "defense",
        ],
        MatterType.EMPLOYMENT: [
            "employment",
            "wrongful termination",
            "discrimination",
            "harassment",
            "wage",
            "overtime",
            "fired",
            "laid off",
            "hostile work",
            "eeoc",
            "retaliation",
            "whistleblower",
        ],
        MatterType.BANKRUPTCY: [
            "bankruptcy",
            "chapter 7",
            "chapter 13",
            "debt",
            "creditor",
            "foreclosure",
            "insolvency",
            "discharg",
        ],
    }

    scores: dict[MatterType, int] = {}
    for matter_type, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in desc)
        if score > 0:
            scores[matter_type] = score

    if scores:
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        confidence = min(scores[best] * 2, 10)
    else:
        best = MatterType.GENERAL
        confidence = 3

    # Estimate complexity based on keyword density and urgency
    complexity = 5
    if intake.urgency == "emergency":
        complexity += 2
    elif intake.urgency == "urgent":
        complexity += 1
    if intake.opposing_counsel:
        complexity += 1
    if len(desc) > 500:
        complexity += 1
    complexity = min(max(complexity, 1), 10)

    return MatterClassification(
        matter_type=best,
        sub_category="",
        jurisdiction="",
        statute_of_limitations="",
        complexity_score=complexity,
        complexity_factors=[],
        key_issues=[],
        recommended_practice_group=best.value + " Group",
    )


# ---------------------------------------------------------------------------
# Fee estimation
# ---------------------------------------------------------------------------


def estimate_fees(
    classification: MatterClassification,
    fee_schedule_csv: str | None = None,
) -> FeeEstimate:
    """Estimate fees based on matter classification and firm fee schedule."""
    schedule = DEFAULT_FEE_SCHEDULE.copy()

    # Override with firm's fee schedule CSV if provided
    if fee_schedule_csv:
        try:
            reader = csv.DictReader(StringIO(fee_schedule_csv))
            for row in reader:
                mt = row.get("matter_type", "").strip()
                if mt in schedule:
                    schedule[mt] = {
                        "structure": FeeStructure(row.get("fee_structure", "Hourly")),
                        "contingency_pct": float(row.get("contingency_percentage", 0)),
                        "range_low": float(row.get("range_low", 0)),
                        "range_high": float(row.get("range_high", 0)),
                        "retainer": float(row.get("retainer_amount", 0)),
                        "hourly_rate": float(row.get("hourly_rate", 0)),
                        "est_hours": float(row.get("estimated_hours", 0)),
                    }
        except Exception:
            pass  # Fall back to defaults

    matter_key = classification.matter_type.value
    fee_info = schedule.get(matter_key, schedule["General"])

    # Adjust ranges based on complexity
    complexity_multiplier = 0.5 + (classification.complexity_score / 10)
    range_low = fee_info["range_low"] * complexity_multiplier
    range_high = fee_info["range_high"] * complexity_multiplier

    rationale = _build_fee_rationale(classification, fee_info)

    return FeeEstimate(
        fee_structure=fee_info["structure"],
        estimated_range_low=round(range_low, 2),
        estimated_range_high=round(range_high, 2),
        retainer_amount=float(fee_info["retainer"]),
        estimated_hours=float(fee_info["est_hours"]),
        hourly_rate=float(fee_info["hourly_rate"]),
        contingency_percentage=float(fee_info["contingency_pct"]),
        rationale=rationale,
    )


def _build_fee_rationale(
    classification: MatterClassification,
    fee_info: dict,
) -> str:
    """Build a human-readable explanation for the fee estimate."""
    parts = [
        f"Based on {classification.matter_type.value} matter classification "
        f"(complexity: {classification.complexity_score}/10)."
    ]

    structure = fee_info["structure"]
    if isinstance(structure, FeeStructure):
        structure_val = structure.value
    else:
        structure_val = str(structure)

    if structure_val == "Contingency":
        parts.append(
            f"Standard contingency fee of {fee_info['contingency_pct']}%. "
            f"No upfront cost to the client."
        )
    elif structure_val == "Flat Fee":
        parts.append("Flat fee based on matter type and anticipated complexity.")
    elif structure_val == "Hourly":
        parts.append(
            f"Hourly rate of ${fee_info['hourly_rate']}/hr, "
            f"estimated {fee_info['est_hours']} hours."
        )
    elif structure_val == "Retainer":
        parts.append(
            f"Retainer of ${fee_info['retainer']:,.0f} against hourly rate "
            f"of ${fee_info['hourly_rate']}/hr."
        )
    elif structure_val == "Hybrid":
        parts.append(
            f"Hybrid arrangement: reduced hourly rate with "
            f"{fee_info['contingency_pct']}% contingency on recovery."
        )

    if classification.complexity_score >= 7:
        parts.append("Higher complexity may push fees toward the upper range.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Engagement letter drafting
# ---------------------------------------------------------------------------


def draft_engagement_letter(
    intake: IntakeData,
    classification: MatterClassification,
    fee_estimate: FeeEstimate,
) -> EngagementDraft:
    """Draft an engagement letter. Uses Claude if available, otherwise template."""
    client = _get_claude_client()
    if client:
        user_msg = (
            f"CLIENT: {intake.client_name}\n"
            f"MATTER: {intake.matter_description}\n"
            f"MATTER TYPE: {classification.matter_type.value}\n"
            f"SUB-CATEGORY: {classification.sub_category}\n"
            f"COMPLEXITY: {classification.complexity_score}/10\n"
            f"FEE STRUCTURE: {fee_estimate.fee_structure.value}\n"
            f"FEE RANGE: ${fee_estimate.estimated_range_low:,.0f} - "
            f"${fee_estimate.estimated_range_high:,.0f}\n"
            f"HOURLY RATE: ${fee_estimate.hourly_rate}/hr\n"
            f"RETAINER: ${fee_estimate.retainer_amount:,.0f}\n"
            f"CONTINGENCY: {fee_estimate.contingency_percentage}%\n"
        )
        result = _call_claude(client, ENGAGEMENT_LETTER_PROMPT, user_msg)
        if result:
            return EngagementDraft(
                firm_name=result.get("firm_name", "The Firm"),
                client_name=result.get("client_name", intake.client_name),
                matter_description=result.get(
                    "matter_description", intake.matter_description
                ),
                fee_structure=result.get(
                    "fee_structure", fee_estimate.fee_structure.value
                ),
                fee_details=result.get("fee_details", ""),
                scope_of_work=result.get("scope_of_work", ""),
                exclusions=result.get("exclusions", ""),
                retainer_amount=result.get("retainer_amount", ""),
                letter_body=result.get("letter_body", ""),
            )

    # Fallback: template-based letter
    return _draft_letter_template(intake, classification, fee_estimate)


def _draft_letter_template(
    intake: IntakeData,
    classification: MatterClassification,
    fee_estimate: FeeEstimate,
) -> EngagementDraft:
    """Generate a template-based engagement letter."""
    fee_struct = fee_estimate.fee_structure.value

    if fee_estimate.fee_structure == FeeStructure.CONTINGENCY:
        fee_details = (
            f"This matter will be handled on a contingency fee basis. Our fee will be "
            f"{fee_estimate.contingency_percentage}% of any recovery obtained on your "
            f"behalf. If there is no recovery, there is no attorney fee."
        )
    elif fee_estimate.fee_structure == FeeStructure.FLAT_FEE:
        fee_details = (
            f"Our fee for this matter is a flat fee in the range of "
            f"${fee_estimate.estimated_range_low:,.0f} to "
            f"${fee_estimate.estimated_range_high:,.0f}, depending on final scope."
        )
    elif fee_estimate.fee_structure == FeeStructure.HOURLY:
        fee_details = (
            f"Our services will be billed at ${fee_estimate.hourly_rate:.0f} per hour. "
            f"Based on our initial assessment, we estimate this matter will require "
            f"approximately {fee_estimate.estimated_hours:.0f} hours, for an estimated "
            f"total of ${fee_estimate.estimated_range_low:,.0f} to "
            f"${fee_estimate.estimated_range_high:,.0f}."
        )
    elif fee_estimate.fee_structure == FeeStructure.RETAINER:
        fee_details = (
            f"We require an initial retainer of ${fee_estimate.retainer_amount:,.0f}, "
            f"which will be applied against services billed at "
            f"${fee_estimate.hourly_rate:.0f} per hour. Additional retainer "
            f"replenishment may be required as the matter progresses."
        )
    else:
        fee_details = (
            f"This matter will be handled on a hybrid fee arrangement. "
            f"A reduced retainer of ${fee_estimate.retainer_amount:,.0f} is required, "
            f"with a {fee_estimate.contingency_percentage}% contingency fee "
            f"on any recovery obtained."
        )

    scope = (
        f"Representation in the matter of {intake.matter_description[:200]}. "
        f"This includes initial case evaluation, document review, correspondence "
        f"with opposing parties, and representation through resolution of the matter."
    )

    exclusions = (
        "This engagement does not cover appeals, separate or related litigation, "
        "or matters not specifically described in the scope above."
    )

    retainer_text = ""
    if fee_estimate.retainer_amount > 0:
        retainer_text = f"${fee_estimate.retainer_amount:,.0f}"

    today = date.today().strftime("%B %d, %Y")

    letter_body = f"""
{today}

{intake.client_name}
{intake.client_address or "[Address]"}

Re: {classification.matter_type.value} Matter -- {intake.matter_description[:100]}

Dear {intake.client_name.split()[0] if intake.client_name else "Client"},

Thank you for choosing our firm to represent you. We appreciate your confidence in us \
and look forward to working with you on this matter.

SCOPE OF REPRESENTATION

We have been retained to represent you in connection with {intake.matter_description}. \
{scope}

FEE ARRANGEMENT

{fee_details}

{f"An initial retainer of {retainer_text} is due upon execution of this agreement." if retainer_text else ""}

You will also be responsible for costs and expenses incurred in connection with your \
matter, including but not limited to filing fees, service fees, expert witness fees, \
deposition costs, and travel expenses. We will obtain your approval before incurring \
any single expense exceeding $500.

CLIENT RESPONSIBILITIES

To enable us to represent you effectively, we ask that you:
- Respond promptly to our requests for information and documents
- Keep us informed of any developments related to your matter
- Provide accurate and complete information
- Maintain copies of all documents related to this matter

TERMINATION

Either party may terminate this engagement at any time upon written notice. In the event \
of termination, you will be responsible for fees and costs incurred through the date of \
termination.

Please indicate your agreement to the terms set forth above by signing and returning a \
copy of this letter.

We look forward to representing you.

Very truly yours,

[Firm Name]
[Attorney Name]
[Bar Number]

AGREED AND ACCEPTED:

_________________________________
{intake.client_name}
Date: ________________
""".strip()

    return EngagementDraft(
        firm_name="The Firm",
        client_name=intake.client_name,
        matter_description=intake.matter_description[:200],
        fee_structure=fee_struct,
        fee_details=fee_details,
        scope_of_work=scope,
        exclusions=exclusions,
        retainer_amount=retainer_text,
        letter_body=letter_body,
    )


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def run_full_intake(
    intake_text: str,
    existing_clients_csv: str,
    fee_schedule_csv: str | None = None,
    generate_letter: bool = True,
) -> IntakeReport:
    """Run the complete intake processing pipeline."""
    notes: list[str] = []
    has_ai = _get_claude_client() is not None
    if not has_ai:
        notes.append(
            "Running without API key -- using heuristic analysis. "
            "Set ANTHROPIC_API_KEY for AI-powered processing."
        )

    # Step 1: Parse intake form
    intake = parse_intake_text(intake_text)
    notes.append(f"Extracted intake data for: {intake.client_name}")

    # Step 2: Conflict check
    existing = load_existing_clients(existing_clients_csv)
    conflict_result = check_conflicts(intake, existing)
    notes.append(
        f"Conflict check: {conflict_result.severity.value} "
        f"({len(conflict_result.hits)} matches)"
    )

    # Step 3: Classify matter
    classification = classify_matter(intake)
    notes.append(
        f"Classification: {classification.matter_type.value} "
        f"(complexity {classification.complexity_score}/10)"
    )

    # Step 4: Estimate fees
    fee_estimate = estimate_fees(classification, fee_schedule_csv)
    notes.append(
        f"Fee estimate: {fee_estimate.fee_structure.value} "
        f"${fee_estimate.estimated_range_low:,.0f}-"
        f"${fee_estimate.estimated_range_high:,.0f}"
    )

    # Step 5: Draft engagement letter
    engagement = None
    if generate_letter:
        engagement = draft_engagement_letter(intake, classification, fee_estimate)
        notes.append("Engagement letter drafted")

    return IntakeReport(
        intake=intake,
        conflict_result=conflict_result,
        classification=classification,
        fee_estimate=fee_estimate,
        engagement_draft=engagement,
        processing_notes=notes,
    )
