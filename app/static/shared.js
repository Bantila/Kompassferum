/* Утилиты, общие для мини-приложения ученика и кабинета педагога. */

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
));

function bars(entries, max, format) {
  return entries.map(([name, value]) => `
    <div class="barline">
      <div class="name">${esc(name)}</div>
      <div class="track"><i style="width:${Math.round((value / max) * 100)}%"></i></div>
      <div class="val">${format(value)}</div>
    </div>`).join('');
}

/* Запрос к API с токеном. Ошибку отдаёт с человекочитаемым detail с бэкенда
   и полем status — чтобы вызывающий мог отличить 401 от прочих сбоев. */
async function apiFetch(path, options = {}, token = null) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const body = await response.text();
  if (!response.ok) {
    let detail = body.slice(0, 300);
    try { detail = JSON.parse(body).detail || detail; } catch { /* не JSON — оставляем текст */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return body ? JSON.parse(body) : null;
}
