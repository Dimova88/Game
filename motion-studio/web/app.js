// Motion Studio · lógica de la interfaz (sin dependencias).
const $ = (sel) => document.querySelector(sel);
const state = { meta: null, project: null, plan: null, styleKey: "neon_tech", jobTimer: null };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return node;
}

function showBanner(msg, kind = "warn") {
  const b = $("#banner");
  b.textContent = msg;
  b.className = "banner " + (kind === "error" ? "error" : "");
  b.classList.toggle("hidden", !msg);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function fmtTime(s) {
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(1).padStart(4, "0");
  return `${String(m).padStart(2, "0")}:${sec}`;
}

// ---------------------------------------------------------------- arranque
async function init() {
  state.meta = await api("/api/meta");
  const m = state.meta;
  $("#meta").textContent = `ffmpeg: ${m.ffmpeg.split("/").pop()} · fuentes: ${m.fonts.bold ? "sistema" : "integrada"}`;
  const lang = $("#language");
  for (const [k, v] of Object.entries(m.languages)) lang.append(el("option", { value: k }, v));
  const wm = $("#whisper_model");
  for (const w of m.whisper_models) wm.append(el("option", { value: w, selected: w === m.default_whisper_model ? "selected" : null }, w));
  const planner = $("#planner");
  planner.querySelector('option[value="llm"]').disabled = !m.llm_configured;
  $("#llm-hint").textContent = m.llm_configured
    ? `LLM configurado: ${m.llm_model}`
    : "Para usar un LLM define MOTION_LLM_BASE_URL y MOTION_LLM_MODEL (opcional).";
  const aspect = $("#aspect");
  for (const a of m.aspects) aspect.append(el("option", { value: a, selected: a === "16:9" ? "selected" : null }, a === "16:9" ? "16:9 · YouTube" : a === "9:16" ? "9:16 · Shorts" : "1:1"));
  const res = $("#resolution");
  for (const r of m.resolutions) res.append(el("option", { value: r, selected: r === "1080p" ? "selected" : null }, r));
  const fps = $("#fps");
  for (const f of m.fps) fps.append(el("option", { value: f, selected: f === 30 ? "selected" : null }, String(f)));
  renderStyles();
  await refreshProjects();
}

function renderStyles() {
  const box = $("#styles");
  box.innerHTML = "";
  for (const s of state.meta.styles) {
    const sw = el("div", { class: "swatch", style: `background: linear-gradient(135deg, rgb(${s.bg_top}), rgb(${s.bg_bottom}))` },
      ...s.swatch.map((c) => el("i", { style: `background: rgb(${c})` })));
    const card = el("label", { class: "style-card" + (s.key === state.styleKey ? " selected" : ""), "data-key": s.key },
      sw, el("b", {}, s.name), el("p", {}, s.description));
    card.addEventListener("click", () => {
      state.styleKey = s.key;
      box.querySelectorAll(".style-card").forEach((c) => c.classList.toggle("selected", c.dataset.key === s.key));
    });
    box.append(card);
  }
}

// ---------------------------------------------------------------- proyectos
async function refreshProjects() {
  const list = await api("/api/projects");
  const ul = $("#projects");
  ul.innerHTML = "";
  if (!list.length) ul.append(el("li", {}, el("span", {}, "Aún no hay proyectos.")));
  for (const p of list) {
    const label = el("div", {}, el("b", {}, p.name), el("br"), el("span", {}, `${p.status} · ${p.created.replace("T", " ").slice(0, 16)}`));
    const open = el("button", {}, "Abrir");
    open.addEventListener("click", () => openProject(p.id).catch((e) => showBanner(e.message, "error")));
    const del = el("button", { title: "Eliminar" }, "✕");
    del.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar "${p.name}"?`)) return;
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      if (state.project?.project.id === p.id) location.reload();
      refreshProjects();
    });
    const li = el("li", { class: state.project?.project.id === p.id ? "active" : "" }, label, el("div", { class: "actions" }, open, del));
    ul.append(li);
  }
}

async function openProject(pid) {
  const data = await api(`/api/projects/${pid}`);
  state.project = data;
  state.plan = data.plan;
  renderProject();
  await refreshProjects();
}

function renderProject() {
  const { project, plan, transcript, has_audio } = state.project;
  $("#project-card").classList.remove("hidden");
  $("#project-title").textContent = project.name;
  const info = [
    `Estado: ${project.status}`,
    project.duration ? `Duración: ${fmtTime(project.duration)}` : null,
    project.transcript_source ? `Transcripción: ${project.transcript_source}` : null,
    project.word_count ? `${project.word_count} palabras` : null,
    project.scene_count ? `${project.scene_count} escenas` : null,
    has_audio ? "Audio incluido" : "Sin audio (solo transcripción)",
  ].filter(Boolean).join(" · ");
  $("#project-info").textContent = info;
  showBanner((project.warnings || []).join(" ") || "", "warn");
  if (project.error) showBanner("Error: " + project.error, "error");

  $("#transcript").textContent = transcript ? transcript.words.map((w) => w.text).join(" ") : "Sin transcripción todavía.";

  const hasPlan = !!plan;
  $("#scenes-card").classList.toggle("hidden", !hasPlan);
  $("#style-card").classList.toggle("hidden", !hasPlan);
  $("#output-card").classList.toggle("hidden", !(project.outputs && project.outputs.length));
  if (hasPlan) renderScenes(plan.scenes);
  renderOutputs(project);
}

const KIND_OPTIONS = [
  ["title", "Texto cinético"], ["stat", "Cifra destacada"], ["bullets", "Lista animada"],
  ["comparison", "Comparación"], ["question", "Pregunta"], ["quote", "Cita"],
];

function renderScenes(scenes) {
  const tbody = $("#scenes tbody");
  tbody.innerHTML = "";
  for (const s of scenes) {
    const kind = el("select", { "data-id": s.id, "data-field": "kind" },
      ...KIND_OPTIONS.map(([v, l]) => el("option", { value: v, selected: v === s.kind ? "selected" : null }, l)));
    const emph = el("input", { type: "text", value: s.tokens.filter((t) => t.emph).map((t) => t.text.replace(/[^\p{L}\p{N}%$€]/gu, "")).join(", "), "data-id": s.id, "data-field": "emphasis", placeholder: "palabras" });
    tbody.append(el("tr", {},
      el("td", {}, String(s.id + 1)),
      el("td", { class: "time" }, `${fmtTime(s.start)}–${fmtTime(s.end)}`),
      el("td", {}, kind),
      el("td", { class: "text" }, s.sentence),
      el("td", { class: "emph" }, emph)));
  }
}

async function savePlan(quiet = false) {
  const edits = [];
  document.querySelectorAll('#scenes [data-field="kind"]').forEach((sel) => {
    const id = Number(sel.dataset.id);
    const emphInput = document.querySelector(`#scenes [data-field="emphasis"][data-id="${id}"]`);
    const emphasis = emphInput.value.split(",").map((x) => x.trim()).filter(Boolean);
    edits.push({ id, kind: sel.value, emphasis });
  });
  const data = await api(`/api/projects/${state.project.project.id}/plan`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenes: edits }),
  });
  state.plan = data.plan;
  renderScenes(data.plan.scenes);
  if (!quiet) {
    showBanner("Escenas guardadas.", "warn");
    setTimeout(() => showBanner(""), 2000);
  }
}

$("#btn-save-plan").addEventListener("click", () => savePlan().catch((e) => showBanner(e.message, "error")));

function renderOutputs(project) {
  const ul = $("#outputs");
  ul.innerHTML = "";
  const outs = (project.outputs || []).slice().reverse();
  for (const o of outs) {
    const play = el("button", {}, "Ver");
    play.addEventListener("click", () => showVideo(project.id, o.file));
    ul.append(el("li", {}, el("div", {}, el("b", {}, o.style_name), el("br"), el("span", {}, `${o.resolution} · ${o.fps} fps · ${o.aspect}`)), play));
  }
  if (outs.length) showVideo(project.id, outs[0].file);
}

function showVideo(pid, file) {
  $("#output-card").classList.remove("hidden");
  $("#player").src = `/api/projects/${pid}/files/${encodeURIComponent(file)}`;
  $("#download").href = `/api/projects/${pid}/files/${encodeURIComponent(file)}`;
  $("#download").setAttribute("download", file);
}

// ---------------------------------------------------------------- trabajos
function watchJob(jid, onDone) {
  $("#progress-card").classList.remove("hidden");
  const bar = $("#progress-bar"), text = $("#progress-text");
  clearInterval(state.jobTimer);
  state.jobTimer = setInterval(async () => {
    try {
      const j = await api(`/api/jobs/${jid}`);
      bar.style.width = `${Math.round(j.progress * 100)}%`;
      text.textContent = `${j.stage} · ${Math.round(j.progress * 100)}%`;
      if (j.status === "done" || j.status === "error") {
        clearInterval(state.jobTimer);
        if (j.status === "error") showBanner("Error: " + j.error, "error");
        onDone(j);
      }
    } catch (e) {
      clearInterval(state.jobTimer);
      showBanner(e.message, "error");
    }
  }, 700);
}

$("#new-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("#btn-analyze");
  const fd = new FormData(ev.target);
  if (!fd.get("audio")?.name && !fd.get("transcript")?.name) {
    showBanner("Sube un audio o una transcripción.", "error");
    return;
  }
  btn.disabled = true;
  showBanner("");
  try {
    const { project_id, job_id } = await api("/api/projects", { method: "POST", body: fd });
    watchJob(job_id, async (j) => {
      btn.disabled = false;
      if (j.status === "done") {
        await openProject(project_id);
        $("#scenes-card").scrollIntoView({ behavior: "smooth" });
      } else {
        await refreshProjects();
      }
    });
  } catch (e) {
    btn.disabled = false;
    showBanner(e.message, "error");
  }
});

$("#btn-render").addEventListener("click", async () => {
  const pid = state.project.project.id;
  const btn = $("#btn-render");
  btn.disabled = true;
  try {
    // Guarda antes cualquier cambio pendiente de escenas
    await savePlan(true);
    const { job_id } = await api(`/api/projects/${pid}/render`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        style: state.styleKey,
        aspect: $("#aspect").value,
        resolution: $("#resolution").value,
        fps: Number($("#fps").value),
        captions: $("#captions").checked,
      }),
    });
    watchJob(job_id, async (j) => {
      btn.disabled = false;
      if (j.status === "done") await openProject(pid);
      else await refreshProjects();
    });
  } catch (e) {
    btn.disabled = false;
    showBanner(e.message, "error");
  }
});

init().catch((e) => showBanner("No se pudo conectar con el servidor: " + e.message, "error"));
