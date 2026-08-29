from pathlib import Path

import pandas as pd

from reconcile_engine import run_reconciliation


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]

INVOICES_FILE = (
    PROJECT_DIRECTORY
    / "sample_data"
    / "sample_invoices.csv"
)

PAYMENTS_FILE = (
    PROJECT_DIRECTORY
    / "sample_data"
    / "sample_payments.csv"
)


def load_results():
    invoices = pd.read_csv(INVOICES_FILE)
    payments = pd.read_csv(PAYMENTS_FILE)

    return run_reconciliation(
        invoices,
        payments,
    )


def test_reconciliation_kpis():
    results = load_results()

    kpis = dict(
        zip(
            results["kpi_summary"]["metric"],
            results["kpi_summary"]["value"],
        )
    )

    assert kpis["Total invoices"] == 10
    assert kpis["Total invoice value"] == 11315
    assert kpis["Assigned payment value"] == 10595
    assert kpis["Matched invoices"] == 7
    assert kpis["Matching rate"] == 70
    assert kpis["Outstanding amount"] == 780
    assert kpis["Overpayment amount"] == 60
    assert kpis["Duplicate payments"] == 1
    assert kpis["Unmatched payments"] == 1


def test_fuzzy_company_match():
    results = load_results()

    assignment = (
        results["payment_assignments"]
        .query("payment_id == 'PAY-007'")
        .iloc[0]
    )

    assert assignment["invoice_id"] == "INV-1006"
    assert assignment["match_method"] == "Fuzzy Match"
    assert assignment["confidence_score"] >= 80


def test_duplicate_payment_detection():
    results = load_results()

    duplicate_ids = set(
        results["duplicate_payments"][
            "payment_id"
        ]
    )

    assert duplicate_ids == {"PAY-006"}


def test_unmatched_payment_detection():
    results = load_results()

    unmatched_ids = set(
        results["unmatched_payments"][
            "payment_id"
        ]
    )

    assert unmatched_ids == {"PAY-008"}


def test_invoice_statuses():
    results = load_results()

    report = (
        results["reconciliation_report"]
        .set_index("invoice_id")
    )

    assert (
        report.loc[
            "INV-1002",
            "reconciliation_status",
        ]
        == "Partial Payment"
    )

    assert (
        report.loc[
            "INV-1004",
            "reconciliation_status",
        ]
        == "Overpayment"
    )

    assert (
        report.loc[
            "INV-1007",
            "reconciliation_status",
        ]
        == "Unpaid Invoice"
    )

    assert (
        report.loc[
            "INV-1010",
            "reconciliation_status",
        ]
        == "Matched"
    )
