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
const ERROR_TITLES = {
  calculation: 'Вычислительные', sign: 'Знак', unit: 'Единицы измерения',
  attention: 'Невнимательность', conceptual: 'Понимание темы',
  methodology: 'Порядок решения', incomplete: 'Неполный ответ',
};
// Пропуск знаниевого вопроса. Не «нет ответа», а заведомо неверный индекс:
// иначе пропустивший сложные вопросы получил бы завышенный knowledge_score.
const SKIPPED = -1;

const view = document.getElementById('view');
const barTitle = document.getElementById('bar-title');
const barAction = document.getElementById('bar-action');
const barProgress = document.getElementById('bar-progress');
const tabsBar = document.getElementById('tabs');

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
    classId: null,
    fullName: '',
    token: null,
    guestMode: false,
  };
}

function save() {
  localStorage.setItem(LS_KEY, JSON.stringify(S));
}

/* ---------- утилиты ---------- */

const api = (path, options = {}) => apiFetch(path, options, S.token);

/* Профиль с сервера в локальное состояние. */
function applyProfile(profile) {
  S.userId = profile.max_user_id;
  S.fullName = profile.full_name || '';
  S.classId = profile.class_id || null;
  S.schoolClass = profile.school_class || '';
  S.role = profile.role;
  S.guestMode = false;
  save();
}

/* tab — какую вкладку подсветить внизу. Не передан (вход, вопросы теста) —
   панель прячется, чтобы во время прохождения ничто не отвлекало. */
function render(html, { title = 'Компас', progress = 0, action = null, tab = null } = {}) {
  barTitle.textContent = title;
  // без правого действия заголовок центрируется — так в макете
  barTitle.parentElement.classList.toggle('split', !!action);
  barProgress.style.width = `${Math.round(progress * 100)}%`;
  barAction.classList.toggle('hidden', !action);
  if (action) {
    barAction.textContent = action.label;
    barAction.onclick = action.onClick;
  }
  tabsBar.classList.toggle('hidden', !tab);
  tabsBar.querySelectorAll('[data-tab]').forEach((el) => {
    el.classList.toggle('on', el.dataset.tab === tab);
  });
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
// названия предметов приходят с бэкенда вместе с банком вопросов
const subjectTitle = (code) => Q?.subject_titles?.[code] || code;
// Бэкенд считает профиль и по части ответов, поэтому предварительный результат
// можно показать сразу после блока A — не заставляя пройти все 74 вопроса.
const canPreview = () => blockA().every((q) => isAnswered(q.id));

/* ---------- экраны входа ---------- */

const LOGO_TILE = `
  <div style="width:64px;height:64px;border-radius:20px;background:var(--grad-blue);display:flex;align-items:center;justify-content:center">
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none"><circle cx="15" cy="15" r="12" stroke="#fff" stroke-width="2"></circle><path d="M19.5 10.5l-3 6-6 3 3-6 6-3z" fill="#fff"></path></svg>
  </div>`;

/* Приветствие: регистрация, вход или прохождение без аккаунта. */
function screenWelcome() {
  render(`
    <div style="display:flex;flex-direction:column;gap:12px;padding-top:16px">
      ${LOGO_TILE}
      <div class="h1">Компас</div>
      <div style="font-size:16px;line-height:22px;color:var(--t3)">Тест на 74 вопроса покажет, какие профессии тебе подходят и какие предметы для них стоит подтянуть. Аккаунт нужен, чтобы прогресс сохранялся и учитель видел твой класс.</div>
    </div>
    <div class="bottom" style="display:flex;flex-direction:column;gap:8px">
      <div class="btn" data-go="register">Создать аккаунт</div>
      <div class="btn sec" data-go="login">У меня уже есть аккаунт</div>
      <div class="link" style="text-align:center" data-go="guest">Пройти тест без аккаунта</div>
    </div>
  `, { progress: 0 });
}

/* Общая обвязка формы: собирает значения полей, шлёт запрос, показывает ошибку. */
function formScreen({ title, subtitle, fields, submitLabel, footer, onSubmit }) {
  render(`
    <div style="display:flex;flex-direction:column;gap:12px;padding-top:16px">
      ${LOGO_TILE}
      <div class="h1">${title}</div>
      ${subtitle ? `<div style="font-size:16px;line-height:22px;color:var(--t3)">${subtitle}</div>` : ''}
    </div>
    <div class="card pad" style="gap:12px">
      ${fields.map((f) => `<input id="f-${f.name}" class="field" placeholder="${esc(f.placeholder)}"
        type="${f.type || 'text'}" maxlength="${f.maxlength || 255}"
        autocomplete="${f.autocomplete || 'off'}" style="${f.style || ''}">`).join('')}
      <div id="form-status" class="t3" style="min-height:18px"></div>
    </div>
    <div class="bottom" style="display:flex;flex-direction:column;gap:8px">
      <div class="btn" id="form-submit">${submitLabel}</div>
      ${footer || ''}
    </div>
  `, { progress: 0 });

  const status = view.querySelector('#form-status');
  const submit = view.querySelector('#form-submit');
  const inputs = fields.map((f) => view.querySelector(`#f-${f.name}`));
  inputs[0]?.focus();

  const run = async () => {
    const values = Object.fromEntries(fields.map((f, i) => [f.name, inputs[i].value.trim()]));
    const missing = fields.find((f) => !f.optional && !values[f.name]);
    if (missing) {
      status.style.color = 'var(--orange)';
      status.textContent = `Заполни поле «${missing.placeholder}».`;
      return;
    }
    const label = submit.textContent;
    submit.textContent = 'Секунду…';
    status.textContent = '';
    try {
      await onSubmit(values);
    } catch (error) {
      submit.textContent = label;
      status.style.color = 'var(--orange)';
      status.textContent = error.message || 'Что-то пошло не так — попробуй ещё раз.';
    }
  };

  submit.onclick = run;
  // именно addEventListener, а не el.onkeydown = ...: обработчик-стрелка вернул бы
  // false на любой клавише кроме Enter, а false из onkeydown отменяет ввод символа —
  // поле выглядело бы «залипшим»: курсор мигает, но ничего не печатается и не вставляется
  inputs.forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
  });
}

function screenRegister() {
  formScreen({
    title: 'Создать аккаунт',
    subtitle: 'Код класса можно ввести сразу или позже — он нужен, чтобы попасть в сводку учителя.',
    submitLabel: 'Зарегистрироваться',
    footer: '<div class="link" style="text-align:center" data-go="login">У меня уже есть аккаунт</div>',
    fields: [
      { name: 'full_name', placeholder: 'Имя и фамилия', autocomplete: 'name' },
      { name: 'email', placeholder: 'Почта', type: 'email', autocomplete: 'email' },
      { name: 'password', placeholder: 'Пароль (минимум 6 символов)', type: 'password', autocomplete: 'new-password' },
      { name: 'join_code', placeholder: 'Код класса (необязательно)', optional: true, maxlength: 8,
        style: 'text-transform:uppercase;letter-spacing:2px' },
    ],
    onSubmit: async (v) => {
      const data = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          full_name: v.full_name,
          email: v.email,
          password: v.password,
          join_code: v.join_code ? v.join_code.toUpperCase() : null,
          // если человек уже отвечал гостем — прогресс переедет в новый аккаунт
          guest_max_user_id: S.guestMode ? S.userId : null,
        }),
      });
      S.token = data.access_token;
      applyProfile(data.user);
      screenOnboarding();
    },
  });
}

function screenLogin() {
  formScreen({
    title: 'Вход',
    submitLabel: 'Войти',
    footer: '<div class="link" style="text-align:center" data-go="register">Создать аккаунт</div>',
    fields: [
      { name: 'email', placeholder: 'Почта', type: 'email', autocomplete: 'email' },
      { name: 'password', placeholder: 'Пароль', type: 'password', autocomplete: 'current-password' },
    ],
    onSubmit: async (v) => {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: v.email, password: v.password }),
      });
      S.token = data.access_token;
      applyProfile(data.user);
      screenOnboarding();
    },
  });
}

/* Вступление в класс по коду — для тех, кто зарегистрировался без него. */
function screenJoinClass() {
  formScreen({
    title: 'Код класса',
    subtitle: 'Код даёт учитель — 6 символов. С ним ты попадёшь в сводку своего класса.',
    submitLabel: 'Вступить',
    footer: '<div class="link" style="text-align:center" data-go="home">Позже</div>',
    fields: [
      { name: 'join_code', placeholder: 'Например: AB12CD', maxlength: 8,
        style: 'text-transform:uppercase;font-size:22px;text-align:center;letter-spacing:4px;font-weight:600' },
    ],
    onSubmit: async (v) => {
      const data = await api('/api/classes/join', {
        method: 'POST',
        body: JSON.stringify({ join_code: v.join_code.toUpperCase() }),
      });
      S.classId = data.class_id;
      S.schoolClass = data.class_name;
      save();
      screenOnboarding();
    },
  });
}

/* ---------- экран: онбординг ---------- */

/* Карточка уровня и серии — визитка прогресса, как на главном экране AI-Atlas. */
function xpCard(p) {
  if (!p) return '';
  return `
    <div class="xp-card">
      <div class="xp-head">
        <div class="level-ring">${p.level}</div>
        <div style="flex:1">
          <div class="h5">Уровень ${p.level}</div>
          <div class="t3">${p.xp} XP · до следующего ${p.xp_to_next}</div>
        </div>
        ${p.streak_days ? `<div class="streak">🔥 ${p.streak_days} ${plural(p.streak_days, 'день', 'дня', 'дней')}</div>` : ''}
      </div>
      <div class="prog"><i style="width:${(p.xp_in_level / p.xp_per_level) * 100}%"></i></div>
      ${p.total_tasks ? `<div class="t3">Решено задач: ${p.total_tasks} · точность ${Math.round(p.accuracy * 100)}%</div>` : ''}
    </div>`;
}

/* Вкладка «Главная» — одно понятное действие на текущий момент. */
async function screenOnboarding() {
  const done = answeredCount();
  const total = totalCount();
  const testDone = done >= total;
  const started = done > 0;

  // главное действие зависит от того, где ученик остановился
  const [actionLabel, actionGo, statusText] = !started
    ? ['Пройти тест', 'next', 'Тест из 74 вопросов покажет подходящие профессии и предметы, которые стоит подтянуть.']
    : testDone
      ? ['Тренироваться', 'practice', 'Тест пройден. Теперь подтягивай предметы, которых не хватает твоим профессиям.']
      : ['Продолжить тест', 'next', 'Ответы сохранены — можно продолжить с того же места.'];

  // прогресс необязателен: без него главная просто покажется без карточки уровня
  let progress = null;
  if (S.token) {
    try { progress = await api('/api/practice/progress'); } catch { /* не критично */ }
  }

  render(`
    <div class="h2">${S.fullName ? `Привет, ${esc(S.fullName.split(' ')[0])}` : 'Привет'}</div>

    ${progress && progress.total_tasks ? xpCard(progress) : ''}

    <div class="card pad" style="gap:14px">
      <div style="display:flex;align-items:baseline;justify-content:space-between">
        <div class="label">Тест «Компас»</div>
        <div style="font-size:15px;font-weight:600;color:${testDone ? 'var(--green)' : 'var(--accent)'}">${done} / ${total}</div>
      </div>
      <div class="prog"><i style="width:${(done / total) * 100}%;${testDone ? 'background:var(--green)' : ''}"></i></div>
      <div class="t3">${statusText}</div>
      <div class="btn" data-go="${actionGo}">${actionLabel}</div>
      ${!testDone && canPreview() ? '<div class="link" style="text-align:center" data-go="preview">Посмотреть предварительный результат</div>' : ''}
    </div>

    ${testDone ? `
      <div class="list">
        <div class="row" data-go="careers"><div class="grow"><div class="h5">Мои профессии</div><div class="t3">Кто тебе подходит и почему</div></div></div>
        <div class="sep"></div>
        <div class="row" data-go="practice"><div class="grow"><div class="h5">Тренажёр</div><div class="t3">Задачи по предметам, которые нужно подтянуть</div></div></div>
      </div>` : `
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
      </div>`}

    ${!S.token ? '<div class="hint"><i style="background:var(--orange)"></i><p>Ты без аккаунта — прогресс хранится только в этом браузере. Создай аккаунт во вкладке «Профиль», чтобы он не потерялся.</p></div>' : ''}
  `, { progress: done / total, tab: 'home' });
}

/* ---------- вкладка: тренажёр задач ---------- */

let pack = { tasks: [], index: 0, correct: 0, reason: '' };

/* Стартовый экран вкладки: задания от учителя + свободная тренировка. */
async function screenPractice() {
  if (!S.token) return screenNeedAccount('тренажёр');

  render('<div style="display:flex;align-items:center;gap:10px"><div class="spinner"></div><div class="t3">Загружаем…</div></div>',
    { title: 'Задачи', tab: 'practice' });

  let assignments = [];
  if (S.classId) {
    try { assignments = await api('/api/classes/my-assignments'); } catch { /* необязательно */ }
  }

  render(`
    ${assignments.length ? `
      <div class="list">
        <div class="section-label">Задания от учителя</div>
        ${assignments.map((a, i) => `
          ${i ? '<div class="sep"></div>' : ''}
          <div class="row" data-assignment="${a.id}" style="align-items:flex-start">
            <div class="grow">
              <div class="h5">${esc(a.title)}</div>
              <div class="t3">${a.size} ${plural(a.size, 'задача', 'задачи', 'задач')}${a.difficulty ? ` · ${esc(a.difficulty)}` : ''}${a.due_date ? ` · до ${new Date(a.due_date).toLocaleDateString('ru-RU')}` : ''}</div>
            </div>
          </div>`).join('')}
      </div>` : ''}

    <div class="card pad" style="gap:12px">
      <div class="h4">Свободная тренировка</div>
      <div class="t3">Пять задач по предметам, которые нужны твоим профессиям.</div>
      <div class="btn" id="free-pack">Начать</div>
    </div>
  `, { title: 'Задачи', tab: 'practice' });

  view.querySelector('#free-pack').onclick = () => startPack('/api/practice/pack?size=5');
  view.querySelectorAll('[data-assignment]').forEach((row) => {
    const a = assignments.find((x) => x.id === row.dataset.assignment);
    row.onclick = () => {
      const params = new URLSearchParams({ size: a.size });
      if (a.subjects.length === 1) params.set('subject', a.subjects[0]);
      if (a.difficulty) params.set('difficulty', a.difficulty);
      startPack(`/api/practice/pack?${params}`, a.title);
    };
  });
}

async function startPack(url, title = '') {
  render('<div style="display:flex;align-items:center;gap:10px"><div class="spinner"></div><div class="t3">Собираем задачи…</div></div>',
    { title: 'Задачи', tab: 'practice' });
  try {
    const data = await api(url);
    pack = { tasks: data.tasks, index: 0, correct: 0, reason: title || data.reason };
  } catch (error) {
    return screenError(error, screenPractice);
  }
  screenTask();
}

function screenTask() {
  const task = pack.tasks[pack.index];
  if (!task) return screenPackDone();

  render(`
    <div style="display:flex;align-items:baseline;justify-content:space-between">
      <div class="label">${esc(subjectTitle(task.subject))} · ${esc(task.topic)}</div>
      <div class="t3">${pack.index + 1} из ${pack.tasks.length}</div>
    </div>
    <div class="prog xs"><i style="width:${(pack.index / pack.tasks.length) * 100}%"></i></div>

    <div class="card pad" style="gap:16px">
      <div class="task-q">${esc(task.question)}</div>
      <input id="answer" class="field" placeholder="Твой ответ" autocomplete="off">
      ${task.hint ? `<div class="link" id="hint-toggle">Показать подсказку</div>
        <div class="t3 hidden" id="hint">${esc(task.hint)}</div>` : ''}
    </div>

    <div class="bottom" style="display:flex;flex-direction:column;gap:8px">
      <div class="btn" id="check">Проверить</div>
      <div class="link" style="text-align:center" id="skip">Пропустить</div>
    </div>
  `, { title: 'Задачи', tab: 'practice' });

  const input = view.querySelector('#answer');
  const check = view.querySelector('#check');
  input.focus();

  const submit = async () => {
    const answer = input.value.trim();
    if (!answer) { input.focus(); return; }
    check.textContent = 'Проверяем…';
    try {
      const verdict = await api('/api/practice/answer', {
        method: 'POST',
        body: JSON.stringify({ task_id: task.id, answer }),
      });
      if (verdict.is_correct) pack.correct += 1;
      screenVerdict(task, answer, verdict);
    } catch (error) {
      check.textContent = 'Проверить';
      screenError(error, screenTask);
    }
  };

  check.onclick = submit;
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  view.querySelector('#skip').onclick = () => { pack.index += 1; screenTask(); };
  const toggle = view.querySelector('#hint-toggle');
  if (toggle) toggle.onclick = () => view.querySelector('#hint').classList.toggle('hidden');
}

/* Разбор ответа: верно/ошибка, тип ошибки и объяснение от ИИ. */
function screenVerdict(task, answer, verdict) {
  const ok = verdict.is_correct;
  render(`
    <div class="verdict ${ok ? 'ok' : 'err'}">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
        <div class="head">${ok ? 'Верно!' : esc(verdict.error_label)}</div>
        ${verdict.xp_earned ? `<div class="streak">+${verdict.xp_earned} XP</div>` : ''}
      </div>
      ${ok ? '' : `<div class="body-text">Твой ответ: <b>${esc(answer)}</b> · правильный: <b>${esc(verdict.correct_answer)}</b></div>`}
      <div class="body-text">${esc(verdict.recommendation)}</div>
    </div>

    ${verdict.level_up ? `
      <div class="card pad center" style="gap:6px">
        <div class="level-ring" style="width:56px;height:56px;border-radius:28px">${verdict.level}</div>
        <div class="h4">Новый уровень!</div>
        <div class="t3">Ты добрался до ${verdict.level} уровня — так держать.</div>
      </div>` : ''}

    ${verdict.new_achievements?.length ? `
      <div class="card pad">
        <div class="h4">${verdict.new_achievements.length > 1 ? 'Новые достижения' : 'Новое достижение'}</div>
        <div class="badges">
          ${verdict.new_achievements.map((a) => `
            <div class="badge"><div class="ico">${a.icon}</div><div class="nm">${esc(a.title)}</div></div>`).join('')}
        </div>
      </div>` : ''}

    ${verdict.ai_explanation ? `
      <div class="card pad" style="gap:8px">
        <div class="label">Разбор от ИИ</div>
        <div class="body-text">${esc(verdict.ai_explanation)}</div>
      </div>` : ''}

    ${!ok && verdict.explanation ? `
      <div class="card pad" style="gap:8px">
        <div class="label">Как решать</div>
        <div class="body-text">${esc(verdict.explanation)}</div>
      </div>` : ''}

    <div class="bottom"><div class="btn" id="next-task">
      ${pack.index + 1 < pack.tasks.length ? 'Следующая задача' : 'Завершить'}
    </div></div>
  `, { title: 'Разбор', tab: 'practice' });

  view.querySelector('#next-task').onclick = () => { pack.index += 1; screenTask(); };
}

async function screenPackDone() {
  const total = pack.tasks.length;
  let stats = null;
  try { stats = await api('/api/practice/stats'); } catch { /* статистика необязательна */ }

  render(`
    <div class="card pad center" style="gap:10px;padding:24px 16px">
      <div class="h1" style="color:var(--accent)">${pack.correct} из ${total}</div>
      <div class="t3">${pack.correct === total ? 'Отличная работа — весь пак без ошибок!' : 'Ошибки разобраны — в следующий раз будет легче.'}</div>
    </div>

    ${stats && stats.by_subject.length ? `
      <div class="card pad">
        <div class="h4">Точность по предметам</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          ${bars(stats.by_subject.map((s) => [subjectTitle(s.subject), s.accuracy * 5]), 5,
            (v) => `${Math.round((v / 5) * 100)}%`)}
        </div>
        <div class="t4s">Всего решено задач: ${stats.total_answered}</div>
      </div>` : ''}

    ${stats && Object.keys(stats.error_breakdown).length ? `
      <div class="card pad">
        <div class="h4">Типичные ошибки</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${Object.entries(stats.error_breakdown).map(([type, count]) =>
            `<div class="tag">${esc(ERROR_TITLES[type] || type)} · ${count}</div>`).join('')}
        </div>
      </div>` : ''}

    <div class="bottom" style="display:flex;flex-direction:column;gap:8px">
      <div class="btn" data-go="practice">Ещё пак задач</div>
      <div class="btn sec" data-go="home">На главную</div>
    </div>
  `, { title: 'Итог', tab: 'practice' });
}

/* ---------- вкладка: профессии ---------- */

async function screenCareers() {
  if (!S.token) return screenNeedAccount('профессии');

  render('<div style="display:flex;align-items:center;gap:10px"><div class="spinner"></div><div class="t3">Загружаем результаты…</div></div>',
    { title: 'Профессии', tab: 'careers' });

  let data;
  try {
    data = await api(`/api/users/${encodeURIComponent(S.userId)}/history`);
  } catch (error) {
    if (error.status !== 404) return screenError(error, screenCareers);
    data = { attempts: 0, history: [] };
  }

  const last = data.history[0];
  if (!last || !last.professions.length) {
    return render(`
      <div class="card pad" style="gap:12px">
        <div class="h4">Профессий пока нет</div>
        <div class="t3">Пройди тест — и здесь появятся пять профессий с объяснением, почему они тебе подходят.</div>
        <div class="btn" data-go="next">Пройти тест</div>
      </div>
    `, { title: 'Профессии', tab: 'careers' });
  }

  const [top, ...rest] = last.professions;
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
        <div class="btn" data-go="practice">Тренироваться по этим предметам</div>
      </div>
    </div>

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

    ${data.attempts > 1 ? '<div class="link" style="text-align:center" data-go="history">История прохождений</div>' : ''}
  `, { title: 'Профессии', tab: 'careers' });

  view.querySelectorAll('[data-profession]').forEach((row) => {
    row.onclick = () => row.querySelector('[data-reasoning]').classList.toggle('hidden');
  });
}

/* ---------- вкладка: профиль ---------- */

async function screenProfile() {
  let progress = null;
  if (S.token) {
    try { progress = await api('/api/practice/progress'); } catch { /* не критично */ }
  }

  render(`
    ${S.token ? `
      <div class="card pad" style="gap:6px">
        <div class="h4">${esc(S.fullName || 'Без имени')}</div>
        <div class="t3">${S.classId ? `Класс ${esc(S.schoolClass)}` : 'Класс не указан'}</div>
      </div>

      ${progress ? xpCard(progress) : ''}

      ${progress ? `
        <div class="card pad">
          <div style="display:flex;align-items:baseline;justify-content:space-between">
            <div class="h4">Достижения</div>
            <div class="t3">${progress.earned_count} из ${progress.total_achievements}</div>
          </div>
          <div class="badges">
            ${progress.achievements.map((a) => `
              <div class="badge ${a.earned ? '' : 'locked'}" title="${esc(a.hint)}">
                <div class="ico">${a.earned ? a.icon : '🔒'}</div>
                <div class="nm">${esc(a.earned ? a.title : a.hint)}</div>
              </div>`).join('')}
          </div>
        </div>` : ''}
      <div class="list">
        ${S.classId ? '' : '<div class="row" data-go="join-class"><div class="grow"><div class="h5">Ввести код класса</div><div class="t3">Чтобы попасть в сводку учителя</div></div></div><div class="sep"></div>'}
        <div class="row" data-go="history"><div class="grow"><div class="h5">История прохождений</div><div class="t3">Как менялись результаты</div></div></div>
        <div class="sep"></div>
        <div class="row" data-go="restart"><div class="grow"><div class="h5">Пройти тест заново</div><div class="t3">Ответы будут сброшены</div></div></div>
      </div>
      <div class="btn sec" data-go="logout">Выйти из аккаунта</div>
    ` : `
      <div class="card pad" style="gap:12px">
        <div class="h4">Ты без аккаунта</div>
        <div class="t3">Прогресс сохранён только в этом браузере. Создай аккаунт — ответы перенесутся, а учитель увидит тебя в классе.</div>
        <div class="btn" data-go="register">Создать аккаунт</div>
        <div class="btn sec" data-go="login">Войти</div>
      </div>
      <div class="list">
        <div class="row" data-go="restart"><div class="grow"><div class="h5">Пройти тест заново</div><div class="t3">Ответы будут сброшены</div></div></div>
      </div>
    `}
    <div class="link" style="text-align:center" data-go="teacher">Я педагог — открыть кабинет</div>
  `, { title: 'Профиль', tab: 'profile' });
}

/* Заглушка для вкладок, которым нужен аккаунт. */
function screenNeedAccount(what) {
  render(`
    <div class="card pad" style="gap:12px">
      <div class="h4">Нужен аккаунт</div>
      <div class="t3">Чтобы ${esc(what)} сохранялся между заходами, создай аккаунт — это займёт полминуты.</div>
      <div class="btn" data-go="register">Создать аккаунт</div>
      <div class="btn sec" data-go="login">У меня уже есть аккаунт</div>
    </div>
  `, { title: 'Аккаунт', tab: 'practice' });
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
        full_name: S.fullName || null,
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
    { title: 'История', progress: 1, tab: 'profile' });
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
    <div class="btn bottom sec" data-go="profile">Назад в профиль</div>
  `, { title: 'История', progress: 1, tab: 'profile' });
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
    practice: screenPractice,
    careers: screenCareers,
    profile: screenProfile,
    history: screenHistory,
    teacher: () => { window.location.href = '/static/teacher.html'; },
    register: screenRegister,
    login: screenLogin,
    'join-class': screenJoinClass,
    guest: () => {
      S.guestMode = true;
      save();
      screenOnboarding();
    },
    logout: () => {
      if (!confirm('Выйти из аккаунта? Ответы на этом устройстве останутся.')) return;
      S.token = null;
      S.fullName = '';
      S.classId = null;
      S.schoolClass = '';
      S.guestMode = false;
      save();
      screenWelcome();
    },
    restart: () => {
      if (!confirm('Все ответы будут удалены. Начать заново?')) return;
      S.answers = {};
      save();
      screenOnboarding();
    },
  };
  actions[target.dataset.go]?.();
});

// нижние вкладки — тот же набор переходов, что и data-go на экранах
tabsBar.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-tab]');
  if (!tab) return;
  ({ home: screenOnboarding, practice: screenPractice,
     careers: screenCareers, profile: screenProfile })[tab.dataset.tab]?.();
});

/* ---------- старт ---------- */

(async function start() {
  try {
    Q = await api('/api/tests/questions');
  } catch (error) {
    return screenError(error, start);
  }

  // токен мог протухнуть за месяц — сверяем его с сервером до показа экранов
  if (S.token) {
    try {
      applyProfile(await api('/api/auth/me'));
    } catch (error) {
      if (error.status === 401) {
        S.token = null;
        save();
      }
    }
  }

  if (!S.token && !S.guestMode) return screenWelcome();
  screenOnboarding();
})();
