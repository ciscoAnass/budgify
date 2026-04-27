from __future__ import annotations

import copy
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "budgify.json"
BACKUP_DIR = DATA_DIR / "backups"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

MONTH_NUMBER = {name: i + 1 for i, name in enumerate(MONTHS)}
NUMBER_MONTH = {i + 1: name for i, name in enumerate(MONTHS)}

DEFAULT_SECTIONS: list[dict[str, Any]] = [
    # Income sections
    {"id": "income-work-salary", "name": "Work Salary", "type": "income", "priority": "necessary", "monthly_budget": 0, "system": False},
    {"id": "income-freelance", "name": "Freelance", "type": "income", "priority": "not_necessary", "monthly_budget": 0, "system": False},
    {"id": "income-sell-product", "name": "Sell Product", "type": "income", "priority": "not_necessary", "monthly_budget": 0, "system": False},
    {"id": "income-extra", "name": "Extra", "type": "income", "priority": "not_necessary", "monthly_budget": 0, "system": False},
    {"id": "income-loan-return", "name": "Loan Return", "type": "income", "priority": "not_necessary", "monthly_budget": 0, "system": True},

    # Expense sections
    {"id": "expense-rent", "name": "Rent", "type": "expense", "priority": "necessary", "monthly_budget": 500, "system": False},
    {"id": "expense-food", "name": "Food", "type": "expense", "priority": "necessary", "monthly_budget": 150, "system": False},
    {"id": "expense-phone", "name": "Phone", "type": "expense", "priority": "necessary", "monthly_budget": 20, "system": False},
    {"id": "expense-transport", "name": "Transport", "type": "expense", "priority": "necessary", "monthly_budget": 50, "system": False},
    {"id": "expense-ai-subscription", "name": "AI Subscription", "type": "expense", "priority": "necessary", "monthly_budget": 20, "system": False},
    {"id": "expense-go-out", "name": "Go Out", "type": "expense", "priority": "not_necessary", "monthly_budget": 100, "system": False},
    {"id": "expense-festival", "name": "Festival", "type": "expense", "priority": "not_necessary", "monthly_budget": 0, "system": False},
    {"id": "expense-tattoo", "name": "Tattoo", "type": "expense", "priority": "not_necessary", "monthly_budget": 0, "system": False},
    {"id": "expense-loan-given", "name": "Loan Given", "type": "expense", "priority": "not_necessary", "monthly_budget": 0, "system": True},
]

DEFAULT_DATA: dict[str, Any] = {
    "app_name": "Budgify",
    "version": 3,
    "settings": {"currency": "€"},
    "savings_balance": 0.0,
    "sections": DEFAULT_SECTIONS,
    "years": {},
    "loans": [],
    "goals": [],
    "savings_history": [],
}


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_year_month() -> tuple[str, str]:
    now = datetime.now()
    return str(now.year), NUMBER_MONTH[now.month]


def date_to_year_month(date_text: str | None) -> tuple[str, str]:
    if not date_text:
        return now_year_month()
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%d")
        return str(dt.year), NUMBER_MONTH[dt.month]
    except ValueError:
        return now_year_month()


def money(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_type(section_type: str) -> str:
    if section_type in {"outcome", "expense", "expenses"}:
        return "expense"
    return "income"


def load_db() -> dict[str, Any]:
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        save_db(copy.deepcopy(DEFAULT_DATA))

    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data = migrate_data(data)
    return data


def save_db(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(DATA_FILE)


def migrate_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keep old Budgify JSON files usable after this redesign."""
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, copy.deepcopy(value))

    data["version"] = 3
    data.setdefault("settings", {"currency": "€"})
    data.setdefault("savings_balance", 0.0)
    data.setdefault("years", {})
    data.setdefault("loans", [])
    data.setdefault("goals", [])
    data.setdefault("savings_history", [])

    # Normalize and add missing built-in sections without deleting user sections.
    seen = {s.get("id") for s in data.get("sections", [])}
    for section in data.get("sections", []):
        section["type"] = normalize_type(section.get("type", "expense"))
        section.setdefault("priority", "necessary")
        section.setdefault("monthly_budget", 0)
        section.setdefault("system", False)
    for default_section in DEFAULT_SECTIONS:
        if default_section["id"] not in seen:
            data["sections"].append(copy.deepcopy(default_section))

    for year, months in data.get("years", {}).items():
        for month, month_data in months.items():
            if "outcomes" in month_data and "expenses" not in month_data:
                month_data["expenses"] = month_data.pop("outcomes")
            ensure_month(data, str(year), month)
            # Old v2 files could have per-month budget overrides.
            # Budgets now live only in the global Sections page, so migrate them there.
            old_budgets = month_data.get("sections", {}).pop("budgets", {})
            for section_id, budget in old_budgets.items():
                section = next((s for s in data.get("sections", []) if s.get("id") == section_id), None)
                if section and section.get("type") == "expense" and money(budget) > 0:
                    section["monthly_budget"] = money(budget)

    for loan in data.get("loans", []):
        original = money(loan.get("original_amount", loan.get("amount", 0)))
        loan["original_amount"] = original
        loan.setdefault("payments", [])
        paid = sum(money(p.get("amount")) for p in loan.get("payments", []))
        if not loan.get("payments") and loan.get("status") == "paid":
            paid = original
        loan["paid_amount"] = round(paid, 2)
        loan["remaining_amount"] = max(round(original - paid, 2), 0.0)
        loan["status"] = loan_status(loan)

    return data


def ensure_month(data: dict[str, Any], year: str, month: str) -> dict[str, Any]:
    data.setdefault("years", {})
    data["years"].setdefault(str(year), {})
    data["years"][str(year)].setdefault(month, {})
    month_data = data["years"][str(year)][month]
    month_data.setdefault("incomes", [])
    month_data.setdefault("expenses", [])
    month_data.setdefault("savings", [])
    month_data.setdefault("loans", [])
    month_data.setdefault("goals", [])
    month_data.setdefault("sections", {})
    month_data["sections"].setdefault("active_optional", [])
    return month_data


def section_by_id(data: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    return next((s for s in data.get("sections", []) if s.get("id") == section_id), None)


def section_name(data: dict[str, Any], section_id: str) -> str:
    section = section_by_id(data, section_id)
    return section.get("name", "Unknown") if section else "Unknown"


def activate_section_for_month(data: dict[str, Any], year: str, month: str, section_id: str) -> None:
    month_data = ensure_month(data, year, month)
    section = section_by_id(data, section_id)
    if not section:
        return
    active = month_data["sections"].setdefault("active_optional", [])
    if section.get("priority") == "not_necessary" and section_id not in active:
        active.append(section_id)


def entries_for_section(month_data: dict[str, Any], entry_type: str, section_id: str) -> list[dict[str, Any]]:
    key = "incomes" if entry_type == "income" else "expenses"
    return [e for e in month_data.get(key, []) if e.get("section_id") == section_id]


def section_has_entries(month_data: dict[str, Any], section_id: str) -> bool:
    return bool(entries_for_section(month_data, "income", section_id) or entries_for_section(month_data, "expense", section_id))


def sections_for_month(data: dict[str, Any], year: str, month: str, section_type: str) -> list[dict[str, Any]]:
    month_data = ensure_month(data, year, month)
    active = set(month_data.get("sections", {}).get("active_optional", []))
    result = []
    for section in data.get("sections", []):
        if section.get("type") != section_type:
            continue
        is_visible = (
            section.get("priority") == "necessary"
            or section.get("id") in active
            or section_has_entries(month_data, section.get("id"))
        )
        if is_visible:
            result.append(section)
    return sorted(result, key=lambda s: (s.get("priority") != "necessary", s.get("name", "")))


def inactive_optional_sections(data: dict[str, Any], year: str, month: str, section_type: str | None = None) -> list[dict[str, Any]]:
    month_data = ensure_month(data, year, month)
    active = set(month_data.get("sections", {}).get("active_optional", []))
    visible_ids = {s["id"] for t in ("income", "expense") for s in sections_for_month(data, year, month, t)}
    result = []
    for section in data.get("sections", []):
        if section_type and section.get("type") != section_type:
            continue
        if section.get("priority") != "not_necessary":
            continue
        if section.get("id") in active or section.get("id") in visible_ids:
            continue
        result.append(section)
    return sorted(result, key=lambda s: (s.get("type", ""), s.get("name", "")))


def budget_for_section(data: dict[str, Any], year: str, month: str, section: dict[str, Any]) -> float:
    # Budgets are managed globally in the Sections page.
    # The Month page only shows the budget; it does not edit it.
    return money(section.get("monthly_budget", 0))


def build_section_cards(data: dict[str, Any], year: str, month: str, section_type: str) -> list[dict[str, Any]]:
    month_data = ensure_month(data, year, month)
    cards = []
    for section in sections_for_month(data, year, month, section_type):
        key = "incomes" if section_type == "income" else "expenses"
        entries = [e for e in month_data.get(key, []) if e.get("section_id") == section.get("id")]
        entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)
        total = round(sum(money(e.get("amount")) for e in entries), 2)
        budget = budget_for_section(data, year, month, section) if section_type == "expense" else 0.0
        remaining = round(budget - total, 2) if budget else None
        over_budget = bool(budget and total > budget)
        cards.append({
            "section": section,
            "entries": entries,
            "total": total,
            "budget": budget,
            "remaining": remaining,
            "over_budget": over_budget,
            "over_amount": round(total - budget, 2) if over_budget else 0.0,
        })
    return cards


def calc_month(data: dict[str, Any], year: str, month: str) -> dict[str, float]:
    month_data = ensure_month(data, year, month)
    income = sum(money(x.get("amount")) for x in month_data.get("incomes", []))
    expenses_monthly = sum(money(x.get("amount")) for x in month_data.get("expenses", []) if x.get("source", "monthly") == "monthly")
    expenses_savings = sum(money(x.get("amount")) for x in month_data.get("expenses", []) if x.get("source") == "savings")
    saved_from_month = sum(money(x.get("amount")) for x in month_data.get("savings", []) if x.get("kind") == "add_from_monthly")
    withdrawn_to_month = sum(money(x.get("amount")) for x in month_data.get("savings", []) if x.get("kind") == "withdraw_to_month")
    remaining = income + withdrawn_to_month - expenses_monthly - saved_from_month
    return {
        "income": round(income, 2),
        "expenses": round(expenses_monthly, 2),
        "expenses_from_savings": round(expenses_savings, 2),
        "saved_from_month": round(saved_from_month, 2),
        "withdrawn_to_month": round(withdrawn_to_month, 2),
        "remaining": round(remaining, 2),
    }


def active_loans(data: dict[str, Any]) -> list[dict[str, Any]]:
    refresh_all_loans(data)
    return [l for l in data.get("loans", []) if l.get("status") in {"active", "partial"}]


def total_active_loan_remaining(data: dict[str, Any]) -> float:
    return round(sum(money(l.get("remaining_amount")) for l in active_loans(data)), 2)


def loan_status(loan: dict[str, Any]) -> str:
    original = money(loan.get("original_amount", loan.get("amount", 0)))
    paid = sum(money(p.get("amount")) for p in loan.get("payments", []))
    if paid <= 0:
        return "active"
    if paid >= original:
        return "paid"
    return "partial"


def refresh_loan(loan: dict[str, Any]) -> dict[str, Any]:
    original = money(loan.get("original_amount", loan.get("amount", 0)))
    paid = round(sum(money(p.get("amount")) for p in loan.get("payments", [])), 2)
    loan["original_amount"] = original
    loan["paid_amount"] = min(paid, original) if original else paid
    loan["remaining_amount"] = max(round(original - paid, 2), 0.0)
    loan["status"] = loan_status(loan)
    if loan["status"] == "paid" and loan.get("payments"):
        loan["paid_date"] = loan["payments"][-1].get("date")
    return loan


def refresh_all_loans(data: dict[str, Any]) -> None:
    for loan in data.get("loans", []):
        refresh_loan(loan)


def chart_payload(data: dict[str, Any], year: str) -> dict[str, Any]:
    income_values, expense_values, remaining_values, savings_values = [], [], [], []
    for m in MONTHS:
        stats = calc_month(data, year, m)
        income_values.append(stats["income"])
        expense_values.append(stats["expenses"])
        remaining_values.append(stats["remaining"])
        savings_values.append(stats["saved_from_month"])
    return {"months": MONTHS, "income": income_values, "expenses": expense_values, "remaining": remaining_values, "saved": savings_values}


def priority_spending(data: dict[str, Any], year: str, month: str) -> dict[str, float]:
    month_data = ensure_month(data, year, month)
    section_map = {s["id"]: s for s in data.get("sections", [])}
    necessary = 0.0
    optional = 0.0
    for expense in month_data.get("expenses", []):
        if expense.get("source") == "savings":
            continue
        section = section_map.get(expense.get("section_id"), {})
        if section.get("priority") == "necessary":
            necessary += money(expense.get("amount"))
        else:
            optional += money(expense.get("amount"))
    return {"Necessary": round(necessary, 2), "Not necessary": round(optional, 2)}


def best_worst_month(data: dict[str, Any], year: str) -> dict[str, Any]:
    values = [(month, calc_month(data, year, month)["remaining"]) for month in MONTHS]
    best = max(values, key=lambda x: x[1])
    worst = min(values, key=lambda x: x[1])
    return {"best": {"month": best[0], "amount": best[1]}, "worst": {"month": worst[0], "amount": worst[1]}}


def recent_entries(data: dict[str, Any], year: str, month: str, limit: int = 6) -> list[dict[str, Any]]:
    month_data = ensure_month(data, year, month)
    items = []
    for entry in month_data.get("incomes", []):
        e = copy.deepcopy(entry)
        e["kind"] = "Income"
        items.append(e)
    for entry in month_data.get("expenses", []):
        e = copy.deepcopy(entry)
        e["kind"] = "Expense"
        items.append(e)
    return sorted(items, key=lambda e: e.get("date", ""), reverse=True)[:limit]


def create_entry(
    data: dict[str, Any],
    year: str,
    month: str,
    entry_type: str,
    section_id: str,
    amount: float,
    title: str,
    date: str | None = None,
    notes: str = "",
    source: str = "monthly",
    linked_type: str | None = None,
    linked_id: str | None = None,
) -> dict[str, Any]:
    month_data = ensure_month(data, year, month)
    section = section_by_id(data, section_id)
    if not section:
        raise ValueError("Unknown section")

    activate_section_for_month(data, year, month, section_id)
    entry = {
        "id": new_id(),
        "section_id": section_id,
        "section_name": section.get("name"),
        "title": title or section.get("name"),
        "amount": money(amount),
        "date": date or today_iso(),
        "notes": notes or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if linked_type:
        entry["linked_type"] = linked_type
    if linked_id:
        entry["linked_id"] = linked_id

    if entry_type == "income":
        month_data["incomes"].append(entry)
    else:
        entry["source"] = source or "monthly"
        month_data["expenses"].append(entry)
        if entry["source"] == "savings":
            data["savings_balance"] = round(money(data.get("savings_balance")) - entry["amount"], 2)
    return entry


def add_savings_history(data: dict[str, Any], year: str, month: str, kind: str, amount: float, note: str, date: str, section_id: str | None = None) -> dict[str, Any]:
    month_data = ensure_month(data, year, month)
    item = {
        "id": new_id(),
        "kind": kind,
        "amount": money(amount),
        "note": note,
        "date": date,
        "year": year,
        "month": month,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if section_id:
        item["section_id"] = section_id
    month_data["savings"].append(item)
    data.setdefault("savings_history", []).append(copy.deepcopy(item))
    return item


@app.context_processor
def inject_globals() -> dict[str, Any]:
    data = load_db()
    return {
        "months": MONTHS,
        "currency": data.get("settings", {}).get("currency", "€"),
        "current_year": now_year_month()[0],
        "current_month": now_year_month()[1],
        "today": today_iso(),
    }


@app.route("/")
def dashboard():
    data = load_db()
    year = request.args.get("year") or now_year_month()[0]
    month = request.args.get("month") or now_year_month()[1]
    ensure_month(data, year, month)
    refresh_all_loans(data)
    stats = calc_month(data, year, month)
    loans_active = active_loans(data)
    total_remaining_loans = total_active_loan_remaining(data)
    chart_data = chart_payload(data, year)
    priority_data = priority_spending(data, year, month)
    cards_income = build_section_cards(data, year, month, "income")
    cards_expense = build_section_cards(data, year, month, "expense")
    over_budget_cards = [c for c in cards_expense if c["over_budget"]]
    goals = data.get("goals", [])[:4]
    save_db(data)
    return render_template(
        "dashboard.html",
        data=data,
        year=year,
        month=month,
        stats=stats,
        active_loans=loans_active,
        total_remaining_loans=total_remaining_loans,
        chart_data=chart_data,
        priority_data=priority_data,
        income_cards=cards_income,
        expense_cards=cards_expense,
        over_budget_cards=over_budget_cards,
        recent_entries=recent_entries(data, year, month),
        goals=goals,
        best_worst=best_worst_month(data, year),
    )


@app.route("/month")
def month_tracking():
    data = load_db()
    year = request.args.get("year") or now_year_month()[0]
    month = request.args.get("month") or now_year_month()[1]
    ensure_month(data, year, month)
    stats = calc_month(data, year, month)
    income_cards = build_section_cards(data, year, month, "income")
    expense_cards = build_section_cards(data, year, month, "expense")
    optional_income = inactive_optional_sections(data, year, month, "income")
    optional_expense = inactive_optional_sections(data, year, month, "expense")
    save_db(data)
    return render_template(
        "month.html",
        data=data,
        year=year,
        month=month,
        stats=stats,
        income_cards=income_cards,
        expense_cards=expense_cards,
        optional_income=optional_income,
        optional_expense=optional_expense,
    )


@app.post("/entries/add")
def add_entry():
    data = load_db()
    year = request.form.get("year") or now_year_month()[0]
    month = request.form.get("month") or now_year_month()[1]
    entry_type = normalize_type(request.form.get("entry_type", "expense"))
    if request.form.get("entry_type") == "income":
        entry_type = "income"
    section_id = request.form.get("section_id", "")
    amount = money(request.form.get("amount"))
    title = request.form.get("title", "")
    date = request.form.get("date") or today_iso()
    notes = request.form.get("notes", "")
    source = request.form.get("source", "monthly")

    if amount <= 0:
        flash("Please enter an amount bigger than 0.", "error")
        return redirect(request.referrer or url_for("month_tracking", year=year, month=month))

    section = section_by_id(data, section_id)
    if not section:
        flash("Please choose a valid section.", "error")
        return redirect(request.referrer or url_for("month_tracking", year=year, month=month))

    if section.get("type") == "income":
        create_entry(data, year, month, "income", section_id, amount, title, date, notes)
        flash(f"Income added to {section.get('name')}.", "success")
    else:
        create_entry(data, year, month, "expense", section_id, amount, title, date, notes, source=source)
        flash(f"Expense added to {section.get('name')}.", "success")
    save_db(data)
    return redirect(url_for("month_tracking", year=year, month=month))


@app.post("/entries/<entry_type>/<entry_id>/delete")
def delete_entry(entry_type: str, entry_id: str):
    data = load_db()
    year = request.form.get("year") or now_year_month()[0]
    month = request.form.get("month") or now_year_month()[1]
    month_data = ensure_month(data, year, month)
    key = "incomes" if entry_type == "income" else "expenses"
    items = month_data.get(key, [])
    for item in list(items):
        if item.get("id") == entry_id:
            if key == "expenses" and item.get("source") == "savings":
                data["savings_balance"] = round(money(data.get("savings_balance")) + money(item.get("amount")), 2)
            items.remove(item)
            flash("Entry deleted.", "success")
            break
    save_db(data)
    return redirect(url_for("month_tracking", year=year, month=month))


@app.post("/sections/activate")
def activate_section():
    data = load_db()
    year = request.form.get("year") or now_year_month()[0]
    month = request.form.get("month") or now_year_month()[1]
    section_id = request.form.get("section_id", "")
    section = section_by_id(data, section_id)
    if section and section.get("priority") == "not_necessary":
        activate_section_for_month(data, year, month, section_id)
        flash(f"{section.get('name')} added only to {month} {year}.", "success")
    else:
        flash("This section cannot be added manually.", "error")
    save_db(data)
    return redirect(url_for("month_tracking", year=year, month=month))


@app.post("/sections/budget")
def set_month_budget():
    # Kept only for compatibility with older forms/bookmarks.
    # Budgets are now managed only from the Sections page.
    flash("Budgets are edited only in the Sections page.", "error")
    return redirect(url_for("sections"))


@app.route("/sections")
def sections():
    data = load_db()
    income_sections = [s for s in data.get("sections", []) if s.get("type") == "income"]
    expense_sections = [s for s in data.get("sections", []) if s.get("type") == "expense"]
    return render_template("sections.html", income_sections=income_sections, expense_sections=expense_sections)


@app.post("/sections/add")
def add_section():
    data = load_db()
    name = request.form.get("name", "").strip()
    section_type = normalize_type(request.form.get("type", "expense"))
    priority = request.form.get("priority", "necessary")
    monthly_budget = money(request.form.get("monthly_budget"))
    if not name:
        flash("Section name is required.", "error")
        return redirect(url_for("sections"))
    section = {
        "id": f"{section_type}-{new_id()}",
        "name": name,
        "type": section_type,
        "priority": priority,
        "monthly_budget": monthly_budget if section_type == "expense" else 0,
        "system": False,
    }
    data.setdefault("sections", []).append(section)
    save_db(data)
    flash(f"{name} section created.", "success")
    return redirect(url_for("sections"))


@app.post("/sections/<section_id>/update")
def update_section(section_id: str):
    data = load_db()
    section = section_by_id(data, section_id)
    if section and not section.get("system"):
        section["name"] = request.form.get("name", section.get("name", "")).strip() or section.get("name")
        section["priority"] = request.form.get("priority", section.get("priority", "necessary"))
        section["monthly_budget"] = money(request.form.get("monthly_budget")) if section.get("type") == "expense" else 0
        flash("Section updated.", "success")
    elif section and section.get("system"):
        # System sections can still have default budgets edited if needed.
        section["monthly_budget"] = money(request.form.get("monthly_budget")) if section.get("type") == "expense" else 0
        flash("System section budget updated.", "success")
    save_db(data)
    return redirect(url_for("sections"))


@app.post("/sections/<section_id>/delete")
def delete_section(section_id: str):
    data = load_db()
    section = section_by_id(data, section_id)
    if not section:
        flash("Section not found.", "error")
    elif section.get("system"):
        flash("System sections cannot be deleted.", "error")
    else:
        data["sections"] = [s for s in data.get("sections", []) if s.get("id") != section_id]
        flash("Section deleted. Old entries will keep their saved section name.", "success")
    save_db(data)
    return redirect(url_for("sections"))


@app.route("/savings")
def savings():
    data = load_db()
    year = request.args.get("year") or now_year_month()[0]
    month = request.args.get("month") or now_year_month()[1]
    ensure_month(data, year, month)
    stats = calc_month(data, year, month)
    expense_sections = sections_for_month(data, year, month, "expense")
    history = sorted(data.get("savings_history", []), key=lambda x: x.get("date", ""), reverse=True)
    saved_by_month = []
    for m in MONTHS:
        month_data = ensure_month(data, year, m)
        saved_by_month.append(sum(money(x.get("amount")) for x in month_data.get("savings", []) if x.get("kind") == "add_from_monthly"))
    save_db(data)
    return render_template(
        "savings.html",
        data=data,
        year=year,
        month=month,
        stats=stats,
        expense_sections=expense_sections,
        history=history,
        savings_chart={"months": MONTHS, "saved": saved_by_month},
    )


@app.post("/savings/action")
def savings_action():
    data = load_db()
    action = request.form.get("action", "add_from_monthly")
    amount = money(request.form.get("amount"))
    date = request.form.get("date") or today_iso()
    year, month = date_to_year_month(date)
    note = request.form.get("note", "")
    if amount <= 0:
        flash("Please enter an amount bigger than 0.", "error")
        return redirect(url_for("savings"))

    if action == "add_from_monthly":
        data["savings_balance"] = round(money(data.get("savings_balance")) + amount, 2)
        add_savings_history(data, year, month, "add_from_monthly", amount, note or "Moved money to savings", date)
        flash("Money moved to savings.", "success")
    elif action == "withdraw_to_month":
        if amount > money(data.get("savings_balance")):
            flash("You do not have enough savings for this withdrawal.", "error")
            return redirect(url_for("savings"))
        data["savings_balance"] = round(money(data.get("savings_balance")) - amount, 2)
        add_savings_history(data, year, month, "withdraw_to_month", amount, note or "Withdrawn from savings", date)
        flash("Money withdrawn from savings into this month.", "success")
    elif action == "spend_from_savings":
        section_id = request.form.get("section_id", "")
        if amount > money(data.get("savings_balance")):
            flash("You do not have enough savings for this expense.", "error")
            return redirect(url_for("savings"))
        section = section_by_id(data, section_id)
        if not section or section.get("type") != "expense":
            flash("Please choose a valid expense section.", "error")
            return redirect(url_for("savings"))
        create_entry(data, year, month, "expense", section_id, amount, note or section.get("name"), date, note, source="savings")
        add_savings_history(data, year, month, "spend_from_savings", amount, note or f"Spent from savings: {section.get('name')}", date, section_id)
        flash("Expense paid from savings.", "success")
    elif action == "remove_from_savings":
        if amount > money(data.get("savings_balance")):
            flash("You cannot remove more than your current savings balance.", "error")
            return redirect(url_for("savings"))
        data["savings_balance"] = round(money(data.get("savings_balance")) - amount, 2)
        add_savings_history(data, year, month, "remove_from_savings", amount, note or "Removed from savings", date)
        flash("Savings removed from your balance.", "success")
    save_db(data)
    return redirect(url_for("savings", year=year, month=month))


@app.route("/loans")
def loans():
    data = load_db()
    refresh_all_loans(data)
    year = request.args.get("year") or now_year_month()[0]
    month = request.args.get("month") or now_year_month()[1]
    stats = calc_month(data, year, month)
    loans_sorted = sorted(data.get("loans", []), key=lambda l: l.get("date", ""), reverse=True)
    save_db(data)
    return render_template(
        "loans.html",
        loans=loans_sorted,
        year=year,
        month=month,
        stats=stats,
        total_remaining_loans=total_active_loan_remaining(data),
    )


@app.post("/loans/add")
def add_loan():
    data = load_db()
    person = request.form.get("person", "").strip()
    amount = money(request.form.get("amount"))
    date = request.form.get("date") or today_iso()
    description = request.form.get("description", "")
    source = request.form.get("source", "monthly")
    if not person or amount <= 0:
        flash("Person and amount are required.", "error")
        return redirect(url_for("loans"))

    year, month = date_to_year_month(date)
    if source == "savings" and amount > money(data.get("savings_balance")):
        flash("You do not have enough savings to give this loan from savings.", "error")
        return redirect(url_for("loans"))

    loan = {
        "id": new_id(),
        "person": person,
        "original_amount": amount,
        "paid_amount": 0.0,
        "remaining_amount": amount,
        "date": date,
        "description": description,
        "source": source,
        "status": "active",
        "payments": [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data.setdefault("loans", []).append(loan)
    ensure_month(data, year, month).setdefault("loans", []).append(loan["id"])

    # A loan given is real money going out. Add it as an expense automatically.
    create_entry(
        data,
        year,
        month,
        "expense",
        "expense-loan-given",
        amount,
        f"Loan to {person}",
        date,
        description,
        source=source,
        linked_type="loan_given",
        linked_id=loan["id"],
    )
    flash(f"Loan added. {amount:.2f} was counted as money going out.", "success")
    save_db(data)
    return redirect(url_for("loans", year=year, month=month))


@app.post("/loans/<loan_id>/payment")
def receive_loan_payment(loan_id: str):
    data = load_db()
    loan = next((l for l in data.get("loans", []) if l.get("id") == loan_id), None)
    if not loan:
        flash("Loan not found.", "error")
        return redirect(url_for("loans"))

    refresh_loan(loan)
    amount = money(request.form.get("amount"))
    date = request.form.get("date") or today_iso()
    description = request.form.get("description", "Loan money received")
    if amount <= 0:
        flash("Please enter a received amount bigger than 0.", "error")
        return redirect(url_for("loans"))
    if amount > money(loan.get("remaining_amount")):
        flash("The received amount is bigger than the remaining loan.", "error")
        return redirect(url_for("loans"))

    year, month = date_to_year_month(date)
    payment = {
        "id": new_id(),
        "amount": amount,
        "date": date,
        "description": description,
        "year": year,
        "month": month,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    loan.setdefault("payments", []).append(payment)

    # A loan return is real money coming in. Add it as income automatically.
    income_entry = create_entry(
        data,
        year,
        month,
        "income",
        "income-loan-return",
        amount,
        f"Loan return from {loan.get('person')}",
        date,
        description,
        linked_type="loan_return",
        linked_id=loan_id,
    )
    payment["income_entry_id"] = income_entry["id"]
    refresh_loan(loan)
    flash("Loan payment received and added as monthly income.", "success")
    save_db(data)
    return redirect(url_for("loans", year=year, month=month))


@app.post("/loans/<loan_id>/delete")
def delete_loan(loan_id: str):
    data = load_db()
    data["loans"] = [l for l in data.get("loans", []) if l.get("id") != loan_id]
    for months in data.get("years", {}).values():
        for month_data in months.values():
            if loan_id in month_data.get("loans", []):
                month_data["loans"].remove(loan_id)
    flash("Loan record deleted. Existing linked income/expense entries are not deleted automatically.", "success")
    save_db(data)
    return redirect(url_for("loans"))


@app.route("/goals")
def goals():
    data = load_db()
    goals_sorted = sorted(data.get("goals", []), key=lambda g: g.get("created_at", ""), reverse=True)
    return render_template("goals.html", goals=goals_sorted, savings_balance=money(data.get("savings_balance")))


@app.post("/goals/add")
def add_goal():
    data = load_db()
    name = request.form.get("name", "").strip()
    target_price = money(request.form.get("target_price"))
    description = request.form.get("description", "")
    if not name or target_price <= 0:
        flash("Goal name and price are required.", "error")
        return redirect(url_for("goals"))
    data.setdefault("goals", []).append({
        "id": new_id(),
        "name": name,
        "target_price": target_price,
        "description": description,
        "status": "active",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_db(data)
    flash("Goal created.", "success")
    return redirect(url_for("goals"))


@app.post("/goals/<goal_id>/complete")
def complete_goal(goal_id: str):
    data = load_db()
    for goal in data.get("goals", []):
        if goal.get("id") == goal_id:
            goal["status"] = "completed"
            goal["completed_at"] = datetime.now().isoformat(timespec="seconds")
            flash("Goal marked as completed.", "success")
            break
    save_db(data)
    return redirect(url_for("goals"))


@app.post("/goals/<goal_id>/delete")
def delete_goal(goal_id: str):
    data = load_db()
    data["goals"] = [g for g in data.get("goals", []) if g.get("id") != goal_id]
    save_db(data)
    flash("Goal deleted.", "success")
    return redirect(url_for("goals"))


@app.route("/export")
def export_data():
    data = load_db()
    save_db(data)
    return send_file(DATA_FILE, as_attachment=True, download_name="budgify-export.json")


@app.route("/backup")
def backup_data():
    data = load_db()
    save_db(data)
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"budgify-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    shutil.copy2(DATA_FILE, backup_path)
    flash(f"Backup created: {backup_path.name}", "success")
    return redirect(request.referrer or url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
