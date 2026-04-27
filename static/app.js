function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModals() {
  document.querySelectorAll('.modal.open').forEach((modal) => {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  });
}

function filterEntrySections(type, preferredSectionId = '') {
  const select = document.getElementById('modalSectionSelect');
  const entryType = document.getElementById('modalEntryType');
  const sourceField = document.getElementById('sourceField');
  const title = document.getElementById('entryModalTitle');
  const submit = document.getElementById('modalSubmitButton');
  if (!select || !entryType) return;

  entryType.value = type;
  if (title) title.textContent = type === 'income' ? 'Add income' : 'Add expense';
  if (submit) submit.textContent = type === 'income' ? 'Save income' : 'Save expense';
  if (sourceField) sourceField.style.display = type === 'income' ? 'none' : 'grid';

  const options = [...select.options];
  options.forEach((option) => {
    const shouldShow = option.dataset.type === type;
    option.hidden = !shouldShow;
    option.disabled = !shouldShow;
  });

  const preferred = options.find((option) => option.value === preferredSectionId && !option.disabled);
  const first = options.find((option) => !option.disabled);
  if (preferred) select.value = preferred.value;
  else if (first) select.value = first.value;
}

function filterOptionalSections(type) {
  const select = document.getElementById('optionalSectionSelect');
  if (!select) return;
  const options = [...select.options];
  options.forEach((option) => {
    const shouldShow = option.dataset.type === type;
    option.hidden = !shouldShow;
    option.disabled = !shouldShow;
  });
  const first = options.find((option) => !option.disabled);
  if (first) select.value = first.value;
}

function initModals() {
  document.querySelectorAll('[data-close-modal]').forEach((btn) => btn.addEventListener('click', closeModals));
  document.querySelectorAll('.modal').forEach((modal) => {
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModals();
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModals();
  });

  document.querySelectorAll('[data-open-entry]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.entryType || 'expense';
      filterEntrySections(type, btn.dataset.sectionId || '');
      openModal('entryModal');
    });
  });

  document.querySelectorAll('[data-open-section]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.sectionKind || 'expense';
      filterOptionalSections(type);
      openModal('sectionModal');
    });
  });

  document.querySelectorAll('[data-section-filter]').forEach((btn) => {
    btn.addEventListener('click', () => filterOptionalSections(btn.dataset.sectionFilter));
  });

  document.querySelectorAll('[data-open-savings]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.openSavings;
      const actionInput = document.getElementById('savingsAction');
      const title = document.getElementById('savingsModalTitle');
      const sectionField = document.getElementById('savingsSectionField');
      if (actionInput) actionInput.value = action;
      if (sectionField) sectionField.style.display = action === 'spend_from_savings' ? 'grid' : 'none';
      if (title) {
        title.textContent = {
          add_from_monthly: 'Add money to savings',
          withdraw_to_month: 'Withdraw from savings',
          spend_from_savings: 'Spend from savings',
          remove_from_savings: 'Remove savings'
        }[action] || 'Savings action';
      }
      openModal('savingsModal');
    });
  });
}

function initDarkMode() {
  const saved = localStorage.getItem('budgify-theme');
  if (saved === 'dark') document.body.classList.add('dark');
  const btn = document.getElementById('darkModeToggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    document.body.classList.toggle('dark');
    localStorage.setItem('budgify-theme', document.body.classList.contains('dark') ? 'dark' : 'light');
  });
}

function initCharts() {
  if (!window.Chart) return;

  const monthly = document.getElementById('monthlyChart');
  if (monthly) {
    const data = JSON.parse(monthly.dataset.chart || '{}');
    new Chart(monthly, {
      type: 'bar',
      data: {
        labels: data.months || [],
        datasets: [
          { label: 'Income', data: data.income || [] },
          { label: 'Expenses', data: data.expenses || [] },
          { label: 'Remaining', data: data.remaining || [], type: 'line' }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
  }

  const priority = document.getElementById('priorityChart');
  if (priority) {
    const data = JSON.parse(priority.dataset.chart || '{}');
    new Chart(priority, {
      type: 'doughnut',
      data: {
        labels: Object.keys(data),
        datasets: [{ data: Object.values(data) }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
  }

  const savings = document.getElementById('savingsChart');
  if (savings) {
    const data = JSON.parse(savings.dataset.chart || '{}');
    new Chart(savings, {
      type: 'line',
      data: {
        labels: data.months || [],
        datasets: [{ label: 'Saved', data: data.saved || [], tension: 0.3 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initDarkMode();
  initModals();
  initCharts();
});
