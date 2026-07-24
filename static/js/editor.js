// ── Character counter ──────────────────────────────────────────────────────────
const codeInput  = document.getElementById('code-input');
const charCount  = document.getElementById('char-count');
const MAX_CHARS  = 20000;

function updateCount() {
  const len = codeInput.value.length;
  charCount.textContent = `${len.toLocaleString()} / ${MAX_CHARS.toLocaleString()}`;
  charCount.style.color = len > MAX_CHARS * 0.9
    ? 'var(--warn)'
    : len >= MAX_CHARS
      ? 'var(--err)'
      : 'var(--muted)';
}
codeInput.addEventListener('input', updateCount);
updateCount();

// ── File upload label ──────────────────────────────────────────────────────────
const fileInput  = document.getElementById('file-input');
const fileNameEl = document.getElementById('file-name');

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (file) {
    fileNameEl.textContent = file.name;
    // Clear the textarea so the file takes priority
    codeInput.value = '';
    updateCount();
  } else {
    fileNameEl.textContent = '';
  }
});

// ── Scan-line + spinner on submit ──────────────────────────────────────────────
const form       = document.getElementById('analyze-form');
const analyzeBtn = document.getElementById('analyze-btn');
const btnText    = analyzeBtn.querySelector('.btn-text');
const btnSpinner = analyzeBtn.querySelector('.btn-spinner');
const scanLine   = document.getElementById('scan-line');

form.addEventListener('submit', () => {
  // Show spinner
  btnText.hidden   = true;
  btnSpinner.hidden = false;
  analyzeBtn.disabled = true;

  // Start scan-line animation
  scanLine.classList.add('running');
});

// ── Tab key inserts spaces in editor ──────────────────────────────────────────
codeInput.addEventListener('keydown', e => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const start = codeInput.selectionStart;
    const end   = codeInput.selectionEnd;
    codeInput.value =
      codeInput.value.substring(0, start) +
      '  ' +
      codeInput.value.substring(end);
    codeInput.selectionStart = codeInput.selectionEnd = start + 2;
    updateCount();
  }
});
