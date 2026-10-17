"""
Cyberpunk Student Budget Tracker (SQLite + Pandas + Streamlit + Plotly)
=======================================================================
A full-stack student expense tracker combining a SQLite3 & Pandas backend with
a dark-mode cyberpunk Streamlit interface (#0D1117 deep slate, #00F0FF neon cyan,
and #FF0055 hot pink).

Run with:
    python -m streamlit run student_budget_tracker.py
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Constants & Cyberpunk Theme Palette
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = "student_budget.db"

BG_DEEP_SLATE = "#0D1117"
BG_PANEL_SLATE = "#161B22"
NEON_CYAN = "#00F0FF"
HOT_PINK = "#FF0055"
TEXT_PRIMARY = "#E6EDF3"
TEXT_MUTED = "#8B949E"

CYBERPUNK_CHART_PALETTE: List[str] = [
    "#00F0FF",  # Neon Cyan
    "#FF0055",  # Hot Pink
    "#B829FF",  # Electric Purple
    "#00FF9F",  # Cyber Mint
    "#FFB800",  # Laser Amber
    "#0088FF",  # Hyper Blue
    "#FF5500",  # Plasma Orange
    "#FF00AA",  # Magenta Pulse
    "#50FA7B",  # Matrix Green
]

STUDENT_CATEGORIES: List[str] = [
    "Rent & Utilities",
    "Groceries",
    "Textbooks & Supplies",
    "Dining Out",
    "Transit",
    "Tech & Software",
    "Health & Wellness",
    "Entertainment",
    "Miscellaneous",
]


# ---------------------------------------------------------------------------
# Backend Logic (SQLite3 + Pandas)
# ---------------------------------------------------------------------------
def init_db(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    """Initialize the SQLite database and create the expenses table if needed."""
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount >= 0),
                    description TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category)"
            )


def add_expense(
    expense_date: Union[str, date],
    category: str,
    amount: float,
    description: str = "",
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Validate and insert a new expense record into the database."""
    if isinstance(expense_date, (date, datetime)):
        parsed_date = expense_date.strftime("%Y-%m-%d")
    else:
        try:
            parsed_date = datetime.strptime(
                str(expense_date).strip(), "%Y-%m-%d"
            ).strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Invalid date '{expense_date}'. Expected format 'YYYY-MM-DD'."
            ) from exc

    cleaned_category = str(category).strip()
    if not cleaned_category:
        raise ValueError("Category cannot be empty.")

    numeric_amount = float(amount)
    if numeric_amount < 0:
        raise ValueError(f"Amount must be non-negative, got {numeric_amount}.")

    init_db(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO expenses (date, category, amount, description)
                VALUES (?, ?, ?, ?)
                """,
                (
                    parsed_date,
                    cleaned_category,
                    round(numeric_amount, 2),
                    str(description).strip(),
                ),
            )
            return int(cursor.lastrowid)


def delete_expense(
    expense_id: Union[int, Sequence[int]],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Delete one or more expense records by ID."""
    init_db(db_path)

    if isinstance(expense_id, int):
        ids_to_delete = [int(expense_id)]
    else:
        ids_to_delete = [int(i) for i in expense_id]

    if not ids_to_delete:
        return 0

    placeholders = ",".join("?" for _ in ids_to_delete)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                f"DELETE FROM expenses WHERE id IN ({placeholders})",
                ids_to_delete,
            )
            return int(cursor.rowcount)


def fetch_all_expenses(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """Retrieve all expense records from the database as a Pandas DataFrame."""
    init_db(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        df = pd.read_sql_query(
            """
            SELECT id, date, category, amount, description
            FROM expenses
            ORDER BY date DESC, id DESC
            """,
            conn,
        )

    if df.empty:
        return pd.DataFrame(
            columns=["id", "date", "category", "amount", "description"]
        )

    df["id"] = df["id"].astype(int)
    df["amount"] = df["amount"].astype(float).round(2)
    return df


def calculate_spending_by_category(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    year_month: Optional[str] = None,
) -> pd.DataFrame:
    """Calculate total spending, transaction count, and percentage share per category."""
    df = fetch_all_expenses(db_path)

    if year_month is not None:
        cleaned_ym = year_month.strip()
        try:
            datetime.strptime(cleaned_ym, "%Y-%m")
        except ValueError as exc:
            raise ValueError(
                f"Invalid year_month '{year_month}'. Expected format 'YYYY-MM'."
            ) from exc
        df = df[df["date"].str.startswith(cleaned_ym)]

    if df.empty:
        return pd.DataFrame(
            columns=[
                "category",
                "total_spent",
                "transaction_count",
                "percentage_of_total",
            ]
        )

    summary = (
        df.groupby("category", as_index=False)
        .agg(
            total_spent=("amount", "sum"),
            transaction_count=("id", "count"),
        )
        .sort_values(by=["total_spent", "category"], ascending=[False, True])
        .reset_index(drop=True)
    )

    grand_total = summary["total_spent"].sum()
    summary["total_spent"] = summary["total_spent"].round(2)
    summary["percentage_of_total"] = (
        ((summary["total_spent"] / grand_total) * 100).round(2)
        if grand_total > 0
        else 0.0
    )

    return summary


def check_monthly_budget(
    budget_threshold: float,
    year_month: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Check whether total spending for a target month exceeds the budget threshold."""
    threshold = float(budget_threshold)
    if threshold <= 0:
        raise ValueError(
            f"Budget threshold must be greater than 0, got {threshold}."
        )

    target_ym = (
        year_month.strip()
        if year_month is not None
        else datetime.now().strftime("%Y-%m")
    )
    try:
        datetime.strptime(target_ym, "%Y-%m")
    except ValueError as exc:
        raise ValueError(
            f"Invalid year_month '{target_ym}'. Expected format 'YYYY-MM'."
        ) from exc

    df = fetch_all_expenses(db_path)
    monthly_df = df[df["date"].str.startswith(target_ym)]

    total_spent = (
        round(float(monthly_df["amount"].sum()), 2)
        if not monthly_df.empty
        else 0.0
    )
    remaining = round(threshold - total_spent, 2)
    exceeded = total_spent > threshold
    overage = round(max(0.0, total_spent - threshold), 2)
    utilization_pct = round((total_spent / threshold) * 100, 2)

    return {
        "year_month": target_ym,
        "budget_threshold": round(threshold, 2),
        "total_spent": total_spent,
        "remaining_budget": remaining,
        "overage_amount": overage,
        "utilization_pct": utilization_pct,
        "exceeded": exceeded,
    }


def seed_demo_data(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> int:
    """Populate the database with realistic student expenses if needed."""
    current_ym = datetime.now().strftime("%Y-%m")
    sample_rows = [
        (f"{current_ym}-01", "Rent & Utilities", 450.00, "Shared apartment rent & fiber split"),
        (f"{current_ym}-03", "Textbooks & Supplies", 85.50, "Data Structures & Algorithms textbook"),
        (f"{current_ym}-05", "Groceries", 64.20, "Weekly meal prep & produce haul"),
        (f"{current_ym}-08", "Dining Out", 22.50, "Late-night ramen after lab session"),
        (f"{current_ym}-10", "Transit", 30.00, "Monthly student metro & bus pass"),
        (f"{current_ym}-12", "Tech & Software", 16.00, "Cloud GPU compute & IDE student add-on"),
        (f"{current_ym}-15", "Groceries", 52.80, "Coffee beans, oats, and frozen berries"),
    ]
    for exp_date, cat, amt, desc in sample_rows:
        add_expense(exp_date, cat, amt, desc, db_path=db_path)
    return len(sample_rows)


# ---------------------------------------------------------------------------
# Cyberpunk UI Styling & Components (Streamlit + Plotly)
# ---------------------------------------------------------------------------
def inject_cyberpunk_css() -> None:
    """Inject custom CSS for the #0D1117 / #00F0FF / #FF0055 cyberpunk aesthetic."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Orbitron:wght@600;800&display=swap');

        .stApp {{
            background-color: {BG_DEEP_SLATE};
            color: {TEXT_PRIMARY};
            font-family: 'JetBrains Mono', monospace;
        }}

        [data-testid="stHeader"] {{
            background-color: rgba(13, 17, 23, 0.85);
            border-bottom: 1px solid rgba(0, 240, 255, 0.18);
        }}

        [data-testid="stSidebar"] {{
            background-color: #090D13 !important;
            border-right: 1px solid rgba(0, 240, 255, 0.35);
            box-shadow: 4px 0 20px rgba(0, 240, 255, 0.08);
        }}

        h1, h2, h3, .cyber-title {{
            font-family: 'Orbitron', 'JetBrains Mono', sans-serif !important;
            letter-spacing: 1.5px;
            text-transform: uppercase;
        }}

        .cyber-banner {{
            background: linear-gradient(135deg, rgba(0, 240, 255, 0.09) 0%, rgba(255, 0, 85, 0.09) 100%);
            border: 1px solid {NEON_CYAN};
            border-left: 5px solid {HOT_PINK};
            border-radius: 8px;
            padding: 1.1rem 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 0 18px rgba(0, 240, 255, 0.15);
        }}

        .cyber-banner h1 {{
            color: {NEON_CYAN};
            font-size: 1.75rem;
            margin: 0;
            text-shadow: 0 0 10px rgba(0, 240, 255, 0.55);
        }}

        .cyber-banner p {{
            color: {TEXT_MUTED};
            margin: 0.35rem 0 0 0;
            font-size: 0.88rem;
        }}

        .cyber-card {{
            background: {BG_PANEL_SLATE};
            border: 1px solid rgba(0, 240, 255, 0.45);
            border-top: 3px solid {NEON_CYAN};
            border-radius: 8px;
            padding: 1.15rem 1.25rem;
            box-shadow: 0 0 15px rgba(0, 240, 255, 0.12), inset 0 0 12px rgba(0, 240, 255, 0.04);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}

        .cyber-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 0 22px rgba(0, 240, 255, 0.28);
        }}

        .cyber-card.pink-alert {{
            border-color: rgba(255, 0, 85, 0.65);
            border-top: 3px solid {HOT_PINK};
            box-shadow: 0 0 18px rgba(255, 0, 85, 0.22), inset 0 0 12px rgba(255, 0, 85, 0.06);
        }}

        .cyber-card-label {{
            color: {TEXT_MUTED};
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 1.4px;
            margin-bottom: 0.35rem;
        }}

        .cyber-card-value {{
            font-family: 'Orbitron', monospace;
            font-size: 1.85rem;
            font-weight: 800;
            color: {NEON_CYAN};
            text-shadow: 0 0 10px rgba(0, 240, 255, 0.45);
            margin-bottom: 0.35rem;
        }}

        .cyber-card-value.pink-text {{
            color: {HOT_PINK};
            text-shadow: 0 0 12px rgba(255, 0, 85, 0.55);
        }}

        .cyber-card-sub {{
            font-size: 0.78rem;
            color: {TEXT_PRIMARY};
            opacity: 0.85;
        }}

        .cyber-progress-wrap {{
            background: #161B22;
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 6px;
            height: 12px;
            width: 100%;
            overflow: hidden;
            margin: 0.85rem 0 1.4rem 0;
        }}

        .cyber-progress-fill {{
            height: 100%;
            transition: width 0.3s ease;
        }}

        .cyber-section-header {{
            color: {NEON_CYAN};
            font-family: 'Orbitron', monospace;
            font-size: 1.02rem;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            border-bottom: 1px solid rgba(0, 240, 255, 0.3);
            padding-bottom: 0.45rem;
            margin-bottom: 0.9rem;
        }}

        .stButton > button, .stFormSubmitButton > button {{
            background: linear-gradient(90deg, rgba(0, 240, 255, 0.16) 0%, rgba(255, 0, 85, 0.16) 100%) !important;
            color: {NEON_CYAN} !important;
            border: 1px solid {NEON_CYAN} !important;
            border-radius: 6px !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700 !important;
            letter-spacing: 1px !important;
            text-transform: uppercase !important;
            box-shadow: 0 0 10px rgba(0, 240, 255, 0.2) !important;
            transition: all 0.2s ease !important;
        }}

        .stButton > button:hover, .stFormSubmitButton > button:hover {{
            background: {HOT_PINK} !important;
            color: #FFFFFF !important;
            border-color: {HOT_PINK} !important;
            box-shadow: 0 0 16px rgba(255, 0, 85, 0.6) !important;
        }}

        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        .stDateInput > div > div {{
            background-color: {BG_PANEL_SLATE} !important;
            border-color: rgba(0, 240, 255, 0.35) !important;
            color: {TEXT_PRIMARY} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_category_donut_chart(category_df: pd.DataFrame) -> go.Figure:
    """Build an interactive cyberpunk Plotly donut chart for category spending."""
    if category_df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="NO EXPENSES RECORDED",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(
                family="Orbitron, JetBrains Mono, monospace",
                size=16,
                color=TEXT_MUTED,
            ),
        )
        fig.update_layout(
            paper_bgcolor=BG_DEEP_SLATE,
            plot_bgcolor=BG_DEEP_SLATE,
            height=380,
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    grand_total = float(category_df["total_spent"].sum())

    fig = go.Figure(
        data=[
            go.Pie(
                labels=category_df["category"],
                values=category_df["total_spent"],
                hole=0.62,
                marker=dict(
                    colors=CYBERPUNK_CHART_PALETTE[: len(category_df)],
                    line=dict(color=BG_DEEP_SLATE, width=2.5),
                ),
                textinfo="label+percent",
                textposition="outside",
                textfont=dict(
                    family="JetBrains Mono, monospace",
                    size=12,
                    color=TEXT_PRIMARY,
                ),
                customdata=category_df[["transaction_count", "percentage_of_total"]],
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "Total Spent: $%{value:,.2f}<br>"
                    "Share: %{customdata[1]:.2f}%<br>"
                    "Transactions: %{customdata[0]}<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        paper_bgcolor=BG_DEEP_SLATE,
        plot_bgcolor=BG_DEEP_SLATE,
        font=dict(family="JetBrains Mono, monospace", color=TEXT_PRIMARY),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.22,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color=TEXT_PRIMARY),
        ),
        annotations=[
            dict(
                text=(
                    f"<span style='color:{TEXT_MUTED};font-size:11px;'>TOTAL</span><br>"
                    f"<b style='color:{NEON_CYAN};font-size:18px;'>${grand_total:,.2f}</b>"
                ),
                x=0.5,
                y=0.5,
                font=dict(family="Orbitron, monospace", size=14, color=NEON_CYAN),
                showarrow=False,
            )
        ],
        height=400,
        margin=dict(t=30, b=60, l=20, r=20),
    )
    return fig


def filter_transactions(
    expenses_df: pd.DataFrame,
    search_query: str = "",
    selected_categories: Optional[Sequence[str]] = None,
    year_month: Optional[str] = None,
) -> pd.DataFrame:
    """Filter transactions by month, category list, and free-text search query."""
    filtered = expenses_df.copy()

    if year_month and year_month != "All Months":
        filtered = filtered[filtered["date"].str.startswith(year_month)]

    if selected_categories:
        filtered = filtered[filtered["category"].isin(selected_categories)]

    query = search_query.strip().lower()
    if query and not filtered.empty:
        mask = (
            filtered["description"].fillna("").str.lower().str.contains(query, regex=False)
            | filtered["category"].fillna("").str.lower().str.contains(query, regex=False)
            | filtered["date"].fillna("").str.lower().str.contains(query, regex=False)
            | filtered["id"].astype(str).str.contains(query, regex=False)
            | filtered["amount"].map(lambda x: f"{x:.2f}").str.contains(query, regex=False)
        )
        filtered = filtered[mask]

    return filtered.reset_index(drop=True)


def render_streamlit_app(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    """Render the complete Cyberpunk Student Budget Tracker Streamlit application."""
    st.set_page_config(
        page_title="NEON LEDGER // Student Budget Tracker",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_db(db_path)
    inject_cyberpunk_css()

    # -----------------------------------------------------------------------
    # 1. Sidebar Form: Add New Expenses & Budget Configuration
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.markdown(
            f"<h2 style='color:{NEON_CYAN};margin-bottom:0.2rem;'>⚡ NEON LEDGER</h2>"
            f"<p style='color:{TEXT_MUTED};font-size:0.8rem;margin-top:0;'>"
            "CYBERPUNK STUDENT TELEMETRY</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown(
            "<div class='cyber-section-header'>01 // BUDGET PARAMETERS</div>",
            unsafe_allow_html=True,
        )
        monthly_budget = st.number_input(
            "Monthly Budget Limit ($)",
            min_value=10.0,
            max_value=50000.0,
            value=800.0,
            step=25.0,
            format="%.2f",
            help="Set your target monthly spending cap.",
        )

        all_df_initial = fetch_all_expenses(db_path)
        current_ym = datetime.now().strftime("%Y-%m")
        available_months = sorted(
            set(
                all_df_initial["date"].str.slice(0, 7).tolist()
                if not all_df_initial.empty
                else []
            )
            | {current_ym},
            reverse=True,
        )
        selected_month = st.selectbox(
            "Active Telemetry Month",
            options=available_months,
            index=0,
            help="Month used for top metric cards and category breakdown.",
        )

        st.divider()
        st.markdown(
            "<div class='cyber-section-header'>02 // LOG NEW EXPENSE</div>",
            unsafe_allow_html=True,
        )

        with st.form("add_expense_form", clear_on_submit=True):
            input_date = st.date_input("Transaction Date", value=date.today())
            input_category = st.selectbox(
                "Expense Category",
                options=STUDENT_CATEGORIES,
                index=1,
            )
            input_amount = st.number_input(
                "Amount ($)",
                min_value=0.01,
                max_value=100000.0,
                value=15.00,
                step=1.00,
                format="%.2f",
            )
            input_description = st.text_input(
                "Description",
                placeholder="e.g., Campus coffee & lab notebook",
            )
            submitted = st.form_submit_button(
                "⚡ LOG EXPENSE", use_container_width=True
            )

            if submitted:
                try:
                    new_id = add_expense(
                        expense_date=input_date,
                        category=input_category,
                        amount=input_amount,
                        description=input_description,
                        db_path=db_path,
                    )
                    st.toast(
                        f"Logged #{new_id}: ${input_amount:.2f} in {input_category}",
                        icon="⚡",
                    )
                    st.rerun()
                except ValueError as err:
                    st.error(str(err))

        if all_df_initial.empty:
            st.divider()
            if st.button("⚡ LOAD DEMO STUDENT DATA", use_container_width=True):
                seed_demo_data(db_path)
                st.rerun()

    # -----------------------------------------------------------------------
    # Header Banner
    # -----------------------------------------------------------------------
    st.markdown(
        """
        <div class="cyber-banner">
            <h1>NEON LEDGER // STUDENT EXPENSE MATRIX</h1>
            <p>REAL-TIME SQLITE3 &amp; PANDAS FINANCIAL TELEMETRY // ACTIVE MONITOR</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------------------------------------------------
    # 2. Top Metric Cards: 'Total Spent', 'Monthly Budget', 'Remaining Balance'
    # -----------------------------------------------------------------------
    budget_status = check_monthly_budget(
        budget_threshold=monthly_budget,
        year_month=selected_month,
        db_path=db_path,
    )
    total_spent = budget_status["total_spent"]
    budget_limit = budget_status["budget_threshold"]
    remaining_balance = budget_status["remaining_budget"]
    utilization_pct = budget_status["utilization_pct"]
    is_exceeded = budget_status["exceeded"]

    col_spent, col_budget, col_rem = st.columns(3)

    with col_spent:
        st.markdown(
            f"""
            <div class="cyber-card">
                <div class="cyber-card-label">Total Spent ({selected_month})</div>
                <div class="cyber-card-value">${total_spent:,.2f}</div>
                <div class="cyber-card-sub">⚡ {utilization_pct:.1f}% of monthly allocation used</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_budget:
        st.markdown(
            f"""
            <div class="cyber-card">
                <div class="cyber-card-label">Monthly Budget</div>
                <div class="cyber-card-value">${budget_limit:,.2f}</div>
                <div class="cyber-card-sub">🎯 Threshold locked for {selected_month}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_rem:
        rem_card_class = "cyber-card pink-alert" if is_exceeded else "cyber-card"
        rem_val_class = "cyber-card-value pink-text" if is_exceeded else "cyber-card-value"
        rem_prefix = "-" if remaining_balance < 0 else ""
        rem_sub = (
            f"🚨 EXCEEDED BY ${budget_status['overage_amount']:,.2f}"
            if is_exceeded
            else "✅ WITHIN SAFE OPERATING THRESHOLD"
        )
        st.markdown(
            f"""
            <div class="{rem_card_class}">
                <div class="cyber-card-label">Remaining Balance</div>
                <div class="{rem_val_class}">{rem_prefix}${abs(remaining_balance):,.2f}</div>
                <div class="cyber-card-sub">{rem_sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Neon Utilization Bar
    bar_width = min(100.0, max(0.0, utilization_pct))
    bar_color = (
        f"linear-gradient(90deg, {NEON_CYAN} 0%, {HOT_PINK} 100%)"
        if is_exceeded
        else f"linear-gradient(90deg, {NEON_CYAN} 0%, #00FF9F 100%)"
    )
    st.markdown(
        f"""
        <div class="cyber-progress-wrap" title="Budget Utilization: {utilization_pct:.1f}%">
            <div class="cyber-progress-fill" style="width:{bar_width}%;background:{bar_color};"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if is_exceeded:
        st.error(
            f"⚠️ **SYSTEM ALERT // BUDGET THRESHOLD EXCEEDED:** Spending for **{selected_month}** "
            f"(${total_spent:,.2f}) has surpassed your **${budget_limit:,.2f}** cap by "
            f"**${budget_status['overage_amount']:,.2f}**."
        )

    # -----------------------------------------------------------------------
    # 3. Interactive Plotly Donut Chart & 4. Searchable Transaction Table
    # -----------------------------------------------------------------------
    left_col, right_col = st.columns([5, 7], gap="large")

    with left_col:
        st.markdown(
            f"<div class='cyber-section-header'>03 // CATEGORY SPENDING BREAKDOWN ({selected_month})</div>",
            unsafe_allow_html=True,
        )
        category_df = calculate_spending_by_category(
            db_path=db_path, year_month=selected_month
        )
        donut_fig = build_category_donut_chart(category_df)
        st.plotly_chart(donut_fig, use_container_width=True)

        if not category_df.empty:
            st.dataframe(
                category_df.rename(
                    columns={
                        "category": "Category",
                        "total_spent": "Total ($)",
                        "transaction_count": "Txns",
                        "percentage_of_total": "Share (%)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with right_col:
        st.markdown(
            "<div class='cyber-section-header'>04 // RECENT TRANSACTIONS &amp; LEDGER CONTROL</div>",
            unsafe_allow_html=True,
        )

        expenses_df = fetch_all_expenses(db_path)

        search_col, cat_filter_col, scope_col = st.columns([5, 4, 3])
        with search_col:
            search_query = st.text_input(
                "Search Transactions",
                placeholder="🔍 Search description, category, date, or amount...",
                label_visibility="collapsed",
            )
        with cat_filter_col:
            category_filter = st.multiselect(
                "Filter Category",
                options=STUDENT_CATEGORIES,
                placeholder="Filter by category...",
                label_visibility="collapsed",
            )
        with scope_col:
            month_scope = st.selectbox(
                "Month Scope",
                options=[selected_month, "All Months"],
                index=0,
                label_visibility="collapsed",
            )

        filtered_df = filter_transactions(
            expenses_df=expenses_df,
            search_query=search_query,
            selected_categories=category_filter,
            year_month=month_scope,
        )

        if filtered_df.empty:
            st.info(
                "No matching transactions found. Log an expense in the sidebar or adjust your search filters."
            )
        else:
            editor_df = filtered_df.copy()
            editor_df.insert(0, "Delete", False)

            edited_table = st.data_editor(
                editor_df,
                hide_index=True,
                use_container_width=True,
                disabled=["id", "date", "category", "amount", "description"],
                column_config={
                    "Delete": st.column_config.CheckboxColumn(
                        "🗑️",
                        help="Check to mark this transaction for deletion",
                        default=False,
                        width="small",
                    ),
                    "id": st.column_config.NumberColumn("ID", width="small"),
                    "date": st.column_config.TextColumn("Date", width="small"),
                    "category": st.column_config.TextColumn("Category", width="medium"),
                    "amount": st.column_config.NumberColumn(
                        "Amount ($)", format="$%.2f", width="small"
                    ),
                    "description": st.column_config.TextColumn(
                        "Description", width="large"
                    ),
                },
                key="transactions_data_editor",
            )

            selected_ids = edited_table.loc[
                edited_table["Delete"] == True, "id"  # noqa: E712
            ].tolist()

            del_col_btn, del_col_quick = st.columns([1, 1])
            with del_col_btn:
                if st.button(
                    f"🗑️ DELETE SELECTED ({len(selected_ids)})",
                    disabled=(len(selected_ids) == 0),
                    use_container_width=True,
                ):
                    deleted_count = delete_expense(selected_ids, db_path=db_path)
                    st.toast(
                        f"Purged {deleted_count} transaction(s) from ledger.",
                        icon="🗑️",
                    )
                    st.rerun()

            with del_col_quick:
                with st.popover("⚡ Quick Delete by ID", use_container_width=True):
                    target_id = st.selectbox(
                        "Select Transaction ID to Delete",
                        options=filtered_df["id"].tolist(),
                        format_func=lambda x: (
                            f"#{x} — {filtered_df.loc[filtered_df['id'] == x, 'category'].values[0]} "
                            f"(${filtered_df.loc[filtered_df['id'] == x, 'amount'].values[0]:.2f})"
                        ),
                    )
                    if st.button("Confirm Delete", key="confirm_single_delete", use_container_width=True):
                        delete_expense(int(target_id), db_path=db_path)
                        st.toast(f"Deleted transaction #{target_id}.", icon="🗑️")
                        st.rerun()


# ---------------------------------------------------------------------------
# Execution Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    render_streamlit_app()