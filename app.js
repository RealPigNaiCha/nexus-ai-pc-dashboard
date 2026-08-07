(() => {
  "use strict";

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const stateKey = "nexus-ai-pc-dashboard";
  const defaultState = {
    theme: "light",
    indexedCount: 0,
    projectCount: 0,
    agentCount: 0,
    note: "",
    provider: "OpenAI",
    endpoint: "https://api.openai.com/v1",
    dataPath: "C:\\AI-PC",
    importedFiles: [],
    projects: []
  };
  const providerDefaultEndpoints = {
    OpenAI: "https://api.openai.com/v1",
    Anthropic: "https://api.anthropic.com/v1",
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta",
    DeepSeek: "https://api.deepseek.com",
    "阿里云百炼": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  };
  const roleLabels = {
    reasoning: "深度推理",
    fast: "快速任务",
    vision: "视觉理解",
    embedding: "文本向量"
  };

  let state = loadState();
  let backendConnected = false;
  let libraryItems = [];
  let libraryDataMode = "offline";
  let libraryRequestSerial = 0;
  let libraryLastRequest = { kind: "documents", query: "" };
  let librarySearchMode = "hybrid";
  let learningDashboard = null;
  let learningCourseId = "";
  let learningRequestSerial = 0;
  let researchProjects = [];
  let researchProjectId = "";
  let researchSearches = [];
  let researchPapers = [];
  let researchScreening = [];
  let researchNotes = [];
  let agentTasks = [];
  let agentRuntime = null;
  let toolRegistry = [];
  let paperqaStatus = null;
  let chatRoles = [];
  let chatSending = false;
  let chatMessageId = 0;

  async function apiFetch(path, options = {}) {
    if (window.location.protocol === "file:") return null;
    const { headers = {}, ...requestOptions } = options;
    let response;
    try {
      response = await fetch(`/api${path}`, {
        ...requestOptions,
        headers: { "Content-Type": "application/json", ...headers }
      });
    } catch {
      setServiceStatus(false);
      throw new Error("无法连接本地服务");
    }
    if (!response.ok) {
      let detail = "";
      try {
        const payload = await response.json();
        detail = typeof payload?.detail === "string" ? payload.detail : "";
      } catch {
        // Some server errors do not include a JSON response body.
      }
      throw new Error(detail || `API ${response.status}`);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function setServiceStatus(connected) {
    const title = qs(".device-status strong");
    const detail = qs(".device-status div span");
    const dot = qs(".device-status .status-dot");
    backendConnected = connected;
    if (!title || !detail || !dot) return;
    title.textContent = connected ? "本地服务正常" : "服务未连接";
    detail.textContent = connected ? "SQLite · 127.0.0.1" : "资料导入和检索暂不可用";
    dot.classList.toggle("is-online", connected);
    if (!connected) {
      ["#indexed-count", "#project-count", "#agent-count", "#overview-learning-mastery"].forEach((selector) => {
        if (qs(selector)) qs(selector).textContent = "—";
      });
      if (qs("#indexed-status")) qs("#indexed-status").textContent = "服务未连接";
      if (qs("#project-count-status")) qs("#project-count-status").textContent = "服务未连接";
      if (qs("#agent-count-status")) qs("#agent-count-status").textContent = "服务未连接";
      if (qs("#overview-learning-status")) qs("#overview-learning-status").textContent = "服务未连接";
      setCredentialStatus(false, "本地服务未连接，无法读取凭据状态");
      showLearningUnavailable("本地服务未连接", "启动本地服务后可创建课程、记录答题并计算复习时间。");
      clearResearchProject("本地服务未连接");
      setPaperQAUnavailable("本地服务未连接");
      renderOverviewTasksUnavailable();
      renderOverviewActivityUnavailable();
      if (qs("#semantic-index-state")) qs("#semantic-index-state").textContent = "服务未连接";
      showAgentUnavailable("本地服务未连接");
      showToolsUnavailable("本地服务未连接");
      showChatUnavailable();
    }
  }

  async function hydrateFromApi() {
    if (window.location.protocol === "file:") {
      setServiceStatus(false);
      showLibraryOffline("本地服务未连接", "启动本地服务后可导入路径并检索资料。");
      showLearningUnavailable("本地服务未连接", "请通过 Dashboard 本地地址打开页面，再创建或读取学习记录。");
      return;
    }
    try {
      const health = await apiFetch("/health");
      setServiceStatus(health?.status === "ok");
      const overview = await apiFetch("/overview");
      if (overview) {
        state.projectCount = overview.research_projects ?? state.projectCount;
        state.agentCount = overview.active_agent_tasks ?? state.agentCount;
        if (qs("#project-count")) qs("#project-count").textContent = state.projectCount;
        if (qs("#agent-count")) qs("#agent-count").textContent = state.agentCount;
        if (qs("#project-count-status")) qs("#project-count-status").textContent = "数据库记录";
        if (qs("#agent-count-status")) qs("#agent-count-status").textContent = "未完成任务";
        const learningMastery = overview.learning_mastery === null || overview.learning_mastery === undefined
          ? Number.NaN
          : Number(overview.learning_mastery);
        if (Number.isFinite(learningMastery)) {
          if (qs("#overview-learning-mastery")) qs("#overview-learning-mastery").textContent = `${Math.round(learningMastery)}%`;
          if (qs("#overview-learning-status")) qs("#overview-learning-status").textContent = "本地学习记录";
        } else if (qs("#overview-learning-status")) {
          qs("#overview-learning-status").textContent = "暂无本地记录";
        }
        updateStorageFromApi(overview);
      }
      const settings = await apiFetch("/settings");
      if (settings) {
        state.provider = settings.provider || state.provider;
        state.endpoint = settings.endpoint || state.endpoint;
        state.dataPath = settings.data_path || state.dataPath;
        if (qs("#provider-select")) qs("#provider-select").value = state.provider;
        if (qs("#api-endpoint")) qs("#api-endpoint").value = state.endpoint;
        if (qs("#data-path") && state.dataPath) qs("#data-path").value = state.dataPath;
      }
      await loadLearningDashboard({ quiet: true });
      await loadCoachReport({ quiet: true });
      await loadCoachPlan({ quiet: true });
      await loadDeepTutorStatus({ quiet: true });
      await loadResearchProjects({ quiet: true });
      await refreshCredentialStatus();
      await loadModelRoles({ quiet: true });
      await loadChatSetup({ quiet: true });
      await loadPaperQAStatus({ quiet: true });
      await loadZoteroStatus({ quiet: true });
      await loadOpsStatus({ quiet: true });
      await loadBrowserStatus({ quiet: true });
      await loadBrowserActions({ quiet: true });
      await loadSemanticStatus();
      await loadLibraryDocuments({ quiet: true });
      await loadAgentData({ quiet: true });
      await loadTools({ quiet: true });
      await loadOverviewActivity({ quiet: true });
      renderOverviewTasks();
    } catch {
      setServiceStatus(false);
      showLibraryOffline("本地服务暂不可用", "恢复服务后可重试读取资料库。");
      showLearningUnavailable("学习数据暂不可用", "恢复本地服务后点击“刷新进度”重试。");
    }
  }

  function learningEmptyMarkup(icon, title, detail) {
    return `<div class="learning-empty"><i data-lucide="${icon}" aria-hidden="true"></i><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div></div>`;
  }

  function learningStatusLabel(status, isDue = false) {
    if (isDue) return "待复习";
    return ({ not_started: "待开始", learning: "学习中", review: "需巩固", stable: "稳固" })[status] || "学习中";
  }

  function learningRatingLabel(rating) {
    return ({ 1: "重学", 2: "困难", 3: "良好", 4: "轻松" })[Number(rating)] || "—";
  }

  function learningErrorMessage(error) {
    const message = error?.message || "未知错误";
    return ({
      "Course title already exists": "课程名称已存在",
      "Course not found": "没有找到该课程",
      "Concept name already exists": "该课程中已存在同名知识点",
      "Prerequisite not found in course": "前置知识点不属于所选课程",
      "Concept not found": "没有找到该知识点",
      "API 422": "输入内容未通过校验"
    })[message] || message;
  }

  function formatLearningDateTime(value) {
    if (!value) return "尚未排程";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(parsed);
  }

  function formatStudyTime(seconds) {
    const total = Math.max(0, Number(seconds) || 0);
    if (total > 0 && total < 60) return "<1 分钟";
    const minutes = Math.round(total / 60);
    if (minutes < 60) return `${minutes} 分钟`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours} 小时 ${remainder} 分` : `${hours} 小时`;
  }

  function setLearningControls(online, courses = [], concepts = []) {
    qsa("#learning-course-form input, #learning-course-form textarea, #learning-course-form select, #learning-course-form button")
      .forEach((control) => { control.disabled = !online; });
    qsa("#learning-concept-form input, #learning-concept-form textarea, #learning-concept-form select, #learning-concept-form button")
      .forEach((control) => { control.disabled = !online || courses.length === 0; });
    qsa("#learning-attempt-form input, #learning-attempt-form textarea, #learning-attempt-form select, #learning-attempt-form button")
      .forEach((control) => { control.disabled = !online || concepts.length === 0; });
    const prerequisiteSelect = qs("#learning-concept-prerequisites");
    if (prerequisiteSelect && online && courses.length) prerequisiteSelect.disabled = prerequisiteSelect.options.length === 0 || !prerequisiteSelect.options[0]?.value;
    if (qs("#start-session")) qs("#start-session").disabled = !online || concepts.length === 0;
  }

  function showLearningUnavailable(title, detail) {
    learningDashboard = null;
    const source = qs("#learning-progress-source");
    if (source) { source.textContent = "服务未连接"; source.className = "status-label is-danger"; }
    const dataStatus = qs("#learning-data-status");
    if (dataStatus) { dataStatus.textContent = "不可用"; dataStatus.className = "status-label is-danger learning-sample-label"; }
    ["#learning-course-count", "#learning-concept-count", "#learning-due-count"].forEach((selector) => {
      if (qs(selector)) qs(selector).textContent = "—";
    });
    if (qs("#learning-study-time")) qs("#learning-study-time").textContent = "—";
    const ring = qs(".mastery-ring");
    if (ring) {
      ring.style.background = "conic-gradient(var(--primary) 0 0%, var(--surface-strong) 0% 100%)";
      ring.setAttribute("aria-label", "总体掌握度不可用");
    }
    if (qs("#learning-mastery-value")) qs("#learning-mastery-value").textContent = "—";
    if (qs("#learning-mastery-list")) qs("#learning-mastery-list").innerHTML = learningEmptyMarkup("wifi-off", title, detail);
    if (qs("#learning-review-list")) qs("#learning-review-list").innerHTML = learningEmptyMarkup("wifi-off", title, detail);
    if (qs("#learning-next-focus")) qs("#learning-next-focus").hidden = true;
    if (qs("#learning-progress-total")) qs("#learning-progress-total").textContent = "—";
    if (qs("#learning-due-total")) qs("#learning-due-total").textContent = "—";
    if (qs("#learning-history-wrap")) qs("#learning-history-wrap").hidden = true;
    const historyEmpty = qs("#learning-history-empty");
    if (historyEmpty) { historyEmpty.hidden = false; historyEmpty.innerHTML = `<i data-lucide="wifi-off" aria-hidden="true"></i><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`; }
    if (qs("#learning-history-state")) qs("#learning-history-state").textContent = "不可用";
    const attemptState = qs("#learning-attempt-state");
    if (attemptState) { attemptState.textContent = "服务未连接"; attemptState.className = "status-label is-danger"; }
    setLearningControls(false);
    refreshIcons();
  }

  function renderLearningCourseOptions(courses) {
    const validCourse = courses.some((course) => String(course.id) === learningCourseId);
    if (learningCourseId && !validCourse) learningCourseId = "";
    const options = courses.map((course) => `<option value="${Number(course.id)}">${escapeHtml(course.title)}</option>`).join("");
    const scopeSelect = qs("#learning-course-select");
    if (scopeSelect) {
      scopeSelect.innerHTML = `<option value="">全部课程</option>${options}`;
      scopeSelect.value = learningCourseId;
    }
    const conceptCourse = qs("#learning-concept-course");
    if (conceptCourse) {
      const previous = conceptCourse.value;
      conceptCourse.innerHTML = courses.length ? `<option value="">请选择课程</option>${options}` : '<option value="">请先创建课程</option>';
      const preferred = learningCourseId || (courses.some((course) => String(course.id) === previous) ? previous : String(courses[0]?.id || ""));
      conceptCourse.value = preferred;
    }
  }

  function updateLearningPrerequisites() {
    const select = qs("#learning-concept-prerequisites");
    if (!select) return;
    const courseId = qs("#learning-concept-course")?.value || "";
    const concepts = Array.isArray(learningDashboard?.concepts) ? learningDashboard.concepts : [];
    const eligible = concepts.filter((concept) => String(concept.course_id) === courseId);
    select.innerHTML = eligible.length
      ? eligible.map((concept) => `<option value="${Number(concept.id)}">${escapeHtml(concept.name)}</option>`).join("")
      : '<option value="">暂无可选前置知识点</option>';
    select.disabled = eligible.length === 0;
  }

  function renderLearningConceptOptions(concepts, dueReviews, nextConcept) {
    const select = qs("#learning-attempt-concept");
    if (!select) return;
    const previous = select.value;
    const showCourse = !learningCourseId;
    select.innerHTML = '<option value="">请选择知识点</option>' + concepts.map((concept) => {
      const prefix = showCourse && concept.course_title ? `${concept.course_title} · ` : "";
      return `<option value="${Number(concept.id)}">${escapeHtml(prefix + concept.name)}</option>`;
    }).join("");
    const validPrevious = concepts.some((concept) => String(concept.id) === previous);
    const recommended = dueReviews[0]?.id || nextConcept?.id || concepts[0]?.id || "";
    select.value = validPrevious ? previous : String(recommended);
  }

  function renderLearningMastery(concepts) {
    const list = qs("#learning-mastery-list");
    if (!list) return;
    if (!concepts.length) {
      list.innerHTML = learningEmptyMarkup("book-open", "还没有知识点", "先创建课程，再添加需要掌握的知识点。");
      return;
    }
    const now = Date.now();
    list.innerHTML = concepts.map((concept) => {
      const mastery = Math.max(0, Math.min(100, Number(concept.mastery) || 0));
      const dueTime = concept.due_at ? new Date(concept.due_at).getTime() : Number.NaN;
      const isDue = Number.isFinite(dueTime) && dueTime <= now;
      const detail = `${learningCourseId ? "" : `${concept.course_title || "未归类"} · `}${learningStatusLabel(concept.status, isDue)} · ${Number(concept.attempt_count) || 0} 次答题`;
      return `<div class="mastery-row"><div><strong>${escapeHtml(concept.name)}</strong><span>${escapeHtml(detail)}</span></div><progress value="${mastery}" max="100">${Math.round(mastery)}%</progress><b>${Math.round(mastery)}%</b><button class="icon-button compact" type="button" data-record-concept="${Number(concept.id)}" aria-label="记录 ${escapeHtml(concept.name)} 的答题"><i data-lucide="clipboard-pen-line" aria-hidden="true"></i></button></div>`;
    }).join("");
  }

  function renderLearningReviews(dueReviews, nextConcept) {
    const list = qs("#learning-review-list");
    const focus = qs("#learning-next-focus");
    if (list) {
      list.innerHTML = dueReviews.length ? dueReviews.map((concept) => (
        `<article><div class="review-state"><i data-lucide="alarm-clock" aria-hidden="true"></i></div><div><strong>${escapeHtml(concept.name)}</strong><span>${escapeHtml(concept.course_title || "未归类")} · 掌握度 ${Math.round(Number(concept.mastery) || 0)}% · ${escapeHtml(formatLearningDateTime(concept.due_at))}</span></div><button class="secondary-button compact-review-button" type="button" data-record-concept="${Number(concept.id)}"><i data-lucide="pencil-line" aria-hidden="true"></i><span>记录复习</span></button></article>`
      )).join("") : learningEmptyMarkup("calendar-check-2", "暂无到期复习", "完成答题后，系统会计算下一次复习时间。");
    }
    if (focus) {
      focus.hidden = !nextConcept;
      if (nextConcept) {
        const untouched = Number(nextConcept.attempt_count) === 0;
        focus.innerHTML = `<span class="lesson-index"><i data-lucide="${untouched ? "sparkles" : "calendar-clock"}" aria-hidden="true"></i></span><div><strong>${untouched ? "建议开始" : "下一项"}：${escapeHtml(nextConcept.name)}</strong><p>${untouched ? "该知识点还没有答题证据，可以从一次自测开始。" : `下次复习时间：${escapeHtml(formatLearningDateTime(nextConcept.due_at))}`}</p></div><button class="text-button" type="button" data-record-concept="${Number(nextConcept.id)}">记录答题</button>`;
      }
    }
  }

  function renderLearningHistory(attempts) {
    const wrap = qs("#learning-history-wrap");
    const body = qs("#learning-history-body");
    const empty = qs("#learning-history-empty");
    const stateLabel = qs("#learning-history-state");
    if (!wrap || !body || !empty) return;
    wrap.hidden = attempts.length === 0;
    empty.hidden = attempts.length > 0;
    if (attempts.length) {
      body.innerHTML = attempts.map((attempt) => {
        const confidence = attempt.confidence === null || attempt.confidence === undefined ? "—" : `${Math.round(Number(attempt.confidence) * 100)}%`;
        return `<tr><td>${escapeHtml(formatLearningDateTime(attempt.created_at))}</td><td>${escapeHtml(attempt.concept_name || "未知知识点")}</td><td>${Math.round(Number(attempt.score) * 100)}%</td><td>${escapeHtml(learningRatingLabel(attempt.rating))}</td><td>${confidence}</td><td>${escapeHtml(formatStudyTime(attempt.duration_seconds))}</td></tr>`;
      }).join("");
      if (stateLabel) { stateLabel.textContent = `${attempts.length} 条`; stateLabel.className = "status-label is-success"; }
    } else {
      empty.innerHTML = '<i data-lucide="history" aria-hidden="true"></i><div><strong>还没有答题记录</strong><span>保存第一次练习后，最近记录会显示在这里。</span></div>';
      if (stateLabel) { stateLabel.textContent = "暂无记录"; stateLabel.className = "status-label is-neutral"; }
    }
  }

  function renderLearningDashboard(payload) {
    const courses = Array.isArray(payload?.courses) ? payload.courses : [];
    const concepts = Array.isArray(payload?.concepts) ? payload.concepts : [];
    const dueReviews = Array.isArray(payload?.due_reviews) ? payload.due_reviews : [];
    const attempts = Array.isArray(payload?.recent_attempts) ? payload.recent_attempts : [];
    const summary = payload?.summary || {};
    learningDashboard = { ...payload, courses, concepts, due_reviews: dueReviews, recent_attempts: attempts, summary };
    renderLearningCourseOptions(courses);
    updateLearningPrerequisites();
    renderLearningConceptOptions(concepts, dueReviews, payload?.next_concept);
    renderLearningMastery(concepts);
    renderLearningReviews(dueReviews, payload?.next_concept);
    renderLearningHistory(attempts);

    const mastery = summary.mastery === null || summary.mastery === undefined ? Number.NaN : Number(summary.mastery);
    const masteryPercent = Number.isFinite(mastery) ? Math.max(0, Math.min(100, mastery)) : 0;
    const ring = qs(".mastery-ring");
    if (ring) {
      ring.style.background = `conic-gradient(var(--primary) 0 ${masteryPercent}%, var(--surface-strong) ${masteryPercent}% 100%)`;
      ring.setAttribute("aria-label", Number.isFinite(mastery) ? `总体掌握度 ${Math.round(mastery)}%` : "尚无掌握度记录");
    }
    if (qs("#learning-mastery-value")) qs("#learning-mastery-value").textContent = Number.isFinite(mastery) ? `${Math.round(mastery)}%` : "—";
    if (qs("#learning-course-count")) qs("#learning-course-count").textContent = courses.length;
    if (qs("#learning-concept-count")) qs("#learning-concept-count").textContent = Number(summary.concept_count) || 0;
    if (qs("#learning-due-count")) qs("#learning-due-count").textContent = Number(summary.due_count) || 0;
    if (qs("#learning-study-time")) qs("#learning-study-time").textContent = formatStudyTime(summary.study_seconds);
    if (qs("#learning-progress-total")) qs("#learning-progress-total").textContent = `${concepts.length} 个`;
    if (qs("#learning-due-total")) qs("#learning-due-total").textContent = `${dueReviews.length} 个`;

    const selectedCourse = courses.find((course) => String(course.id) === learningCourseId);
    const description = qs("#learning-page-description");
    if (description) {
      description.textContent = selectedCourse
        ? `${selectedCourse.goal}${selectedCourse.target_date ? ` · 目标日期 ${selectedCourse.target_date}` : ""}`
        : courses.length ? "正在汇总全部课程；选择一门课程可查看对应知识点与答题记录。" : "创建课程和知识点后，系统会根据每次答题记录更新掌握度与复习时间。";
    }
    const source = qs("#learning-progress-source");
    if (source) { source.textContent = "本地数据库"; source.className = "status-label is-success"; }
    const dataStatus = qs("#learning-data-status");
    if (dataStatus) {
      const hasRecords = courses.length > 0 || concepts.length > 0 || attempts.length > 0;
      dataStatus.textContent = hasRecords ? (selectedCourse ? selectedCourse.title : "全部课程") : "暂无本地记录";
      dataStatus.className = `status-label ${hasRecords ? "is-success" : "is-neutral"} learning-sample-label`;
    }
    const courseState = qs("#learning-course-state");
    if (courseState) courseState.textContent = selectedCourse ? selectedCourse.title : courses.length ? `${courses.length} 门课程` : "尚无课程";
    const conceptState = qs("#learning-concept-state");
    if (conceptState) conceptState.textContent = courses.length ? "可添加" : "需先创建课程";
    const attemptState = qs("#learning-attempt-state");
    if (attemptState) {
      attemptState.textContent = concepts.length ? "保存到本地数据库" : "需先添加知识点";
      attemptState.className = `status-label ${concepts.length ? "is-success" : "is-neutral"}`;
    }
    setLearningControls(true, courses, concepts);
    renderOverviewTasks();
    refreshIcons();
  }

  const auditCategoryLabels = {
    library: "资料库", learning: "学习", research: "科研", agent: "编程",
    models: "模型", paperqa: "论文问答", zotero: "Zotero", ops: "运维",
    credentials: "凭据", browser: "浏览器", settings: "设置"
  };
  const auditActionLabels = {
    "library.import": "资料导入",
    "library.index_document": "资料索引",
    "library.reuse_document": "复用资料",
    "learning.create_course": "创建课程",
    "learning.create_concept": "添加知识点",
    "learning.attempt": "记录答题",
    "research.create_project": "新建科研项目",
    "research.search": "文献检索",
    "research.screening": "更新筛选",
    "agent.create": "记录任务",
    "agent.handoff": "请求交接",
    "models.test": "模型连接测试",
    "models.generate": "模型生成",
    "paperqa.index": "建立论文索引",
    "paperqa.ask": "论文问答",
    "zotero.sync": "Zotero 同步",
    "ops.backup": "在线备份",
    "ops.backup_settings": "更新备份设置",
    "ops.backup_prune": "清理旧备份",
    "deeptutor.run": "DeepTutor 调用",
    "credentials.set": "保存凭据",
    "credentials.delete": "删除凭据",
    "browser.action": "浏览器动作",
    "settings.update": "更新设置"
  };

  function auditActionLabel(category, action) {
    return auditActionLabels[`${category}.${action}`] || `${auditCategoryLabels[category] || category} · ${action}`;
  }

  function auditResultLabel(result) {
    if (result === "success") return '<span class="status-label is-success">完成</span>';
    if (result === "error" || result === "cancelled") return '<span class="status-label is-danger">异常</span>';
    if (result === "path_forbidden" || result === "role_not_configured") return '<span class="status-label is-warning">被拒绝</span>';
    return '<span class="status-label is-neutral">已记录</span>';
  }

  function renderOverviewTasksUnavailable() {
    const list = qs("#overview-task-list");
    if (list) list.innerHTML = '<li class="overview-task-empty">服务未连接，无法汇总任务。</li>';
    const state = qs("#overview-tasks-state");
    if (state) { state.textContent = "不可用"; state.className = "status-label is-danger"; }
  }

  function renderOverviewTasks() {
    const list = qs("#overview-task-list");
    const state = qs("#overview-tasks-state");
    if (!list) return;
    const items = [];
    const dueReviews = Array.isArray(learningDashboard?.due_reviews) ? learningDashboard.due_reviews : [];
    dueReviews.slice(0, 5).forEach((concept) => {
      items.push({
        icon: "calendar-clock",
        strong: `复习「${concept.name}」`,
        span: `学习 · ${formatLearningDateTime(concept.due_at)}`,
        go: "learning"
      });
    });
    agentTasks.filter((task) => activeAgentStatuses.has(task.status)).slice(0, 5).forEach((task) => {
      const presentation = agentStatusPresentation[task.status] || { label: task.status, icon: "list-todo" };
      items.push({
        icon: presentation.icon,
        strong: task.title,
        span: `编程 Agent · ${presentation.label}`,
        go: "coding"
      });
    });
    if (!items.length) {
      list.innerHTML = '<li class="overview-task-empty">今天没有到期复习或待交接任务。</li>';
      if (state) { state.textContent = "暂无任务"; state.className = "status-label is-neutral"; }
      return;
    }
    list.innerHTML = items.map((item) => (
      `<li class="overview-task" data-go="${item.go}"><span class="lesson-index"><i data-lucide="${item.icon}" aria-hidden="true"></i></span><div><strong>${escapeHtml(item.strong)}</strong><span>${escapeHtml(item.span)}</span></div></li>`
    )).join("");
    if (state) { state.textContent = `${items.length} 项`; state.className = "status-label is-warning"; }
    refreshIcons();
  }

  function renderOverviewActivity(events) {
    const body = qs("#overview-activity-body");
    if (!body) return;
    if (!events.length) {
      body.innerHTML = '<tr><td colspan="4"><span class="status-label is-neutral">暂无记录</span></td></tr>';
      return;
    }
    body.innerHTML = events.map((event) => {
      let target = "";
      if (event.target) {
        if (event.category === "paperqa" && event.action === "ask") {
          target = ` · ${event.target === "fast" ? "快速任务" : "深度推理"}`;
        } else {
          target = ` · ${escapeHtml(String(event.target).slice(0, 48))}`;
        }
      }
      return `<tr><td>${escapeHtml(formatLearningDateTime(event.created_at))}</td><td>${escapeHtml(auditActionLabel(event.category, event.action))}${target}</td><td>${escapeHtml(auditCategoryLabels[event.category] || event.category)}</td><td>${auditResultLabel(event.result)}</td></tr>`;
    }).join("");
  }

  function renderOverviewActivityUnavailable() {
    const body = qs("#overview-activity-body");
    if (body) body.innerHTML = '<tr><td colspan="4"><span class="status-label is-danger">服务未连接</span></td></tr>';
  }

  async function loadOverviewActivity({ quiet = false } = {}) {
    if (!backendConnected) {
      renderOverviewActivityUnavailable();
      return false;
    }
    try {
      const events = await apiFetch("/audit?limit=8");
      renderOverviewActivity(Array.isArray(events) ? events : []);
      return true;
    } catch (error) {
      renderOverviewActivityUnavailable();
      if (!quiet) toast(`最近活动读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function loadLearningDashboard({ quiet = false } = {}) {
    const requestSerial = ++learningRequestSerial;
    if (!(await ensureBackendConnection())) {
      if (requestSerial === learningRequestSerial) showLearningUnavailable("本地服务未连接", "恢复服务后点击“刷新进度”重试。");
      return false;
    }
    const source = qs("#learning-progress-source");
    if (!quiet && source) { source.textContent = "正在读取"; source.className = "status-label is-neutral"; }
    try {
      const query = learningCourseId ? `?course_id=${encodeURIComponent(learningCourseId)}` : "";
      const payload = await apiFetch(`/learning/dashboard${query}`);
      if (requestSerial !== learningRequestSerial) return false;
      renderLearningDashboard(payload || {});
      return true;
    } catch (error) {
      if (requestSerial !== learningRequestSerial) return false;
      const message = learningErrorMessage(error);
      showLearningUnavailable("学习数据读取失败", message);
      if (!quiet) toast(`无法读取学习进度：${message}`, "circle-alert");
      return false;
    }
  }

  async function createLearningCourse(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (!(await ensureBackendConnection())) { toast("本地服务未连接，课程没有创建", "wifi-off"); return; }
    const button = qs('button[type="submit"]', form);
    if (button) { button.disabled = true; button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>创建中</span>'; refreshIcons(); }
    const targetDate = qs("#learning-course-date")?.value || null;
    try {
      const course = await apiFetch("/learning/courses", {
        method: "POST",
        body: JSON.stringify({
          title: qs("#learning-course-title").value.trim(),
          goal: qs("#learning-course-goal").value.trim(),
          target_date: targetDate
        })
      });
      learningCourseId = String(course.id);
      form.reset();
      await loadLearningDashboard({ quiet: true });
      toast(`课程“${course.title}”已创建`, "book-plus");
    } catch (error) {
      toast(`课程未创建：${learningErrorMessage(error)}`, "circle-alert");
    } finally {
      if (button) { button.disabled = false; button.innerHTML = '<i data-lucide="plus" aria-hidden="true"></i><span>创建课程</span>'; refreshIcons(); }
    }
  }

  async function createLearningConcept(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (!(await ensureBackendConnection())) { toast("本地服务未连接，知识点没有添加", "wifi-off"); return; }
    const courseId = qs("#learning-concept-course")?.value || "";
    if (!courseId) { toast("请先选择所属课程", "list-checks"); return; }
    const prerequisites = qsa("#learning-concept-prerequisites option:checked")
      .map((option) => Number(option.value)).filter((value) => Number.isInteger(value) && value > 0);
    const button = qs('button[type="submit"]', form);
    if (button) { button.disabled = true; button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>添加中</span>'; refreshIcons(); }
    try {
      const concept = await apiFetch("/learning/concepts", {
        method: "POST",
        body: JSON.stringify({
          course_id: Number(courseId),
          name: qs("#learning-concept-name").value.trim(),
          description: qs("#learning-concept-description").value.trim() || null,
          prerequisite_ids: prerequisites
        })
      });
      learningCourseId = courseId;
      form.reset();
      await loadLearningDashboard({ quiet: true });
      if (qs("#learning-attempt-concept")) qs("#learning-attempt-concept").value = String(concept.id);
      toast(`知识点“${concept.name}”已添加`, "list-plus");
    } catch (error) {
      toast(`知识点未添加：${learningErrorMessage(error)}`, "circle-alert");
    } finally {
      if (button) { button.disabled = false; button.innerHTML = '<i data-lucide="plus" aria-hidden="true"></i><span>添加知识点</span>'; refreshIcons(); }
    }
  }

  async function recordLearningAttempt(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (!(await ensureBackendConnection())) { toast("本地服务未连接，答题记录没有保存", "wifi-off"); return; }
    const conceptId = Number(qs("#learning-attempt-concept")?.value);
    if (!Number.isInteger(conceptId) || conceptId < 1) { toast("请先选择知识点", "list-checks"); return; }
    const button = qs('button[type="submit"]', form);
    if (button) { button.disabled = true; button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>保存中</span>'; refreshIcons(); }
    const optionalText = (selector) => qs(selector)?.value.trim() || null;
    try {
      const result = await apiFetch("/learning/attempts", {
        method: "POST",
        body: JSON.stringify({
          concept_id: conceptId,
          score: Number(qs("#learning-attempt-score").value) / 100,
          prompt: optionalText("#learning-attempt-prompt"),
          answer: optionalText("#learning-attempt-answer"),
          feedback: optionalText("#learning-attempt-feedback"),
          confidence: Number(qs("#learning-attempt-confidence").value) / 100,
          duration_seconds: Number(qs("#learning-attempt-duration").value || 0) * 60,
          hints_used: Number(qs("#learning-attempt-hints").value || 0)
        })
      });
      form.reset();
      if (qs("#learning-score-output")) qs("#learning-score-output").textContent = "70%";
      if (qs("#learning-confidence-output")) qs("#learning-confidence-output").textContent = "70%";
      await loadLearningDashboard({ quiet: true });
      await loadCoachReport({ quiet: true });
      await loadCoachPlan({ quiet: true });
      toast(`答题已保存：${learningRatingLabel(result.rating)}，下次 ${formatLearningDateTime(result.due_at)}`, "calendar-check-2");
    } catch (error) {
      toast(`答题记录未保存：${learningErrorMessage(error)}`, "circle-alert");
    } finally {
      if (button) { button.disabled = false; button.innerHTML = '<i data-lucide="save" aria-hidden="true"></i><span>保存答题记录</span>'; refreshIcons(); }
    }
  }

  function focusLearningAttempt(conceptId = "") {
    const select = qs("#learning-attempt-concept");
    if (!select || select.disabled) { toast("请先创建课程和知识点", "book-plus"); return; }
    if (conceptId && qsa("option", select).some((option) => option.value === String(conceptId))) select.value = String(conceptId);
    qs("#learning-attempt-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => select.focus({ preventScroll: true }), 250);
  }

  function setCredentialStatus(configured, message) {
    const label = qs("#provider-state");
    const detail = qs("#provider-message");
    if (label) {
      label.textContent = configured ? "已安全保存" : "未配置";
      label.className = `status-label ${configured ? "is-success" : "is-warning"}`;
    }
    if (detail && message) detail.textContent = message;
  }

  function setProviderTestStatus(ok, message) {
    const label = qs("#provider-state");
    const detail = qs("#provider-message");
    if (label) {
      label.textContent = ok ? "连接正常" : "连接失败";
      label.className = `status-label ${ok ? "is-success" : "is-danger"}`;
    }
    if (detail) detail.textContent = message;
  }

  async function refreshCredentialStatus() {
    if (!backendConnected) {
      setCredentialStatus(false, "本地服务未连接，无法读取凭据状态");
      return false;
    }
    const provider = qs("#provider-select")?.value || state.provider;
    try {
      const result = await apiFetch(`/credentials/${encodeURIComponent(provider)}`);
      const configured = result?.configured === true;
      setCredentialStatus(
        configured,
        configured ? "密钥已存入 Windows 凭据管理器" : "尚未为该服务商保存密钥"
      );
      return configured;
    } catch {
      setCredentialStatus(false, "暂时无法读取 Windows 凭据状态");
      return false;
    }
  }

  async function saveCredential() {
    const input = qs("#api-key");
    const secret = input?.value.trim() || "";
    if (!secret) {
      toast("请先输入 API 密钥", "key-round-warning");
      input?.focus();
      return false;
    }
    if (!backendConnected && !(await ensureBackendConnection())) {
      toast("本地服务未连接，密钥没有保存", "wifi-off");
      return false;
    }
    const provider = qs("#provider-select")?.value || state.provider;
    try {
      const result = await apiFetch(`/credentials/${encodeURIComponent(provider)}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: secret })
      });
      if (input) input.value = "";
      setCredentialStatus(result?.configured === true, "密钥已存入 Windows 凭据管理器；模型连通性尚未测试");
      toast("API 密钥已安全保存", "shield-check");
      return true;
    } catch (error) {
      if (input) input.value = "";
      setCredentialStatus(false, "凭据保存失败，请检查本地服务日志");
      toast(`密钥未保存：${error.message}`, "circle-alert");
      return false;
    }
  }

  function modelConnectionErrorMessage(error) {
    const message = error?.message || "连接测试失败";
    return ({
      "Model credential is not configured": "请先保存该服务商的 API 密钥",
      "Model role is not configured": "请先在角色表单中填写模型 ID 并保存",
      "Model endpoint is not allowed": "API 地址格式不受支持",
      "Model endpoint does not match the provider": "API 地址与所选官方服务商不匹配",
      "Compatible model endpoints must use HTTPS": "兼容服务必须使用 HTTPS；仅本机服务可使用 HTTP",
      "Model service timed out": "模型服务响应超时",
      "Model service is unavailable": "无法连接模型服务，请检查网络和地址",
      "Model service rejected the credential": "模型服务拒绝了该密钥",
      "Model service quota or rate limit was reached": "模型服务额度不足或请求过于频繁",
      "Model service rejected the connection test": "模型服务拒绝了连接测试",
      "Model service rejected the generation request": "模型服务拒绝了生成请求",
      "Model service returned an invalid response": "模型服务返回了无法解析的响应",
      "Model service returned an empty response": "模型服务返回了空内容",
      "Embedding uses the local model and cannot be configured as an external route": "文本向量角色固定使用本地模型",
      "Embedding role does not generate text": "文本向量角色不参与生成",
      "Credential storage is unavailable": "Windows 凭据管理器暂时不可用"
    })[message] || message;
  }

  async function testModelConnection(event) {
    const button = event.currentTarget;
    const endpointInput = qs("#api-endpoint");
    if (!endpointInput?.reportValidity()) return;
    if (!backendConnected && !(await ensureBackendConnection())) {
      toast("本地服务未连接，无法测试模型连接", "wifi-off");
      return;
    }
    if (qs("#api-key")?.value.trim() && !(await saveCredential())) return;

    const provider = qs("#provider-select")?.value || state.provider;
    const endpoint = endpointInput.value.trim();
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>测试中</span>';
    if (qs("#provider-message")) qs("#provider-message").textContent = "正在验证端点和凭据";
    refreshIcons();
    try {
      const result = await apiFetch("/models/test", {
        method: "POST",
        body: JSON.stringify({ provider, endpoint })
      });
      const latency = Math.max(0, Number(result?.latency_ms) || 0);
      setProviderTestStatus(true, `模型服务已响应 · ${latency < 1 ? "<1" : latency} ms`);
      toast("模型连接测试通过", "plug-zap");
    } catch (error) {
      const message = modelConnectionErrorMessage(error);
      setProviderTestStatus(false, message);
      toast(`模型连接测试失败：${message}`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="plug-zap" aria-hidden="true"></i><span>测试连接</span>';
      refreshIcons();
    }
  }

  function changeModelProvider(event) {
    const provider = event.currentTarget.value;
    const endpoint = qs("#api-endpoint");
    state.provider = provider;
    if (endpoint) {
      endpoint.value = providerDefaultEndpoints[provider] || "";
      endpoint.placeholder = providerDefaultEndpoints[provider] || "https://你的模型服务地址/v1";
    }
    refreshCredentialStatus();
  }

  function setRoleStatus(role, ready, detail = "") {
    const row = qs(`.model-role-row[data-role="${role}"]`);
    if (!row) return;
    const label = row.querySelector(".status-label");
    const message = row.querySelector(".role-message");
    if (label) {
      label.textContent = ready ? "已配置" : "未配置";
      label.className = `status-label ${ready ? "is-success" : "is-warning"}`;
    }
    if (message && detail) message.textContent = detail;
  }

  async function loadModelRoles({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return;
    try {
      const payload = await apiFetch("/models/roles");
      const roles = Array.isArray(payload?.roles) ? payload.roles : [];
      for (const role of roles) {
        const row = qs(`.model-role-row[data-role="${role.role}"]`);
        if (!row || role.local_only) continue;
        const provider = qs(".role-provider", row);
        const model = qs(".role-model", row);
        const endpoint = qs(".role-endpoint", row);
        if (provider) provider.value = role.provider || provider.value;
        if (model) model.value = role.model || "";
        if (endpoint) {
          endpoint.value = role.endpoint || providerDefaultEndpoints[role.provider] || "";
          endpoint.placeholder = providerDefaultEndpoints[role.provider] || "https://你的模型服务地址/v1";
        }
        setRoleStatus(
          role.role,
          Boolean(role.ready),
          role.ready ? "角色路由已就绪" : "填写模型 ID 并为该服务商保存密钥后可用"
        );
      }
    } catch (error) {
      if (!quiet) toast(`模型角色读取失败：${modelConnectionErrorMessage(error)}`, "circle-alert");
    }
  }

  function showChatUnavailable() {
    const status = qs("#chat-model-status");
    if (status) {
      status.textContent = "本地服务未连接，无法提问";
      status.classList.add("is-warning");
    }
    if (qs("#chat-go-settings")) qs("#chat-go-settings").hidden = true;
    const input = qs("#chat-input");
    const send = qs("#chat-send");
    if (input) input.disabled = true;
    if (send) send.disabled = true;
  }

  async function loadChatSetup({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const status = qs("#chat-model-status");
    const settingsButton = qs("#chat-go-settings");
    const input = qs("#chat-input");
    const send = qs("#chat-send");
    if (input) input.disabled = false;
    if (send) send.disabled = false;
    try {
      const payload = await apiFetch("/models/roles");
      chatRoles = Array.isArray(payload?.roles) ? payload.roles : [];
      const readyRoles = chatRoles.filter(
        (item) => item.role === "reasoning" || item.role === "fast"
      );
      const ready = readyRoles.some((item) => item.ready === true);
      const readyNames = readyRoles
        .filter((item) => item.ready === true)
        .map((item) => (item.role === "reasoning" ? "深度推理" : "快速任务"));
      if (status) {
        status.textContent = ready
          ? `${readyNames.join("、")}已就绪，可直接提问`
          : "模型未配置：请先保存密钥并配置角色";
        status.classList.toggle("is-warning", !ready);
      }
      if (settingsButton) settingsButton.hidden = ready;
      return ready;
    } catch (error) {
      if (status) {
        status.textContent = "模型配置读取失败";
        status.classList.add("is-warning");
      }
      if (!quiet) toast(`模型配置读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  function chatMessageLocation(item) {
    if (item.page !== null && item.page !== undefined && item.page !== "") {
      return ` · 第 ${item.page} 页`;
    }
    if (item.paragraph !== null && item.paragraph !== undefined && item.paragraph !== "") {
      return ` · 第 ${item.paragraph} 段`;
    }
    return "";
  }

  function renderChatMarkdown(text) {
    const escaped = escapeHtml(text);
    const segments = escaped.split("```");
    let html = "";
    segments.forEach((segment, index) => {
      if (index % 2 === 1) {
        html += `<pre><code>${segment.trim()}</code></pre>`;
        return;
      }
      const lines = segment.split("\n");
      let listTag = "";
      const paragraph = [];
      const flushParagraph = () => {
        if (!paragraph.length) return;
        html += `<p>${paragraph.join("<br>")}</p>`;
        paragraph.length = 0;
      };
      const closeList = () => {
        if (listTag) {
          html += `</${listTag}>`;
          listTag = "";
        }
      };
      for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        const heading = line.match(/^(#{1,4})\s+(.*)$/);
        if (heading) {
          flushParagraph();
          closeList();
          html += `<h4>${heading[2]}</h4>`;
          continue;
        }
        const list = line.match(/^[-*]\s+(.*)$/);
        if (list) {
          flushParagraph();
          if (listTag !== "ul") {
            closeList();
            html += "<ul>";
            listTag = "ul";
          }
          html += `<li>${list[1]}</li>`;
          continue;
        }
        closeList();
        if (line.trim() === "") {
          flushParagraph();
          continue;
        }
        paragraph.push(
          line
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/`([^`]+)`/g, "<code>$1</code>")
        );
      }
      flushParagraph();
      closeList();
    });
    return html;
  }

  function buildChatLearningHtml(learning) {
    if (!learning || !Number(learning.concept_count)) return "";
    const next = learning.next_step || {};
    const kindLabel = ({ review: "复习", new: "新知识点", practice: "练习" })[next.kind] || next.kind || "";
    const nextText = next.concept_name
      ? `建议下一步：${escapeHtml(next.concept_name)}${kindLabel ? `（${kindLabel}）` : ""}`
      : "";
    const concepts = (learning.concepts || [])
      .slice(0, 10)
      .map(
        (item) =>
          `<li>${escapeHtml(item.name)} · 掌握度 ${escapeHtml(String(item.mastery))}% · ${escapeHtml(item.status)}</li>`
      )
      .join("");
    return `<details class="chat-learning"><summary>学习进度（${learning.concept_count} 个知识点 · ${learning.due_count} 个待复习）</summary><div class="chat-learning-summary"><span>薄弱前置：${learning.weak_foundation_count} 个</span>${nextText ? `<span>${nextText}</span>` : ""}</div><ul class="chat-learning-concepts">${concepts}</ul></details>`;
  }

  function appendChatMessage(kind, text, options = {}) {
    const container = qs("#chat-messages");
    if (!container) return null;
    const welcome = qs("#chat-welcome");
    if (welcome) welcome.remove();
    const id = `chat-msg-${++chatMessageId}`;
    const wrapper = document.createElement("div");
    wrapper.className = `chat-message is-${kind}`;
    wrapper.id = id;
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    if (kind === "assistant" && options.pending) {
      bubble.classList.add("is-pending");
      bubble.innerHTML =
        '<i data-lucide="loader-circle" aria-hidden="true"></i><span>正在检索本地资料并生成回答…</span>';
    } else if (kind === "assistant" && options.error) {
      bubble.classList.add("is-error");
      bubble.innerHTML = `<strong>回答失败</strong><span>${escapeHtml(options.error)}</span>`;
    } else {
      bubble.textContent = text;
    }
    wrapper.appendChild(bubble);
    container.appendChild(wrapper);
    refreshIcons();
    container.scrollTop = container.scrollHeight;
    return id;
  }

  function updateChatMessage(id, data) {
    const wrapper = document.getElementById(id);
    const bubble = wrapper?.querySelector(".chat-bubble");
    if (!wrapper || !bubble) return;
    const container = qs("#chat-messages");
    if (data.error) {
      bubble.className = "chat-bubble is-error";
      bubble.innerHTML = `<strong>回答失败</strong><span>${escapeHtml(data.error)}</span>`;
    } else {
      bubble.className = "chat-bubble";
      const evidence = Array.isArray(data.evidence) ? data.evidence : [];
      const usage = data.usage || {};
      const tokens = usage.total_tokens != null ? ` · ${usage.total_tokens} tokens` : "";
      const latency = data.latency_ms != null ? ` · ${Math.round(data.latency_ms)} ms` : "";
      const model = data.model ? escapeHtml(data.model) : "模型";
      const sources = evidence.length
        ? `<details class="chat-sources"><summary>来源（${evidence.length}）</summary>${evidence
            .map(
              (item, index) =>
                `<div class="chat-source"><strong>[${index + 1}] ${escapeHtml(item.title || "未命名资料")}</strong><span>${escapeHtml(item.source_path || "")}${escapeHtml(chatMessageLocation(item))}</span><blockquote>${escapeHtml(item.snippet || "")}</blockquote></div>`
            )
            .join("")}</details>`
        : "";
      const learningHtml = buildChatLearningHtml(data.learning);
      bubble.innerHTML = `<div class="chat-answer">${renderChatMarkdown(data.text || "")}</div><div class="chat-meta">${model}${latency}${tokens}</div>${sources}${learningHtml}`;
    }
    refreshIcons();
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }

  function chatErrorMessage(error) {
    const message = error?.message || "未知错误";
    return (
      {
        "Model role is not configured":
          "模型角色尚未配置：请到设置页保存密钥并配置“深度推理”或“快速任务”。",
        "Model credential is not configured":
          "模型密钥尚未配置：请到设置页为对应服务商保存密钥。",
        "Model service is unavailable": "模型服务不可用，请检查网络或端点地址。",
        "Model service timed out": "模型服务响应超时，请稍后重试。",
        "Model service rejected the credential": "模型服务拒绝了密钥，请检查密钥是否正确。",
        "Model service quota or rate limit was reached": "模型服务达到额度或限流，请稍后重试。"
      }[message] || message
    );
  }

  function setChatSending(active) {
    const button = qs("#chat-send");
    const input = qs("#chat-input");
    if (button) {
      button.disabled = active;
      button.innerHTML = active
        ? '<i data-lucide="loader-circle" aria-hidden="true"></i><span>生成中</span>'
        : '<i data-lucide="send" aria-hidden="true"></i><span>发送</span>';
    }
    if (input) input.disabled = active;
    refreshIcons();
  }

  async function sendChatQuestion() {
    const input = qs("#chat-input");
    const question = input?.value.trim() || "";
    if (!question || chatSending) return;
    if (!backendConnected) {
      toast("本地服务未连接，无法提问", "wifi-off");
      return;
    }
    const role = qs("#chat-role")?.value || "reasoning";
    const scope = qs("#chat-scope")?.value || "all";
    appendChatMessage("user", question);
    input.value = "";
    input.focus();
    const pendingId = appendChatMessage("assistant", "", { pending: true });
    chatSending = true;
    setChatSending(true);
    try {
      const payload = await apiFetch("/chat/ask", {
        method: "POST",
        body: JSON.stringify({ question, role, scope })
      });
      updateChatMessage(pendingId, {
        text: payload.answer || "",
        model: payload.model,
        latency_ms: payload.latency_ms,
        usage: payload.usage,
        evidence: payload.evidence,
        learning: payload.learning_state
      });
    } catch (error) {
      updateChatMessage(pendingId, { error: chatErrorMessage(error) });
      const ready = chatRoles.some((item) => item.role === role && item.ready === true);
      if (!ready) {
        const status = qs("#chat-model-status");
        if (status) {
          status.textContent = "模型未配置：请先保存密钥并配置角色";
          status.classList.add("is-warning");
        }
        if (qs("#chat-go-settings")) qs("#chat-go-settings").hidden = false;
      }
    } finally {
      chatSending = false;
      setChatSending(false);
    }
  }

  async function saveModelRole(event) {
    const button = event.currentTarget;
    const role = button.dataset.role;
    const row = qs(`.model-role-row[data-role="${role}"]`);
    if (!row) return;
    const provider = qs(".role-provider", row)?.value || "";
    const model = qs(".role-model", row)?.value.trim() || "";
    const endpoint = qs(".role-endpoint", row)?.value.trim() || "";
    if (!model) {
      toast("请先填写模型 ID", "circle-alert");
      qs(".role-model", row)?.focus();
      return;
    }
    button.disabled = true;
    try {
      await apiFetch(`/models/roles/${encodeURIComponent(role)}`, {
        method: "PUT",
        body: JSON.stringify({ provider, model, endpoint })
      });
      setRoleStatus(role, true, "角色路由已保存");
      toast(`${roleLabels[role] || role}角色已保存`, "save");
      await loadModelRoles({ quiet: true });
    } catch (error) {
      setRoleStatus(role, false, modelConnectionErrorMessage(error));
      toast(`角色保存失败：${modelConnectionErrorMessage(error)}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  async function generateModelText() {
    const prompt = qs("#generate-prompt")?.value.trim() || "";
    const role = qs("#generate-role")?.value || "reasoning";
    const output = qs("#generate-output");
    if (!prompt) {
      toast("请先输入生成测试提示词", "circle-alert");
      qs("#generate-prompt")?.focus();
      return;
    }
    if (!backendConnected && !(await ensureBackendConnection())) return;
    const button = qs("#generate-test");
    button.disabled = true;
    if (output) {
      output.hidden = false;
      output.className = "generate-output";
      output.textContent = "正在生成…";
    }
    try {
      const result = await apiFetch("/models/generate", {
        method: "POST",
        body: JSON.stringify({ role, prompt, max_tokens: 1024, temperature: 0.2 })
      });
      const latency = Math.max(0, Number(result?.latency_ms) || 0);
      if (output) {
        output.textContent =
          `${result.content}\n\n— ${result.provider} / ${result.model} · ${latency < 1 ? "<1" : latency} ms`;
      }
      toast("生成测试完成", "sparkles");
    } catch (error) {
      const message = modelConnectionErrorMessage(error);
      if (output) {
        output.className = "generate-output is-error";
        output.textContent = message;
      }
      toast(`生成失败：${message}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  function bindRoleProviderChanges() {
    qsa(".model-role-row .role-provider").forEach((select) => {
      select.addEventListener("change", () => {
        const row = select.closest(".model-role-row");
        const endpoint = qs(".role-endpoint", row);
        if (endpoint) {
          endpoint.value = providerDefaultEndpoints[select.value] || "";
          endpoint.placeholder = providerDefaultEndpoints[select.value] || "https://你的模型服务地址/v1";
        }
      });
    });
  }

  function coachStateLabel(ok, message) {
    const state = qs("#coach-state");
    if (state) {
      state.textContent = message || (ok ? "已生成" : "无记录");
      state.className = `status-label ${ok ? "is-success" : "is-neutral"}`;
    }
  }

  function renderCoachReport(report) {
    const container = qs("#coach-report");
    if (!container) return;
    const summary = report?.summary || {};
    if (!Number(summary.concept_count || 0)) {
      container.innerHTML = `<div class="learning-empty"><i data-lucide="book-open-check" aria-hidden="true"></i><div><strong>暂无教练报告</strong><span>创建课程和知识点并记录答题后，这里会解释掌握度变化、薄弱前置和下一步。</span></div></div>`;
      refreshIcons();
      return;
    }
    const mastery = summary.mastery === null || summary.mastery === undefined
      ? "—"
      : `${Math.round(Number(summary.mastery))}%`;
    const facts = [
      ["知识点", `${summary.concept_count ?? 0}`],
      ["答题次数", `${summary.attempt_count ?? 0}`],
      ["待复习", `${summary.due_count ?? 0}`],
      ["总体掌握", `${mastery}`],
      ["薄弱前置", `${summary.weak_foundation_count ?? 0}`],
      ["学习时长", formatStudyTime(Number(summary.study_seconds) || 0)]
    ].map(([label, value]) =>
      `<div class="coach-fact"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`
    ).join("");

    const weakList = (report?.weak_foundations || []).map((item) => {
      const missing = (item.missing_prerequisites || [])
        .map((prerequisite) => `${escapeHtml(prerequisite.name)}（${Math.round(Number(prerequisite.mastery) || 0)}%）`)
        .join("、");
      return `<div class="coach-list-item"><strong>${escapeHtml(item.concept_name)}</strong> 的前置尚未掌握<small>${missing}</small></div>`;
    }).join("");

    const next = report?.next_step || { kind: "none", concept: null };
    let nextText = "暂无待办，等待复习到期或创建新知识点";
    if (next.kind !== "none" && next.concept) {
      const action = next.kind === "review" ? "复习" : next.kind === "new" ? "开始学习" : "继续练习";
      nextText = `${action}「${next.concept.name}」`;
    }
    container.innerHTML =
      `<div class="coach-facts">${facts}</div>` +
      `<div class="coach-next">下一步：${escapeHtml(nextText)}</div>` +
      (weakList ? `<div class="coach-list">${weakList}</div>` : "");
    refreshIcons();
  }

  async function loadCoachReport({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const state = qs("#coach-state");
    if (!quiet && state) state.textContent = "生成中";
    try {
      const query = learningCourseId ? `?course_id=${encodeURIComponent(learningCourseId)}` : "";
      const report = await apiFetch(`/coach/report${query}`);
      renderCoachReport(report || {});
      coachStateLabel(Boolean(report?.summary?.concept_count), "");
      return true;
    } catch (error) {
      coachStateLabel(false, "读取失败");
      if (!quiet) toast(`教练报告读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  function renderCoachPlan(plan) {
    const container = qs("#coach-plan");
    if (!container) return;
    const summary = plan?.summary || {};
    const days = Array.isArray(plan?.days) ? plan.days : [];
    const hasPlan =
      Number(summary.planned_reviews || 0) > 0 ||
      Number(summary.planned_new_concepts || 0) > 0 ||
      Number(summary.planned_foundations || 0) > 0;
    if (!hasPlan) {
      container.innerHTML = `<div class="learning-empty"><i data-lucide="calendar-range" aria-hidden="true"></i><div><strong>暂无周计划</strong><span>创建知识点并记录答题后，这里会生成未来 7 天的安排。</span></div></div>`;
      refreshIcons();
      return;
    }
    const total =
      Number(summary.planned_reviews || 0) +
      Number(summary.planned_new_concepts || 0) +
      Number(summary.planned_foundations || 0);
    const dayHtml = days.map((day) => {
      const dayDate = new Date(`${day.date}T00:00:00`);
      const label = Number.isNaN(dayDate.getTime())
        ? escapeHtml(day.date || "")
        : escapeHtml(dayDate.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", weekday: "short" }));
      const parts = [];
      if (day.reviews?.length) parts.push(`复习 ${day.reviews.map((item) => escapeHtml(item.name)).join("、")}`);
      if (day.new_concepts?.length) parts.push(`新学 ${day.new_concepts.map((item) => escapeHtml(item.name)).join("、")}`);
      if (day.foundation_concepts?.length) parts.push(`补基础 ${day.foundation_concepts.map((item) => escapeHtml(item.name)).join("、")}`);
      return `<div class="coach-plan-day"><strong>${label}</strong><span>${parts.join(" · ") || "休息或弹性安排"}</span></div>`;
    }).join("");
    container.innerHTML =
      `<div class="coach-next">本周共 ${total} 项 · 复习 ${summary.planned_reviews || 0} · 新学 ${summary.planned_new_concepts || 0} · 补基础 ${summary.planned_foundations || 0} · 预计约 ${summary.estimated_minutes || 0} 分钟</div>` +
      dayHtml;
    refreshIcons();
  }

  async function loadCoachPlan({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const state = qs("#coach-plan-state");
    if (!quiet && state) state.textContent = "生成中";
    try {
      const query = learningCourseId ? `?course_id=${encodeURIComponent(learningCourseId)}` : "";
      const plan = await apiFetch(`/coach/plan${query}`);
      renderCoachPlan(plan || {});
      if (state) state.textContent = "已生成";
      return true;
    } catch (error) {
      if (state) state.textContent = "读取失败";
      if (!quiet) toast(`周计划读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function loadDeepTutorStatus({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const state = qs("#deeptutor-state");
    const message = qs("#deeptutor-message");
    if (!state) return false;
    try {
      const status = await apiFetch("/deeptutor/status");
      const roles = Array.isArray(status?.roles) ? status.roles : [];
      const readyRoles = roles.filter((item) => item.ready === true);
      const roleSelect = qs("#deeptutor-role");
      if (roleSelect && roles.length) {
        const current = roleSelect.value;
        roleSelect.innerHTML = roles
          .filter((item) => item.role === "reasoning" || item.role === "fast")
          .map((item) => {
            const label = item.role === "reasoning" ? "深度推理" : "快速任务";
            return `<option value="${escapeHtml(item.role)}"${item.role === current ? " selected" : ""}>${escapeHtml(label)}${item.ready ? "" : "（未配置）"}</option>`;
          })
          .join("");
      }
      if (!status?.installed) {
        state.className = "status-label is-danger";
        state.textContent = "未安装";
        if (message) message.textContent = "DeepTutor 运行环境不可用";
        return true;
      }
      if (readyRoles.length === 0) {
        state.className = "status-label is-warning";
        state.textContent = "待配置角色";
        if (message) message.textContent = "请先在设置页配置模型角色与密钥";
        return true;
      }
      state.className = "status-label is-success";
      state.textContent = `已就绪（v${escapeHtml(status.version || "?")}）`;
      if (message) message.textContent = `${readyRoles.length} 个模型角色可用`;
      return true;
    } catch (error) {
      state.className = "status-label is-danger";
      state.textContent = "读取失败";
      if (message) message.textContent = error.message;
      if (!quiet) toast(`DeepTutor 状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function runDeepTutor(event) {
    const button = event.currentTarget;
    const message = qs("#deeptutor-message");
    const output = qs("#deeptutor-output");
    if (!backendConnected && !(await ensureBackendConnection())) return;
    const prompt = qs("#deeptutor-prompt")?.value.trim();
    if (!prompt) {
      if (message) message.textContent = "请输入提示词";
      return;
    }
    button.disabled = true;
    if (message) message.textContent = "DeepTutor 正在运行，可能需要数十秒…";
    if (output) {
      output.hidden = false;
      output.textContent = "运行中…";
    }
    try {
      const result = await apiFetch("/deeptutor/run", {
        method: "POST",
        body: JSON.stringify({
          capability: qs("#deeptutor-capability")?.value || "chat",
          role: qs("#deeptutor-role")?.value || "reasoning",
          language: "zh",
          prompt,
          timeout_seconds: 300
        })
      });
      if (output) {
        output.textContent = result.answer || "（未返回内容）";
        output.insertAdjacentHTML(
          "beforeend",
          `<small>模型：${escapeHtml(result.provider)} / ${escapeHtml(result.model)} · ${escapeHtml(result.latency_ms)} ms · 会话 ${escapeHtml(result.session_id || "—")}</small>`
        );
      }
      if (message) message.textContent = `完成（${result.latency_ms} ms）`;
      toast("DeepTutor 调用完成", "sparkles");
    } catch (error) {
      if (message) message.textContent = `失败：${error.message}`;
      if (output) {
        output.hidden = false;
        output.textContent = `调用失败：${error.message}`;
      }
      toast(`DeepTutor 调用失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  async function loadZoteroStatus({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const container = qs("#zotero-status");
    if (!container) return false;
    try {
      const status = await apiFetch("/zotero/status");
      if (!status?.available) {
        container.innerHTML =
          `<span class="status-label is-warning">未检测到数据目录</span>` +
          `<small>${escapeHtml(status?.database_path || "尚未配置 Zotero 数据目录")}</small>`;
        return true;
      }
      const sync = status.last_sync;
      const last = !sync
        ? "尚未同步，可点击“同步 Zotero”"
        : sync.status === "success"
          ? `最近同步：${formatLearningDateTime(sync.finished_at)} · ${sync.item_count} 条条目 / ${sync.collection_count} 个集合 / ${sync.attachment_count} 个附件`
          : `上次同步失败：${escapeHtml(sync.error || "未知错误")}`;
      const autoSync = status.auto_sync_enabled
        ? ` · 自动同步每 ${status.auto_sync_interval_hours || 6} 小时`
        : " · 自动同步未启用";
      container.innerHTML = `<span class="status-label is-success">数据目录已就绪</span><small>${escapeHtml(last)}${autoSync}</small>`;
      return true;
    } catch (error) {
      container.innerHTML = `<span class="status-label is-danger">读取失败</span><small>${escapeHtml(error.message)}</small>`;
      if (!quiet) toast(`Zotero 状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function syncZotero(event) {
    const button = event.currentTarget;
    if (!backendConnected && !(await ensureBackendConnection())) return;
    button.disabled = true;
    try {
      const result = await apiFetch("/zotero/sync", { method: "POST" });
      toast(`Zotero 同步完成：${result.items} 条条目、${result.attachments} 个附件`, "library");
      await loadZoteroStatus({ quiet: true });
    } catch (error) {
      toast(`Zotero 同步失败：${error.message}`, "circle-alert");
      await loadZoteroStatus({ quiet: true });
    } finally {
      button.disabled = false;
    }
  }

  async function loadOpsStatus({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    const container = qs("#ops-status");
    if (!container) return false;
    try {
      const status = await apiFetch("/ops/status");
      const database = status?.database || {};
      const storage = status?.storage || {};
      const backup = status?.backup;
      const settings = status?.backup_settings || {};
      const enabledInput = qs("#backup-enabled");
      const intervalInput = qs("#backup-interval");
      const keepInput = qs("#backup-keep");
      if (enabledInput) enabledInput.checked = settings.enabled === true;
      if (intervalInput) intervalInput.value = settings.interval_hours ?? 24;
      if (keepInput) keepInput.value = settings.keep_count ?? 14;
      const freeGb = (Number(storage.free_bytes) || 0) / 1024 ** 3;
      const facts = [
        ["完整性检查", `${database.quick_check || "—"}`],
        ["磁盘剩余", `${freeGb.toFixed(1)} GB（${Number(storage.free_percent) || 0}%）`],
        ["最近备份", backup ? `${backup.age_days} 天前` : "无"],
        ["数据库大小", `${Math.max(1, Math.round((Number(database.size_bytes) || 0) / 1024))} KB`]
      ].map(([label, value]) =>
        `<div class="ops-fact"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`
      ).join("");
      const warnings = (status?.warnings || [])
        .map((warning) => `<div class="coach-list-item"><strong>${escapeHtml(warning)}</strong></div>`)
        .join("");
      container.innerHTML =
        `<div class="ops-facts">${facts}</div>` +
        (warnings ? `<div class="ops-list">${warnings}</div>` : "");
      return true;
    } catch (error) {
      container.innerHTML = `<span class="status-label is-danger">读取失败</span><small>${escapeHtml(error.message)}</small>`;
      if (!quiet) toast(`运维状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function runBackup(event) {
    const button = event.currentTarget;
    if (!backendConnected && !(await ensureBackendConnection())) return;
    button.disabled = true;
    try {
      const result = await apiFetch("/ops/backup", { method: "POST" });
      toast(`备份完成：${result.path.split(/[\\/]/).pop()}（完整性 ${result.quick_check}）`, "database-backup");
      await loadOpsStatus({ quiet: true });
    } catch (error) {
      toast(`备份失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  async function saveBackupSettings(event) {
    const button = event.currentTarget;
    const message = qs("#backup-settings-message");
    if (!backendConnected && !(await ensureBackendConnection())) return;
    button.disabled = true;
    if (message) message.textContent = "保存中…";
    try {
      const enabled = qs("#backup-enabled")?.checked === true;
      const intervalHours = Math.max(1, Math.min(720, Number(qs("#backup-interval")?.value) || 24));
      const keepCount = Math.max(1, Math.min(365, Number(qs("#backup-keep")?.value) || 14));
      const result = await apiFetch("/ops/backup/settings", {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          interval_hours: intervalHours,
          keep_count: keepCount
        })
      });
      const enabledInput = qs("#backup-enabled");
      const intervalInput = qs("#backup-interval");
      const keepInput = qs("#backup-keep");
      if (enabledInput) enabledInput.checked = result.enabled === true;
      if (intervalInput) intervalInput.value = result.interval_hours;
      if (keepInput) keepInput.value = result.keep_count;
      if (message) message.textContent = "备份设置已保存";
      toast("备份设置已保存", "save");
      await loadOpsStatus({ quiet: true });
    } catch (error) {
      if (message) message.textContent = "保存失败";
      toast(`备份设置保存失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  function renderBrowserActions(actions) {
    const container = qs("#browser-actions");
    if (!container) return;
    const items = Array.isArray(actions) ? actions : [];
    if (!items.length) {
      container.innerHTML = `<div class="learning-empty"><i data-lucide="globe" aria-hidden="true"></i><div><strong>暂无浏览器动作</strong><span>由本地 API 或 MCP 提交的动作会出现在这里等待审批。</span></div></div>`;
      refreshIcons();
      return;
    }
    const statusClass = {
      pending: "is-warning",
      executing: "is-warning",
      succeeded: "is-success",
      failed: "is-danger",
      rejected: "is-neutral",
      stopped: "is-neutral"
    };
    const riskLabel = { low: "低", medium: "中", high: "高" };
    const rows = items.map((item) => {
      const target = item.action === "open"
        ? item.url || ""
        : item.action === "snapshot"
          ? "当前页面快照"
          : `${item.selector || ""}${item.text ? ` → ${item.text}` : ""}`;
      const buttons = item.status === "pending"
        ? `<div class="field-action"><button class="secondary-button browser-approve" type="button" data-id="${escapeHtml(item.id)}"><i data-lucide="check" aria-hidden="true"></i><span>批准</span></button><button class="secondary-button browser-reject" type="button" data-id="${escapeHtml(item.id)}"><i data-lucide="x" aria-hidden="true"></i><span>拒绝</span></button></div>`
        : "";
      return `<article class="browser-action-row"><div><strong>${escapeHtml(item.action)} · ${riskLabel[item.risk] || item.risk} 风险</strong><span>${escapeHtml(target)}</span></div><span class="status-label ${statusClass[item.status] || "is-neutral"}">${escapeHtml(item.status)}</span>${buttons}</article>`;
    }).join("");
    container.innerHTML = rows;
    refreshIcons();
    qsa(".browser-approve", container).forEach((button) =>
      button.addEventListener("click", () => approveBrowserAction(button.dataset.id))
    );
    qsa(".browser-reject", container).forEach((button) =>
      button.addEventListener("click", () => rejectBrowserAction(button.dataset.id))
    );
  }

  async function loadBrowserStatus({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    try {
      const status = await apiFetch("/browser/status");
      const input = qs("#browser-allowlist");
      if (input) input.value = (status?.allowlist || []).join(", ");
      const state = qs("#browser-state");
      if (state) {
        if (status?.emergency_stopped) {
          state.textContent = "已紧急停止";
          state.className = "status-label is-danger";
        } else if (!status?.available) {
          state.textContent = "Playwright 未安装";
          state.className = "status-label is-warning";
        } else {
          state.textContent = `可用 · 待审批 ${status?.pending_count || 0}`;
          state.className = "status-label is-success";
        }
      }
      const message = qs("#browser-message");
      if (message) {
        message.textContent = status?.emergency_stopped
          ? "紧急停止已触发，恢复前不接受新动作"
          : `白名单 ${(status?.allowlist || []).length} 个域名 · 最近记录 ${status?.recent_count || 0} 条`;
      }
      return true;
    } catch (error) {
      if (!quiet) toast(`浏览器状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function loadBrowserActions({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) return false;
    try {
      const payload = await apiFetch("/browser/actions");
      renderBrowserActions(Array.isArray(payload) ? payload : []);
      return true;
    } catch (error) {
      if (!quiet) toast(`浏览器动作读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function saveBrowserAllowlist() {
    const input = qs("#browser-allowlist");
    const domains = (input?.value || "").split(",").map((value) => value.trim()).filter(Boolean);
    try {
      const result = await apiFetch("/browser/allowlist", {
        method: "PUT",
        body: JSON.stringify({ domains })
      });
      toast(`浏览器白名单已保存：${(result?.allowlist || []).join(", ")}`, "save");
      await loadBrowserStatus({ quiet: true });
    } catch (error) {
      toast(`白名单保存失败：${error.message}`, "circle-alert");
    }
  }

  async function approveBrowserAction(actionId) {
    try {
      const result = await apiFetch(`/browser/actions/${encodeURIComponent(actionId)}/approve`, { method: "POST" });
      toast(`浏览器动作已执行：${result?.status || "succeeded"}`, "check-circle-2");
      await loadBrowserActions({ quiet: true });
      await loadBrowserStatus({ quiet: true });
    } catch (error) {
      toast(`浏览器动作执行失败：${error.message}`, "circle-alert");
      await loadBrowserActions({ quiet: true });
      await loadBrowserStatus({ quiet: true });
    }
  }

  async function rejectBrowserAction(actionId) {
    try {
      await apiFetch(`/browser/actions/${encodeURIComponent(actionId)}/reject`, { method: "POST" });
      toast("浏览器动作已拒绝", "x");
      await loadBrowserActions({ quiet: true });
      await loadBrowserStatus({ quiet: true });
    } catch (error) {
      toast(`拒绝失败：${error.message}`, "circle-alert");
    }
  }

  async function browserStop() {
    try {
      await apiFetch("/browser/stop", { method: "POST" });
      toast("已紧急停止浏览器自动化", "octagon-alert");
      await loadBrowserStatus({ quiet: true });
      await loadBrowserActions({ quiet: true });
    } catch (error) {
      toast(`紧急停止失败：${error.message}`, "circle-alert");
    }
  }

  async function browserResume() {
    try {
      await apiFetch("/browser/resume", { method: "POST" });
      toast("浏览器自动化已恢复", "play-circle");
      await loadBrowserStatus({ quiet: true });
    } catch (error) {
      toast(`恢复失败：${error.message}`, "circle-alert");
    }
  }

  function loadState() {
    try {
      const loaded = { ...defaultState, ...JSON.parse(localStorage.getItem(stateKey) || "{}") };
      if (!loaded.dataPath || loaded.dataPath === "D:\\AI-PC") loaded.dataPath = "C:\\AI-PC";
      return loaded;
    } catch {
      return { ...defaultState };
    }
  }

  function saveState() {
    try {
      // API keys deliberately never enter this object or localStorage.
      localStorage.setItem(stateKey, JSON.stringify(state));
    } catch {
      // The dashboard remains usable when browser storage is unavailable.
    }
  }

  function refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons({ attrs: { width: 16, height: 16, "stroke-width": 1.8 } });
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    }[character]));
  }

  function toast(message, icon = "check-circle-2") {
    const region = qs("#toast-region");
    if (!region) return;
    const item = document.createElement("div");
    item.className = "toast";
    item.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${escapeHtml(message)}</span>`;
    region.appendChild(item);
    refreshIcons();
    window.setTimeout(() => item.remove(), 3600);
  }

  function updateCounters() {
    const indexed = qs("#indexed-count");
    const projects = qs("#project-count");
    const agents = qs("#agent-count");
    if (indexed) indexed.textContent = state.indexedCount;
    if (projects) projects.textContent = state.projectCount;
    if (agents) agents.textContent = state.agentCount;
  }

  function setTheme(theme) {
    state.theme = theme;
    document.documentElement.dataset.theme = theme;
    const button = qs("#theme-toggle");
    if (button) {
      button.innerHTML = `<i data-lucide="${theme === "dark" ? "sun" : "moon"}" aria-hidden="true"></i>`;
      button.setAttribute("aria-label", theme === "dark" ? "切换到浅色主题" : "切换到深色主题");
      button.dataset.tooltip = theme === "dark" ? "浅色主题" : "深色主题";
    }
    saveState();
    refreshIcons();
  }

  const pageNames = {
    overview: ["工作台", "总览"],
    chat: ["本地知识助手", "AI 对话"],
    learning: ["个人进度", "学习"],
    library: ["本地知识", "资料库"],
    research: ["研究工作台", "科研"],
    coding: ["Agent 工作区", "编程"],
    automation: ["任务与工具", "自动化"],
    settings: ["系统配置", "设置"]
  };

  function showPage(pageName) {
    const page = qs(`#page-${pageName}`);
    if (!page) return;
    qsa(".page").forEach((item) => item.classList.toggle("is-active", item === page));
    qsa(".nav-item[data-page]").forEach((item) => {
      const active = item.dataset.page === pageName;
      item.classList.toggle("is-active", active);
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    const labels = pageNames[pageName] || ["工作台", pageName];
    qs("#page-eyebrow").textContent = labels[0];
    qs("#page-title").textContent = labels[1];
    qs("#sidebar")?.classList.remove("is-open");
    qs("#mobile-scrim")?.classList.remove("is-visible");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openDialog(id) {
    const dialog = qs(id);
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closeDialog(id) {
    const dialog = qs(id);
    if (dialog?.open) dialog.close();
  }

  function normalizeLibraryPayload(payload) {
    if (Array.isArray(payload)) return payload;
    for (const key of ["results", "items", "documents"]) {
      if (Array.isArray(payload?.[key])) return payload[key];
    }
    return [];
  }

  function libraryType(item) {
    const raw = String(item.document_type || item.type || "文件").toUpperCase();
    if (["MD", "MARKDOWN", "TXT", "NOTE", "NOTES"].includes(raw)) return { filter: "笔记", label: raw === "MARKDOWN" ? "MD" : raw === "NOTE" || raw === "NOTES" ? "笔记" : raw, icon: "notebook-text" };
    if (raw === "PDF") return { filter: "PDF", label: "PDF", icon: "file-text" };
    return { filter: "其他", label: raw, icon: "file-question" };
  }

  function isIndexedLibraryDocument(item) {
    const type = String(item.document_type || item.type || "").toUpperCase();
    const supported = ["PDF", "MD", "MARKDOWN", "TXT"].includes(type);
    const indexed = Boolean(item.source_path || item.content_hash || item.indexed_at);
    return supported && indexed;
  }

  function libraryStatus(item) {
    const value = String(item.status || "ready").toLowerCase().replaceAll("_", "-");
    if (["ready", "indexed", "available", "可用"].includes(value)) return { key: "ready", label: "可用", className: "is-success" };
    if (["needs-review", "review", "warning", "error", "需检查"].includes(value)) return { key: "needs-review", label: "需检查", className: "is-warning" };
    return { key: "pending", label: "处理中", className: "is-neutral" };
  }

  function librarySourcePath(item) {
    return item.source_path || item.location || item.path || item.source || "";
  }

  function libraryTitle(item) {
    if (item.title) return item.title;
    const sourcePath = librarySourcePath(item);
    return sourcePath.split(/[\\/]/).filter(Boolean).pop() || "未命名资料";
  }

  function safeSnippetHtml(value) {
    return escapeHtml(value || "")
      .replace(/&lt;mark&gt;/gi, "<mark>")
      .replace(/&lt;\/mark&gt;/gi, "</mark>");
  }

  function formatFileSize(value) {
    if (value === null || value === undefined || value === "") return "";
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
    return `${(bytes / 1024 ** 4).toFixed(1)} TB`;
  }

  function updateStorageFromApi(overview) {
    const total = Number(overview.storage_total_bytes);
    const used = Number(overview.storage_used_bytes);
    const free = Number(overview.storage_free_bytes);
    if (![total, used, free].every(Number.isFinite) || total <= 0) return;
    if (qs("#storage-used")) qs("#storage-used").textContent = formatFileSize(used);
    if (qs("#storage-total")) qs("#storage-total").textContent = formatFileSize(total);
    if (qs("#storage-free")) qs("#storage-free").textContent = formatFileSize(free);
    if (qs("#storage-root")) qs("#storage-root").textContent = overview.storage_root || "C:\\AI-PC";
    const fill = qs("#storage-meter-fill");
    if (fill) fill.style.width = `${Math.min(100, Math.max(0, used / total * 100)).toFixed(1)}%`;
  }

  async function loadSemanticStatus() {
    const label = qs("#semantic-index-state");
    if (!label) return null;
    if (!backendConnected) {
      label.textContent = "服务未连接";
      return null;
    }
    try {
      const status = await apiFetch("/library/semantic/status");
      const points = Number(status?.point_count);
      if (status?.available) {
        label.textContent = Number.isFinite(points) ? `可用 · ${points} 个片段` : "本地 BGE 可用";
        label.title = status.model_name || "本地语义索引";
      } else {
        label.textContent = "SQLite 回退";
        label.title = status?.reason || "语义索引暂不可用";
      }
      return status;
    } catch (error) {
      label.textContent = "状态未知";
      label.title = error.message;
      return null;
    }
  }

  async function rebuildSemanticIndex(event) {
    const button = event.currentTarget;
    if (!backendConnected && !(await ensureBackendConnection())) {
      toast("本地服务未连接，无法重建索引", "wifi-off");
      return;
    }
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i>';
    refreshIcons();
    try {
      const result = await apiFetch("/library/semantic/rebuild", { method: "POST" });
      toast(`语义索引已重建：${result.chunks_indexed} 个片段`, "database-zap");
    } catch (error) {
      toast(`语义索引未完成：${error.message}；关键词检索仍可用`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="refresh-cw" aria-hidden="true"></i>';
      refreshIcons();
      await loadSemanticStatus();
    }
  }

  function formatLibraryPosition(item) {
    const parts = [];
    const page = item.page ?? item.page_number;
    const paragraph = item.paragraph ?? item.paragraph_number;
    const rawChunkIndex = item.chunk_index ?? item.chunk_number;
    const chunk = rawChunkIndex !== null && rawChunkIndex !== undefined
      ? Number(rawChunkIndex) + 1
      : (typeof item.chunk === "number" ? item.chunk : null);
    if (page !== null && page !== undefined) parts.push(`第 ${page} 页`);
    if (paragraph !== null && paragraph !== undefined) parts.push(`段落 ${paragraph}`);
    if (chunk !== null && chunk !== undefined) parts.push(`片段 ${chunk}`);
    if (!parts.length && Number(item.chunk_count) > 0) parts.push(`${item.chunk_count} 个片段`);
    return parts.join(" · ") || "—";
  }

  function librarySnippet(item) {
    const snippet = item.snippet || (typeof item.chunk === "string" ? item.chunk : item.content || "");
    if (snippet) return safeSnippetHtml(snippet);
    const details = [formatFileSize(item.file_size), item.indexed_at ? "已建立索引" : ""].filter(Boolean);
    return escapeHtml(details.join(" · ") || "—");
  }

  function libraryRow(item) {
    const type = libraryType(item);
    const status = libraryStatus(item);
    const sourcePath = librarySourcePath(item);
    return `<tr data-type="${escapeHtml(type.filter)}" data-status="${escapeHtml(status.key)}">
      <td><div class="document-name"><i data-lucide="${type.icon}" aria-hidden="true"></i><span><strong>${escapeHtml(libraryTitle(item))}</strong><small>${escapeHtml(type.label)}</small></span></div></td>
      <td class="source-path" title="${escapeHtml(sourcePath)}"><span>${escapeHtml(sourcePath || "—")}</span></td>
      <td class="citation-position">${escapeHtml(formatLibraryPosition(item))}</td>
      <td class="document-snippet">${librarySnippet(item)}</td>
      <td><span class="status-label ${status.className}">${status.label}</span></td>
    </tr>`;
  }

  function setLibraryState(kind, title = "", detail = "", { showTable = false, retry = false } = {}) {
    const panel = qs(".library-table-panel");
    const status = qs("#library-state");
    const table = qs("#library-table-wrap");
    const retryButton = qs("#library-retry");
    if (!status || !table) return;
    panel?.setAttribute("aria-busy", kind === "loading" ? "true" : "false");
    status.hidden = kind === "ready";
    status.dataset.state = kind;
    table.hidden = kind === "ready" ? false : !showTable;
    if (qs("#library-state-title")) qs("#library-state-title").textContent = title;
    if (qs("#library-state-detail")) qs("#library-state-detail").textContent = detail;
    if (retryButton) retryButton.hidden = !retry;
    const icon = qs("#library-state > svg, #library-state > i");
    if (icon) {
      icon.setAttribute("data-lucide", ({ loading: "loader-circle", error: "circle-alert", empty: "search-x", offline: "wifi-off" })[kind] || "info");
    }
    refreshIcons();
  }

  function renderLibraryItems() {
    const typeFilter = qs("#library-type")?.value || "all";
    const statusFilter = qs("#library-status")?.value || "all";
    const filtered = libraryItems.filter((item) => {
      const type = libraryType(item).filter;
      const status = libraryStatus(item).key;
      return (typeFilter === "all" || type === typeFilter) && (statusFilter === "all" || status === statusFilter);
    });
    const body = qs("#library-table tbody");
    if (body) body.innerHTML = filtered.map(libraryRow).join("");
    const count = qs("#library-result-count");
    if (count) count.textContent = `${filtered.length} 条结果`;
    if (!filtered.length) {
      const searched = libraryDataMode === "search";
      setLibraryState("empty", searched ? "没有找到相关内容" : "资料库还是空的", searched ? "换一个关键词，或清除筛选条件后重试。" : "输入本机文件或文件夹路径即可开始建立索引。");
    } else {
      setLibraryState("ready");
    }
    refreshIcons();
  }

  function showLibraryOffline(title = "本地服务未连接", detail = "启动本地服务后可导入路径并检索资料。") {
    const body = qs("#library-table tbody");
    if (body) body.innerHTML = "";
    libraryItems = [];
    libraryDataMode = "offline";
    if (qs("#library-result-count")) qs("#library-result-count").textContent = "—";
    if (qs("#library-file-count")) qs("#library-file-count").textContent = "服务未连接";
    setLibraryState("offline", title, detail, { retry: true });
    refreshIcons();
  }

  function filterLibrary() {
    if (libraryDataMode === "offline") showLibraryOffline();
    else renderLibraryItems();
  }

  async function ensureBackendConnection() {
    if (backendConnected) return true;
    if (window.location.protocol === "file:") return false;
    try {
      const health = await apiFetch("/health");
      const connected = health?.status === "ok";
      setServiceStatus(connected);
      return connected;
    } catch {
      setServiceStatus(false);
      return false;
    }
  }

  async function loadLibraryDocuments({ quiet = false } = {}) {
    libraryLastRequest = { kind: "documents", query: "" };
    qs("#documents-title").textContent = "资料列表";
    if (!backendConnected && !quiet) await ensureBackendConnection();
    if (!backendConnected) {
      showLibraryOffline();
      if (!quiet) toast("本地服务尚未连接", "wifi-off");
      return;
    }
    const requestId = ++libraryRequestSerial;
    setLibraryState("loading", "正在读取资料库", "正在读取本地文档索引。");
    if (qs("#library-result-count")) qs("#library-result-count").textContent = "读取中";
    try {
      const payload = await apiFetch("/library/documents");
      if (requestId !== libraryRequestSerial) return;
      libraryItems = normalizeLibraryPayload(payload).filter(isIndexedLibraryDocument);
      libraryDataMode = "documents";
      renderLibraryItems();
      state.indexedCount = libraryItems.length;
      if (qs("#library-file-count")) qs("#library-file-count").textContent = `${libraryItems.length} 个文件`;
      if (qs("#indexed-status")) qs("#indexed-status").textContent = "本地索引";
      updateCounters();
      saveState();
      if (!quiet) toast("资料列表已刷新", "refresh-cw");
    } catch (error) {
      if (requestId !== libraryRequestSerial) return;
      showLibraryOffline("未能读取资料库", error.message);
    }
  }

  async function searchLibrary(query) {
    const value = query.trim();
    const clearButton = qs("#library-search-clear");
    if (clearButton) clearButton.hidden = !value;
    if (!value) {
      await loadLibraryDocuments({ quiet: true });
      return;
    }
    libraryLastRequest = { kind: "search", query: value };
    qs("#documents-title").textContent = "检索结果";
    if (!backendConnected) await ensureBackendConnection();
    if (!backendConnected) {
      showLibraryOffline("无法搜索资料库", "本地服务未连接，恢复服务后再重试。");
      return;
    }
    const requestId = ++libraryRequestSerial;
    setLibraryState("loading", "正在检索索引", `关键词：${value}`);
    if (qs("#library-result-count")) qs("#library-result-count").textContent = "检索中";
    try {
      const payload = await apiFetch(`/library/search?q=${encodeURIComponent(value)}&limit=20&mode=${encodeURIComponent(librarySearchMode)}`);
      if (requestId !== libraryRequestSerial) return;
      libraryItems = normalizeLibraryPayload(payload);
      libraryDataMode = "search";
      renderLibraryItems();
    } catch (error) {
      if (requestId !== libraryRequestSerial) return;
      setLibraryState("error", "检索失败", error.message, { showTable: libraryItems.length > 0, retry: true });
      if (qs("#library-result-count")) qs("#library-result-count").textContent = "检索失败";
    }
  }

  async function importLibraryPath(event) {
    event.preventDefault();
    const input = qs("#library-import-path");
    const button = qs("#library-import-submit");
    const feedback = qs("#library-import-feedback");
    const path = input?.value.trim() || "";
    if (!path) {
      if (feedback) { feedback.textContent = "请输入文件或文件夹路径。"; feedback.dataset.state = "error"; }
      input?.focus();
      return;
    }
    if (!backendConnected) await ensureBackendConnection();
    if (!backendConnected) {
      if (feedback) { feedback.textContent = "本地服务未连接，暂时无法读取该路径。"; feedback.dataset.state = "error"; }
      toast("启动本地服务后再导入资料", "wifi-off");
      return;
    }
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>正在索引</span>';
    if (feedback) { feedback.textContent = "正在读取路径并建立索引…"; feedback.dataset.state = "loading"; }
    refreshIcons();
    try {
      const result = await apiFetch("/library/import", { method: "POST", body: JSON.stringify({ path }) });
      const changed = result?.changed === true || result?.imported === true || result?.rebuilt === true;
      const chunkCount = Number(result?.chunks_indexed || result?.document?.chunk_count || 0);
      const message = changed
        ? `资料已导入并建立索引${chunkCount ? `（${chunkCount} 个片段）` : ""}。`
        : "相同内容已存在，无需重复导入。";
      if (feedback) { feedback.textContent = message; feedback.dataset.state = "success"; }
      toast(message, changed ? "file-check-2" : "copy-check");
      await loadLibraryDocuments({ quiet: true });
      await loadSemanticStatus();
    } catch (error) {
      if (feedback) { feedback.textContent = error.message; feedback.dataset.state = "error"; }
      toast(`导入失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="scan-line" aria-hidden="true"></i><span>导入并索引</span>';
      refreshIcons();
    }
  }

  function safeExternalUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function setResearchTrace(project) {
    const flags = {
      project: Boolean(project?.question),
      search: researchSearches.length > 0,
      screen: researchScreening.length > 0,
      note: researchNotes.length > 0
    };
    let completed = 0;
    qsa("#research-trace-list [data-trace]").forEach((item) => {
      const done = Boolean(flags[item.dataset.trace]);
      completed += Number(done);
      item.classList.toggle("is-done", done);
      const icon = qs("svg, i", item);
      if (icon) icon.setAttribute("data-lucide", done ? "check-circle-2" : "circle");
    });
    if (qs("#research-trace-count")) qs("#research-trace-count").textContent = `${completed} / 4`;
    refreshIcons();
  }

  function updateResearchScreeningSummary() {
    const counts = { pending: 0, include: 0, maybe: 0, exclude: 0 };
    researchPapers.forEach((paper) => {
      const decision = paper.screening_decision;
      if (decision && decision in counts) counts[decision] += 1;
      else counts.pending += 1;
    });
    Object.entries(counts).forEach(([key, value]) => {
      if (qs(`#screening-${key}`)) qs(`#screening-${key}`).textContent = value;
    });
    const next = qs("#research-next-action");
    if (next) {
      next.textContent = !researchProjectId
        ? "创建项目后开始检索"
        : !researchSearches.length
          ? "运行首次文献检索"
          : counts.pending > 0
            ? `筛选 ${counts.pending} 篇候选文献`
            : "记录当前筛选结论";
    }
  }

  function researchDecisionOptions(selected) {
    const options = [
      ["", "待筛选"],
      ["include", "纳入"],
      ["maybe", "待定"],
      ["exclude", "排除"]
    ];
    return options.map(([value, label]) => `<option value="${value}"${selected === value ? " selected" : ""}>${label}</option>`).join("");
  }

  function renderResearchPapers() {
    const body = qs("#research-paper-body");
    const wrap = qs("#research-paper-wrap");
    const empty = qs("#research-paper-empty");
    if (body) {
      body.innerHTML = researchPapers.map((paper) => {
        const url = safeExternalUrl(paper.url);
        const title = escapeHtml(paper.title || "未命名论文");
        const titleMarkup = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title;
        const authors = Array.isArray(paper.authors) && paper.authors.length ? paper.authors.join(", ") : "作者未知";
        const identifier = paper.doi ? `DOI ${paper.doi}` : "无 DOI";
        const providers = Array.isArray(paper.providers)
          ? paper.providers.map((provider) => ({ crossref: "Crossref", openalex: "OpenAlex" })[provider] || provider).join(" + ")
          : "—";
        return `<tr data-paper-id="${Number(paper.id)}">
          <td><strong>${titleMarkup}</strong><small>${escapeHtml(authors)} · ${escapeHtml(identifier)}</small></td>
          <td>${escapeHtml(paper.publication_year ?? "—")}</td>
          <td>${escapeHtml(providers)}</td>
          <td>${escapeHtml(paper.citation_count ?? "—")}</td>
          <td><select data-screen-paper="${Number(paper.id)}" aria-label="${escapeHtml(paper.title || "论文")}的筛选状态">${researchDecisionOptions(paper.screening_decision || "")}</select></td>
        </tr>`;
      }).join("");
    }
    if (wrap) wrap.hidden = researchPapers.length === 0;
    if (empty) empty.hidden = researchPapers.length > 0;
    if (qs("#research-paper-count")) qs("#research-paper-count").textContent = `${researchPapers.length} 篇`;
    updateResearchScreeningSummary();
  }

  function clearResearchProject(message = "尚未选择科研项目") {
    researchProjectId = "";
    researchSearches = [];
    researchPapers = [];
    researchScreening = [];
    researchNotes = [];
    if (qs("#research-question-title")) qs("#research-question-title").textContent = message;
    if (qs("#research-intro-status")) qs("#research-intro-status").textContent = researchProjects.length ? `${researchProjects.length} 个项目 · 请选择一个项目` : message;
    if (qs("#research-project-name")) qs("#research-project-name").textContent = "—";
    if (qs("#research-project-type")) qs("#research-project-type").textContent = "—";
    if (qs("#research-search-count")) qs("#research-search-count").textContent = "0 次";
    if (qs("#research-project-status")) qs("#research-project-status").textContent = "—";
    if (qs("#research-project-state")) { qs("#research-project-state").textContent = "暂无项目"; qs("#research-project-state").className = "status-label is-neutral"; }
    if (qs("#research-search-source")) qs("#research-search-source").textContent = "尚未检索";
    if (qs("#research-note")) { qs("#research-note").value = ""; qs("#research-note").disabled = true; }
    if (qs("#save-note")) qs("#save-note").disabled = true;
    if (qs("#note-save-state")) qs("#note-save-state").textContent = "未选择项目";
    renderResearchPapers();
    setResearchTrace(null);
  }

  function renderResearchProject(project, latestSearch) {
    if (qs("#research-question-title")) qs("#research-question-title").textContent = project.question;
    if (qs("#research-project-name")) qs("#research-project-name").textContent = project.name;
    if (qs("#research-project-type")) qs("#research-project-type").textContent = project.research_type;
    if (qs("#research-search-count")) qs("#research-search-count").textContent = `${researchSearches.length} 次`;
    if (qs("#research-project-status")) qs("#research-project-status").textContent = project.status === "active" ? "进行中" : project.status;
    if (qs("#research-project-state")) { qs("#research-project-state").textContent = "本地记录"; qs("#research-project-state").className = "status-label is-success"; }
    if (qs("#research-intro-status")) qs("#research-intro-status").textContent = `${researchProjects.length} 个项目 · 当前：${project.name}`;
    const searchSource = qs("#research-search-source");
    if (searchSource) {
      const providers = Array.isArray(latestSearch?.search?.providers) ? latestSearch.search.providers.map((provider) => provider === "crossref" ? "Crossref" : provider === "openalex" ? "OpenAlex" : provider).join(" + ") : "";
      searchSource.textContent = latestSearch ? `${providers} · ${latestSearch.search.result_count} 篇` : "尚未检索";
    }
    const query = qs("#research-search-query");
    if (query) query.value = latestSearch?.search?.query || project.question;
    const feedback = qs("#research-search-feedback");
    if (feedback) {
      feedback.textContent = latestSearch
        ? `最近检索：${latestSearch.search.query} · ${formatLearningDateTime(latestSearch.search.created_at)}`
        : "尚未运行文献检索";
      feedback.dataset.state = latestSearch ? "success" : "";
    }
    if (qs("#research-note")) { qs("#research-note").disabled = false; qs("#research-note").value = researchNotes[0]?.body || ""; }
    if (qs("#save-note")) qs("#save-note").disabled = false;
    if (qs("#note-save-state")) qs("#note-save-state").textContent = researchNotes.length ? `已保存 ${formatLearningDateTime(researchNotes[0].created_at)}` : "未保存";
    renderResearchPapers();
    setResearchTrace(project);
  }

  async function loadResearchProject(projectId) {
    const project = researchProjects.find((item) => String(item.id) === String(projectId));
    if (!project) { clearResearchProject(); return; }
    researchProjectId = String(project.id);
    if (qs("#research-project-select")) qs("#research-project-select").value = researchProjectId;
    try {
      [researchSearches, researchScreening, researchNotes] = await Promise.all([
        apiFetch(`/research/projects/${project.id}/searches?limit=50`),
        apiFetch(`/research/projects/${project.id}/screening`),
        apiFetch(`/research/projects/${project.id}/notes`)
      ]);
      const latestSearch = researchSearches[0]
        ? await apiFetch(`/research/searches/${researchSearches[0].id}`)
        : null;
      researchPapers = latestSearch?.papers || [];
      renderResearchProject(project, latestSearch);
    } catch (error) {
      clearResearchProject("科研记录暂时无法读取");
      if (qs("#research-search-feedback")) { qs("#research-search-feedback").textContent = error.message; qs("#research-search-feedback").dataset.state = "error"; }
    }
  }

  async function loadResearchProjects({ quiet = false, selectedId = null } = {}) {
    if (!backendConnected) {
      clearResearchProject("本地服务未连接");
      return;
    }
    try {
      researchProjects = await apiFetch("/research/projects");
      const select = qs("#research-project-select");
      if (select) {
        select.innerHTML = `<option value="">${researchProjects.length ? "选择项目" : "暂无项目"}</option>${researchProjects.map((project) => `<option value="${Number(project.id)}">${escapeHtml(project.name)}</option>`).join("")}`;
      }
      state.projectCount = researchProjects.length;
      if (qs("#project-count")) qs("#project-count").textContent = researchProjects.length;
      const preferred = selectedId || (researchProjects.some((item) => String(item.id) === researchProjectId) ? researchProjectId : researchProjects[0]?.id);
      if (preferred) await loadResearchProject(preferred);
      else clearResearchProject();
      if (!quiet) toast("科研项目已刷新", "refresh-cw");
    } catch (error) {
      clearResearchProject("科研项目暂时无法读取");
      if (!quiet) toast(`科研项目读取失败：${error.message}`, "circle-alert");
    }
  }

  function paperqaStatusLabel(status) {
    if (!status) return { text: "不可用", tone: "is-danger" };
    if (status.ready) return { text: "就绪 · 可提问", tone: "is-success" };
    const reasons = [];
    if (!status.llm?.ready) {
      reasons.push(
        status.llm?.error === "credential_missing"
          ? "缺少模型密钥"
          : status.llm?.error === "credential_store_unavailable"
            ? "凭据存储不可用"
            : "模型角色未配置"
      );
    }
    if (!status.index?.built) reasons.push("未建立索引");
    return { text: reasons.join(" · ") || "未就绪", tone: "is-warning" };
  }

  function setPaperQAAskEnabled(enabled) {
    qsa("#paperqa-ask-form input, #paperqa-ask-form select, #paperqa-ask-form button")
      .forEach((control) => { control.disabled = !enabled; });
  }

  function setPaperQAIndexEnabled(enabled) {
    qsa("#paperqa-index-form input, #paperqa-index-form select, #paperqa-index-form button")
      .forEach((control) => { control.disabled = !enabled; });
  }

  function setPaperQAUnavailable(detail) {
    paperqaStatus = null;
    const label = qs("#paperqa-status");
    if (label) { label.textContent = "不可用"; label.className = "status-label is-danger"; }
    const feedback = qs("#paperqa-feedback");
    if (feedback) { feedback.textContent = detail; feedback.dataset.state = "error"; }
    setPaperQAAskEnabled(false);
    setPaperQAIndexEnabled(false);
  }

  async function loadPaperQAStatus({ quiet = false } = {}) {
    if (!backendConnected) {
      setPaperQAUnavailable("本地服务未连接");
      return;
    }
    try {
      paperqaStatus = await apiFetch("/paperqa/status");
      const status = paperqaStatus;
      const label = qs("#paperqa-status");
      if (label) {
        const presentation = paperqaStatusLabel(status);
        label.textContent = presentation.text;
        label.className = `status-label ${presentation.tone}`;
      }
      const indexPath = qs("#paperqa-index-path-label");
      if (indexPath) indexPath.textContent = status?.index_path || "…";
      const feedback = qs("#paperqa-feedback");
      if (feedback) {
        const index = status?.index;
        if (status?.ready) feedback.textContent = `索引 ${index?.document_count ?? 0} 篇文档 · 可以提问`;
        else if (index?.built) feedback.textContent = `已索引 ${index?.document_count ?? 0} 篇文档 · 配置模型角色后即可提问`;
        else feedback.textContent = "先建立索引，再配置模型角色即可提问";
        feedback.dataset.state = "idle";
      }
      setPaperQAAskEnabled(Boolean(status?.ready));
      setPaperQAIndexEnabled(true);
      if (!quiet && status?.index?.built) {
        toast(`论文索引状态：${status.index.document_count} 篇文档`, "library-big");
      }
    } catch (error) {
      setPaperQAUnavailable(error.message || "无法读取论文问答状态");
      if (!quiet) toast(`论文问答状态读取失败：${error.message}`, "circle-alert");
    }
  }

  async function buildPaperQAIndex(event) {
    event.preventDefault();
    const path = qs("#paperqa-index-path")?.value.trim() || "";
    const role = "reasoning";
    if (!path) return;
    const button = qs('#paperqa-index-form button[type="submit"]');
    const feedback = qs("#paperqa-feedback");
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>建立中</span>';
    if (feedback) { feedback.textContent = "正在解析文档并建立本地向量索引…"; feedback.dataset.state = "loading"; }
    refreshIcons();
    try {
      const result = await apiFetch("/paperqa/index", {
        method: "POST",
        body: JSON.stringify({ path, role })
      });
      if (feedback) {
        feedback.textContent = `已索引 ${result.document_count} 篇文档，可在下方提问。`;
        feedback.dataset.state = "success";
      }
      await loadPaperQAStatus({ quiet: true });
      toast(`论文索引建立完成：${result.document_count} 篇`, "library-big");
    } catch (error) {
      if (feedback) { feedback.textContent = error.message; feedback.dataset.state = "error"; }
      toast(`建立索引失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="library-big" aria-hidden="true"></i><span>建立索引</span>';
      refreshIcons();
    }
  }

  async function askPaperQA(event) {
    event.preventDefault();
    const question = qs("#paperqa-question")?.value.trim() || "";
    const role = qs("#paperqa-role")?.value || "reasoning";
    if (!question) return;
    if (!paperqaStatus?.ready) {
      toast("请先配置模型角色并建立论文索引", "settings-2");
      return;
    }
    const button = qs('#paperqa-ask-form button[type="submit"]');
    const feedback = qs("#paperqa-feedback");
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>回答中</span>';
    if (feedback) { feedback.textContent = "正在检索证据并生成回答…"; feedback.dataset.state = "loading"; }
    refreshIcons();
    try {
      const result = await apiFetch("/paperqa/ask", {
        method: "POST",
        body: JSON.stringify({ question, role, max_tokens: 1024, temperature: 0.2 })
      });
      renderPaperQAAnswer(result);
      if (feedback) {
        feedback.textContent = `回答完成 · ${result.latency_ms} ms`;
        feedback.dataset.state = "success";
      }
    } catch (error) {
      if (feedback) { feedback.textContent = error.message; feedback.dataset.state = "error"; }
      toast(`提问失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="sparkles" aria-hidden="true"></i><span>提问</span>';
      refreshIcons();
    }
  }

  function renderPaperQAAnswer(result) {
    const wrap = qs("#paperqa-result");
    const answer = qs("#paperqa-answer-text");
    const sources = qs("#paperqa-sources");
    const count = qs("#paperqa-source-count");
    if (wrap) wrap.hidden = false;
    if (answer) answer.textContent = result.answer || result.formatted_answer || result.context || "（未返回回答）";
    const items = Array.isArray(result.sources) ? result.sources : [];
    if (count) count.textContent = items.length;
    if (sources) {
      sources.innerHTML = items.map((source) => {
        const rawText = source.text || "";
        const text = rawText.length > 700 ? `${rawText.slice(0, 700)}…` : rawText;
        const title = source.citation || source.docname || "未命名来源";
        return `<article class="paperqa-source"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(text)}</p><small>相关度 ${Number(source.score) || 0}</small></article>`;
      }).join("") || '<p class="paperqa-no-sources">未返回具体引用来源。</p>';
    }
    refreshIcons();
  }

  async function runResearchSearch(event) {
    event.preventDefault();
    if (!researchProjectId) { toast("请先选择或创建科研项目", "folder-search"); return; }
    const query = qs("#research-search-query")?.value.trim() || "";
    if (!query) return;
    const button = qs("#run-literature-search");
    const feedback = qs("#research-search-feedback");
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>检索中</span>';
    if (feedback) { feedback.textContent = "正在查询 Crossref 和 OpenAlex…"; feedback.dataset.state = "loading"; }
    refreshIcons();
    try {
      const result = await apiFetch(`/research/projects/${researchProjectId}/searches`, {
        method: "POST",
        body: JSON.stringify({ query, limit: Number(qs("#research-search-limit")?.value || 10) })
      });
      if (feedback) { feedback.textContent = `已保存 ${result.search.result_count} 篇候选文献，重复 DOI 已合并。`; feedback.dataset.state = "success"; }
      await loadResearchProject(researchProjectId);
      toast(`检索完成：${result.search.result_count} 篇候选文献`, "search-check");
    } catch (error) {
      if (feedback) { feedback.textContent = error.message; feedback.dataset.state = "error"; }
      toast(`文献检索失败：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
      button.innerHTML = '<i data-lucide="search" aria-hidden="true"></i><span>检索文献</span>';
      refreshIcons();
    }
  }

  async function updateResearchScreening(select) {
    const paperId = Number(select.dataset.screenPaper);
    const decision = select.value;
    if (!researchProjectId || !paperId || !decision) return;
    select.disabled = true;
    try {
      await apiFetch(`/research/projects/${researchProjectId}/papers/${paperId}/screening`, {
        method: "PUT",
        body: JSON.stringify({ decision, reason: null })
      });
      const paper = researchPapers.find((item) => Number(item.id) === paperId);
      if (paper) paper.screening_decision = decision;
      researchScreening = await apiFetch(`/research/projects/${researchProjectId}/screening`);
      updateResearchScreeningSummary();
      setResearchTrace(researchProjects.find((item) => String(item.id) === researchProjectId));
      toast("筛选决定已保存", "list-checks");
    } catch (error) {
      toast(`筛选决定未保存：${error.message}`, "circle-alert");
      await loadResearchProject(researchProjectId);
    } finally {
      select.disabled = false;
    }
  }

  async function saveResearchNote() {
    const body = qs("#research-note")?.value.trim() || "";
    if (!researchProjectId) { toast("请先选择科研项目", "folder-search"); return; }
    if (!body) { toast("请先写下研究记录", "notebook-pen"); return; }
    const button = qs("#save-note");
    button.disabled = true;
    try {
      const note = await apiFetch(`/research/projects/${researchProjectId}/notes`, { method: "POST", body: JSON.stringify({ body }) });
      researchNotes.unshift(note);
      if (qs("#note-save-state")) qs("#note-save-state").textContent = "已保存刚刚";
      setResearchTrace(researchProjects.find((item) => String(item.id) === researchProjectId));
      toast("研究日志已保存到 SQLite", "save");
    } catch (error) {
      toast(`研究日志未保存：${error.message}`, "circle-alert");
    } finally {
      button.disabled = false;
    }
  }

  async function createResearchProject(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const name = qs("#project-name")?.value.trim();
    const question = qs("#project-question")?.value.trim();
    if (!name || !question || !form.reportValidity()) return;
    if (!backendConnected && !(await ensureBackendConnection())) { toast("本地服务未连接，项目未创建", "circle-alert"); return; }
    const submit = qs('button[type="submit"]', form);
    submit.disabled = true;
    try {
      const project = await apiFetch("/research/projects", {
        method: "POST",
        body: JSON.stringify({ name, question, research_type: qs("#project-type")?.value || "文献综述" })
      });
      closeDialog("#project-dialog");
      form.reset();
      await loadResearchProjects({ quiet: true, selectedId: project.id });
      toast(`科研项目“${name}”已创建`, "folder-plus");
    } catch (error) {
      toast(`项目未创建：${error.message}`, "circle-alert");
    } finally {
      submit.disabled = false;
    }
  }

  const activeAgentStatuses = new Set(["queued", "handoff_pending", "handoff_requested"]);
  const agentStatusPresentation = {
    queued: { label: "等待交接", icon: "list-todo", tone: "neutral" },
    handoff_pending: { label: "正在请求交接", icon: "loader-circle", tone: "warning" },
    handoff_requested: { label: "已请求交接", icon: "external-link", tone: "success" },
    handoff_failed: { label: "交接失败", icon: "circle-alert", tone: "warning" },
    completed: { label: "已完成", icon: "check", tone: "success" }
  };

  const toolPresentation = {
    "nexus-core": { name: "AI-PC 本地底座", icon: "database", detail: "SQLite / FTS / Qdrant、FSRS、科研记录、凭据与审计" },
    vscode: { name: "Visual Studio Code", icon: "code-2", detail: "隔离源码工作区的图形开发环境" },
    cline: { name: "Cline", icon: "square-terminal", detail: "当前编程任务的显式交接执行器" },
    deeptutor: { name: "DeepTutor", icon: "graduation-cap", detail: "教学、出题与深度研究；安全凭据适配器待接入" },
    "codex-cli": { name: "Codex CLI", icon: "terminal", detail: "独立 CODEX_HOME 的备用编程执行器" },
    obsidian: { name: "Obsidian", icon: "notebook-pen", detail: "Markdown 知识库；Vault 已纳入资料索引白名单" },
    zotero: { name: "Zotero", icon: "library", detail: "科研文献管理；自动同步适配器待接入" },
    paperqa2: { name: "PaperQA2", icon: "file-search", detail: "带引用的论文问答增强候选" },
    openadapt: { name: "OpenAdapt", icon: "mouse-pointer-2", detail: "受审批的电脑操作增强候选" }
  };

  function setAgentRuntimeState(runtime) {
    agentRuntime = runtime;
    const stateLabel = qs("#agent-runtime-state");
    const modeLabel = qs("#agent-queue-mode");
    if (!runtime?.available) {
      let detail = "交接工具不可用";
      if (runtime?.workspace_exists && !runtime?.workspace_approved) detail = "工作区未获批准";
      else if (runtime && !runtime.workspace_exists) detail = "隔离工作区缺失";
      else if (runtime && !runtime.vscode_available) detail = "VS Code 未检测到";
      else if (runtime && !runtime.cline_available) detail = "Cline 未检测到";
      if (stateLabel) { stateLabel.textContent = detail; stateLabel.className = "status-label is-warning"; }
      if (modeLabel) { modeLabel.textContent = "仅记录任务"; modeLabel.className = "status-label is-neutral"; }
    } else {
      if (stateLabel) { stateLabel.textContent = `Cline ${runtime.cline_version || "可用"}`; stateLabel.className = "status-label is-success"; }
      if (modeLabel) { modeLabel.textContent = "显式交接"; modeLabel.className = "status-label is-success"; }
    }
    renderAgentTasks();
  }

  function showAgentUnavailable(message = "Agent 状态不可用") {
    agentRuntime = null;
    const stateLabel = qs("#agent-runtime-state");
    const modeLabel = qs("#agent-queue-mode");
    if (stateLabel) { stateLabel.textContent = message; stateLabel.className = "status-label is-danger"; }
    if (modeLabel) { modeLabel.textContent = "仅记录任务"; modeLabel.className = "status-label is-neutral"; }
    renderAgentTasks();
  }

  function agentTaskMeta(task) {
    const options = [];
    if (Number(task.run_tests)) options.push("测试");
    if (Number(task.generate_summary)) options.push("变更说明");
    if (Number(task.allow_dependencies)) options.push("可提议依赖");
    const time = task.handoff_requested_at || task.created_at;
    return `${task.project} · ${formatLearningDateTime(time)}${options.length ? ` · ${options.join(" / ")}` : ""}`;
  }

  function renderAgentTasks() {
    const list = qs("#agent-task-list");
    if (!list) return;
    renderOverviewTasks();
    if (qs("#agent-task-total")) qs("#agent-task-total").textContent = `${agentTasks.length} 个`;
    if (!agentTasks.length) {
      list.innerHTML = '<div class="learning-empty" id="agent-task-empty"><i data-lucide="inbox" aria-hidden="true"></i><div><strong>还没有任务记录</strong><span>新任务会先进入本地队列，再由你决定何时交给 Cline。</span></div></div>';
      refreshIcons();
      return;
    }
    list.innerHTML = agentTasks.map((task) => {
      const presentation = agentStatusPresentation[task.status] || agentStatusPresentation.queued;
      const canHandoff = task.status === "queued" && agentRuntime?.available === true;
      const action = task.status === "queued"
        ? `<button class="secondary-button agent-task-action" type="button" data-agent-handoff="${Number(task.id)}" ${canHandoff ? "" : "disabled"}><i data-lucide="external-link" aria-hidden="true"></i><span>${canHandoff ? "交给 Cline" : "暂不可交接"}</span></button>`
        : `<span class="status-label ${presentation.tone === "success" ? "is-success" : presentation.tone === "warning" ? "is-warning" : "is-neutral"}">${presentation.label}</span>`;
      const error = task.status === "handoff_failed" && task.last_error ? " · 可查看审计记录" : "";
      return `<article><div class="task-state ${presentation.tone}"><i data-lucide="${presentation.icon}" aria-hidden="true"></i></div><div class="agent-task-meta"><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(agentTaskMeta(task) + error)}</span></div>${action}</article>`;
    }).join("");
    refreshIcons();
  }

  async function loadAgentStatus({ quiet = false } = {}) {
    if (!backendConnected) {
      showAgentUnavailable("本地服务未连接");
      return false;
    }
    try {
      const runtime = await apiFetch("/agent/status");
      setAgentRuntimeState(runtime || null);
      return runtime?.available === true;
    } catch (error) {
      showAgentUnavailable("Agent 状态读取失败");
      if (!quiet) toast(`Agent 状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function loadAgentTasks({ quiet = false } = {}) {
    if (!backendConnected) {
      renderAgentTasks();
      return false;
    }
    try {
      const tasks = await apiFetch("/agent/tasks");
      agentTasks = Array.isArray(tasks) ? tasks : [];
      state.agentCount = agentTasks.filter((task) => activeAgentStatuses.has(task.status)).length;
      updateCounters();
      renderAgentTasks();
      return true;
    } catch (error) {
      if (!quiet) toast(`任务队列读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  async function loadAgentData({ quiet = false } = {}) {
    if (!backendConnected && !(await ensureBackendConnection())) {
      showAgentUnavailable("本地服务未连接");
      return false;
    }
    const [runtimeLoaded, tasksLoaded] = await Promise.all([
      loadAgentStatus({ quiet }),
      loadAgentTasks({ quiet })
    ]);
    return runtimeLoaded || tasksLoaded;
  }

  async function handoffAgentTask(taskId, button) {
    const task = agentTasks.find((item) => Number(item.id) === Number(taskId));
    if (!task || task.status !== "queued") return;
    if (!agentRuntime?.available) {
      toast("VS Code、Cline 或隔离工作区当前不可用", "circle-alert");
      return;
    }
    const confirmed = window.confirm(`将任务 #${task.id} 交给 Cline，并打开隔离源码工作区。是否继续？`);
    if (!confirmed) return;
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>正在交接</span>';
    refreshIcons();
    try {
      const result = await apiFetch(`/agent/tasks/${task.id}/handoff`, {
        method: "POST",
        headers: { "X-AI-PC-Action": "agent-handoff" }
      });
      const index = agentTasks.findIndex((item) => Number(item.id) === Number(task.id));
      if (index >= 0 && result?.task) agentTasks[index] = result.task;
      renderAgentTasks();
      toast("交接请求已发送，后续操作仍由 Cline 逐步确认", "external-link");
    } catch (error) {
      await loadAgentTasks({ quiet: true });
      toast(`任务未能交接：${error.message}`, "circle-alert");
    }
  }

  function showToolsUnavailable(message = "工具状态不可用") {
    const list = qs("#tool-registry-list");
    if (!list) return;
    list.innerHTML = `<div class="tool-registry-empty"><i data-lucide="wifi-off" aria-hidden="true"></i><span>${escapeHtml(message)}</span></div>`;
    refreshIcons();
  }

  function renderTools() {
    const list = qs("#tool-registry-list");
    if (!list) return;
    if (!toolRegistry.length) {
      showToolsUnavailable("尚未读取本机工具状态");
      return;
    }
    const statusLabel = { ready: "已接入", installed: "已安装", planned: "候选", unavailable: "未检测到" };
    const integrationLabel = {
      active: "由 Dashboard 使用",
      adapter_pending: "安全适配器待接入",
      isolated_manual: "隔离配置，暂手动使用",
      vault_pending: "Vault 待配置",
      planned: "后续评估",
      missing: "未安装"
    };
    list.innerHTML = toolRegistry.map((tool) => {
      const presentation = toolPresentation[tool.id] || { name: tool.name, icon: "box", detail: tool.category || "外部能力" };
      const readyClass = tool.status === "ready" ? "is-ready" : tool.status === "installed" ? "is-installed" : "";
      const labelClass = tool.status === "ready" ? "is-success" : tool.status === "unavailable" ? "is-danger" : tool.status === "planned" ? "is-warning" : "is-neutral";
      const version = tool.version ? `v${tool.version}` : integrationLabel[tool.integration] || "";
      return `<article class="tool-registry-item"><div class="tool-registry-icon ${readyClass}"><i data-lucide="${presentation.icon}" aria-hidden="true"></i></div><div class="tool-registry-main"><strong>${escapeHtml(presentation.name)}</strong><span>${escapeHtml(presentation.detail)}</span></div><div class="tool-registry-side"><span class="status-label ${labelClass}">${statusLabel[tool.status] || tool.status}</span><small>${escapeHtml(version)}</small></div></article>`;
    }).join("");
    refreshIcons();
  }

  async function loadTools({ quiet = false } = {}) {
    if (!backendConnected) {
      showToolsUnavailable("本地服务未连接");
      return false;
    }
    try {
      const payload = await apiFetch("/tools");
      toolRegistry = Array.isArray(payload?.tools) ? payload.tools : [];
      renderTools();
      return true;
    } catch (error) {
      showToolsUnavailable("工具状态读取失败");
      if (!quiet) toast(`工具状态读取失败：${error.message}`, "circle-alert");
      return false;
    }
  }

  function bindEvents() {
    qsa(".nav-item[data-page]").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
    qsa("[data-go]").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.go)));
    qs("#theme-toggle")?.addEventListener("click", () => setTheme(state.theme === "dark" ? "light" : "dark"));
    qs("#mobile-menu")?.addEventListener("click", () => {
      qs("#sidebar")?.classList.add("is-open");
      qs("#mobile-scrim")?.classList.add("is-visible");
    });
    qs("#mobile-scrim")?.addEventListener("click", () => {
      qs("#sidebar")?.classList.remove("is-open");
      qs("#mobile-scrim")?.classList.remove("is-visible");
    });

    qs("#continue-setup")?.addEventListener("click", () => showPage("settings"));
    qs("#chat-send")?.addEventListener("click", sendChatQuestion);
    qs("#chat-input")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendChatQuestion();
      }
    });
    qsa(".chat-example").forEach((button) =>
      button.addEventListener("click", () => {
        const input = qs("#chat-input");
        if (input) input.value = button.dataset.example || "";
        sendChatQuestion();
      })
    );
    qs("#chat-go-settings")?.addEventListener("click", () => showPage("settings"));
    qs("#start-session")?.addEventListener("click", () => focusLearningAttempt());
    qs("#refresh-learning")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>刷新中</span>';
      refreshIcons();
      await loadLearningDashboard();
      await loadCoachReport({ quiet: true });
      await loadCoachPlan({ quiet: true });
      button.disabled = false;
      button.innerHTML = '<i data-lucide="refresh-cw" aria-hidden="true"></i><span>刷新进度</span>';
      refreshIcons();
    });
    qs("#learning-course-select")?.addEventListener("change", async (event) => {
      learningCourseId = event.currentTarget.value;
      await loadLearningDashboard({ quiet: true });
      await loadCoachReport({ quiet: true });
      await loadCoachPlan({ quiet: true });
    });
    qs("#learning-concept-course")?.addEventListener("change", updateLearningPrerequisites);
    qs("#learning-course-form")?.addEventListener("submit", createLearningCourse);
    qs("#learning-concept-form")?.addEventListener("submit", createLearningConcept);
    qs("#learning-attempt-form")?.addEventListener("submit", recordLearningAttempt);
    qs("#learning-attempt-score")?.addEventListener("input", (event) => {
      if (qs("#learning-score-output")) qs("#learning-score-output").textContent = `${event.currentTarget.value}%`;
    });
    qs("#learning-attempt-confidence")?.addEventListener("input", (event) => {
      if (qs("#learning-confidence-output")) qs("#learning-confidence-output").textContent = `${event.currentTarget.value}%`;
    });
    qs("#page-learning")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-record-concept]");
      if (button) focusLearningAttempt(button.dataset.recordConcept);
    });
    qs("#library-import-form")?.addEventListener("submit", importLibraryPath);
    qs("#focus-import-path")?.addEventListener("click", () => {
      qs("#library-import-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
      qs("#library-import-path")?.focus({ preventScroll: true });
    });
    qs("#library-search-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      searchLibrary(qs("#library-search")?.value || "");
    });
    qs("#library-search")?.addEventListener("input", (event) => {
      const hasQuery = Boolean(event.currentTarget.value.trim());
      if (qs("#library-search-clear")) qs("#library-search-clear").hidden = !hasQuery;
      if (!hasQuery && libraryDataMode === "search") loadLibraryDocuments({ quiet: true });
    });
    qs("#library-search-clear")?.addEventListener("click", () => {
      const input = qs("#library-search");
      if (input) { input.value = ""; input.focus(); }
      qs("#library-search-clear").hidden = true;
      loadLibraryDocuments({ quiet: true });
    });
    qsa("#library-search-mode [data-search-mode]").forEach((button) => button.addEventListener("click", () => {
      librarySearchMode = button.dataset.searchMode;
      qsa("#library-search-mode [data-search-mode]").forEach((item) => item.classList.toggle("is-active", item === button));
      const query = qs("#library-search")?.value.trim() || "";
      if (query) searchLibrary(query);
    }));
    ["#library-type", "#library-status"].forEach((selector) => qs(selector)?.addEventListener("change", filterLibrary));
    qs("#semantic-rebuild")?.addEventListener("click", rebuildSemanticIndex);
    qs("#library-retry")?.addEventListener("click", () => {
      if (libraryLastRequest.kind === "search") searchLibrary(libraryLastRequest.query);
      else loadLibraryDocuments();
    });
    qs("#sync-library")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.innerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i><span>刷新中</span>';
      refreshIcons();
      await loadLibraryDocuments();
      button.disabled = false;
      button.innerHTML = '<i data-lucide="refresh-cw" aria-hidden="true"></i><span>刷新列表</span>';
      refreshIcons();
    });

    qsa("[data-research-view]").forEach((button) => button.addEventListener("click", () => {
      qsa("[data-research-view]").forEach((item) => item.classList.toggle("is-current", item === button));
      const target = ({ question: ".research-focus", search: "#research-search-form", screen: "#research-paper-wrap", notes: "#research-note" })[button.dataset.researchView];
      qs(target)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }));
    qsa("[data-open-research]").forEach((button) => button.addEventListener("click", () => {
      const target = button.dataset.openResearch;
      const tab = qs(`[data-research-view="${target}"]`);
      tab?.click();
      qs("#page-research")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    qs("#new-project")?.addEventListener("click", () => openDialog("#project-dialog"));
    qs("#research-project-select")?.addEventListener("change", (event) => event.currentTarget.value ? loadResearchProject(event.currentTarget.value) : clearResearchProject());
    qs("#research-search-form")?.addEventListener("submit", runResearchSearch);
    qs("#research-paper-body")?.addEventListener("change", (event) => {
      const select = event.target.closest("[data-screen-paper]");
      if (select) updateResearchScreening(select);
    });
    qs("#research-note")?.addEventListener("input", () => {
      const stateLabel = qs("#note-save-state");
      if (stateLabel) stateLabel.textContent = "有未保存修改";
    });
    qs("#save-note")?.addEventListener("click", saveResearchNote);
    qs("#overview-task-list")?.addEventListener("click", (event) => {
      const item = event.target.closest("[data-go]");
      if (item) showPage(item.dataset.go);
    });
    qs("#paperqa-index-form")?.addEventListener("submit", buildPaperQAIndex);
    qs("#paperqa-ask-form")?.addEventListener("submit", askPaperQA);

    qs("#refresh-agent")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      await loadAgentData();
      button.disabled = false;
    });
    qs("#agent-task-list")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-agent-handoff]");
      if (button) handoffAgentTask(button.dataset.agentHandoff, button);
    });
    qs("#agent-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = qs("#agent-task");
      if (!input.value.trim()) { toast("先写下要完成的任务", "message-circle-warning"); input.focus(); return; }
      const title = input.value.trim();
      if (!backendConnected) await ensureBackendConnection();
      if (!backendConnected) {
        toast("本地服务未连接，任务未创建", "circle-alert");
        return;
      }
      try {
        const task = await apiFetch("/agent/tasks", {
          method: "POST",
          body: JSON.stringify({
            project: qs("#agent-project")?.value || "AI-PC Dashboard",
            title,
            run_tests: qs("#agent-run-tests")?.checked === true,
            generate_summary: qs("#agent-generate-summary")?.checked === true,
            allow_dependencies: qs("#agent-allow-dependencies")?.checked === true
          })
        });
        agentTasks = [task, ...agentTasks.filter((item) => Number(item.id) !== Number(task.id))];
      } catch (error) {
        toast(`任务未写入 SQLite：${error.message}`, "circle-alert");
        return;
      }
      state.agentCount = agentTasks.filter((task) => activeAgentStatuses.has(task.status)).length;
      updateCounters();
      renderAgentTasks();
      saveState();
      toast("任务已记录到本地队列，等待你确认交接", "database");
      input.value = "";
    });
    qs("#save-browser-allowlist")?.addEventListener("click", saveBrowserAllowlist);
    qs("#browser-stop")?.addEventListener("click", browserStop);
    qs("#browser-resume")?.addEventListener("click", browserResume);

    qs("#provider-select")?.addEventListener("change", changeModelProvider);
    qs("#refresh-tools")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      await loadTools();
      button.disabled = false;
    });
    qs("#save-provider")?.addEventListener("click", saveCredential);
    qs("#test-provider")?.addEventListener("click", testModelConnection);
    qs("#sync-zotero")?.addEventListener("click", syncZotero);
    qs("#run-backup")?.addEventListener("click", runBackup);
    qs("#save-backup-settings")?.addEventListener("click", saveBackupSettings);
    qs("#run-deeptutor")?.addEventListener("click", runDeepTutor);
    qs("#refresh-model-roles")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      await loadModelRoles();
      button.disabled = false;
    });
    qsa(".role-save").forEach((button) => button.addEventListener("click", saveModelRole));
    qs("#generate-test")?.addEventListener("click", generateModelText);
    bindRoleProviderChanges();
    qs("#save-settings")?.addEventListener("click", async () => {
      state.provider = qs("#provider-select")?.value || state.provider;
      state.endpoint = qs("#api-endpoint")?.value || state.endpoint;
      state.dataPath = qs("#data-path")?.value || state.dataPath;
      const hasPendingCredential = Boolean(qs("#api-key")?.value.trim());
      saveState();
      if (!backendConnected) await ensureBackendConnection();
      if (backendConnected) {
        try {
          await apiFetch("/settings", { method: "PUT", body: JSON.stringify({ provider: state.provider, endpoint: state.endpoint, data_path: state.dataPath }) });
          toast("设置已保存到本地服务（密钥不写入浏览器存储）", "save");
          if (hasPendingCredential) await saveCredential();
        } catch {
          toast("设置已保存在浏览器，后端暂时不可用", "circle-alert");
        }
      } else {
        toast("设置已保存在浏览器（密钥不写入持久存储）", "save");
        if (hasPendingCredential) toast("本地服务未连接，API 密钥没有保存", "wifi-off");
      }
    });
    qs("#toggle-key")?.addEventListener("click", () => {
      const input = qs("#api-key");
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
      qs("#toggle-key").innerHTML = `<i data-lucide="${input.type === "password" ? "eye" : "eye-off"}" aria-hidden="true"></i>`;
      refreshIcons();
    });

    qsa("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.closeDialog)));

    qs("#project-form")?.addEventListener("submit", createResearchProject);

    qs("#global-search")?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const query = event.currentTarget.value.trim();
      if (!query) return;
      showPage("library");
      const librarySearch = qs("#library-search");
      if (librarySearch) librarySearch.value = query;
      searchLibrary(query);
      toast(`已在资料库中搜索“${query}”`, "search");
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        qs("#global-search")?.focus();
      }
    });
  }

  function hydrate() {
    setTheme(state.theme);
    clearResearchProject();
    if (qs("#provider-select")) qs("#provider-select").value = state.provider;
    if (qs("#api-endpoint")) qs("#api-endpoint").value = state.endpoint;
    if (qs("#data-path")) qs("#data-path").value = state.dataPath;
    const today = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date());
    if (qs("#today-label")) qs("#today-label").textContent = `功能概览 · ${today}`;
    refreshIcons();
    hydrateFromApi();
  }

  bindEvents();
  hydrate();
})();
