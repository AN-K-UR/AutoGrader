"use strict";
/* Everything in a report can come from an untrusted program, so all of it is written
   with textContent through el(). Nothing here builds HTML from strings. */

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
let lastResult = null;
let rules = [];

function el(tag, options = {}, ...children) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.title) node.title = options.title;
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${url}`);
  return response.json();
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function describeRules() {
  const chosen = rules.find((item) => item.file === $("rules").value);
  $("rules-detail").textContent = chosen
    ? `${chosen.description} Limits: ${chosen.time_limit_s} s, ${chosen.memory_limit_mb} MB. ` +
      `${chosen.metrics.length} metrics.`
    : "";
}

function showSystem(status) {
  const entries = [
    ["Sandbox", status.sandbox ? status.sandbox.name : "none available"],
    ["Local LLM", status.ollama.status === "ok"
      ? `Ollama, ${status.ollama.models.length} model(s)` : "not running"],
  ];
  for (const [term, value] of entries) {
    $("system").append(el("div", {}, el("dt", {}, term), el("dd", {}, value)));
  }
  if (status.ollama.status !== "ok") {
    $("use-llm").disabled = true;
    $("llm-row").classList.add("off");
    $("llm-label").textContent = "Local LLM remarks are off: Ollama is not running. Grading does not need it.";
  }
  if (!status.sandbox) showError("No secure sandbox is available, so grading is refused.");
}

async function initialize() {
  try {
    const [ruleSets, samples, status] = await Promise.all([
      getJson("/api/rules"), getJson("/api/samples"), getJson("/api/status")]);
    rules = ruleSets;
    for (const item of rules) {
      $("rules").append(new Option(`${item.problem} (${item.file})`, item.file));
    }
    describeRules();
    showSystem(status);
    for (const sample of samples) {
      const option = new Option(sample.name, sample.name);
      option.dataset.source = sample.source;
      option.dataset.rules = sample.rules;
      $("sample").append(option);
    }
  } catch (error) {
    showError(error.message);
  }
}

function useSample() {
  const option = $("sample").selectedOptions[0];
  if (!option.value) return;
  $("source").value = option.dataset.source;
  $("filename").value = option.value;
  $("rules").value = option.dataset.rules;
  describeRules();
}

async function useFile() {
  const file = $("file").files[0];
  if (!file) return;
  $("source").value = await file.text();
  $("filename").value = file.name;
  $("sample").value = "";
}

async function grade() {
  showError("");
  const button = $("grade");
  button.disabled = true;
  button.textContent = "Grading…";
  try {
    const response = await fetch("/api/grade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: $("filename").value.trim(),
        source: $("source").value,
        rules: $("rules").value,
        use_llm: $("use-llm").checked,
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    lastResult = body;
    renderReport(body.report);
  } catch (error) {
    showError(error.message || "Grading failed.");
  } finally {
    button.disabled = false;
    button.textContent = "Grade submission";
  }
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = el("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadReport(extension) {
  const stem = lastResult.report.submission.replace(/\.c$/, "");
  if (extension === "json") {
    download(`${stem}.json`, JSON.stringify(lastResult.report, null, 2), "application/json");
  } else {
    download(`${stem}.txt`, lastResult.text, "text/plain");
  }
}

function button(label, handler) {
  const node = el("button", { className: "secondary" }, label);
  node.type = "button";
  node.addEventListener("click", handler);
  return node;
}

const FLAG_LABELS = {
  compilation_failed: "Did not compile",
  suspected_infinite_loop: "Suspected infinite loop",
  smoke_crashed: "Failed the smoke run",
  suspected_copying: "Similarity flag: human review needed",
  style_signals_advisory: "Style hints (advisory)",
};

function renderHero(report) {
  const shown = report.grade === null ? "Not gradable" : report.grade.toFixed(2);
  const number = el("div", { className: "grade" }, shown,
    report.grade === null ? null : el("small", {}, " / 100"));
  const statusClass = report.evaluation_status === "complete" ? "good" : "warn";
  const chips = el("div", { className: "chips" },
    el("span", { className: `chip ${statusClass}` }, `Evaluation ${report.evaluation_status}`),
    el("span", { className: "chip" }, `Sandbox: ${report.execution.name}`));
  for (const flag of report.flags) {
    const severe = flag.type !== "style_signals_advisory";
    chips.append(el("span", { className: `chip ${severe ? "bad" : ""}` },
      FLAG_LABELS[flag.type] || flag.type));
  }
  return el("div", { className: "panel" },
    el("div", { className: "hero" },
      el("div", {}, number,
        el("p", { className: "muted" }, `${report.submission} · ${report.problem}`)),
      el("div", { className: "actions" },
        button("JSON report", () => downloadReport("json")),
        button("Text report", () => downloadReport("txt")))),
    chips);
}

function bar(fraction, label) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 100 8");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const rect = document.createElementNS(SVG, "rect");
  rect.setAttribute("width", String(Math.max(0, Math.min(1, fraction)) * 100));
  rect.setAttribute("height", "8");
  svg.append(rect);
  return el("div", { className: "bar", title: label }, svg);
}

function renderMetric(metric) {
  const available = metric.max_contribution;
  let marks = "Not scored";
  if (metric.status === "scored" || metric.status === "blocked") {
    marks = `${metric.contribution.toFixed(1)} / ${available.toFixed(1)}`;
  }
  const verdict = metric.status === "blocked" ? `Blocked: ${metric.feedback}`
    : metric.status === "scored" ? metric.feedback : `Not evaluated: ${metric.feedback}`;
  const fraction = available > 0 ? metric.contribution / available : 0;
  return el("div", { className: "metric" },
    el("div", { className: "name" }, metric.name),
    el("div", { className: "marks" }, marks),
    bar(fraction, `${metric.name}: ${marks}`),
    el("div", { className: "verdict small" }, verdict));
}

function codeBlock(heading, text) {
  const value = text === null || text === undefined ? "(no reference answer)" : text;
  return el("div", {}, el("h4", {}, heading), el("pre", {}, value === "" ? "(empty)" : value));
}

function renderFailures(report) {
  const failures = report.feedback.where_you_failed;
  if (!failures.length) return null;
  const panel = el("div", { className: "panel" }, el("h2", {}, "Where it failed"));
  for (const item of failures) {
    const label = item.origin === "testset" ? "Test" : "Generated case";
    panel.append(el("div", { className: "failure" },
      el("strong", {}, `${label} ${item.test_id}`),
      el("span", { className: "muted small" }, ` ${item.outcome.replace(/_/g, " ")}`),
      el("div", { className: "pairs" },
        codeBlock("Input", item.input), codeBlock("Expected", item.expected),
        codeBlock("Got", item.got)),
      el("p", {}, item.why)));
  }
  return panel;
}

function renderSuggestions(report) {
  const { suggestions, advisory_llm_remarks: remarks } = report.feedback;
  if (!suggestions.length && !remarks.length) return null;
  const panel = el("div", { className: "panel" }, el("h2", {}, "How to raise the grade"));
  const list = el("ul", { className: "plain" });
  for (const item of suggestions.slice(0, 12)) {
    const lost = item.marks_lost ? `, ${item.marks_lost} marks lost` : "";
    list.append(el("li", {}, item.text,
      el("div", { className: "muted small" }, `${item.metric}${lost}`)));
  }
  panel.append(list);
  if (remarks.length) {
    const advice = el("ul", { className: "plain" });
    for (const remark of remarks) advice.append(el("li", {}, remark));
    panel.append(el("h3", {}, "Local LLM remarks (advisory, unscored)"), advice);
  }
  return panel;
}

function table(headings, rows) {
  const head = el("tr");
  for (const heading of headings) head.append(el("th", {}, heading));
  const body = el("tbody");
  for (const row of rows) {
    const line = el("tr");
    for (const value of row) line.append(el("td", {}, value));
    body.append(line);
  }
  return el("table", {}, el("thead", {}, head), body);
}

function section(title, ...content) {
  return el("details", {}, el("summary", {}, title), ...content);
}

function metricByAnalyzer(report, analyzer) {
  return report.metrics.find((item) => item.analyzer === analyzer);
}

function compilationSection(report) {
  const compilation = report.compilation;
  return section("Compilation",
    el("p", {}, compilation.success ? "Compiled" : "Did not compile",
      ` with ${compilation.compiler_version}`),
    el("p", { className: "muted small mono" }, compilation.flags.join(" ")),
    el("p", {}, `Smoke run: ${report.first_pass.smoke_detail || "not run"}`),
    compilation.output ? el("pre", {}, compilation.output) : null);
}

function testsSection(report) {
  const metric = metricByAnalyzer(report, "io_tests");
  if (!metric || !metric.evidence.results) return null;
  const rows = metric.evidence.results.map((item) => [
    item.test_id, item.status.replace(/_/g, " "), item.description,
    item.duration_s === null ? "" : `${item.duration_s.toFixed(3)} s`,
  ]);
  return section(`Test cases (${metric.evidence.tests_passed} of ${metric.evidence.tests_total} pass)`,
    table(["Test", "Result", "Description", "Time"], rows));
}

function complexitySection(report) {
  const metric = metricByAnalyzer(report, "complexity_estimator");
  if (!metric || !metric.evidence.estimated) return null;
  const { sizes, operation_counts: counts, estimated, required, confidence } = metric.evidence;
  return section(`Time complexity (estimated ${estimated}, required ${required})`,
    table(["Input size n", "Operations"],
      sizes.map((size, index) => [size, counts[index].toLocaleString()])),
    el("p", { className: "muted small" },
      `An estimate from exact operation counts, confidence ${confidence}. Time inside library calls is not counted.`));
}

function memorySection(report) {
  const metric = metricByAnalyzer(report, "sanitizer_run");
  if (!metric || metric.evidence.note === undefined) return null;
  const rows = metric.evidence.diagnostics.map((item) => [item.tool, item.line || "", item.message]);
  return section(`Memory safety (${rows.length} finding(s))`,
    rows.length ? table(["Tool", "Line", "Finding"], rows) : null,
    el("p", { className: "muted small" }, metric.evidence.note));
}

function structureSection(report) {
  const metric = metricByAnalyzer(report, "static_analysis");
  if (!metric || !metric.evidence.functions) return null;
  const findings = (metric.evidence.cppcheck_findings || []).map((item) => [
    item.line || "", item.severity, item.message]);
  return section("Structure",
    table(["Function", "Cyclomatic complexity", "Lines"],
      metric.evidence.functions.map((item) => [item.name, item.cyclomatic, item.length])),
    findings.length ? table(["Line", "Severity", "Cppcheck finding"], findings) : null);
}

function readabilitySection(report) {
  const metric = metricByAnalyzer(report, "llm_review");
  if (!metric || !metric.evidence.criteria) return null;
  const llm = metric.evidence.llm || {};
  const note = { disabled: "Not requested", ok: `Remarks from ${llm.model}` }[llm.status]
    || llm.reason || llm.status;
  return section("Readability",
    table(["Criterion", "Score"], Object.entries(metric.evidence.criteria)
      .map(([name, value]) => [name.replace(/_/g, " "), value.toFixed(2)])),
    el("p", { className: "muted small" },
      `The score comes from fixed checks. Local LLM: ${note}.`));
}

function similaritySection(report) {
  const metric = metricByAnalyzer(report, "similarity_flag");
  if (!metric) return null;
  if (metric.status !== "scored") return section("Similarity", el("p", {}, metric.feedback));
  return section(`Similarity (max ${metric.evidence.max_similarity.toFixed(2)})`,
    table(["Compared with", "Kind", "Similarity", "Containment"],
      metric.evidence.top_matches.map((item) => [item.target, item.kind,
        item.jaccard.toFixed(2), item.containment.toFixed(2)])),
    el("p", { className: "muted small" }, "Similarity is a reason for review. It does not prove copying."));
}

function skippedSection(report) {
  const skipped = report.feedback.skipped_checks;
  if (!skipped.length) return null;
  return section(`Skipped checks (${skipped.length})`,
    table(["Check", "Status", "Reason"],
      skipped.map((item) => [item.check, item.status.replace(/_/g, " "), item.reason])));
}

function limitsSection(report) {
  const block = report.usefulness_limitations;
  if (!block) return null;
  const list = (items, title) => {
    const node = el("ul", { className: "plain" });
    for (const item of items) {
      node.append(el("li", {}, el("strong", {}, title(item)), el("div", { className: "small" }, item.example)));
    }
    return node;
  };
  return section("Usefulness and limitations",
    el("h3", {}, "Useful for"), list(block.usefulness, (item) => item.use_case),
    el("h3", {}, "Limits of this report"), list(block.limitations, (item) => item.limitation));
}

function renderReport(report) {
  const metrics = el("div", { className: "panel" }, el("h2", {}, "Marks by metric"));
  for (const metric of report.metrics) metrics.append(renderMetric(metric));
  const details = el("div", { className: "panel" }, el("h2", {}, "Details"));
  for (const part of [compilationSection, testsSection, complexitySection, memorySection,
    structureSection, readabilitySection, similaritySection, skippedSection, limitsSection]) {
    const node = part(report);
    if (node) details.append(node);
  }
  const parts = [renderHero(report), metrics, renderFailures(report),
    renderSuggestions(report), details].filter(Boolean);
  $("results").replaceChildren(...parts);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("rules").addEventListener("change", describeRules);
$("sample").addEventListener("change", useSample);
$("file").addEventListener("change", useFile);
$("grade").addEventListener("click", grade);
initialize();
