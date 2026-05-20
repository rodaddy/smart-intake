"""Pydantic models for smart client intake processing."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class MatterType(str, Enum):
    PERSONAL_INJURY = "Personal Injury"
    FAMILY_LAW = "Family Law"
    REAL_ESTATE = "Real Estate"
    COMMERCIAL_LITIGATION = "Commercial Litigation"
    ESTATE_PLANNING = "Estate/Probate"
    IMMIGRATION = "Immigration"
    CRIMINAL_DEFENSE = "Criminal Defense"
    EMPLOYMENT = "Employment"
    BANKRUPTCY = "Bankruptcy"
    GENERAL = "General"


class FeeStructure(str, Enum):
    HOURLY = "Hourly"
    FLAT_FEE = "Flat Fee"
    CONTINGENCY = "Contingency"
    HYBRID = "Hybrid"
    RETAINER = "Retainer"


class ConflictSeverity(str, Enum):
    CLEAR = "clear"
    POTENTIAL = "potential"
    CONFLICT = "conflict"


class IntakeData(BaseModel):
    """Structured data extracted from a client intake form."""

    client_name: str
    client_email: str = ""
    client_phone: str = ""
    client_address: str = ""
    date_of_inquiry: date = Field(default_factory=date.today)
    matter_description: str = ""
    opposing_party: str = ""
    opposing_counsel: str = ""
    incident_date: str = ""
    urgency: str = ""  # "routine", "urgent", "emergency"
    referral_source: str = ""
    prior_representation: str = ""
    additional_notes: str = ""


class ConflictHit(BaseModel):
    """A single match found during conflict checking."""

    existing_client: str
    existing_matter: str
    match_type: str  # "client_name", "opposing_party", "related_party"
    match_detail: str
    severity: ConflictSeverity


class ConflictResult(BaseModel):
    """Result of a conflict-of-interest check."""

    has_conflict: bool
    severity: ConflictSeverity
    hits: list[ConflictHit]
    summary: str
    recommendation: str


class MatterClassification(BaseModel):
    """AI classification of the legal matter."""

    matter_type: MatterType
    sub_category: str = ""
    jurisdiction: str = ""
    statute_of_limitations: str = ""
    complexity_score: int = Field(ge=1, le=10, default=5)
    complexity_factors: list[str] = Field(default_factory=list)
    key_issues: list[str] = Field(default_factory=list)
    recommended_practice_group: str = ""


class FeeEstimate(BaseModel):
    """Fee estimate based on matter type and complexity."""

    fee_structure: FeeStructure
    estimated_range_low: float
    estimated_range_high: float
    retainer_amount: float = 0.0
    estimated_hours: float = 0.0
    hourly_rate: float = 0.0
    contingency_percentage: float = 0.0
    rationale: str = ""


class EngagementDraft(BaseModel):
    """Draft engagement letter content."""

    firm_name: str = "The Firm"
    client_name: str
    matter_description: str
    fee_structure: str
    fee_details: str
    scope_of_work: str
    exclusions: str = ""
    retainer_amount: str = ""
    letter_body: str


class IntakeReport(BaseModel):
    """Complete intake processing result."""

    intake: IntakeData
    conflict_result: ConflictResult
    classification: MatterClassification
    fee_estimate: FeeEstimate
    engagement_draft: EngagementDraft | None = None
    processing_notes: list[str] = Field(default_factory=list)
