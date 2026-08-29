
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from reconcile_engine import run_reconciliation


st.set_page_config(
    page_title="ReconcileFlow",
    page_icon="🔄",
    layout="wide",
)


st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        [data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 16px;
        }

        .reconcile-subtitle {
            color: #64748B;
            font-size: 1.05rem;
            margin-bottom: 1.5rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def read_uploaded_csv(uploaded_file):
    file_bytes = uploaded_file.getvalue()

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]

    errors = []

    for encoding in encodings:
        try:
            dataframe = pd.read_csv(
                io.BytesIO(file_bytes),
                encoding=encoding,
                sep=None,
                engine="python",
            )

            return dataframe, encoding

        except Exception as error:
            errors.append(
                f"{encoding}: {error}"
            )

    raise ValueError(
        "The CSV file could not be read. "
        "Check its encoding and separator."
    )


def create_excel_report(results):
    output = io.BytesIO()

    sheets = {
        "KPI Summary":
            results["kpi_summary"],

        "Reconciliation":
            results["reconciliation_report"],

        "Payment Assignments":
            results["payment_assignments"],

        "Match Candidates":
            results["best_candidates"],

        "Unmatched Payments":
            results["unmatched_payments"],

        "Duplicate Payments":
            results["duplicate_payments"],
    }

    with pd.ExcelWriter(
        output,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd",
    ) as writer:

        workbook = writer.book

        header_format = workbook.add_format({
            "bold": True,
            "font_color": "white",
            "bg_color": "#2563EB",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })

        money_format = workbook.add_format({
            "num_format": "#,##0.00",
        })

        date_format = workbook.add_format({
            "num_format": "yyyy-mm-dd",
        })

        matched_format = workbook.add_format({
            "bg_color": "#DCFCE7",
            "font_color": "#166534",
        })

        warning_format = workbook.add_format({
            "bg_color": "#FEF3C7",
            "font_color": "#92400E",
        })

        error_format = workbook.add_format({
            "bg_color": "#FEE2E2",
            "font_color": "#991B1B",
        })

        neutral_format = workbook.add_format({
            "bg_color": "#E2E8F0",
            "font_color": "#334155",
        })

        for sheet_name, dataframe in sheets.items():
            export_dataframe = dataframe.copy()

            export_dataframe.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )

            worksheet = writer.sheets[sheet_name]

            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, 26)

            if (
                len(export_dataframe) > 0
                and len(export_dataframe.columns) > 0
            ):
                worksheet.autofilter(
                    0,
                    0,
                    len(export_dataframe),
                    len(export_dataframe.columns) - 1,
                )

            for column_number, column_name in enumerate(
                export_dataframe.columns
            ):
                worksheet.write(
                    0,
                    column_number,
                    column_name,
                    header_format,
                )

                values = (
                    export_dataframe[column_name]
                    .dropna()
                    .astype(str)
                    .head(1000)
                )

                maximum_length = max(
                    [len(str(column_name))]
                    + values.map(len).tolist()
                )

                column_width = min(
                    maximum_length + 3,
                    38,
                )

                normalized_name = column_name.lower()
                column_format = None

                if "date" in normalized_name:
                    column_format = date_format

                elif any(
                    word in normalized_name
                    for word in [
                        "amount",
                        "paid",
                        "outstanding",
                        "value",
                        "variance",
                    ]
                ):
                    column_format = money_format

                worksheet.set_column(
                    column_number,
                    column_number,
                    column_width,
                    column_format,
                )

            if (
                "reconciliation_status"
                in export_dataframe.columns
                and len(export_dataframe) > 0
            ):
                status_column = (
                    export_dataframe.columns.get_loc(
                        "reconciliation_status"
                    )
                )

                status_rules = [
                    (
                        "Matched",
                        matched_format,
                    ),
                    (
                        "Partial Payment",
                        warning_format,
                    ),
                    (
                        "Overpayment",
                        error_format,
                    ),
                    (
                        "Unpaid Invoice",
                        neutral_format,
                    ),
                ]

                for status_text, status_format in status_rules:
                    worksheet.conditional_format(
                        1,
                        status_column,
                        len(export_dataframe),
                        status_column,
                        {
                            "type": "text",
                            "criteria": "containing",
                            "value": status_text,
                            "format": status_format,
                        },
                    )

            if (
                "suggested_status"
                in export_dataframe.columns
                and len(export_dataframe) > 0
            ):
                status_column = (
                    export_dataframe.columns.get_loc(
                        "suggested_status"
                    )
                )

                candidate_rules = [
                    (
                        "Suggested Match",
                        matched_format,
                    ),
                    (
                        "Manual Review",
                        warning_format,
                    ),
                    (
                        "No Match",
                        neutral_format,
                    ),
                ]

                for status_text, status_format in candidate_rules:
                    worksheet.conditional_format(
                        1,
                        status_column,
                        len(export_dataframe),
                        status_column,
                        {
                            "type": "text",
                            "criteria": "containing",
                            "value": status_text,
                            "format": status_format,
                        },
                    )

    output.seek(0)

    return output.getvalue()


def get_kpi_value(kpi_dataframe, metric_name):
    matching_rows = kpi_dataframe[
        kpi_dataframe["metric"] == metric_name
    ]

    if matching_rows.empty:
        return 0

    return matching_rows.iloc[0]["value"]


with st.sidebar:
    st.header("Matching settings")

    auto_match_threshold = st.slider(
        "Automatic match threshold",
        min_value=60,
        max_value=100,
        value=80,
        step=1,
        help=(
            "Candidates with this score or higher "
            "are automatically assigned."
        ),
    )

    manual_review_threshold = st.slider(
        "Manual review threshold",
        min_value=0,
        max_value=99,
        value=60,
        step=1,
        help=(
            "Candidates between the manual and "
            "automatic thresholds require review."
        ),
    )

    st.divider()

    st.caption(
        "Uploaded files are processed only "
        "for the current application session."
    )

    st.caption(
        "Do not upload confidential financial "
        "information to a public demonstration app."
    )


st.title("🔄 ReconcileFlow")

st.markdown(
    """
    <div class="reconcile-subtitle">
        Automated invoice and payment reconciliation
        with exact-reference matching, fuzzy company-name
        comparison, duplicate detection, and exception reporting.
    </div>
    """,
    unsafe_allow_html=True,
)


with st.expander("Required CSV structure"):
    invoice_column, payment_column = st.columns(2)

    with invoice_column:
        st.markdown("**Invoice file columns**")
        st.code(
            "invoice_id\n"
            "customer_name\n"
            "invoice_date\n"
            "due_date\n"
            "invoice_amount\n"
            "currency"
        )

    with payment_column:
        st.markdown("**Payment file columns**")
        st.code(
            "payment_id\n"
            "payment_date\n"
            "reference\n"
            "payer_name\n"
            "payment_amount\n"
            "currency"
        )


upload_column_1, upload_column_2 = st.columns(2)

with upload_column_1:
    invoice_file = st.file_uploader(
        "Upload invoices CSV",
        type=["csv"],
        key="invoice_file",
    )

with upload_column_2:
    payment_file = st.file_uploader(
        "Upload payments CSV",
        type=["csv"],
        key="payment_file",
    )


if manual_review_threshold >= auto_match_threshold:
    st.error(
        "The manual review threshold must be lower "
        "than the automatic match threshold."
    )
    st.stop()


if invoice_file is None or payment_file is None:
    st.info(
        "Upload both CSV files to begin reconciliation."
    )
    st.stop()


current_signature = (
    invoice_file.name,
    len(invoice_file.getvalue()),
    payment_file.name,
    len(payment_file.getvalue()),
    auto_match_threshold,
    manual_review_threshold,
)


run_button = st.button(
    "Run reconciliation",
    type="primary",
    use_container_width=True,
)


if run_button:
    try:
        with st.spinner(
            "Reading files and matching payments..."
        ):
            invoices_dataframe, invoice_encoding = (
                read_uploaded_csv(invoice_file)
            )

            payments_dataframe, payment_encoding = (
                read_uploaded_csv(payment_file)
            )

            reconciliation_results = run_reconciliation(
                invoices_dataframe,
                payments_dataframe,
                auto_match_threshold=auto_match_threshold,
                manual_review_threshold=(
                    manual_review_threshold
                ),
            )

            st.session_state[
                "reconciliation_results"
            ] = reconciliation_results

            st.session_state[
                "reconciliation_signature"
            ] = current_signature

            st.session_state[
                "source_data"
            ] = {
                "invoices": invoices_dataframe,
                "payments": payments_dataframe,
                "invoice_encoding": invoice_encoding,
                "payment_encoding": payment_encoding,
            }

    except Exception as error:
        st.error(f"Reconciliation failed: {error}")
        st.stop()


if (
    st.session_state.get(
        "reconciliation_signature"
    )
    != current_signature
):
    st.info(
        "Click “Run reconciliation” to process "
        "the uploaded files."
    )
    st.stop()


results = st.session_state[
    "reconciliation_results"
]

source_data = st.session_state[
    "source_data"
]

kpi_summary = results["kpi_summary"]
reconciliation_report = results[
    "reconciliation_report"
]


st.success(
    "Invoice and payment reconciliation "
    "completed successfully."
)


metric_columns = st.columns(5)

metric_columns[0].metric(
    "Invoices",
    int(
        get_kpi_value(
            kpi_summary,
            "Total invoices",
        )
    ),
)

metric_columns[1].metric(
    "Matched invoices",
    int(
        get_kpi_value(
            kpi_summary,
            "Matched invoices",
        )
    ),
)

metric_columns[2].metric(
    "Matching rate",
    (
        f"{get_kpi_value(kpi_summary, 'Matching rate'):.1f}%"
    ),
)

metric_columns[3].metric(
    "Outstanding",
    (
        f"{get_kpi_value(kpi_summary, 'Outstanding amount'):,.2f}"
    ),
)

metric_columns[4].metric(
    "Unmatched payments",
    int(
        get_kpi_value(
            kpi_summary,
            "Unmatched payments",
        )
    ),
)


chart_column_1, chart_column_2 = st.columns(2)

with chart_column_1:
    status_figure = px.bar(
        results["status_summary"],
        x="status",
        y="invoice_count",
        color="status",
        text_auto=True,
        title="Invoices by reconciliation status",
        color_discrete_map={
            "Matched": "#22C55E",
            "Partial Payment": "#F59E0B",
            "Overpayment": "#EF4444",
            "Unpaid Invoice": "#64748B",
        },
    )

    status_figure.update_layout(
        showlegend=False,
        xaxis_title=None,
        yaxis_title="Invoices",
    )

    st.plotly_chart(
        status_figure,
        use_container_width=True,
    )


with chart_column_2:
    outstanding_data = reconciliation_report[
        reconciliation_report[
            "outstanding_amount"
        ] > 0
    ]

    if outstanding_data.empty:
        st.success(
            "There are no outstanding invoice balances."
        )

    else:
        outstanding_figure = px.bar(
            outstanding_data,
            x="customer_name",
            y="outstanding_amount",
            color="reconciliation_status",
            text_auto=".2f",
            title="Outstanding amount by customer",
            color_discrete_map={
                "Partial Payment": "#F59E0B",
                "Unpaid Invoice": "#64748B",
            },
        )

        outstanding_figure.update_layout(
            xaxis_title=None,
            yaxis_title="Outstanding amount",
            legend_title="Status",
        )

        st.plotly_chart(
            outstanding_figure,
            use_container_width=True,
        )


tabs = st.tabs([
    "Reconciliation",
    "Payment assignments",
    "Match review",
    "Exceptions",
    "Source data",
])


with tabs[0]:
    st.dataframe(
        reconciliation_report,
        use_container_width=True,
        hide_index=True,
    )


with tabs[1]:
    st.dataframe(
        results["payment_assignments"],
        use_container_width=True,
        hide_index=True,
    )


with tabs[2]:
    candidate_matches = results[
        "best_candidates"
    ]

    if candidate_matches.empty:
        st.info(
            "No fuzzy-match candidates were generated."
        )

    else:
        st.dataframe(
            candidate_matches,
            use_container_width=True,
            hide_index=True,
        )


with tabs[3]:
    exception_column_1, exception_column_2 = (
        st.columns(2)
    )

    with exception_column_1:
        st.subheader("Unmatched payments")

        if results["unmatched_payments"].empty:
            st.success("No unmatched payments.")

        else:
            st.dataframe(
                results["unmatched_payments"],
                use_container_width=True,
                hide_index=True,
            )

    with exception_column_2:
        st.subheader("Duplicate payments")

        if results["duplicate_payments"].empty:
            st.success("No duplicate payments.")

        else:
            st.dataframe(
                results["duplicate_payments"],
                use_container_width=True,
                hide_index=True,
            )


with tabs[4]:
    st.caption(
        "Invoice encoding: "
        f"{source_data['invoice_encoding']} · "
        "Payment encoding: "
        f"{source_data['payment_encoding']}"
    )

    source_tab_1, source_tab_2 = st.tabs([
        "Invoices",
        "Payments",
    ])

    with source_tab_1:
        st.dataframe(
            source_data["invoices"],
            use_container_width=True,
            hide_index=True,
        )

    with source_tab_2:
        st.dataframe(
            source_data["payments"],
            use_container_width=True,
            hide_index=True,
        )


excel_report = create_excel_report(results)

st.download_button(
    label="Download complete Excel report",
    data=excel_report,
    file_name="reconcileflow_report.xlsx",
    mime=(
        "application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet"
    ),
    use_container_width=True,
)


st.caption(
    "ReconcileFlow · Python · Pandas · "
    "RapidFuzz · Plotly · Streamlit"
)
