(() => {
  const $ = (id) => document.getElementById(id);
  const text = $("paperText");
  const message = $("message");
  let activeJob = null;

  function showMessage(value, error = false) {
    message.textContent = value || "";
    message.className = `message${error ? " error" : ""}`;
  }
  function setStatus(id, value, cls = "neutral") {
    const el = $(id);
    el.textContent = value;
    el.className = `status ${cls}`;
  }
  function jsonHeaders() { return { "Content-Type": "application/json" }; }
  async function post(path, payload) {
    const res = await fetch(path, { method: "POST", headers: jsonHeaders(), body: JSON.stringify(payload) });
    const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  }
  function updateCount() { $("charCount").textContent = `${text.value.length.toLocaleString()} 字符`; }
  function displayDiagnosis(data) {
    const d = data.diagnosis || data;
    const stats = d.stats || {};
    const lines = [
      `语言：${d.language || "未知"}`,
      `AI-style level：${(stats.ai_style_level || "unknown").toUpperCase()}`,
      `句子：${stats.n_sentences ?? "—"}，段落：${stats.n_paragraphs ?? "—"}`,
      `句长 CV：${stats.sentence_cv ?? "—"}，模板密度：${stats.template_density ?? "—"}/${stats.density_unit || "1k"}`,
      `模板命中：${(stats.template_hits || []).map(x => `${x.phrase}×${x.count}`).join("，") || "无"}`,
      `机械链：${(stats.chains || []).length} 段`,
    ];
    if (d.qualitative?.overall) lines.push(`LLM 自然度：${d.qualitative.overall.naturalness_score}/5`, d.qualitative.overall.summary || "");
    $("diagnosisOutput").textContent = lines.join("\n");
    setStatus("diagnosisLevel", (stats.ai_style_level || "未知").toUpperCase(), stats.ai_style_level === "high" ? "fail" : "success");
  }
  function displayValidation(validation) {
    const rate = validation.preserved_rate;
    $("preservedRate").textContent = rate == null ? "—" : `保真 ${(rate * 100).toFixed(1)}%`;
    $("preservedRate").className = `status ${validation.passed ? "success" : "fail"}`;
    const violations = validation.violations || [];
    $("violations").className = violations.length ? "violations" : "violations muted";
    $("violations").innerHTML = violations.length
      ? violations.map(v => `<div class="violation ${v.severity === "soft" ? "soft" : ""}"><strong>${escapeHtml(v.rule)}</strong>：${escapeHtml(v.detail)}</div>`).join("")
      : "确定性校验通过，没有发现硬违规。";
  }
  function displayJob(data) {
    const status = data.status || "unknown";
    const cls = status === "success" ? "success" : status === "reverted" || status === "failed" ? "fail" : status === "running" || status === "queued" ? "running" : "neutral";
    setStatus("jobStatus", status.toUpperCase(), cls);
    if (data.validation) displayValidation(data.validation);
    if (data.final_text != null) $("finalOutput").textContent = data.final_text;
    if (data.report != null) $("reportOutput").textContent = data.report;
    const summary = [
      data.status === "reverted" ? "改写未通过保真门禁，当前展示原文。" : data.status === "success" ? "改写完成并通过确定性校验。" : "",
      data.loops_used != null ? `修复轮次：${data.loops_used}` : "",
      ...(data.warnings || []).map(x => `提示：${x}`),
      data.error ? `错误：${data.error}` : "",
    ].filter(Boolean);
    $("rewriteSummary").textContent = summary.join("\n") || "任务处理中……";
  }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])); }

  $("fileInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!/\.(md|markdown|txt)$/i.test(file.name)) { showMessage("只支持 .md、.markdown、.txt 文件", true); return; }
    text.value = await file.text();
    $("fileName").textContent = file.name;
    updateCount();
    showMessage("文件已载入。");
  });
  text.addEventListener("input", updateCount);

  $("diagnoseBtn").addEventListener("click", async () => {
    try { showMessage("正在诊断……"); const data = await post("/api/diagnose", { text: text.value, filename: $("fileName").textContent }); displayDiagnosis(data); showMessage("诊断完成。"); }
    catch (err) { showMessage(err.message, true); }
  });
  $("reviewBtn").addEventListener("click", async () => {
    try { showMessage("正在评审……"); const data = await post("/api/review", { original: text.value }); displayDiagnosis(data.diagnosis || data); showMessage((data.warnings || []).join("\n") || "评审完成。"); }
    catch (err) { showMessage(err.message, true); }
  });
  $("rewriteBtn").addEventListener("click", async () => {
    if (!text.value.trim()) { showMessage("请先输入论文文本。", true); return; }
    try {
      $("rewriteBtn").disabled = true; setStatus("jobStatus", "QUEUED", "running"); showMessage("已加入改写队列……");
      const data = await post("/api/rewrite", { text: text.value, filename: $("fileName").textContent }); activeJob = data.job_id;
      await pollJob(activeJob);
    } catch (err) { showMessage(err.message, true); setStatus("jobStatus", "ERROR", "fail"); }
    finally { $("rewriteBtn").disabled = false; }
  });
  async function pollJob(jobId) {
    const read = async () => { const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`); const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`); displayJob(data); return data; };
    let data = await read();
    while (!["success", "reverted", "failed"].includes(data.status)) { await new Promise(resolve => setTimeout(resolve, 900)); data = await read(); }
    showMessage(data.status === "success" ? "改写完成。" : data.status === "reverted" ? "改写未通过保真门禁，已回滚原文。" : "改写任务失败。", data.status === "failed");
  }
  document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active")); tab.classList.add("active");
    $("finalOutput").classList.toggle("hidden", tab.dataset.target !== "finalOutput");
    $("reportOutput").classList.toggle("hidden", tab.dataset.target !== "reportOutput");
  }));
  updateCount();
})();
