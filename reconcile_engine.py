
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz


INVOICE_COLUMNS = {
    "invoice_id",
    "customer_name",
    "invoice_date",
    "due_date",
    "invoice_amount",
    "currency",
}

PAYMENT_COLUMNS = {
    "payment_id",
    "payment_date",
    "reference",
    "payer_name",
    "payment_amount",
    "currency",
}


def validate_columns(dataframe, required_columns, table_name):
    missing_columns = sorted(
        required_columns - set(dataframe.columns)
    )

    if missing_columns:
        raise ValueError(
            f"{table_name}: missing columns: "
            + ", ".join(missing_columns)
        )


def normalize_reference(value):
    if pd.isna(value):
        return ""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value).upper(),
    )


def normalize_company_name(value):
    if pd.isna(value):
        return ""

    text = str(value).lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\b(doo|llc|ltd|limited|inc|corp|"
        r"corporation|company|co)\b",
        " ",
        text,
    )

    return " ".join(text.split())


def prepare_invoices(dataframe):
    validate_columns(
        dataframe,
        INVOICE_COLUMNS,
        "Invoices",
    )

    result = dataframe.copy()

    result["invoice_id"] = (
        result["invoice_id"]
        .astype(str)
        .str.strip()
    )

    result["customer_name"] = (
        result["customer_name"]
        .astype(str)
        .str.strip()
    )

    result["invoice_date"] = pd.to_datetime(
        result["invoice_date"],
        errors="coerce",
    )

    result["due_date"] = pd.to_datetime(
        result["due_date"],
        errors="coerce",
    )

    result["invoice_amount"] = pd.to_numeric(
        result["invoice_amount"],
        errors="coerce",
    )

    result["currency"] = (
        result["currency"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    result["normalized_invoice_id"] = (
        result["invoice_id"]
        .map(normalize_reference)
    )

    result["normalized_customer_name"] = (
        result["customer_name"]
        .map(normalize_company_name)
    )

    if result["invoice_id"].duplicated().any():
        raise ValueError(
            "Invoices: invoice_id values must be unique."
        )

    if result["invoice_amount"].isna().any():
        raise ValueError(
            "Invoices: invalid invoice_amount values."
        )

    if result["invoice_date"].isna().any():
        raise ValueError(
            "Invoices: invalid invoice_date values."
        )

    return result


def prepare_payments(dataframe):
    validate_columns(
        dataframe,
        PAYMENT_COLUMNS,
        "Payments",
    )

    result = dataframe.copy()

    result["payment_id"] = (
        result["payment_id"]
        .astype(str)
        .str.strip()
    )

    result["reference"] = (
        result["reference"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    result["payer_name"] = (
        result["payer_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    result["payment_date"] = pd.to_datetime(
        result["payment_date"],
        errors="coerce",
    )

    result["payment_amount"] = pd.to_numeric(
        result["payment_amount"],
        errors="coerce",
    )

    result["currency"] = (
        result["currency"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    result["normalized_reference"] = (
        result["reference"]
        .map(normalize_reference)
    )

    result["normalized_payer_name"] = (
        result["payer_name"]
        .map(normalize_company_name)
    )

    if result["payment_id"].duplicated().any():
        raise ValueError(
            "Payments: payment_id values must be unique."
        )

    if result["payment_amount"].isna().any():
        raise ValueError(
            "Payments: invalid payment_amount values."
        )

    if result["payment_date"].isna().any():
        raise ValueError(
            "Payments: invalid payment_date values."
        )

    return result


def calculate_candidate_score(payment, invoice):
    name_score = fuzz.ratio(
        payment["normalized_payer_name"],
        invoice["normalized_customer_name"],
    )

    invoice_balance = invoice["outstanding_before_fuzzy"]
    payment_amount = payment["payment_amount"]

    largest_amount = max(
        abs(invoice_balance),
        abs(payment_amount),
        0.01,
    )

    amount_difference = abs(
        payment_amount - invoice_balance
    )

    amount_score = max(
        0,
        100 - amount_difference / largest_amount * 100,
    )

    days_difference = abs(
        (
            payment["payment_date"]
            - invoice["invoice_date"]
        ).days
    )

    date_score = max(
        0,
        100 - days_difference * 5,
    )

    total_score = (
        name_score * 0.50
        + amount_score * 0.35
        + date_score * 0.15
    )

    return {
        "name_score": round(name_score, 2),
        "amount_score": round(amount_score, 2),
        "date_score": round(date_score, 2),
        "total_score": round(total_score, 2),
    }


def run_reconciliation(
    invoices_dataframe,
    payments_dataframe,
    auto_match_threshold=80,
    manual_review_threshold=60,
    amount_tolerance=0.01,
):
    invoices = prepare_invoices(
        invoices_dataframe
    )

    payments = prepare_payments(
        payments_dataframe
    )

    duplicate_columns = [
        "payment_date",
        "normalized_reference",
        "normalized_payer_name",
        "payment_amount",
        "currency",
    ]

    duplicate_mask = payments.duplicated(
        subset=duplicate_columns,
        keep="first",
    )

    duplicate_payments = (
        payments[duplicate_mask]
        .copy()
        .reset_index(drop=True)
    )

    active_payments = (
        payments[~duplicate_mask]
        .copy()
        .reset_index(drop=True)
    )

    invoice_lookup = invoices[
        [
            "invoice_id",
            "normalized_invoice_id",
            "customer_name",
            "currency",
        ]
    ].rename(
        columns={
            "currency": "invoice_currency",
        }
    )

    exact_matches = active_payments.merge(
        invoice_lookup,
        left_on="normalized_reference",
        right_on="normalized_invoice_id",
        how="inner",
    )

    exact_matches = exact_matches[
        exact_matches["currency"]
        == exact_matches["invoice_currency"]
    ].copy()

    assignment_columns = [
        "payment_id",
        "payment_date",
        "reference",
        "payer_name",
        "payment_amount",
        "currency",
        "invoice_id",
        "customer_name",
        "match_method",
        "confidence_score",
    ]

    exact_assignments = exact_matches.copy()

    exact_assignments["match_method"] = (
        "Exact Reference"
    )

    exact_assignments["confidence_score"] = 100.0

    exact_assignments = exact_assignments[
        assignment_columns
    ]

    exact_payment_ids = set(
        exact_assignments["payment_id"]
    )

    unmatched_reference_payments = (
        active_payments[
            ~active_payments["payment_id"].isin(
                exact_payment_ids
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    exact_payment_totals = (
        exact_assignments
        .groupby("invoice_id", as_index=False)
        ["payment_amount"]
        .sum()
        .rename(
            columns={
                "payment_amount": "exact_paid",
            }
        )
    )

    invoice_balances = invoices.merge(
        exact_payment_totals,
        on="invoice_id",
        how="left",
    )

    invoice_balances["exact_paid"] = (
        invoice_balances["exact_paid"]
        .fillna(0)
    )

    invoice_balances[
        "outstanding_before_fuzzy"
    ] = (
        invoice_balances["invoice_amount"]
        - invoice_balances["exact_paid"]
    )

    candidate_invoices = invoice_balances[
        invoice_balances[
            "outstanding_before_fuzzy"
        ] > amount_tolerance
    ].copy()

    candidate_records = []

    for _, payment in (
        unmatched_reference_payments.iterrows()
    ):
        currency_candidates = candidate_invoices[
            candidate_invoices["currency"]
            == payment["currency"]
        ]

        for _, invoice in (
            currency_candidates.iterrows()
        ):
            scores = calculate_candidate_score(
                payment,
                invoice,
            )

            candidate_records.append({
                "payment_id": payment["payment_id"],
                "payment_date": payment["payment_date"],
                "reference": payment["reference"],
                "payer_name": payment["payer_name"],
                "payment_amount": payment[
                    "payment_amount"
                ],
                "currency": payment["currency"],
                "invoice_id": invoice["invoice_id"],
                "customer_name": invoice[
                    "customer_name"
                ],
                **scores,
            })

    candidate_columns = [
        "payment_id",
        "payment_date",
        "reference",
        "payer_name",
        "payment_amount",
        "currency",
        "invoice_id",
        "customer_name",
        "name_score",
        "amount_score",
        "date_score",
        "total_score",
    ]

    candidate_scores = pd.DataFrame(
        candidate_records,
        columns=candidate_columns,
    )

    if candidate_scores.empty:
        best_candidates = candidate_scores.copy()
        best_candidates["suggested_status"] = (
            pd.Series(dtype="object")
        )

    else:
        best_candidates = (
            candidate_scores
            .sort_values(
                ["payment_id", "total_score"],
                ascending=[True, False],
            )
            .drop_duplicates(
                subset=["payment_id"],
                keep="first",
            )
            .reset_index(drop=True)
        )

        best_candidates["suggested_status"] = (
            np.select(
                [
                    best_candidates["total_score"]
                    >= auto_match_threshold,

                    best_candidates["total_score"]
                    >= manual_review_threshold,
                ],
                [
                    "Suggested Match",
                    "Manual Review",
                ],
                default="No Match",
            )
        )

    accepted_fuzzy_matches = best_candidates[
        best_candidates["suggested_status"]
        == "Suggested Match"
    ].copy()

    fuzzy_assignments = (
        accepted_fuzzy_matches.copy()
    )

    fuzzy_assignments["match_method"] = (
        "Fuzzy Match"
    )

    fuzzy_assignments["confidence_score"] = (
        fuzzy_assignments["total_score"]
    )

    if fuzzy_assignments.empty:
        fuzzy_assignments = pd.DataFrame(
            columns=assignment_columns
        )
    else:
        fuzzy_assignments = fuzzy_assignments[
            assignment_columns
        ]

    payment_assignments = (
        pd.concat(
            [
                exact_assignments,
                fuzzy_assignments,
            ],
            ignore_index=True,
        )
        .sort_values("payment_id")
        .reset_index(drop=True)
    )

    assigned_payment_ids = set(
        payment_assignments["payment_id"]
    )

    unmatched_payments = (
        active_payments[
            ~active_payments["payment_id"].isin(
                assigned_payment_ids
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    payment_summary = (
        payment_assignments
        .groupby("invoice_id", as_index=False)
        .agg(
            total_paid=(
                "payment_amount",
                "sum",
            ),
            payment_count=(
                "payment_id",
                "nunique",
            ),
        )
    )

    reconciliation_report = invoices.merge(
        payment_summary,
        on="invoice_id",
        how="left",
    )

    reconciliation_report["total_paid"] = (
        reconciliation_report["total_paid"]
        .fillna(0)
    )

    reconciliation_report["payment_count"] = (
        reconciliation_report["payment_count"]
        .fillna(0)
        .astype(int)
    )

    reconciliation_report[
        "outstanding_amount"
    ] = (
        reconciliation_report["invoice_amount"]
        - reconciliation_report["total_paid"]
    )

    reconciliation_report[
        "reconciliation_status"
    ] = np.select(
        [
            reconciliation_report["total_paid"]
            .eq(0),

            reconciliation_report[
                "outstanding_amount"
            ] < -amount_tolerance,

            reconciliation_report[
                "outstanding_amount"
            ] > amount_tolerance,
        ],
        [
            "Unpaid Invoice",
            "Overpayment",
            "Partial Payment",
        ],
        default="Matched",
    )

    reconciliation_report = (
        reconciliation_report[
            [
                "invoice_id",
                "customer_name",
                "invoice_date",
                "due_date",
                "invoice_amount",
                "currency",
                "total_paid",
                "outstanding_amount",
                "payment_count",
                "reconciliation_status",
            ]
        ]
        .sort_values("invoice_id")
        .reset_index(drop=True)
    )

    status_order = [
        "Matched",
        "Partial Payment",
        "Overpayment",
        "Unpaid Invoice",
    ]

    status_summary = (
        reconciliation_report[
            "reconciliation_status"
        ]
        .value_counts()
        .reindex(status_order, fill_value=0)
        .rename_axis("status")
        .reset_index(name="invoice_count")
    )

    matched_count = (
        reconciliation_report[
            "reconciliation_status"
        ]
        .eq("Matched")
        .sum()
    )

    total_outstanding = (
        reconciliation_report[
            "outstanding_amount"
        ]
        .clip(lower=0)
        .sum()
    )

    total_overpayment = (
        -reconciliation_report[
            "outstanding_amount"
        ]
        .clip(upper=0)
        .sum()
    )

    kpi_summary = pd.DataFrame({
        "metric": [
            "Total invoices",
            "Total invoice value",
            "Assigned payment value",
            "Matched invoices",
            "Matching rate",
            "Outstanding amount",
            "Overpayment amount",
            "Duplicate payments",
            "Unmatched payments",
        ],
        "value": [
            len(reconciliation_report),
            round(
                reconciliation_report[
                    "invoice_amount"
                ].sum(),
                2,
            ),
            round(
                reconciliation_report[
                    "total_paid"
                ].sum(),
                2,
            ),
            int(matched_count),
            round(
                matched_count
                / max(
                    len(reconciliation_report),
                    1,
                )
                * 100,
                2,
            ),
            round(total_outstanding, 2),
            round(total_overpayment, 2),
            len(duplicate_payments),
            len(unmatched_payments),
        ],
    })

    return {
        "reconciliation_report":
            reconciliation_report,

        "payment_assignments":
            payment_assignments,

        "best_candidates":
            best_candidates,

        "unmatched_payments":
            unmatched_payments,

        "duplicate_payments":
            duplicate_payments,

        "status_summary":
            status_summary,

        "kpi_summary":
            kpi_summary,
    }
