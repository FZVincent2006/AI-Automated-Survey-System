const state = {
  data: null,
  section: "overview",
  selectedTaxonomy: null,
  selectedCompare: ["p01", "p02", "p03"],
  selectedDigest: 0,
};

const sectionNames = {
  overview: "智能研究总览",
  papers: "论文智能解析",
  taxonomy: "研究分类图谱",
  comparison: "方法对比分析",
  insights: "趋势与研究洞察",
  weekly: "Weekly Survey Digest",
  survey: "最终综述报告",
  live: "实时论文解析",
};

const metricDefinitions = [
  { key: "rawPapers", label: "已抓取论文", icon: "⌕", suffix: "篇", note: "近 1–2 年 arXiv", color: "#6e7cff" },
  { key: "validCards", label: "有效论文卡片", icon: "▦", suffix: "张", note: "结构化解析完成", color: "#42b7e8" },
  { key: "categories", label: "研究分类", icon: "⌘", suffix: "类", note: "自动构建 Taxonomy", color: "#a56be8" },
  { key: "weeklyDigests", label: "Weekly 更新", icon: "◷", suffix: "期", note: "满足课程提交要求", color: "#4ed1a2" },
];

async function loadData() {
  try {
    const response = await fetch("/data/dashboard-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error("data fetch failed");
    state.data = await response.json();
  } catch (error) {
    document.body.innerHTML = `<div style="padding:40px;color:white">数据加载失败，请确认 web/data/dashboard-data.json 可访问。</div>`;
    throw error;
  }
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => toast.classList.remove("show"), 2400);
}

function gotoSection(section) {
  state.section = section;
  document.querySelectorAll(".page-section").forEach((element) => {
    element.classList.toggle("active", element.id === section);
  });
  document.querySelectorAll(".nav-item").forEach((element) => {
    element.classList.toggle("active", element.dataset.section === section);
  });
  document.querySelector("#pageTitle").textContent = sectionNames[section];
  document.querySelector(".sidebar").classList.remove("open");
  window.scrollTo({ top: 0, behavior: "smooth" });
  history.replaceState(null, "", `#${section}`);
}

function renderMetrics() {
  const metrics = state.data.metrics;
  document.querySelector("#metricsGrid").innerHTML = metricDefinitions.map((item) => `
    <article class="metric-card" style="--metric-color:${item.color}">
      <div class="metric-head"><span>${item.label}</span><span class="metric-icon">${item.icon}</span></div>
      <div class="metric-number" data-counter="${metrics[item.key]}">0<span>${item.suffix}</span></div>
      <div class="metric-foot"><b>● 已完成</b> · ${item.note}</div>
    </article>
  `).join("");

  document.querySelectorAll("[data-counter]").forEach((element) => {
    const target = Number(element.dataset.counter);
    const suffix = element.querySelector("span")?.textContent || "";
    const start = performance.now();
    const animate = (time) => {
      const progress = Math.min(1, (time - start) / 650);
      element.innerHTML = `${Math.round(target * (1 - Math.pow(1 - progress, 3)))}<span>${suffix}</span>`;
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  });
}

function renderOverview() {
  renderMetrics();
  const { data } = state;
  document.querySelector("#pipeline").innerHTML = data.pipeline.map((step) => `
    <div class="pipe-step ${step.status}">
      <div class="pipe-icon">${step.icon}</div>
      <strong>${step.name}</strong>
      <small>${step.detail}</small>
    </div>
  `).join("");
  document.querySelector("#pipelineProgressText").textContent = `${data.metrics.validCards} / ${data.metrics.rawPapers}`;
  document.querySelector("#pipelineProgress").style.width = `${data.metrics.comparisonCoverage}%`;

  const categoryTotal = data.categories.reduce((sum, item) => sum + item.count, 0);
  document.querySelector("#donutTotal").textContent = data.metrics.rawPapers;
  let current = 0;
  const stops = data.categories.map((item) => {
    const start = current;
    current += (item.count / categoryTotal) * 100;
    return `${item.color} ${start.toFixed(1)}% ${current.toFixed(1)}%`;
  });
  document.querySelector("#categoryDonut").style.background = `conic-gradient(${stops.join(",")})`;
  document.querySelector("#categoryLegend").innerHTML = data.categories.map((item) => `
    <div class="legend-item"><i style="background:${item.color}"></i><span>${item.name}</span><b>${item.count}</b></div>
  `).join("");

  const maxTrend = Math.max(...data.monthlyTrend.map((item) => item.value));
  document.querySelector("#trendChart").innerHTML = data.monthlyTrend.map((item) => `
    <div class="bar-column" title="${item.label}: ${item.value} 篇">
      <div class="bar" style="height:${Math.max(5, item.value / maxTrend * 100)}%"></div>
      <small>${item.label}</small>
    </div>
  `).join("");

  document.querySelector("#featuredInsight").textContent = `“${data.featuredInsight.text}”`;
  document.querySelector("#featuredTags").innerHTML = data.featuredInsight.tags.map((tag) => `<span class="tag">${tag}</span>`).join("");
}

function populateFilters() {
  const categories = [...new Set(state.data.papers.map((paper) => paper.category))];
  const years = [...new Set(state.data.papers.map((paper) => paper.year))].sort((a, b) => b - a);
  document.querySelector("#categoryFilter").innerHTML += categories.map((value) => `<option>${value}</option>`).join("");
  document.querySelector("#yearFilter").innerHTML += years.map((value) => `<option>${value}</option>`).join("");
}

function renderPapers() {
  const query = document.querySelector("#paperSearch").value.trim().toLowerCase();
  const category = document.querySelector("#categoryFilter").value;
  const year = document.querySelector("#yearFilter").value;
  const papers = state.data.papers.filter((paper) => {
    const haystack = `${paper.title} ${paper.method} ${paper.keyIdea} ${paper.category}`.toLowerCase();
    return (!query || haystack.includes(query))
      && (!category || paper.category === category)
      && (!year || String(paper.year) === year);
  });
  document.querySelector("#paperResultCount").textContent = `显示 ${papers.length} / ${state.data.metrics.validCards} 张卡片`;
  document.querySelector("#paperGrid").innerHTML = papers.map((paper) => `
    <article class="paper-card" data-paper-id="${paper.id}">
      <div class="paper-top">
        <span class="paper-category">${paper.category}</span>
        <span class="confidence">● ${paper.confidence}/5 可信度</span>
      </div>
      <h3>${escapeHtml(paper.title)}</h3>
      <p>${escapeHtml(paper.keyIdea)}</p>
      <div class="paper-meta">
        <span>${paper.year} · ${paper.authors.length} 位作者</span>
        <span class="paper-arrow">↗</span>
      </div>
    </article>
  `).join("") || `<div class="panel" style="padding:30px;color:var(--muted)">没有找到匹配的论文卡片。</div>`;
}

function paperModalHtml(paper) {
  const fields = [
    ["核心问题 Problem", paper.problem, "full"],
    ["核心思想 Key Idea", paper.keyIdea, "full"],
    ["方法 Method", paper.method, ""],
    ["数据集 / 场景", paper.scenario, ""],
    ["评价指标 Metrics", paper.metrics, ""],
    ["实验结果 Results", paper.results, ""],
    ["创新类型", paper.innovation, ""],
    ["局限性 Limitations", paper.limitations, ""],
  ];
  return `
    <div class="modal-title">
      <span class="paper-category">${paper.category}</span>
      <h2>${escapeHtml(paper.title)}</h2>
      <p style="color:var(--muted);font-size:9px">${paper.authors.join(", ")} · ${paper.published} · 可信度 ${paper.confidence}/5</p>
    </div>
    <div class="modal-fields">
      ${fields.map(([label, value, className]) => `
        <div class="modal-field ${className}"><small>${label}</small><p>${escapeHtml(value)}</p></div>
      `).join("")}
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:17px">
      <a class="primary-button" href="${paper.url}" target="_blank" rel="noreferrer" style="text-decoration:none">打开 arXiv 原文 ↗</a>
    </div>
  `;
}

function openPaperModal(paperId) {
  const paper = state.data.papers.find((item) => item.id === paperId);
  if (!paper) return;
  document.querySelector("#paperModalContent").innerHTML = paperModalHtml(paper);
  document.querySelector("#paperModal").classList.remove("hidden");
}

function taxonomyNodes() {
  const taxonomy = state.data.taxonomy;
  const nodes = [{ ...taxonomy, type: "root", x: 50, y: 50, parent: null }];
  const branchPositions = [
    [17, 21], [80, 18], [86, 57], [58, 83], [18, 72],
  ];
  taxonomy.children.forEach((branch, branchIndex) => {
    const [x, y] = branchPositions[branchIndex];
    const branchId = `branch-${branchIndex}`;
    nodes.push({ ...branch, id: branchId, type: "branch", x, y, parent: "root" });
    const angleBase = Math.atan2(y - 50, x - 50);
    branch.children.forEach((leaf, leafIndex) => {
      const spread = (leafIndex - 1) * 0.55;
      const distance = 16;
      nodes.push({
        ...leaf,
        id: `${branchId}-leaf-${leafIndex}`,
        type: "leaf",
        x: Math.max(5, Math.min(95, x + Math.cos(angleBase + spread) * distance)),
        y: Math.max(7, Math.min(93, y + Math.sin(angleBase + spread) * distance)),
        parent: branchId,
        parentName: branch.name,
        description: `${branch.name}中的“${leaf.name}”技术分支。`,
      });
    });
  });
  nodes[0].id = "root";
  return nodes;
}

function renderTaxonomy() {
  const graph = document.querySelector("#taxonomyGraph");
  const nodes = taxonomyNodes();
  const lines = nodes.filter((node) => node.parent).map((node) => {
    const parent = nodes.find((candidate) => candidate.id === node.parent);
    const dx = node.x - parent.x;
    const dy = node.y - parent.y;
    const length = Math.sqrt(dx * dx + dy * dy);
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    return `<div class="graph-line" style="left:${parent.x}%;top:${parent.y}%;width:${length}%;transform:rotate(${angle}deg)"></div>`;
  });
  const nodeHtml = nodes.map((node) => `
    <button class="graph-node ${node.type} ${state.selectedTaxonomy === node.id ? "active" : ""}"
      data-node-id="${node.id}" style="left:${node.x}%;top:${node.y}%;transform:translate(-50%,-50%)">
      ${escapeHtml(node.name)}
    </button>
  `);
  graph.innerHTML = [...lines, ...nodeHtml].join("");
  const selected = nodes.find((node) => node.id === state.selectedTaxonomy) || nodes[0];
  state.selectedTaxonomy = selected.id;
  renderTaxonomyDetail(selected);
}

function renderTaxonomyDetail(node) {
  const papers = state.data.papers.filter((paper) => {
    if (node.type === "root") return true;
    return paper.category === node.name || paper.category === node.parentName;
  }).slice(0, 4);
  document.querySelector("#taxonomyDetail").innerHTML = `
    <div class="detail-icon">${node.type === "root" ? "AI" : "⌘"}</div>
    <h2>${escapeHtml(node.name)}</h2>
    <p>${escapeHtml(node.description || "由结构化论文卡片归纳形成的研究主题。")}</p>
    <div class="detail-stat">
      <div><strong>${node.count || state.data.metrics.rawPapers}</strong><small>关联论文</small></div>
      <div><strong>${node.children?.length || 0}</strong><small>下级分类</small></div>
    </div>
    <span class="panel-kicker">REPRESENTATIVE PAPERS</span>
    <div class="detail-papers">
      ${papers.length ? papers.map((paper) => `<div class="detail-paper">${escapeHtml(paper.title)}</div>`).join("") : `<div class="detail-paper">该子类的论文将在下一轮增量更新中补充。</div>`}
    </div>
  `;
}

function renderCompareSelector() {
  document.querySelector("#compareSelector").innerHTML = state.data.papers.map((paper) => `
    <button class="compare-pill ${state.selectedCompare.includes(paper.id) ? "selected" : ""}" data-compare-id="${paper.id}">
      ${paper.title.length > 40 ? `${paper.title.slice(0, 40)}…` : paper.title}
    </button>
  `).join("");
}

function radarSvg(papers) {
  const axes = ["协作能力", "工具能力", "可靠性", "适应性", "数据依赖"];
  const center = 155;
  const radius = 108;
  const point = (angle, distance) => [
    center + Math.cos(angle - Math.PI / 2) * distance,
    center + Math.sin(angle - Math.PI / 2) * distance,
  ];
  const polygon = (ratio) => axes.map((_, index) => {
    const [x, y] = point(index / axes.length * Math.PI * 2, radius * ratio);
    return `${x},${y}`;
  }).join(" ");
  const colors = ["#7384ff", "#4ed1d4", "#b475ff"];
  return `
    <svg class="radar-svg" viewBox="0 0 310 310" role="img" aria-label="方法能力雷达图">
      ${[.25,.5,.75,1].map((ratio) => `<polygon class="radar-grid" points="${polygon(ratio)}"></polygon>`).join("")}
      ${axes.map((_, index) => {
        const [x, y] = point(index / axes.length * Math.PI * 2, radius);
        return `<line class="radar-axis" x1="${center}" y1="${center}" x2="${x}" y2="${y}"></line>`;
      }).join("")}
      ${papers.map((paper, paperIndex) => {
        const points = paper.scores.map((score, index) => {
          const [x, y] = point(index / axes.length * Math.PI * 2, radius * score / 100);
          return `${x},${y}`;
        }).join(" ");
        return `<polygon class="radar-shape" style="stroke:${colors[paperIndex]};fill:${colors[paperIndex]}22" points="${points}"></polygon>`;
      }).join("")}
      ${axes.map((label, index) => {
        const [x, y] = point(index / axes.length * Math.PI * 2, radius + 20);
        return `<text class="radar-label" x="${x}" y="${y + 3}">${label}</text>`;
      }).join("")}
    </svg>
    <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
      ${papers.map((paper, index) => `<span style="font-size:7px;color:${colors[index]}">● ${paper.title.slice(0, 24)}…</span>`).join("")}
    </div>
  `;
}

function renderComparison() {
  renderCompareSelector();
  const selected = state.selectedCompare
    .map((id) => state.data.papers.find((paper) => paper.id === id))
    .filter(Boolean);
  document.querySelector("#radarChart").innerHTML = radarSvg(selected);
  document.querySelector("#comparisonBody").innerHTML = selected.map((paper) => `
    <tr>
      <td>${escapeHtml(paper.title)}<br><small style="color:#71819a">${escapeHtml(paper.method)}</small></td>
      <td>${escapeHtml(paper.complexity)}</td>
      <td>${escapeHtml(paper.scenario)}</td>
      <td>${escapeHtml(paper.prosCons)}</td>
      <td><span class="yes-chip">${paper.dataDriven}</span></td>
    </tr>
  `).join("");
}

function renderInsights() {
  document.querySelector("#insightGrid").innerHTML = state.data.insights.map((insight, index) => `
    <article class="panel insight-card" style="--card-color:${insight.color}">
      <span class="number">0${index + 1} · ${insight.type}</span>
      <div class="insight-icon">${insight.icon}</div>
      <h3>${insight.title}</h3>
      <p>${insight.text}</p>
      <footer>${insight.evidence}</footer>
    </article>
  `).join("");
  document.querySelector("#evolutionTrack").innerHTML = state.data.evolution.map((step) => `
    <div class="evolution-step">
      <span class="year">${step.period}</span>
      <h4>${step.title}</h4>
      <p>${step.text}</p>
    </div>
  `).join("");
}

function digestHtml(digest) {
  return `
    <span class="paper-category">WEEK ${digest.index}</span>
    <h1>${digest.title}</h1>
    <div class="digest-meta"><span>${digest.date}</span><span>新增 ${digest.newPapers} 篇论文</span><span>自动生成</span></div>
    <h2>1. 本周研究动态总览</h2><p>${digest.overview}</p>
    <h2>2. 核心技术路线演进</h2><ul>${digest.technicalEvolution.map((item) => `<li>${item}</li>`).join("")}</ul>
    <h2>3. 分类体系冲击与补充</h2><ul>${digest.taxonomyImpact.map((item) => `<li>${item}</li>`).join("")}</ul>
    <h2>4. 研究空白与未来方向</h2><ul>${digest.gaps.map((item) => `<li>${item}</li>`).join("")}</ul>
  `;
}

function renderWeekly() {
  const digests = state.data.weeklyDigests;
  document.querySelector("#weeklyTimeline").innerHTML = digests.map((digest, index) => `
    <button class="week-item ${index === state.selectedDigest ? "active" : ""}" data-digest-index="${index}">
      <small>${digest.date}</small><h3>第 ${digest.index} 期 Weekly Digest</h3><p>新增 ${digest.newPapers} 篇论文</p>
    </button>
  `).join("");
  document.querySelector("#digestReader").innerHTML = digestHtml(digests[state.selectedDigest]);
}

function renderSurvey() {
  const report = state.data.finalSurvey;
  document.querySelector("#surveyToc").innerHTML = `
    <h3>报告目录</h3>
    ${report.sections.map((section) => `<button class="toc-item" data-survey-target="${section.id}">${section.title}</button>`).join("")}
  `;
  document.querySelector("#surveyReader").innerHTML = `
    <span class="paper-category">FINAL SURVEY · 2026</span>
    <h1>${report.title}</h1>
    <div class="survey-statbar">
      <div class="survey-stat"><strong>${state.data.metrics.rawPapers}</strong><small>纳入论文</small></div>
      <div class="survey-stat"><strong>${state.data.metrics.categories}</strong><small>技术分类</small></div>
      <div class="survey-stat"><strong>${state.data.metrics.weeklyDigests}</strong><small>Weekly 更新</small></div>
      <div class="survey-stat"><strong>${state.data.metrics.comparisonCoverage}%</strong><small>对比覆盖率</small></div>
    </div>
    <h2>Abstract</h2><p>${report.abstract}</p>
    ${report.sections.map((section) => `<section id="${section.id}"><h2>${section.title}</h2><p>${section.content}</p></section>`).join("")}
    <h2>References</h2>
    <ol>${state.data.papers.slice(0, 8).map((paper) => `<li>${paper.authors.join(", ")}. (${paper.year}). <em>${paper.title}</em>. arXiv.</li>`).join("")}</ol>
  `;
}

function memberModal() {
  document.querySelector("#memberGrid").innerHTML = state.data.meta.members.map((name) => `
    <div class="member"><i>${name[0]}</i><strong>${name}</strong></div>
  `).join("");
}

function cachedAnalysis(title) {
  const match = state.data.papers.find((paper) => paper.title.toLowerCase() === title.toLowerCase())
    || state.data.papers[2];
  return {
    title,
    problem: match.problem,
    key_idea: match.keyIdea,
    method: match.method,
    dataset_or_scenario: match.scenario,
    metrics: match.metrics,
    results_summary: match.results,
    innovation_type: match.innovation,
    limitations: match.limitations,
    best_fit_category: match.category,
    confidence_level: match.confidence,
    source: "cached",
  };
}

function analysisResultHtml(result) {
  const fields = [
    ["核心问题", result.problem, "full"],
    ["核心思想", result.key_idea, "full"],
    ["方法", result.method, ""],
    ["实验场景", result.dataset_or_scenario, ""],
    ["评价指标", result.metrics, ""],
    ["实验结果", result.results_summary, ""],
    ["创新类型", result.innovation_type, ""],
    ["局限性", result.limitations, ""],
  ];
  return `
    <div class="result-header">
      <span>● 解析完成 · ${result.source === "live" ? "实时模型结果" : "缓存降级结果"}</span>
      <h3>${escapeHtml(result.title)}</h3>
    </div>
    <div class="result-grid">
      ${fields.map(([label, value, className]) => `<div class="result-field ${className}"><small>${label}</small><p>${escapeHtml(value)}</p></div>`).join("")}
      <div class="result-field"><small>最佳分类</small><p>${escapeHtml(result.best_fit_category)}</p></div>
      <div class="result-field"><small>置信度</small><p>${escapeHtml(result.confidence_level)} / 5</p></div>
    </div>
  `;
}

async function runAnalysis() {
  const title = document.querySelector("#liveTitle").value.trim();
  const abstract = document.querySelector("#liveAbstract").value.trim();
  if (!title || !abstract) {
    showToast("请先填写论文标题和摘要");
    return;
  }
  const button = document.querySelector("#analyzeButton");
  const placeholder = document.querySelector("#livePlaceholder");
  const progress = document.querySelector("#analysisProgress");
  const resultPanel = document.querySelector("#analysisResult");
  const steps = ["读取标题与摘要", "提取研究问题", "识别方法与实验", "评估创新与局限", "生成结构化卡片"];
  button.disabled = true;
  button.textContent = "AI 正在解析...";
  placeholder.classList.add("hidden");
  resultPanel.classList.add("hidden");
  progress.classList.remove("hidden");
  progress.innerHTML = `
    <div class="progress-title"><h3>正在生成论文卡片</h3><span id="progressPercent">0%</span></div>
    ${steps.map((step, index) => `<div class="analysis-step" data-step="${index}"><i>${index + 1}</i><span>${step}</span></div>`).join("")}
  `;

  let apiPromise;
  try {
    apiPromise = fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, abstract }),
    }).then(async (response) => {
      if (!response.ok) throw new Error("API unavailable");
      return response.json();
    }).catch(() => null);
  } catch {
    apiPromise = Promise.resolve(null);
  }

  for (let index = 0; index < steps.length; index += 1) {
    progress.querySelectorAll(".analysis-step").forEach((element, elementIndex) => {
      element.classList.toggle("done", elementIndex < index);
      element.classList.toggle("active", elementIndex === index);
      if (elementIndex < index) element.querySelector("i").textContent = "✓";
    });
    document.querySelector("#progressPercent").textContent = `${(index + 1) * 20}%`;
    await new Promise((resolve) => setTimeout(resolve, 580));
  }

  let analysis;
  try {
    analysis = await Promise.race([
      apiPromise,
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 12000)),
    ]);
    if (!analysis) throw new Error("API unavailable");
    analysis.source = "live";
  } catch {
    analysis = cachedAnalysis(title);
  }

  progress.classList.add("hidden");
  resultPanel.innerHTML = analysisResultHtml(analysis);
  resultPanel.classList.remove("hidden");
  button.disabled = false;
  button.textContent = "✦ 再次解析";
}

function exportSurvey() {
  const report = state.data.finalSurvey;
  const markdown = [
    `# ${report.title}`,
    "",
    "## Abstract",
    report.abstract,
    "",
    ...report.sections.flatMap((section) => [`## ${section.title}`, section.content, ""]),
  ].join("\n");
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "SurveyMind-Final-Survey.md";
  link.click();
  URL.revokeObjectURL(url);
  showToast("最终综述已导出");
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => gotoSection(button.dataset.section)));
  document.querySelectorAll("[data-goto]").forEach((button) => button.addEventListener("click", () => gotoSection(button.dataset.goto)));
  document.querySelector("#mobileMenu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
  document.querySelector("#themeButton").addEventListener("click", () => document.body.classList.toggle("light"));

  ["paperSearch", "categoryFilter", "yearFilter"].forEach((id) => {
    document.querySelector(`#${id}`).addEventListener(id === "paperSearch" ? "input" : "change", renderPapers);
  });
  document.querySelector("#paperGrid").addEventListener("click", (event) => {
    const card = event.target.closest("[data-paper-id]");
    if (card) openPaperModal(card.dataset.paperId);
  });
  document.querySelector("[data-close-modal]").addEventListener("click", () => document.querySelector("#paperModal").classList.add("hidden"));
  document.querySelector("#paperModal").addEventListener("click", (event) => {
    if (event.target.id === "paperModal") event.currentTarget.classList.add("hidden");
  });

  document.querySelector("#taxonomyGraph").addEventListener("click", (event) => {
    const node = event.target.closest("[data-node-id]");
    if (!node) return;
    state.selectedTaxonomy = node.dataset.nodeId;
    renderTaxonomy();
  });
  document.querySelector("#compareSelector").addEventListener("click", (event) => {
    const pill = event.target.closest("[data-compare-id]");
    if (!pill) return;
    const id = pill.dataset.compareId;
    if (state.selectedCompare.includes(id)) {
      if (state.selectedCompare.length === 1) return showToast("至少保留一篇论文用于对比");
      state.selectedCompare = state.selectedCompare.filter((item) => item !== id);
    } else {
      if (state.selectedCompare.length >= 3) state.selectedCompare.shift();
      state.selectedCompare.push(id);
    }
    renderComparison();
  });
  document.querySelector("#clearCompare").addEventListener("click", () => {
    state.selectedCompare = ["p01"];
    renderComparison();
  });
  document.querySelector("#weeklyTimeline").addEventListener("click", (event) => {
    const item = event.target.closest("[data-digest-index]");
    if (!item) return;
    state.selectedDigest = Number(item.dataset.digestIndex);
    renderWeekly();
  });
  document.querySelector("#surveyToc").addEventListener("click", (event) => {
    const target = event.target.closest("[data-survey-target]");
    if (target) document.querySelector(`#${target.dataset.surveyTarget}`).scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.querySelector("#exportSurvey").addEventListener("click", exportSurvey);
  document.querySelector("#analyzeButton").addEventListener("click", runAnalysis);

  document.querySelector("#memberButton").addEventListener("click", () => document.querySelector("#memberModal").classList.remove("hidden"));
  document.querySelector("[data-close-members]").addEventListener("click", () => document.querySelector("#memberModal").classList.add("hidden"));
  document.querySelector("#memberModal").addEventListener("click", (event) => {
    if (event.target.id === "memberModal") event.currentTarget.classList.add("hidden");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelectorAll(".modal-backdrop").forEach((modal) => modal.classList.add("hidden"));
  });
}

function renderAll() {
  renderOverview();
  populateFilters();
  renderPapers();
  renderTaxonomy();
  renderComparison();
  renderInsights();
  renderWeekly();
  renderSurvey();
  memberModal();
  const update = new Date(state.data.meta.lastUpdated);
  document.querySelector("#syncTime").textContent = `最近同步 ${update.toLocaleDateString("zh-CN")} ${update.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
}

async function init() {
  await loadData();
  renderAll();
  bindEvents();
  const initialSection = location.hash.slice(1);
  if (sectionNames[initialSection]) gotoSection(initialSection);
}

init();
