"""Smart Intake -- Streamlit Dashboard.

Run with: uv run streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from analyzer import (
    check_conflicts,
    classify_matter,
    draft_engagement_letter,
    estimate_fees,
    load_existing_clients,
    parse_intake_text,
)

SAMPLE_DIR = Path(__file__).parent / "sample_data"

st.set_page_config(
    page_title="Smart Intake",
    page_icon="📋",
    layout="wide",
)


def load_sample_intake() -> str:
    """Load the sample intake form text."""
    return (SAMPLE_DIR / "intake_form.txt").read_text()


def load_sample_clients() -> str:
    """Load the sample existing clients CSV."""
    return (SAMPLE_DIR / "existing_clients.csv").read_text()


def load_sample_fees() -> str:
    """Load the sample fee schedule CSV."""
    return (SAMPLE_DIR / "fee_schedule.csv").read_text()


def main() -> None:
    st.title("📋 Smart Intake")
    st.markdown(
        "**New client calls. You're in court. By the time you call back, they hired someone else.**  \n"
        "Automate your intake process -- conflict checks in seconds, not minutes."
    )

    st.divider()

    # --- Sidebar ---
    with st.sidebar:
        st.header("Settings")
        data_source = st.radio(
            "Data Source",
            ["Sample Data", "Enter Manually"],
            help="Use sample data to explore, or paste your own intake form.",
        )
        st.divider()
        st.header("About")
        st.markdown(
            "Smart Intake processes client intake forms using AI to:\n\n"
            "- **Check conflicts** against existing clients\n"
            "- **Classify matters** and assess complexity\n"
            "- **Estimate fees** based on your fee schedule\n"
            "- **Draft engagement letters** ready for review\n\n"
            "No API key? The app works without one using built-in heuristics."
        )

    # --- Tabs ---
    tab_intake, tab_conflict, tab_letter = st.tabs(
        ["📝 Intake Processing", "🔍 Conflict Check", "📄 Engagement Letter"]
    )

    # =====================================================================
    # TAB 1: Intake Processing
    # =====================================================================
    with tab_intake:
        st.subheader("Process a Client Intake Form")

        if data_source == "Sample Data":
            intake_text = load_sample_intake()
            clients_csv = load_sample_clients()
            fee_csv = load_sample_fees()
            st.info(
                "Showing sample intake form. Switch to **Enter Manually** in the "
                "sidebar to paste your own."
            )
        else:
            intake_text = ""
            clients_csv = ""
            fee_csv = ""

        col1, col2 = st.columns([2, 1])

        with col1:
            intake_input = st.text_area(
                "Intake Form Text",
                value=intake_text,
                height=350,
                placeholder="Paste the client's intake form or questionnaire here...",
            )

        with col2:
            clients_input = st.text_area(
                "Existing Clients CSV",
                value=clients_csv,
                height=160,
                placeholder="client_name,matter,opposing_party,status\n...",
                help="Your firm's existing client list for conflict checking.",
            )
            fee_input = st.text_area(
                "Fee Schedule CSV (optional)",
                value=fee_csv,
                height=120,
                placeholder="matter_type,fee_structure,hourly_rate,...",
                help="Your firm's fee schedule. If blank, default rates are used.",
            )

        if st.button("⚡ Process Intake", type="primary", use_container_width=True):
            if not intake_input.strip():
                st.error("Please enter an intake form to process.")
            else:
                with st.spinner("Processing intake form..."):
                    # Step 1: Parse intake
                    intake = parse_intake_text(intake_input)

                    # Step 2: Conflict check
                    existing = (
                        load_existing_clients(clients_input)
                        if clients_input.strip()
                        else []
                    )
                    conflict = check_conflicts(intake, existing)

                    # Step 3: Classify
                    classification = classify_matter(intake)

                    # Step 4: Fees
                    fee_estimate = estimate_fees(
                        classification,
                        fee_input if fee_input.strip() else None,
                    )

                    # Store in session state
                    st.session_state["intake"] = intake
                    st.session_state["conflict"] = conflict
                    st.session_state["classification"] = classification
                    st.session_state["fee_estimate"] = fee_estimate

                st.success("Intake processed successfully!")

                # --- Results ---
                st.divider()

                # Extracted Data
                st.subheader("📋 Extracted Client Information")
                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    st.markdown(f"**Client:** {intake.client_name}")
                    st.markdown(f"**Email:** {intake.client_email or 'N/A'}")
                    st.markdown(f"**Phone:** {intake.client_phone or 'N/A'}")
                    st.markdown(f"**Address:** {intake.client_address or 'N/A'}")
                with info_col2:
                    st.markdown(f"**Opposing Party:** {intake.opposing_party or 'N/A'}")
                    st.markdown(f"**Incident Date:** {intake.incident_date or 'N/A'}")
                    st.markdown(f"**Urgency:** {intake.urgency or 'Routine'}")
                    st.markdown(f"**Referral:** {intake.referral_source or 'N/A'}")

                st.markdown(f"**Matter Description:** {intake.matter_description}")

                st.divider()

                # Conflict Check
                st.subheader("🔍 Conflict Check Results")
                severity = conflict.severity.value.upper()
                if conflict.has_conflict:
                    if conflict.severity.value == "conflict":
                        st.error(f"⚠️ **CONFLICT DETECTED** -- {conflict.summary}")
                    else:
                        st.warning(f"⚡ **POTENTIAL CONFLICT** -- {conflict.summary}")
                else:
                    st.success(f"✅ **CLEAR** -- {conflict.summary}")

                st.markdown(f"**Recommendation:** {conflict.recommendation}")

                if conflict.hits:
                    with st.expander(
                        f"View {len(conflict.hits)} match(es)",
                        expanded=conflict.has_conflict,
                    ):
                        for hit in conflict.hits:
                            icon = (
                                "🔴"
                                if hit.severity.value == "conflict"
                                else (
                                    "🟡" if hit.severity.value == "potential" else "🟢"
                                )
                            )
                            st.markdown(
                                f"{icon} **{hit.existing_client}** -- {hit.existing_matter}  \n"
                                f"*{hit.match_detail}*"
                            )

                st.divider()

                # Classification
                st.subheader("📊 Matter Classification")
                class_col1, class_col2, class_col3 = st.columns(3)
                with class_col1:
                    st.metric("Matter Type", classification.matter_type.value)
                with class_col2:
                    st.metric("Complexity", f"{classification.complexity_score}/10")
                with class_col3:
                    st.metric(
                        "Practice Group",
                        classification.recommended_practice_group
                        or classification.matter_type.value,
                    )

                if classification.sub_category:
                    st.markdown(f"**Sub-category:** {classification.sub_category}")
                if classification.jurisdiction:
                    st.markdown(f"**Jurisdiction:** {classification.jurisdiction}")
                if classification.statute_of_limitations:
                    st.markdown(
                        f"**Statute of Limitations:** {classification.statute_of_limitations}"
                    )
                if classification.key_issues:
                    st.markdown("**Key Issues:**")
                    for issue in classification.key_issues:
                        st.markdown(f"- {issue}")
                if classification.complexity_factors:
                    st.markdown("**Complexity Factors:**")
                    for factor in classification.complexity_factors:
                        st.markdown(f"- {factor}")

                st.divider()

                # Fee Estimate
                st.subheader("💰 Fee Estimate")
                fee_col1, fee_col2, fee_col3 = st.columns(3)
                with fee_col1:
                    st.metric("Fee Structure", fee_estimate.fee_structure.value)
                with fee_col2:
                    if fee_estimate.estimated_range_low > 0:
                        st.metric(
                            "Estimated Range",
                            f"${fee_estimate.estimated_range_low:,.0f} - ${fee_estimate.estimated_range_high:,.0f}",
                        )
                    elif fee_estimate.contingency_percentage > 0:
                        st.metric(
                            "Contingency", f"{fee_estimate.contingency_percentage}%"
                        )
                    else:
                        st.metric("Estimated Range", "TBD")
                with fee_col3:
                    if fee_estimate.retainer_amount > 0:
                        st.metric("Retainer", f"${fee_estimate.retainer_amount:,.0f}")
                    elif fee_estimate.hourly_rate > 0:
                        st.metric("Hourly Rate", f"${fee_estimate.hourly_rate:.0f}/hr")
                    else:
                        st.metric("Retainer", "None")

                st.markdown(f"*{fee_estimate.rationale}*")

    # =====================================================================
    # TAB 2: Standalone Conflict Check
    # =====================================================================
    with tab_conflict:
        st.subheader("Quick Conflict Check")
        st.markdown(
            "Run a conflict check without processing a full intake form. "
            "Enter the prospective client's name and opposing party."
        )

        cc_col1, cc_col2 = st.columns(2)
        with cc_col1:
            cc_name = st.text_input("Prospective Client Name", placeholder="Jane Smith")
            cc_opposing = st.text_input("Opposing Party", placeholder="Acme Corp")
            cc_matter = st.text_input(
                "Brief Matter Description",
                placeholder="Slip and fall at commercial property",
            )
        with cc_col2:
            if data_source == "Sample Data":
                cc_clients = load_sample_clients()
            else:
                cc_clients = ""
            cc_clients_input = st.text_area(
                "Existing Clients CSV",
                value=cc_clients,
                height=200,
                key="cc_clients",
            )

        if st.button("🔍 Check Conflicts", use_container_width=True):
            if not cc_name.strip():
                st.error("Please enter a client name.")
            else:
                from models import IntakeData

                quick_intake = IntakeData(
                    client_name=cc_name.strip(),
                    opposing_party=cc_opposing.strip(),
                    matter_description=cc_matter.strip(),
                )
                existing = (
                    load_existing_clients(cc_clients_input)
                    if cc_clients_input.strip()
                    else []
                )

                with st.spinner("Checking for conflicts..."):
                    result = check_conflicts(quick_intake, existing)

                if result.has_conflict:
                    if result.severity.value == "conflict":
                        st.error(f"⚠️ **CONFLICT DETECTED** -- {result.summary}")
                    else:
                        st.warning(f"⚡ **POTENTIAL CONFLICT** -- {result.summary}")
                else:
                    st.success(f"✅ **CLEAR** -- {result.summary}")

                st.markdown(f"**Recommendation:** {result.recommendation}")

                if result.hits:
                    st.divider()
                    for hit in result.hits:
                        icon = (
                            "🔴"
                            if hit.severity.value == "conflict"
                            else ("🟡" if hit.severity.value == "potential" else "🟢")
                        )
                        st.markdown(
                            f"{icon} **{hit.existing_client}** -- {hit.existing_matter}  \n"
                            f"Type: {hit.match_type} | {hit.match_detail}"
                        )

    # =====================================================================
    # TAB 3: Engagement Letter
    # =====================================================================
    with tab_letter:
        st.subheader("Generate Engagement Letter")

        if (
            "intake" in st.session_state
            and "classification" in st.session_state
            and "fee_estimate" in st.session_state
        ):
            intake = st.session_state["intake"]
            classification = st.session_state["classification"]
            fee_estimate = st.session_state["fee_estimate"]

            st.info(
                f"Generating letter for **{intake.client_name}** -- "
                f"{classification.matter_type.value} matter."
            )

            if st.button(
                "📄 Generate Engagement Letter",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner("Drafting engagement letter..."):
                    letter = draft_engagement_letter(
                        intake, classification, fee_estimate
                    )
                    st.session_state["letter"] = letter

            if "letter" in st.session_state:
                letter = st.session_state["letter"]

                # Letter metadata
                meta_col1, meta_col2, meta_col3 = st.columns(3)
                with meta_col1:
                    st.markdown(f"**Client:** {letter.client_name}")
                with meta_col2:
                    st.markdown(f"**Fee Structure:** {letter.fee_structure}")
                with meta_col3:
                    if letter.retainer_amount:
                        st.markdown(f"**Retainer:** {letter.retainer_amount}")

                st.divider()

                # The letter itself
                st.markdown("### Draft Engagement Letter")
                st.text_area(
                    "Letter Content (editable)",
                    value=letter.letter_body,
                    height=500,
                    label_visibility="collapsed",
                )

                st.caption(
                    "This is a draft generated for review. All engagement letters "
                    "should be reviewed by a licensed attorney before sending."
                )
        else:
            st.info(
                "Process an intake form first (Intake Processing tab) to generate "
                "an engagement letter."
            )
            st.markdown(
                "The engagement letter is generated based on:\n"
                "- Client information from the intake form\n"
                "- Matter classification and complexity assessment\n"
                "- Fee estimate based on your firm's schedule"
            )


if __name__ == "__main__":
    main()
