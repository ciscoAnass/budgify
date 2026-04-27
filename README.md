# Budgify

Budgify is a simple personal finance management web app built with Flask, HTML, CSS, JavaScript, JSON storage, and Chart.js.

This updated version focuses on being very easy to use. The main month page uses large category cards and always shows entries inside each card, without needing to click to expand anything.

## Main features

- Simple dashboard with big cards and clear actions
- Monthly tracking by category cards
- Income sections and expense sections
- Necessary sections appear automatically every month
- Not necessary sections are added manually only to the selected month
- Add entries inside each section
- Expense monthly budget limits managed from the Sections page
- Over-budget warnings
- Savings balance and savings history
- Remove savings if money is lost, stolen, or no longer available
- Spend directly from savings
- Real loan logic:
  - Giving a loan creates an expense called `Loan Given`
  - Receiving loan money creates income called `Loan Return`
  - Partial payments are supported
  - Remaining unpaid loan amount stays active
- Goals with progress based on savings
- JSON export and backup
- Dark mode
- Chart.js charts

## Project structure

```text
budgify/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── budgify.json
│   └── backups/
├── static/
│   ├── app.js
│   └── style.css
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── month.html
    ├── sections.html
    ├── savings.html
    ├── loans.html
    └── goals.html
```

## How to run

```bash
cd budgify
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open this in your browser:

```text
http://127.0.0.1:5000
```

## JSON storage

The data is stored in:

```text
data/budgify.json
```

The structure is still organized by year and month:

```json
{
  "years": {
    "2026": {
      "April": {
        "incomes": [],
        "expenses": [],
        "savings": [],
        "loans": [],
        "goals": [],
        "sections": {
          "active_optional": []
        }
      }
    }
  }
}
```

## How sections work

### Necessary sections

These appear automatically every month.

Examples:

- Work Salary
- Rent
- Food
- Phone
- Transport
- AI Subscription

### Not necessary sections

These do not appear automatically. You add them manually from `My Month Tracking` using `+ Add Section`.

Examples:

- Festival
- Tattoo
- Go Out
- Freelance
- Extra

If you add `Festival` to May, it appears only in May. It will not automatically appear in June.

## How loans work

### Giving a loan

If you lend someone €50, Budgify automatically adds an expense:

```text
Section: Loan Given
Amount: €50
```

So your available monthly money goes down.

### Receiving money back

If the person returns €30, Budgify automatically adds income:

```text
Section: Loan Return
Amount: €30
```

The loan remains active with €20 still unpaid.

When the full amount has been returned, the loan becomes paid.

## Important note

This is a local JSON-file app. It is simple and easy to understand, but it is not designed for multiple users editing at the same time.

## Latest changes

- `/month` no longer has any budget edit form. Budgets are edited only in `Sections`.
- Entries are always visible inside the income/expense category cards.
- Savings now has a `Remove savings` action for stolen/lost/unavailable money. This reduces total savings without adding monthly income or expense.
