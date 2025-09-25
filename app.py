from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
from datetime import datetime

app = Flask(__name__)

# Data storage file
DATA_FILE = 'invoice_data.json'


# -----------------------
# Data helpers
# -----------------------
def load_data():
    """Load data from JSON file and ensure backward-compatible fields."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {'outcomes': [], 'incomes': []}
    else:
        data = {'outcomes': [], 'incomes': []}

    # Backfill defaults for old records so new features work without migration
    for o in data.get('outcomes', []):
        if 'monthly_limit' not in o:
            o['monthly_limit'] = float(o.get('cost', 0) or 0)
        if 'transactions' not in o:
            o['transactions'] = []  # [{id, amount, date, note}]
        # keep legacy 'status' if present; UI uses computed status
    return data


def save_data(data):
    """Save data to JSON file"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def current_ym():
    """Return current year-month string, e.g., '2025-09'"""
    return datetime.now().strftime('%Y-%m')


def sum_income(data):
    return sum(float(i.get('amount', 0) or 0) for i in data.get('incomes', []))


def sum_outcome_costs(data):
    # Legacy "cost" sum (kept for your original totals & net balance)
    return sum(float(o.get('cost', 0) or 0) for o in data.get('outcomes', []))


def sum_monthly_limits(data):
    return sum(float(o.get('monthly_limit', 0) or 0) for o in data.get('outcomes', []))


def spent_this_month_for_outcome(o, ym=None):
    """Sum of transactions for an outcome in the current month."""
    ym = ym or current_ym()
    total = 0.0
    for t in o.get('transactions', []):
        # t['date'] format: 'YYYY-MM-DD HH:MM:SS'
        if str(t.get('date', '')).startswith(ym):
            total += float(t.get('amount', 0) or 0)
    return total


def spent_this_month_total(data):
    ym = current_ym()
    return sum(spent_this_month_for_outcome(o, ym) for o in data.get('outcomes', []))


def compute_auto_status(spent: float, limit: float) -> str:
    """Derive status from spending vs budget."""
    eps = 1e-6
    if spent <= eps:
        return "Pending"
    if limit <= eps:
        # No limit but there is spend
        return "In Course"
    if spent + eps < limit:
        return "In Course"
    if abs(spent - limit) <= eps:
        return "Paid"
    return "Over"


# -----------------------
# Routes
# -----------------------
@app.route('/')
def index():
    """Main dashboard page"""
    data = load_data()

    # Original summary (legacy totals)
    total_income = sum_income(data)
    total_outcomes = sum_outcome_costs(data)
    net_balance = total_income - total_outcomes

    # New budget summary (per-month)
    total_monthly_budget = sum_monthly_limits(data)
    total_spent_month = spent_this_month_total(data)
    total_remaining_month = max(total_monthly_budget - total_spent_month, 0)

    # Per-outcome computed fields for the view
    ym = current_ym()
    for o in data['outcomes']:
        o['_spent_month'] = spent_this_month_for_outcome(o, ym)
        o['_remaining_month'] = max(float(o.get('monthly_limit', 0)) - o['_spent_month'], 0)

        limit = float(o.get('monthly_limit', 0) or 0)
        o['_status'] = compute_auto_status(o['_spent_month'], limit)

        if limit <= 0:
            o['_budget_state'] = 'no-limit'
            o['_pct_used'] = 0.0
        else:
            pct = (o['_spent_month'] / limit) * 100.0
            o['_pct_used'] = round(pct, 2)
            if pct < 70:
                o['_budget_state'] = 'ok'
            elif pct <= 100:
                o['_budget_state'] = 'near'
            else:
                o['_budget_state'] = 'over'
        o['_pct_capped'] = min(o['_pct_used'], 100.0)

    return render_template(
        'dashboard.html',
        outcomes=data['outcomes'],
        incomes=data['incomes'],
        total_income=total_income,
        total_outcomes=total_outcomes,
        net_balance=net_balance,
        total_monthly_budget=total_monthly_budget,
        total_spent_month=total_spent_month,
        total_remaining_month=total_remaining_month,
        current_year_month=ym
    )


@app.route('/add_outcome', methods=['POST'])
def add_outcome():
    """Add a new outcome (expense bucket) with optional monthly limit"""
    data = load_data()

    monthly_limit = request.form.get('monthly_limit', '').strip()
    try:
        monthly_limit = float(monthly_limit) if monthly_limit != '' else 0.0
    except ValueError:
        monthly_limit = 0.0

    outcome = {
        'id': (max([o['id'] for o in data['outcomes']], default=0) + 1),
        'name': request.form['name'],
        'cost': float(request.form.get('cost', 0) or 0),  # legacy field (kept)
        'monthly_limit': monthly_limit,
        'status': 'Pending',  # stored for backward compat; UI computes display
        'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'transactions': []
    }

    data['outcomes'].append(outcome)
    save_data(data)
    return redirect(url_for('index'))


@app.route('/add_income', methods=['POST'])
def add_income():
    """Add a new income"""
    data = load_data()
    income = {
        'id': (max([i['id'] for i in data['incomes']], default=0) + 1),
        'name': request.form['name'],
        'amount': float(request.form['amount']),
        'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    data['incomes'].append(income)
    save_data(data)
    return redirect(url_for('index'))


@app.route('/update_outcome_cost', methods=['POST'])
def update_outcome_cost():
    """Update legacy outcome cost"""
    data = load_data()
    outcome_id = int(request.form['outcome_id'])
    new_cost = float(request.form['cost'])

    for outcome in data['outcomes']:
        if outcome['id'] == outcome_id:
            outcome['cost'] = new_cost
            break

    save_data(data)
    return jsonify({'success': True})


@app.route('/update_income_amount', methods=['POST'])
def update_income_amount():
    """Update income amount"""
    data = load_data()
    income_id = int(request.form['income_id'])
    new_amount = float(request.form['amount'])

    for income in data['incomes']:
        if income['id'] == income_id:
            income['amount'] = new_amount
            break

    save_data(data)
    return jsonify({'success': True})


@app.route('/update_monthly_limit', methods=['POST'])
def update_monthly_limit():
    """Update an outcome's monthly limit (budget)"""
    data = load_data()
    outcome_id = int(request.form['outcome_id'])
    new_limit = float(request.form.get('monthly_limit', 0) or 0)

    for outcome in data['outcomes']:
        if outcome['id'] == outcome_id:
            outcome['monthly_limit'] = new_limit
            break

    save_data(data)
    return jsonify({'success': True})


@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    """Add a spend entry to an outcome"""
    data = load_data()
    outcome_id = int(request.form['outcome_id'])
    amount = float(request.form.get('amount', 0) or 0)
    note = request.form.get('note', '').strip()

    for outcome in data['outcomes']:
        if outcome['id'] == outcome_id:
            next_id = (max([t['id'] for t in outcome.get('transactions', [])], default=0) + 1)
            outcome['transactions'].append({
                'id': next_id,
                'amount': amount,
                'note': note,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            break

    save_data(data)
    return redirect(url_for('index'))


@app.route('/delete_transaction/<int:outcome_id>/<int:txn_id>', methods=['POST'])
def delete_transaction(outcome_id, txn_id):
    """Delete a spend entry from an outcome"""
    data = load_data()
    for outcome in data['outcomes']:
        if outcome['id'] == outcome_id:
            outcome['transactions'] = [t for t in outcome.get('transactions', []) if t['id'] != txn_id]
            break
    save_data(data)
    return redirect(url_for('index'))


@app.route('/delete_outcome/<int:outcome_id>', methods=['POST'])
def delete_outcome(outcome_id):
    """Delete an outcome"""
    data = load_data()
    data['outcomes'] = [o for o in data['outcomes'] if o['id'] != outcome_id]
    save_data(data)
    return redirect(url_for('index'))


@app.route('/delete_income/<int:income_id>', methods=['POST'])
def delete_income(income_id):
    """Delete an income"""
    data = load_data()
    data['incomes'] = [i for i in data['incomes'] if i['id'] != income_id]
    save_data(data)
    return redirect(url_for('index'))


# -----------------------
# App bootstrap + template
# -----------------------
if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')

    # Minimalist, modern template (UTF-8 write)
    template_content = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
  <title>budgify</title>

  <!-- Inter font -->
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

  <!-- Minimal icons -->
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">

  <style>
/* =========================
   Design Tokens
   ========================= */
:root{
  /* Core palette */
  --bg: #f6f7f8;         /* app background (neutral) */
  --surface: #ffffff;    /* cards / nav / modals */
  --text: #0f172a;       /* primary text (very dark gray) */
  --muted: #6b7280;      /* secondary text */
  --border: #e5e7eb;     /* subtle borders */

  /* Brand */
  --primary: #2563eb;    /* primary blue */
  --accent:  #f59e0b;    /* accent amber */

  /* Semantic (for status) */
  --ok:       #22c55e;   /* OK/Success */
  --near:     #f59e0b;   /* Near limit */
  --over:     #ef4444;   /* Over */
  --pending:  #9ca3af;   /* Pending (neutral) */

  /* Status tints (backgrounds) */
  --ok-bg:      #ecfdf5;
  --near-bg:    #fff7ed;
  --over-bg:    #fef2f2;
  --pending-bg: #f4f5f7;

  /* Elevation & radii */
  --radius-lg: 14px;
  --radius-md: 12px;
  --radius-sm: 10px;
  --shadow-md: 0 8px 24px rgba(17,24,39,.06);
  --shadow-sm: 0 2px 10px rgba(17,24,39,.06);
  --focus:     0 0 0 3px rgba(37,99,235,.25);
}

/* Global reset & typography */
*{ box-sizing: border-box; }
html,body{ height: 100%; }
body{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Layout shells */
.wrap{ max-width: 1200px; margin: 0 auto; padding: 16px; }
header{
  position: sticky; top: 0; z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  backdrop-filter: saturate(180%) blur(8px);
}
.nav{
  display:flex; align-items:center; justify-content:space-between;
  gap: 12px; padding: 14px 0;
}
.brand{ display:flex; align-items:center; gap: 10px; }
.brand i{ color: var(--primary); }
.brand h1{ font-size: 18px; font-weight: 700; margin: 0; letter-spacing: .2px; }
.meta{ color: var(--muted); font-size: 14px; }

/* Main sections */
main{ padding: 18px 0; display: grid; gap: 16px; }

/* =========================
   Summary (stats)
   ========================= */
.summary{
  display:grid; gap: 12px;
  grid-template-columns: repeat(2,minmax(0,1fr));
}
@media (min-width: 720px){
  .summary{ grid-template-columns: repeat(3,minmax(0,1fr)); }
}
@media (min-width: 1120px){
  .summary{ grid-template-columns: repeat(6,minmax(0,1fr)); }
}
.stat{
  background: var(--surface);
  border:1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px;
  box-shadow: var(--shadow-sm);
}
.stat .label{ color: var(--muted); font-size: 12px; margin-bottom: 6px; display:flex; align-items:center; gap:8px; }
.stat .label i{ color: var(--primary); }
.stat .value{ font-size: 18px; font-weight: 700; }

/* =========================
   Two-column layout
   ========================= */
.columns{
  display:grid; gap: 16px;
  grid-template-columns: 1fr;
}
@media (min-width: 980px){
  .columns{ grid-template-columns: 1.25fr .75fr; }
}

/* =========================
   Cards
   ========================= */
.card{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}
.card-header{
  padding: 16px 18px; border-bottom: 1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between; gap:12px;
}
.card-header h2{ font-size: 16px; font-weight: 700; margin: 0; letter-spacing:.2px; }
.card-body{ padding: 16px 18px; }

/* =========================
   Lists & Items
   ========================= */
.list{ display:flex; flex-direction:column; gap:12px; }
.item{
  border:1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  display:flex; flex-direction:column; gap:12px;
  transition: box-shadow .2s ease, transform .06s ease, border-color .2s ease;
  background: var(--surface);
}
.item:hover{ box-shadow: var(--shadow-sm); transform: translateY(-1px); }
.item-head{
  display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap: wrap;
}
.item-title{ font-weight:700; font-size: 15px; }
.muted{ color: var(--muted); font-size: 13px; }

/* =========================
   STATUS-STYLED EXPENSES
   (card background & border accents)
   ========================= */
/* Pending (spent == 0) */
.item.pending{
  background: var(--pending-bg);
  border-color: #dfe3e8;
  box-shadow: inset 0 0 0 2px rgba(156,163,175,.15);
}

/* In Course (0 < spent < limit) */
.item.in-course{
  background: var(--near-bg);
  border-color: #f3d7b3;
  box-shadow: inset 0 0 0 2px rgba(245,158,11,.18);
}

/* Paid (spent == limit) */
.item.paid{
  background: var(--ok-bg);
  border-color: #bfead4;
  box-shadow: inset 0 0 0 2px rgba(34,197,94,.18);
}

/* Over (spent > limit) */
.item.over{
  background: var(--over-bg);
  border-color: #f5c2c2;
  box-shadow: inset 0 0 0 2px rgba(239,68,68,.18);
}

/* Subtle left accent bar for quick scanning */
.item.pending::before,
.item.in-course::before,
.item.paid::before,
.item.over::before{
  content:"";
  display:block;
  position:relative;
  width: 6px; height: 100%;
  border-radius: 6px;
  margin-right: 10px;
  background: transparent;
  flex: 0 0 6px;
}
.item.pending{ display:flex; }
.item.in-course{ display:flex; }
.item.paid{ display:flex; }
.item.over{ display:flex; }

.item.pending::before{ background: var(--pending); opacity: .28; }
.item.in-course::before{ background: var(--near); opacity: .28; }
.item.paid::before{ background: var(--ok); opacity: .28; }
.item.over::before{ background: var(--over); opacity: .28; }

/* Keep content aligned after the accent bar */
.item > *:not(:first-child){ /* no-op, placeholder in case of future tweaks */ }

/* =========================
   Budget Row (grid inside item)
   ========================= */
.budget{
  display:grid; gap: 10px;
  grid-template-columns: repeat(5,minmax(0,1fr));
  align-items:center;
}
@media (max-width: 720px){
  .budget{ grid-template-columns: 1fr 1fr; }
}
.label{ font-size: 12px; color: var(--muted); margin-bottom: 6px; }

/* Badges */
.badge{
  display:inline-block; padding: 6px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 700; border: 1px solid var(--border); background: #f9fafb;
}
.badge.ok   { color: var(--ok); }
.badge.near { color: var(--near); }
.badge.over { color: var(--over); }
.badge.nolimit{ color: var(--muted); }
.badge.status{ color: var(--text); }

/* Progress */
.progress{ width:100%; height:10px; background:#eef2f7; border-radius:999px; overflow:hidden; }
.progress > div{ height:100%; width:0; background: var(--primary); transition: width .4s ease; }
.progress.near > div{ background: var(--accent); }
.progress.over > div{ background: var(--over); }

/* =========================
   Controls (buttons & inline numbers)
   ========================= */
.row{ display:flex; gap:10px; align-items:center; flex-wrap: wrap; }

.btn{
  appearance:none; -webkit-appearance:none;
  border:1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-weight: 700;
  cursor: pointer;
  transition: transform .06s ease, box-shadow .2s ease, border-color .2s ease, background .2s ease, color .2s ease;
}
.btn:hover{ box-shadow: var(--shadow-sm); transform: translateY(-1px); }
.btn:focus-visible{ outline: none; box-shadow: var(--focus); }
.btn-primary{
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
.btn-primary:hover{ filter: brightness(0.98); }
.btn-danger{
  color:#fff; background: var(--over); border-color: var(--over);
}
.btn-tonal{
  background:#f9fafb; border-color: var(--border);
}
.btn-sm{ padding: 8px 10px; font-size: 13px; border-radius: 8px; }

.num-inline{
  background: transparent; border: 1px dashed transparent;
  font-weight: 800; text-align: right; width: 120px; letter-spacing:.2px;
}
.num-inline.cost{ color: var(--over); }
.num-inline.amount{ color: var(--ok); }
.num-inline.limit{ color: var(--primary); }
.num-inline:focus{ outline: none; border-color: var(--primary); background: #fff; }

/* =========================
   Forms / Inputs
   ========================= */
.field{ display:flex; flex-direction:column; gap:6px; }
.input{
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  font: inherit;
}
.input:focus{ outline: none; box-shadow: var(--focus); }

/* =========================
   Modals
   ========================= */
.modal{ display:none; position:fixed; inset:0; z-index:1000; background: rgba(0,0,0,.35); }
.modal-content{
  position:absolute; left:50%; top:50%; transform: translate(-50%,-50%);
  width: min(560px, 94vw);
  background: var(--surface); border:1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow-md);
  padding: 18px;
}
.modal-header{ display:flex; justify-content:space-between; align-items:center; margin-bottom: 10px; }
.close{ cursor:pointer; border:none; background: transparent; font-size: 20px; color: var(--muted); }
.close:hover{ color: var(--text); }

/* =========================
   Utilities
   ========================= */
.hidden{ display:none!important; }
[disabled]{ opacity:.6; pointer-events:none; }

/* prefers-reduced-motion for accessibility */
@media (prefers-reduced-motion: reduce) {
  .btn, .item, .progress > div{ transition: none !important; }
}

  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <nav class="nav" aria-label="Primary">
        <div class="brand">
          <i class="fa-solid fa-chart-line"></i>
          <h1>budgify</h1>
        </div>
        <div class="meta">Month: <strong>{{ current_year_month }}</strong></div>
      </nav>
    </div>
  </header>

  <main>
    <div class="wrap">
      <!-- Summary -->
      <section class="summary" aria-label="Summary">
        <div class="stat">
          <div class="label"><i class="fa-solid fa-arrow-up"></i>Total Income</div>
          <div class="value">${{ "%.2f"|format(total_income) }}</div>
          <div class="muted">{{ incomes|length }} income sources</div>
        </div>
        <div class="stat">
          <div class="label"><i class="fa-solid fa-arrow-down"></i>Total Expenses (legacy)</div>
          <div class="value">${{ "%.2f"|format(total_outcomes) }}</div>
          <div class="muted">{{ outcomes|length }} expenses tracked</div>
        </div>
        <div class="stat">
          <div class="label"><i class="fa-solid fa-scale-balanced"></i>Net Balance (legacy)</div>
          <div class="value" style="color: {{ '#16a34a' if net_balance >= 0 else '#dc2626' }};">
            ${{ "%.2f"|format(net_balance) }}
          </div>
        </div>
        <div class="stat">
          <div class="label"><i class="fa-regular fa-calendar-check"></i>Total Monthly Budget</div>
          <div class="value">${{ "%.2f"|format(total_monthly_budget) }}</div>
        </div>
        <div class="stat">
          <div class="label"><i class="fa-solid fa-receipt"></i>Spent (this month)</div>
          <div class="value">${{ "%.2f"|format(total_spent_month) }}</div>
        </div>
        <div class="stat">
          <div class="label"><i class="fa-solid fa-wallet"></i>Remaining (this month)</div>
          <div class="value">${{ "%.2f"|format(total_remaining_month) }}</div>
        </div>
      </section>

      <!-- Columns -->
      <section class="columns" aria-label="Content">
        <!-- Expenses -->
        <article class="card">
          <div class="card-header">
            <h2>Expenses</h2>
            <button class="btn btn-primary btn-sm" onclick="openModal('expenseModal')">
              <i class="fa-solid fa-plus"></i>&nbsp;Add Expense
            </button>
          </div>
          <div class="card-body">
            <div class="list">
              {% if outcomes %}
                {% for outcome in outcomes %}
                <div class="item {{ outcome._status.lower().replace(' ', '-') }}">
                  <div class="item-head">
                    <div class="item-title">{{ outcome.name }}</div>
                    <input type="number" class="num-inline cost" value="{{ outcome.cost }}" step="0.01"
                      onchange="updateCost({{ outcome.id }}, this.value)" aria-label="Legacy cost for {{ outcome.name }}">
                  </div>

                  <div class="budget">
                    <div>
                      <div class="label">Monthly Limit</div>
                      <input type="number" class="num-inline limit" value="{{ outcome.monthly_limit }}" step="0.01"
                        onchange="updateMonthlyLimit({{ outcome.id }}, this.value)" aria-label="Monthly limit for {{ outcome.name }}">
                    </div>
                    <div>
                      <div class="label">Spent ({{ current_year_month }})</div>
                      <strong>${{ '%.2f'|format(outcome._spent_month) }}</strong>
                    </div>
                    <div>
                      <div class="label">Remaining</div>
                      <strong>${{ '%.2f'|format(outcome._remaining_month) }}</strong>
                    </div>
                    <div>
                      <div class="label">Status</div>
                      <span class="badge status">{{ outcome._status }}</span>
                    </div>
                    <div>
                      <div class="label">Usage</div>
                      {% if outcome._budget_state == 'ok' %}
                        <span class="badge ok">OK</span>
                      {% elif outcome._budget_state == 'near' %}
                        <span class="badge near">NEAR</span>
                      {% elif outcome._budget_state == 'over' %}
                        <span class="badge over">OVER</span>
                      {% else %}
                        <span class="badge nolimit">NO LIMIT</span>
                      {% endif %}
                    </div>
                  </div>

                  <div class="progress {% if outcome._budget_state=='near' %}near{% elif outcome._budget_state=='over' %}over{% endif %}" aria-label="Usage progress">
                    <div style="width: {{ '%.2f'|format(outcome._pct_capped) }}%"></div>
                  </div>
                  <div class="muted">Used {{ '%.2f'|format(outcome._pct_used) }}%</div>

                  <div class="row">
                    <!-- quick add transaction -->
                    <form method="POST" action="{{ url_for('add_transaction') }}" class="row" style="gap:8px;">
                      <input type="hidden" name="outcome_id" value="{{ outcome.id }}">
                      <input type="number" name="amount" class="input" step="0.01" required placeholder="Amount (e.g., 48.00)" style="width:160px;">
                      <input type="text" name="note" class="input" placeholder="Note (optional)" style="width:200px;">
                      <button type="submit" class="btn btn-tonal btn-sm"><i class="fa-solid fa-plus"></i>&nbsp;Spend</button>
                    </form>

                    <!-- delete outcome -->
                    <form method="POST" action="{{ url_for('delete_outcome', outcome_id=outcome.id) }}" onsubmit="return confirm('Delete this expense bucket? This also deletes its transactions.')" class="row">
                      <button type="submit" class="btn btn-danger btn-sm"><i class="fa-solid fa-trash"></i></button>
                    </form>
                  </div>

                  <!-- transactions (latest 5) -->
                  <div>
                    {% if outcome.transactions %}
                      {% set txns = outcome.transactions | sort(attribute='id', reverse=true) %}
                      {% for t in txns[:5] %}
                      <div class="row" style="justify-content: space-between; border:1px solid var(--border); border-radius:10px; padding:8px 12px;">
                        <div>
                          <strong>${{ '%.2f'|format(t.amount) }}</strong>
                          {% if t.note %}<span class="muted"> — {{ t.note }}</span>{% endif %}
                          <div class="muted" style="font-size:12px;">{{ t.date }}</div>
                        </div>
                        <form method="POST" action="{{ url_for('delete_transaction', outcome_id=outcome.id, txn_id=t.id) }}" onsubmit="return confirm('Delete this spend entry?')">
                          <button class="btn btn-danger btn-sm"><i class="fa-solid fa-trash"></i></button>
                        </form>
                      </div>
                      {% endfor %}
                      {% if outcome.transactions|length > 5 %}
                        <div class="muted">Showing latest 5 of {{ outcome.transactions|length }} entries</div>
                      {% endif %}
                    {% else %}
                      <div class="muted">No spend entries yet. Add your first transaction.</div>
                    {% endif %}
                  </div>
                </div>
                {% endfor %}
              {% else %}
                <div class="muted">No expenses recorded yet. Add your first expense to get started.</div>
              {% endif %}
            </div>
          </div>
        </article>

        <!-- Income -->
        <aside class="card">
          <div class="card-header">
            <h2>Income</h2>
            <button class="btn btn-primary btn-sm" onclick="openModal('incomeModal')">
              <i class="fa-solid fa-plus"></i>&nbsp;Add Income
            </button>
          </div>
          <div class="card-body">
            <div class="list">
              {% if incomes %}
                {% for income in incomes %}
                <div class="item">
                  <div class="item-head">
                    <div class="item-title">{{ income.name }}</div>
                    <input type="number" class="num-inline amount" value="{{ income.amount }}" step="0.01"
                      onchange="updateIncomeAmount({{ income.id }}, this.value)" aria-label="Income amount for {{ income.name }}">
                  </div>
                  <div class="muted">Added: {{ income.date_added }}</div>
                  <div class="row">
                    <form method="POST" action="{{ url_for('delete_income', income_id=income.id) }}" onsubmit="return confirm('Delete this income?')">
                      <button type="submit" class="btn btn-danger btn-sm"><i class="fa-solid fa-trash"></i></button>
                    </form>
                  </div>
                </div>
                {% endfor %}
              {% else %}
                <div class="muted">No income sources yet. Add one to track earnings.</div>
              {% endif %}
            </div>
          </div>
        </aside>
      </section>

      <!-- Modals -->
      <section>
        <!-- Add Expense Modal -->
        <div id="expenseModal" class="modal" role="dialog" aria-modal="true" aria-labelledby="expenseTitle">
          <div class="modal-content">
            <div class="modal-header">
              <h3 id="expenseTitle" style="margin:0; font-size:16px; font-weight:700;">Add New Expense</h3>
              <button class="close" onclick="closeModal('expenseModal')" aria-label="Close">&times;</button>
            </div>
            <form method="POST" action="{{ url_for('add_outcome') }}" class="list">
              <div class="field">
                <label class="label" for="expense-name">Expense Name</label>
                <input type="text" id="expense-name" name="name" class="input" required placeholder="e.g., Groceries">
              </div>
              <div class="field">
                <label class="label" for="expense-cost">Legacy Cost ($)</label>
                <input type="number" id="expense-cost" name="cost" class="input" step="0.01" placeholder="0.00">
                <span class="muted">Optional (kept for original totals)</span>
              </div>
              <div class="field">
                <label class="label" for="expense-limit">Monthly Limit ($)</label>
                <input type="number" id="expense-limit" name="monthly_limit" class="input" step="0.01" required placeholder="e.g., 150.00">
              </div>
              <div class="row" style="justify-content:flex-end;">
                <button type="button" class="btn" onclick="closeModal('expenseModal')">Cancel</button>
                <button type="submit" class="btn btn-primary">Add</button>
              </div>
            </form>
          </div>
        </div>

        <!-- Add Income Modal -->
        <div id="incomeModal" class="modal" role="dialog" aria-modal="true" aria-labelledby="incomeTitle">
          <div class="modal-content">
            <div class="modal-header">
              <h3 id="incomeTitle" style="margin:0; font-size:16px; font-weight:700;">Add New Income</h3>
              <button class="close" onclick="closeModal('incomeModal')" aria-label="Close">&times;</button>
            </div>
            <form method="POST" action="{{ url_for('add_income') }}" class="list">
              <div class="field">
                <label class="label" for="income-name">Income Source</label>
                <input type="text" id="income-name" name="name" class="input" required placeholder="e.g., Salary, Freelance">
              </div>
              <div class="field">
                <label class="label" for="income-amount">Amount ($)</label>
                <input type="number" id="income-amount" name="amount" class="input" step="0.01" required placeholder="0.00">
              </div>
              <div class="row" style="justify-content:flex-end;">
                <button type="button" class="btn" onclick="closeModal('incomeModal')">Cancel</button>
                <button type="submit" class="btn btn-primary">Add</button>
              </div>
            </form>
          </div>
        </div>
      </section>

      <footer class="wrap" aria-label="Footer">
        <div class="muted">© {{ current_year_month.split('-')[0] }} · Invoice Manager Pro</div>
      </footer>
    </div>
  </main>

  <script>
    function openModal(id){ document.getElementById(id).style.display='block'; }
    function closeModal(id){ document.getElementById(id).style.display='none'; }

    function updateCost(outcomeId,cost){
      fetch('/update_outcome_cost',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:`outcome_id=${outcomeId}&cost=${cost}`})
        .then(r=>r.json()).then(d=>{ if(d.success) setTimeout(()=>location.reload(),200); });
    }

    function updateMonthlyLimit(outcomeId,limit){
      fetch('/update_monthly_limit',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:`outcome_id=${outcomeId}&monthly_limit=${limit}`})
        .then(r=>r.json()).then(d=>{ if(d.success) setTimeout(()=>location.reload(),200); });
    }

    function updateIncomeAmount(incomeId,amount){
      fetch('/update_income_amount',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:`income_id=${incomeId}&amount=${amount}`})
        .then(r=>r.json()).then(d=>{ if(d.success) setTimeout(()=>location.reload(),200); });
    }

    // close modals by clicking backdrop
    window.addEventListener('click', (e)=>{
      const modals = document.querySelectorAll('.modal');
      modals.forEach(m => { if(e.target === m){ m.style.display = 'none'; } });
    });
  </script>
</body>
</html>'''

    # WRITE UTF-8 to avoid UnicodeDecodeError on Windows
    with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(template_content)

    print("✅ UI refreshed: minimalist design (Inter, neutral base + primary + accent).")
    print("✅ Auto status from spending (Pending/In Course/Paid/Over).")
    print("✅ Monthly budgets, transactions, inline edits, responsive layout.")
    print("➡  Run: 1) pip install flask  2) python app.py  3) http://localhost:5000")

    app.run(debug=True)
