/* Демо-двойник бэкенда: считает в браузере то, что в проде делают
   app/services/test_scoring.py и app/services/ai_recommender.py.

   Живёт только внутри автономной демо-страницы. Источник правды — Python:
   формулы ниже повторяют его один в один, банк вопросов и список
   fallback-профессий вшиваются при сборке прямо из исходников. */

const KNOWLEDGE_WEIGHT = 0.65;
const INTEREST_WEIGHT = 0.35;
const STRONG_SUBJECT_THRESHOLD = 4.0;

const round = (value, digits) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

/* ---------- порт calculate_scores ---------- */

function questionIndex() {
  const index = {};
  for (const key of ['block_a_interests', 'block_b_subjects', 'block_c_softskills']) {
    for (const question of DEMO_DATA.questions[key]) index[question.id] = question;
  }
  return index;
}

function calculateScores(answers) {
  const index = questionIndex();
  const interests = {};
  const softskills = {};
  const subjects = {};

  for (const [id, answer] of Object.entries(answers)) {
    const question = index[id];
    if (!question) continue;
    const likert = () => (typeof answer === 'object' ? answer.value ?? answer.selected_index : answer);

    if (question.skill) {
      (softskills[question.skill] ??= []).push(Number(likert()));
    } else if (!question.subject) {
      (interests[question.type] ??= []).push(Number(likert()));
    } else {
      const bucket = (subjects[question.subject] ??= { correct: 0, total: 0, interest: null });
      if (question.type === 'knowledge') {
        bucket.total += 1;
        const selected = typeof answer === 'object' ? answer.selected_index : answer;
        if (selected === question.correct_index) bucket.correct += 1;
      } else {
        bucket.interest = Number(likert());
      }
    }
  }

  const mean = (values) => round(values.reduce((a, b) => a + b, 0) / values.length, 2);
  const average = (source) => Object.fromEntries(
    Object.entries(source).map(([key, values]) => [key, mean(values)]),
  );

  const subjectsOut = {};
  for (const [subject, bucket] of Object.entries(subjects)) {
    // 0/3 → 1.0, 1/3 → 2.3, 2/3 → 3.7, 3/3 → 5.0
    const knowledge = bucket.total ? round(1 + 4 * bucket.correct / bucket.total, 1) : null;
    const interest = bucket.interest;
    const subjectScore = (knowledge !== null && interest !== null)
      ? round(knowledge * KNOWLEDGE_WEIGHT + interest * INTEREST_WEIGHT, 3)
      : (knowledge ?? interest);

    subjectsOut[subject] = {
      correct_count: bucket.correct,
      total_questions: bucket.total,
      knowledge_score: knowledge,
      interest,
      subject_score: subjectScore,
    };
  }

  return { interests: average(interests), subjects: subjectsOut, softskills: average(softskills) };
}

/* ---------- порт build_fallback ---------- */

function buildFallback(scores) {
  const interests = scores.interests || {};
  const keys = Object.keys(interests);
  const topType = keys.length
    ? keys.reduce((best, key) => (interests[key] > interests[best] ? key : best), keys[0])
    : 'investigative';
  const topScore = interests[topType];

  const titles = DEMO_DATA.questions.subject_titles;
  const strong = new Set();
  for (const [code, data] of Object.entries(scores.subjects || {})) {
    if (data.subject_score !== null && data.subject_score >= STRONG_SUBJECT_THRESHOLD) {
      strong.add((titles[code] || code).toLowerCase());
    }
  }

  const label = DEMO_DATA.typeLabels[topType] || topType;
  const hint = topScore === undefined ? '' : ` (балл ${topScore})`;
  const professions = (DEMO_DATA.fallbackProfessions[topType] || DEMO_DATA.fallbackProfessions.investigative)
    .map((item) => ({
      ...item,
      subjects_to_improve: item.subjects_to_improve.filter((s) => !strong.has(s.toLowerCase())),
      reasoning: `У тебя ярче всего выражен ${label}${hint}. `
        + `Профессия «${item.name}» опирается именно на этот склад. `
        + 'Это подборка упрощённым алгоритмом — пройди тест ещё раз чуть позже, чтобы получить разбор от ИИ.',
    }));

  return { professions, fallback: true, top_interest: topType };
}

/* ---------- мок HTTP-слоя ---------- */

const RESULTS_KEY = 'kompas_demo_results';
const loadResults = () => { try { return JSON.parse(localStorage.getItem(RESULTS_KEY)) || []; } catch { return []; } };
const saveResults = (list) => localStorage.setItem(RESULTS_KEY, JSON.stringify(list));

const DEMO = {
  async handle(path, options = {}) {
    // небольшая пауза, чтобы был виден экран ожидания ответа модели
    await new Promise((resolve) => setTimeout(resolve, options.method === 'POST' ? 900 : 120));

    if (path.startsWith('/api/tests/questions')) {
      const { block_a_interests, block_b_subjects, block_c_softskills, ...rest } = DEMO_DATA.questions;
      const strip = (list) => list.map(({ correct_index, ...question }) => question);
      return {
        ...rest,
        block_a_interests: strip(block_a_interests),
        block_b_subjects: strip(block_b_subjects),
        block_c_softskills: strip(block_c_softskills),
      };
    }

    if (path === '/api/tests/submit') {
      const payload = JSON.parse(options.body);
      const scores = calculateScores(payload.answers);
      const ai = buildFallback(scores);
      const total = Object.keys(questionIndex()).length;
      const answered = Object.keys(payload.answers).filter((id) => questionIndex()[id]).length;

      const result = {
        test_result_id: crypto.randomUUID(),
        completed_at: new Date().toISOString(),
        progress: {
          answered,
          total,
          percent: round(100 * answered / total, 1),
          is_complete: answered === total,
        },
        computed_scores: scores,
        recommendations: ai.professions,
        fallback: true,
        model_used: 'fallback:rule-based',
      };
      saveResults([result, ...loadResults()].slice(0, 10));
      return result;
    }

    if (path.includes('/history')) {
      const results = loadResults();
      return {
        user: { id: crypto.randomUUID(), max_user_id: 'demo', role: 'student', created_at: new Date().toISOString() },
        attempts: results.length,
        history: results.map((item) => ({
          test_result_id: item.test_result_id,
          completed_at: item.completed_at,
          top_interests: Object.entries(item.computed_scores.interests || {})
            .sort((a, b) => b[1] - a[1]).slice(0, 3).map(([key]) => key),
          professions: item.recommendations,
          fallback: true,
        })),
      };
    }

    if (path.startsWith('/api/recommendations/')) {
      const id = path.split('/').pop();
      const found = loadResults().find((item) => item.test_result_id === id);
      if (!found) throw new Error('404: результат не найден');
      return { ...found, professions: found.recommendations };
    }

    throw new Error(`404: в демо нет обработчика для ${path}`);
  },
};

/* ---------- кабинет педагога: снимок реального ответа API ---------- */

const TEACHER_SOFTSKILLS = {
  teamwork: 'Работа в команде', leadership: 'Лидерство', creativity: 'Творческое мышление',
  analytical: 'Аналитика', resilience: 'Усидчивость',
};
const HOLLAND_LONG = {
  realistic: 'Реалист', investigative: 'Исследователь', artistic: 'Артист',
  social: 'Социальный', enterprising: 'Предприним.', conventional: 'Конвенц.',
};

function renderTeacher() {
  const data = DEMO_DATA.classSummary;
  const escape = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const bars = (entries, max, format) => entries.map(([name, value]) => `
    <div class="barline">
      <div class="name">${escape(name)}</div>
      <div class="track"><i style="width:${Math.round((value / max) * 100)}%"></i></div>
      <div class="val">${format(value)}</div>
    </div>`).join('');

  const categories = Object.entries(data.category_distribution);
  const maxCategory = Math.max(1, ...categories.map(([, n]) => n));
  const interests = Object.entries(data.average_interests).sort((a, b) => b[1] - a[1]);
  const softskills = Object.entries(data.average_softskills).sort((a, b) => b[1] - a[1]);

  document.getElementById('teacher-out').innerHTML = `
    <div class="stats" style="margin-bottom:16px">
      <div class="stat"><div class="t3">Прошли тест</div><div class="num">${data.students_tested}</div><div class="t4s">учеников класса ${escape(data.school_class)}</div></div>
      <div class="stat"><div class="t3">Всего прохождений</div><div class="num">${data.tests_completed}</div><div class="t4s">включая повторные</div></div>
      <div class="stat"><div class="t3">Ведущее направление</div><div class="num" style="font-size:20px;line-height:26px">${escape(categories[0]?.[0] || '—')}</div><div class="t4s">${categories[0]?.[1] || 0} упоминаний</div></div>
    </div>

    <div class="cols">
      <div class="panel" style="flex:1.4 1 340px">
        <div style="display:flex;align-items:baseline;justify-content:space-between">
          <div class="h5" style="font-size:16px">Категории профессий в рекомендациях</div>
          <div class="t4s">${data.students_tested} учеников</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:12px">${bars(categories, maxCategory, (n) => n)}</div>
      </div>
      <div class="panel">
        <div class="h5" style="font-size:16px">Слабые предметы класса</div>
        <div style="display:flex;flex-direction:column;gap:10px">
          ${data.weakest_subjects.map((item, i) => `
            ${i ? '<div style="height:1px;background:var(--line)"></div>' : ''}
            <div style="display:flex;align-items:center;gap:10px">
              <div style="flex:1;font-size:14px;color:var(--t2)">${escape(item.title || item.subject)}</div>
              <div style="font-size:14px;color:var(--t3);font-variant-numeric:tabular-nums">средний ${Math.round((item.average_knowledge / 5) * 100)}%</div>
            </div>`).join('')}
        </div>
        <div class="t4s" style="margin-top:auto">Балл знаний по шкале 1–5 переведён в проценты.</div>
      </div>
    </div>

    <div class="cols" style="margin-top:16px">
      <div class="panel">
        <div class="h5" style="font-size:16px">Средний профиль интересов</div>
        <div style="display:flex;flex-direction:column;gap:12px">${bars(interests.map(([k, v]) => [HOLLAND_LONG[k] || k, v]), 5, (v) => v.toFixed(1))}</div>
      </div>
      <div class="panel">
        <div class="h5" style="font-size:16px">Soft skills класса</div>
        <div style="display:flex;flex-direction:column;gap:12px">${bars(softskills.map(([k, v]) => [TEACHER_SOFTSKILLS[k] || k, v]), 5, (v) => v.toFixed(1))}</div>
      </div>
    </div>`;
}

/* ---------- переключение вкладок ---------- */

document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    const teacher = tab.dataset.tab === 'teacher';
    document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    document.getElementById('stage-student').classList.toggle('off', teacher);
    document.getElementById('stage-teacher').classList.toggle('on', teacher);
    if (teacher) renderTeacher();
  };
});
