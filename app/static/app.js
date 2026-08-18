/* Мини-приложение «Компас»: онбординг → тест → рекомендации.
   Ванильный JS без сборки — MVP крутится в вебвью MAX, лишний рантайм ни к чему.
   Прогресс живёт в localStorage: тест из 74 вопросов проходится за несколько заходов. */

const LS_KEY = 'kompas_state_v1';
const SCALE_LABELS = [
  'Совсем не про меня', 'Скорее не про меня', 'Как когда',
  'Скорее про меня', 'Точно про меня',
];
const INTEREST_LABELS = ['Совсем не интересно', 'Скорее не интересно', 'Так себе', 'Интересно', 'Очень интересно'];
const HOLLAND_TITLES = {
  investigative: 'Исследователь', artistic: 'Артист', social: 'Социальный',
  enterprising: 'Предприниматель', conventional: 'Конвенц.', realistic: 'Реалист',
};
// порядок осей радара по часовой стрелке, начиная сверху
const RADAR_ORDER = ['investigative', 'artistic', 'social', 'enterprising', 'conventional', 'realistic'];
const SOFTSKILL_TITLES = {
  teamwork: 'Работа в команде', leadership: 'Лидерство', creativity: 'Творческое мышление',
  analytical: 'Аналитика', resilience: 'Усидчивость',
};
const CATEGORY_GRADIENTS = {
  'технологии': 'var(--grad-blue)', 'наука': 'var(--grad-green)', 'творчество': 'var(--grad-pink)',
  'услуги': 'var(--grad-orange)', 'менеджмент': 'var(--grad-violet)',
  'медицина': 'var(--grad-green)', 'образование': 'var(--grad-violet)',
};
// Пропуск знаниевого вопроса. Не «нет ответа», а заведомо неверный индекс:
// иначе пропустивший сложные вопросы получил бы завышенный knowledge_score.
const SKIPPED = -1;

const view = document.getElementById('view');
const barTitle = document.getElementById('bar-title');
const barAction = document.getElementById('bar-action');
const barProgress = document.getElementById('bar-progress');

let Q = null;          // банк вопросов с бэкенда
let S = loadState();   // состояние прохождения
let questionShownAt = Date.now();

/* ---------- состояние ---------- */

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY));
    if (saved && saved.userId) return saved;
  } catch { /* битый localStorage — начинаем заново */ }
  return {
    userId: 'web_' + Math.random().toString(36).slice(2, 10),
    answers: {},
    lastResultId: null,
    schoolClass: '',
  };
}

function save() {
  localStorage.setItem(LS_KEY, JSON.stringify(S));
}

/* ---------- утилиты ---------- */

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body.slice(0, 300)}`);
  }
  return response.json();
}

function render(html, { title = 'Компас', progress = 0, action = null } = {}) {
  barTitle.textContent = title;
  // без правого действия заголовок центрируется — так в макете
  barTitle.parentElement.classList.toggle('split', !!action);
  barProgress.style.width = `${Math.round(progress * 100)}%`;
  barAction.classList.toggle('hidden', !action);
  if (action) {
    barAction.textContent = action.label;
    barAction.onclick = action.onClick;
  }
  view.innerHTML = html;
  view.scrollTop = 0;
  questionShownAt = Date.now();
}

const blockA = () => Q.block_a_interests;
const blockC = () => Q.block_c_softskills;
const subjectCodes = () => [...new Set(Q.block_b_subjects.map((q) => q.subject))];
const subjectQuestions = (code) => Q.block_b_subjects.filter((q) => q.subject === code);
const answeredCount = () => Object.keys(S.answers).length;
const totalCount = () => blockA().length + Q.block_b_subjects.length + blockC().length;
const isAnswered = (id) => S.answers[id] !== undefined;
// Бэкенд считает профиль и по части ответов, поэтому предварительный результат
// можно показать сразу после блока A — не заставляя пройти все 74 вопроса.
const canPreview = () => blockA().every((q) => isAnswered(q.id));

/* ---------- экран: онбординг ---------- */

function screenOnboarding() {
  const done = answeredCount();
  const total = totalCount();

  if (done > 0 && done < total) {
    render(`
      <div class="h2">Продолжим?</div>
      <div class="card pad" style="gap:14px">
        <div style="display:flex;align-items:baseline;justify-content:space-between">
          <div class="label">Прогресс теста</div>
          <div style="font-size:15px;font-weight:600;color:var(--accent)">${done} / ${total}</div>
        </div>
        <div class="prog"><i style="width:${(done / total) * 100}%"></i></div>
        <div class="t3">Ответы сохранены на этом устройстве — можно продолжить с того же места.</div>
      </div>
      <div class="btn" data-go="next">Продолжить</div>
      ${canPreview() ? '<div class="link" style="text-align:center" data-go="preview">Показать предварительный результат</div>' : ''}
      <div class="list">
        <div class="row" data-go="restart"><div style="font-size:16px;flex:1">Начать заново</div></div>
        <div class="sep"></div>
        <div class="row" data-go="history"><div style="font-size:16px;flex:1">История прохождений</div></div>
      </div>
    `, { progress: done / total });
    return;
  }

  render(`
    <div style="display:flex;flex-direction:column;gap:12px;padding-top:16px">
      <div style="width:64px;height:64px;border-radius:20px;background:var(--grad-blue);display:flex;align-items:center;justify-content:center">
        <svg width="30" height="30" viewBox="0 0 30 30" fill="none"><circle cx="15" cy="15" r="12" stroke="#fff" stroke-width="2"></circle><path d="M19.5 10.5l-3 6-6 3 3-6 6-3z" fill="#fff"></path></svg>
      </div>
      <div class="h1">Разберёмся, что тебе<br>реально интересно</div>
      <div style="font-size:16px;line-height:22px;color:var(--t3)">74 вопроса про интересы, школьные предметы и то, как ты работаешь с людьми. В конце — пять профессий с объяснением, почему именно они.</div>
    </div>
    <div class="list" style="gap:2px;overflow:hidden">
      ${[['A', `Интересы · ${blockA().length} вопросов`, '3 мин'],
         ['B', `Предметы · ${Q.block_b_subjects.length} вопроса`, 'по частям'],
         ['C', `Как ты работаешь · ${blockC().length}`, '2 мин']].map(([letter, text, time], i) => `
        ${i ? '<div class="sep inset"></div>' : ''}
        <div class="row">
          <div style="width:28px;height:28px;border-radius:9px;background:rgb(0 122 255 / .16);color:var(--accent);font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center">${letter}</div>
          <div style="font-size:15px;line-height:20px;color:var(--t2);flex:1">${text}</div>
          <div class="t4s">${time}</div>
        </div>`).join('')}
    </div>
    <div style="font-size:13px;line-height:18px;color:var(--t4)">Прогресс сохраняется — можно закрыть и вернуться позже.</div>
    <div class="bottom" style="display:flex;flex-direction:column;gap:8px">
      <div class="btn" data-go="next">Начать тест</div>
      <div class="link" style="text-align:center" data-go="teacher">Я педагог</div>
    </div>
  `, { progress: 0 });
}

/* ---------- экран: шкала 1–5 (блоки A и C) ---------- */

function screenScale(block) {
  const questions = block === 'a' ? blockA() : blockC();
  const index = questions.findIndex((q) => !isAnswered(q.id));
  if (index === -1) return next();

  const question = questions[index];
  const title = block === 'a' ? 'Интересы' : 'Как ты работаешь';

  render(`
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div class="t3">Блок ${block.toUpperCase()} · вопрос ${index + 1} из ${questions.length}</div>
      <div class="t4s">весь тест ${Math.round((answeredCount() / totalCount()) * 100)}%</div>
    </div>
    <div class="card" style="padding:20px 18px;display:flex;flex-direction:column;gap:24px">
      <div class="q">${esc(question.text)}</div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="scale" data-scale>
          ${[1, 2, 3, 4, 5].map((v) => `<div class="seg" data-value="${v}"><i></i></div>`).join('')}
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div class="t4s">совсем не про меня</div><div class="t4s">точно про меня</div>
        </div>
        <div class="scale-value" data-scale-value>&nbsp;</div>
      </div>
    </div>
    <div class="dots">
      ${questions.map((q, i) => `<i class="${i <= index ? 'on' : ''}"></i>`).join('')}
    </div>
    <div class="bottom" style="display:flex;gap:8px">
      <div class="btn sec" style="padding:0 20px" data-back>Назад</div>
      <div class="btn" style="flex:1" data-next disabled>Далее</div>
    </div>
  `, { title, progress: answeredCount() / totalCount() });

  let picked = null;
  view.querySelectorAll('.seg').forEach((seg) => {
    seg.onclick = () => {
      picked = Number(seg.dataset.value);
      view.querySelectorAll('.seg').forEach((s) => s.classList.toggle('on', s === seg));
      view.querySelector('[data-scale-value]').textContent = SCALE_LABELS[picked - 1];
      view.querySelector('[data-next]').removeAttribute('disabled');
    };
  });
  view.querySelector('[data-next]').onclick = () => {
    if (!picked) return;
    S.answers[question.id] = picked;
    save();
    next();
  };
  view.querySelector('[data-back]').onclick = () => {
    if (index > 0) delete S.answers[questions[index - 1].id];
    save();
    index > 0 ? screenScale(block) : screenOnboarding();
  };
}

/* ---------- экран: список предметов ---------- */

function screenSubjects() {
  const codes = subjectCodes();
  const status = codes.map((code) => {
    const questions = subjectQuestions(code);
    const done = questions.filter((q) => isAnswered(q.id)).length;
    return { code, title: Q.subject_titles[code], done, total: questions.length };
  });
  const remaining = status.filter((s) => s.done < s.total);
  const answeredB = status.reduce((sum, s) => sum + s.done, 0);
  const totalB = status.reduce((sum, s) => sum + s.total, 0);

  render(`
    <div style="display:flex;flex-direction:column;gap:10px">
      <div style="display:flex;align-items:baseline;justify-content:space-between">
        <div class="h3">${remaining.length ? `Осталось ${remaining.length} предмет${plural(remaining.length, '', 'а', 'ов')}` : 'Все предметы пройдены'}</div>
        <div style="font-size:15px;font-weight:600;color:var(--accent)">${answeredB} / ${totalB}</div>
      </div>
      <div class="prog"><i style="width:${(answeredB / totalB) * 100}%"></i></div>
      <div style="font-size:13px;line-height:18px;color:var(--t3)">Можно проходить по одному предмету и возвращаться — ответы сохраняются.</div>
    </div>
    <div class="list">
      ${status.map((s, i) => `
        ${i ? '<div class="sep inset"></div>' : ''}
        <div class="row" data-subject="${s.code}">
          ${s.done === s.total
            ? `<div style="width:28px;height:28px;border-radius:14px;background:var(--green);display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="14" height="11" viewBox="0 0 14 11" fill="none"><path d="M1 5.5L5 9.5L13 1.5" stroke="rgb(23 24 28)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path></svg></div>`
            : s.done
              ? `<div style="width:28px;height:28px;border-radius:14px;border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;flex:0 0 auto;font-size:12px;font-weight:600;color:var(--accent)">${s.done}</div>`
              : `<div style="width:28px;height:28px;border-radius:14px;border:2px solid rgb(255 255 255 / .12);flex:0 0 auto"></div>`}
          <div class="grow">
            <div class="h5">${esc(s.title)}</div>
            ${s.done === s.total
              ? '<div style="font-size:13px;color:var(--green)">Пройдено</div>'
              : s.done
                ? `<div class="prog xs" style="margin-top:6px"><i style="width:${(s.done / s.total) * 100}%"></i></div>`
                : `<div class="t3">${s.total} вопроса · 2 мин</div>`}
          </div>
          ${s.done === s.total ? '' : '<svg width="8" height="14" viewBox="0 0 8 14" fill="none"><path d="M1 1l6 6-6 6" stroke="rgb(255 255 255 / .28)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></svg>'}
        </div>`).join('')}
    </div>
    <div class="hint"><i></i><p>Правильные ответы не показываем во время теста — так результат честнее отражает уровень.</p></div>
    <div class="bottom" style="display:flex;flex-direction:column;gap:10px">
      <div class="btn" data-go="next">${remaining.length ? `Продолжить с предмета «${esc(remaining[0].title)}»` : 'Дальше'}</div>
      ${canPreview() && remaining.length ? '<div class="link" style="text-align:center" data-go="preview">Показать предварительный результат</div>' : ''}
    </div>
  `, { title: 'Предметы', progress: answeredCount() / totalCount() });

  view.querySelectorAll('[data-subject]').forEach((row) => {
    row.onclick = () => screenSubject(row.dataset.subject);
  });
}

const plural = (n, one, few, many) => {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

/* ---------- экран: вопрос по предмету ---------- */

function screenSubject(code) {
  const questions = subjectQuestions(code);
  const index = questions.findIndex((q) => !isAnswered(q.id));
  if (index === -1) return screenSubjects();

  const question = questions[index];
  const title = Q.subject_titles[code];
  const backTo = () => {
    if (index > 0) delete S.answers[questions[index - 1].id];
    save();
    index > 0 ? screenSubject(code) : screenSubjects();
  };

  if (question.type === 'interest') {
    render(`
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div class="t3">Вопрос ${index + 1} из ${questions.length}</div>
        <div class="t4s">${esc(title)}</div>
      </div>
      <div class="card" style="padding:20px 18px;display:flex;flex-direction:column;gap:24px">
        <div class="q">${esc(question.text)}</div>
        <div style="display:flex;flex-direction:column;gap:14px">
          <div class="scale">${[1, 2, 3, 4, 5].map((v) => `<div class="seg" data-value="${v}"><i></i></div>`).join('')}</div>
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div class="t4s">совсем нет</div><div class="t4s">очень</div>
          </div>
          <div class="scale-value" data-scale-value>&nbsp;</div>
        </div>
      </div>
      <div class="hint"><i></i><p>Это единственный вопрос про предмет, где важно твоё мнение, а не правильный ответ.</p></div>
      <div class="bottom" style="display:flex;gap:8px">
        <div class="btn sec" style="padding:0 20px" data-back>Назад</div>
        <div class="btn" style="flex:1" data-next disabled>Далее</div>
      </div>
    `, { title, progress: answeredCount() / totalCount() });

    let picked = null;
    view.querySelectorAll('.seg').forEach((seg) => {
      seg.onclick = () => {
        picked = Number(seg.dataset.value);
        view.querySelectorAll('.seg').forEach((s) => s.classList.toggle('on', s === seg));
        view.querySelector('[data-scale-value]').textContent = INTEREST_LABELS[picked - 1];
        view.querySelector('[data-next]').removeAttribute('disabled');
      };
    });
    view.querySelector('[data-next]').onclick = () => {
      S.answers[question.id] = picked;
      save();
      screenSubject(code);
    };
    view.querySelector('[data-back]').onclick = backTo;
    return;
  }

  render(`
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div class="t3">Вопрос ${index + 1} из ${questions.length}</div>
      <div class="t4s">${esc(question.topic || '')}</div>
    </div>
    <div class="q">${esc(question.text)}</div>
    <div style="display:flex;flex-direction:column;gap:10px" data-answers>
      ${question.options.map((option, i) => `
        <div class="ans" data-index="${i}">
          <div class="key">${'АБВГ'[i] || i + 1}</div>
          <div class="txt">${esc(option)}</div>
          <svg class="tick" width="16" height="12" viewBox="0 0 16 12" fill="none"><path d="M1 6l5 5 9-10" stroke="rgb(0 122 255)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path></svg>
        </div>`).join('')}
    </div>
    <div class="link" style="align-self:flex-start" data-skip>Не знаю — пропустить</div>
    <div class="bottom" style="display:flex;gap:8px">
      <div class="btn sec" style="padding:0 20px" data-back>Назад</div>
      <div class="btn" style="flex:1" data-next disabled>Далее</div>
    </div>
  `, { title, progress: answeredCount() / totalCount() });

  let picked = null;
  view.querySelectorAll('.ans').forEach((answer) => {
    answer.onclick = () => {
      picked = Number(answer.dataset.index);
      view.querySelectorAll('.ans').forEach((a) => a.classList.toggle('on', a === answer));
      view.querySelector('[data-next]').removeAttribute('disabled');
    };
  });
  const commit = (value) => {
    // время ответа копим для будущего антифрод-анализа, в скоринге оно не участвует
    S.answers[question.id] = {
      selected_index: value,
      time_spent_seconds: Math.round((Date.now() - questionShownAt) / 100) / 10,
    };
    save();
    screenSubject(code);
  };
  view.querySelector('[data-next]').onclick = () => picked !== null && commit(picked);
  view.querySelector('[data-skip]').onclick = () => commit(SKIPPED);
  view.querySelector('[data-back]').onclick = backTo;
}

/* ---------- экран: отправка и ожидание ИИ ---------- */

async function screenSubmit() {
  render(`
    <div style="display:flex;align-items:center;gap:10px">
      <div class="spinner"></div>
      <div style="font-size:15px;color:var(--t2);flex:1">Подбираем профессии…</div>
    </div>
    ${[1, .6, .35].map((opacity, i) => `
      <div class="card pad" style="gap:10px;opacity:${opacity}">
        <div class="sk live" style="height:22px;width:${96 - i * 8}px;animation-delay:${i * .15}s"></div>
        <div class="sk live" style="height:20px;width:${74 - i * 8}%;animation-delay:${i * .15 + .1}s"></div>
        <div class="sk live" style="animation-delay:${i * .15 + .2}s"></div>
      </div>`).join('')}
    <div style="font-size:13px;line-height:18px;color:var(--t4);text-align:center;padding-top:4px">Обычно занимает 5–10 секунд. Можно закрыть — результат сохранится.</div>
  `, { title: 'Результаты', progress: 1 });

  try {
    const data = await api('/api/tests/submit', {
      method: 'POST',
      body: JSON.stringify({
        max_user_id: S.userId,
        answers: S.answers,
        school_class: S.schoolClass || null,
      }),
    });
    S.lastResultId = data.test_result_id;
    save();
    screenResults(data.recommendations, data.computed_scores, data.fallback, data.progress);
  } catch (error) {
    screenError(error, screenSubmit);
  }
}

/* ---------- экран: результаты ---------- */

function radarSVG(interests) {
  const cx = 140, cy = 132, R = 96;
  const point = (i, ratio) => {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    return [cx + Math.cos(angle) * R * ratio, cy + Math.sin(angle) * R * ratio];
  };
  const ring = (ratio) => RADAR_ORDER.map((_, i) => point(i, ratio).map((n) => n.toFixed(1)).join(',')).join(' ');
  const values = RADAR_ORDER.map((key) => Math.max(0, Math.min(5, interests[key] ?? 0)) / 5);
  const shape = values.map((v, i) => point(i, v).map((n) => n.toFixed(1)).join(',')).join(' ');

  const labels = RADAR_ORDER.map((key, i) => {
    const [x, y] = point(i, 1.22);
    const percent = Math.round(((interests[key] ?? 0) / 5) * 100);
    return `<text x="${x.toFixed(0)}" y="${y.toFixed(0)}" text-anchor="middle" font-size="11" font-weight="600" fill="rgb(255 255 255 / .8)">${HOLLAND_TITLES[key]}</text>
            <text x="${x.toFixed(0)}" y="${(y + 12).toFixed(0)}" text-anchor="middle" font-size="11" fill="rgb(255 255 255 / .44)">${percent}</text>`;
  }).join('');

  return `<svg width="280" height="280" viewBox="0 0 280 280" role="img" aria-label="Профиль интересов">
    <polygon points="${ring(1)}" fill="rgb(255 255 255 / .04)" stroke="rgb(255 255 255 / .12)"></polygon>
    <polygon points="${ring(0.66)}" fill="none" stroke="rgb(255 255 255 / .06)"></polygon>
    <polygon points="${ring(0.33)}" fill="none" stroke="rgb(255 255 255 / .06)"></polygon>
    ${RADAR_ORDER.map((_, i) => {
      const [x, y] = point(i, 1);
      return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgb(255 255 255 / .06)"></line>`;
    }).join('')}
    <polygon points="${shape}" fill="rgb(0 122 255 / .28)" stroke="rgb(0 122 255)" stroke-width="2" stroke-linejoin="round"></polygon>
    ${values.map((v, i) => {
      const [x, y] = point(i, v);
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="rgb(0 122 255)"></circle>`;
    }).join('')}
    ${labels}
  </svg>`;
}

function screenResults(professions, scores, fallback, progress = null) {
  const [top, ...rest] = professions;
  const softskills = Object.entries(scores.softskills || {});

  render(`
    <div class="hero">
      <div class="hero-top" style="background:${CATEGORY_GRADIENTS[top.category] || 'var(--grad-blue)'}">
        <div class="label">Лучшее совпадение · ${esc(top.category)}</div>
        <div class="h1">${esc(top.name)}</div>
      </div>
      <div style="padding:16px 18px;display:flex;flex-direction:column;gap:14px">
        <div class="body-text">${esc(top.reasoning)}</div>
        ${top.subjects_to_improve?.length ? `
          <div style="display:flex;flex-direction:column;gap:8px">
            <div class="label" style="letter-spacing:.5px">Стоит подтянуть</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px">${top.subjects_to_improve.map((s) => `<div class="tag">${esc(s)}</div>`).join('')}</div>
          </div>` : ''}
      </div>
    </div>

    ${Object.keys(scores.interests || {}).length ? `
      <div class="card pad">
        <div class="h4">Профиль интересов</div>
        <div style="display:flex;justify-content:center">${radarSVG(scores.interests)}</div>
      </div>` : ''}

    ${rest.length ? `
      <div class="list">
        <div class="section-label">Ещё подходят</div>
        ${rest.map((p, i) => `
          ${i ? '<div class="sep" style="margin-left:36px"></div>' : ''}
          <div class="row" style="padding:12px 16px;align-items:flex-start" data-profession="${i}">
            <div class="bar-strip" style="background:${CATEGORY_GRADIENTS[p.category] || 'var(--grad-violet)'}"></div>
            <div class="grow">
              <div class="h5">${esc(p.name)}</div>
              <div class="t3">${esc(p.category)}</div>
              <div class="body-text hidden" style="padding-top:6px" data-reasoning>${esc(p.reasoning)}</div>
            </div>
          </div>`).join('')}
      </div>` : ''}

    ${softskills.length ? `
      <div class="card pad">
        <div class="h4">Как ты работаешь</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          ${softskills.map(([key, value]) => `
            <div class="barline">
              <div class="name">${SOFTSKILL_TITLES[key] || key}</div>
              <div class="track"><i style="width:${(value / 5) * 100}%"></i></div>
              <div class="val">${value.toFixed(1)}</div>
            </div>`).join('')}
        </div>
      </div>` : ''}

    ${progress && !progress.is_complete ? `
      <div class="hint"><i style="background:var(--orange)"></i><p>Это предварительный результат — пройдено ${progress.answered} из ${progress.total} вопросов. Чем больше ответов, тем точнее подборка.</p></div>
    ` : ''}

    ${fallback ? `
      <div class="hint"><i style="background:var(--orange)"></i><p>Рекомендации подобраны упрощённым алгоритмом — ИИ был недоступен. Результаты теста сохранены, можно обновить подборку позже.</p></div>
    ` : ''}

    <div style="display:flex;flex-direction:column;gap:8px">
      ${progress && !progress.is_complete ? '<div class="btn" data-go="next">Продолжить тест</div>' : ''}
      <div class="btn sec" data-go="history">История прохождений</div>
      <div class="btn sec" data-go="restart">Пройти тест заново</div>
    </div>
  `, { title: 'Результаты', progress: 1 });

  view.querySelectorAll('[data-profession]').forEach((row) => {
    row.onclick = () => row.querySelector('[data-reasoning]').classList.toggle('hidden');
  });
}

/* ---------- экран: история ---------- */

async function screenHistory() {
  render('<div style="display:flex;align-items:center;gap:10px"><div class="spinner"></div><div class="t3">Загружаем историю…</div></div>',
    { title: 'История', progress: 1 });
  let data;
  try {
    data = await api(`/api/users/${encodeURIComponent(S.userId)}/history`);
  } catch (error) {
    if (!String(error).includes('404')) return screenError(error, screenHistory);
    data = { attempts: 0, history: [] };
  }

  render(`
    ${data.attempts === 0 ? '<div class="hint"><i></i><p>Пока нет ни одного завершённого прохождения.</p></div>' : `
      <div class="t3">Всего прохождений: ${data.attempts}. Видно, как меняются интересы со временем.</div>
      <div class="list">
        ${data.history.map((item, i) => `
          ${i ? '<div class="sep"></div>' : ''}
          <div class="row" style="align-items:flex-start">
            <div class="grow">
              <div class="h5">${new Date(item.completed_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })}</div>
              <div class="t3">${item.professions.slice(0, 3).map((p) => esc(p.name)).join(' · ') || '—'}</div>
              <div style="display:flex;flex-wrap:wrap;gap:6px;padding-top:8px">
                ${item.top_interests.map((key) => `<div class="tag">${HOLLAND_TITLES[key] || key}</div>`).join('')}
              </div>
              ${item.fallback ? '<div style="font-size:13px;color:var(--orange);padding-top:6px">упрощённый алгоритм</div>' : ''}
            </div>
          </div>`).join('')}
      </div>`}
    <div class="btn bottom" data-go="home">На главный экран</div>
  `, { title: 'История', progress: 1 });
}

/* ---------- экран: ошибка ---------- */

function screenError(error, retry) {
  console.error(error);
  render(`
    <div class="body center" style="gap:20px;padding-top:60px">
      <div style="width:64px;height:64px;border-radius:20px;background:var(--fill);display:flex;align-items:center;justify-content:center">
        <svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4v14" stroke="rgb(255 159 10)" stroke-width="2.4" stroke-linecap="round"></path><circle cx="14" cy="23" r="1.6" fill="rgb(255 159 10)"></circle></svg>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;max-width:300px">
        <div class="h2">Не получилось загрузить</div>
        <div style="font-size:15px;line-height:21px;color:var(--t3)">Похоже, пропала связь. Ответы на тест сохранены — рекомендации подберём, как только интернет вернётся.</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;width:100%">
        <div class="btn" data-retry>Попробовать снова</div>
        <div class="btn sec" data-go="home">На главный экран</div>
      </div>
    </div>
  `, { title: 'Ошибка' });
  view.querySelector('[data-retry]').onclick = retry;
}

/* ---------- переходы ---------- */

function next() {
  if (blockA().some((q) => !isAnswered(q.id))) return screenScale('a');
  if (Q.block_b_subjects.some((q) => !isAnswered(q.id))) return screenSubjects();
  if (blockC().some((q) => !isAnswered(q.id))) return screenScale('c');
  return screenSubmit();
}

view.addEventListener('click', (event) => {
  const target = event.target.closest('[data-go]');
  if (!target) return;
  const actions = {
    next,
    preview: screenSubmit,
    home: screenOnboarding,
    history: screenHistory,
    teacher: () => { window.location.href = '/static/teacher.html'; },
    restart: () => {
      if (!confirm('Все ответы будут удалены. Начать заново?')) return;
      S.answers = {};
      save();
      screenOnboarding();
    },
  };
  actions[target.dataset.go]?.();
});

/* ---------- старт ---------- */

(async function start() {
  try {
    Q = await api('/api/tests/questions');
  } catch (error) {
    return screenError(error, start);
  }
  screenOnboarding();
})();
