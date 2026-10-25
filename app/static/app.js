"use strict";

const $ = (id) => document.getElementById(id);

function fmtInt(n) {
  return n.toLocaleString("pt-PT");
}

function updateRangeInfo() {
  const lo = parseInt($("lo").value, 10);
  const hi = parseInt($("hi").value, 10);
  const info = $("rangeinfo");
  if (Number.isNaN(lo) || Number.isNaN(hi) || hi < lo) {
    info.textContent = "Intervalo invalido.";
    return;
  }
  const n = hi - lo + 1;
  info.innerHTML =
    `Espaco de procura: <strong>${fmtInt(n)}</strong> seeds candidatos ` +
    `(em vez de 2<sup>256</sup> &asymp; 1.2&times;10<sup>77</sup> chaves).`;
}

$("lo").addEventListener("input", updateRangeInfo);
$("hi").addEventListener("input", updateRangeInfo);
updateRangeInfo();

async function previewSplit() {
  try {
    const r = await fetch("/api/split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: $("message").value }),
    });
    const d = await r.json();
    if (r.ok) {
      $("ivhex").textContent = d.iv_hex;
      $("ctinfo").textContent = `${d.ct_len} bytes`;
    }
  } catch (_) {
    /* ignora */
  }
}
$("message").addEventListener("input", previewSplit);
previewSplit();

function runAttack() {
  const btn = $("run");
  btn.disabled = true;
  $("resultPanel").hidden = true;
  $("errorPanel").hidden = true;
  $("fill").style.width = "0%";
  $("counter").textContent = "0 / 0";
  $("rate").textContent = "";
  $("timer").textContent = "0.00 s";

  const body = JSON.stringify({
    message: $("message").value,
    lo: parseInt($("lo").value, 10),
    hi: parseInt($("hi").value, 10),
    crib: $("crib").value,
  });

  const t0 = performance.now();
  const tick = setInterval(() => {
    $("timer").textContent = ((performance.now() - t0) / 1000).toFixed(2) + " s";
  }, 100);

  fetch("/api/crack-stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  })
    .then((resp) => {
      if (!resp.ok) return resp.json().then((d) => Promise.reject(d.error || "Erro"));
      return streamSSE(resp, t0);
    })
    .catch((err) => showError(typeof err === "string" ? err : JSON.stringify(err)))
    .finally(() => {
      clearInterval(tick);
      btn.disabled = false;
    });
}

async function streamSSE(resp, t0) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const chunk of parts) {
      const ev = parseEvent(chunk);
      if (!ev) continue;
      if (ev.event === "start") {
        total = ev.data.total;
        $("counter").textContent = `0 / ${fmtInt(total)}`;
      } else if (ev.event === "progress") {
        setProgress(ev.data.tried, ev.data.total, t0);
      } else if (ev.event === "found") {
        setProgress(ev.data.seeds_tried, ev.data.total, t0);
        showResult(ev.data);
      } else if (ev.event === "notfound") {
        setProgress(ev.data.seeds_tried, ev.data.total, t0);
        showError(
          `Nenhum seed no intervalo produziu o prefixo conhecido ` +
            `(${fmtInt(ev.data.seeds_tried)} testados em ${ev.data.elapsed_s} s).`
        );
      } else if (ev.event === "error") {
        showError(ev.data.message);
      }
    }
  }
}

function parseEvent(chunk) {
  const lines = chunk.split("\n");
  let event = "message";
  let data = "";
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch (_) {
    return null;
  }
}

function setProgress(tried, total, t0) {
  const pct = total ? (tried / total) * 100 : 0;
  $("fill").style.width = pct.toFixed(2) + "%";
  $("counter").textContent = `${fmtInt(tried)} / ${fmtInt(total)}`;
  const secs = (performance.now() - t0) / 1000;
  if (secs > 0) {
    $("rate").textContent = fmtInt(Math.round(tried / secs)) + " seeds/s";
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function showResult(d) {
  $("rseed").textContent = d.seed;
  $("rutc").textContent = d.seed_utc;
  $("rkey").textContent = d.key_hex;
  $("rtried").textContent = `${fmtInt(d.seeds_tried)} de ${fmtInt(d.total)} (${d.elapsed_s} s)`;

  const crib = $("crib").value;
  let html = escapeHtml(d.plaintext);
  if (crib && d.plaintext.startsWith(crib)) {
    html = "<mark>" + escapeHtml(crib) + "</mark>" + escapeHtml(d.plaintext.slice(crib.length));
  }
  $("plaintext").innerHTML = html;
  $("resultPanel").hidden = false;
  $("fill").style.width = "100%";
}

function showError(msg) {
  $("errmsg").textContent = msg;
  $("errorPanel").hidden = false;
}

$("run").addEventListener("click", runAttack);

// --- Comparação académica: dia / semana / mês / ano ------------------------

const SECONDS_PER_YEAR = 31557600;

function fmtTime(s) {
  if (!isFinite(s)) return "∞";
  if (s < 1e-3) return (s * 1e6).toFixed(0) + " µs";
  if (s < 1) return (s * 1e3).toFixed(0) + " ms";
  if (s < 60) return s.toFixed(2) + " s";
  if (s < 3600) return (s / 60).toFixed(1) + " min";
  if (s < 86400) return (s / 3600).toFixed(1) + " h";
  if (s < SECONDS_PER_YEAR) return (s / 86400).toFixed(1) + " dias";
  const years = s / SECONDS_PER_YEAR;
  if (years < 1e4) return years.toFixed(1) + " anos";
  return years.toExponential(1).replace("e+", "×10^").replace(".", ",") + " anos";
}

function fmtSeeds(n) {
  if (n >= 1e6) return fmtInt(n) + " (≈2^" + Math.log2(n).toFixed(1) + ")";
  return fmtInt(n);
}

function runBenchmark() {
  const btn = $("runBench");
  btn.disabled = true;
  btn.textContent = "A medir…";
  fetch("/api/benchmark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: $("message").value }),
  })
    .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(d.error || "Erro"))))
    .then(renderBenchmark)
    .catch((err) => showError(typeof err === "string" ? err : JSON.stringify(err)))
    .finally(() => {
      btn.disabled = false;
      btn.textContent = "Comparar dia / semana / mês / ano";
    });
}

function renderBenchmark(d) {
  const rows = d.results.slice();
  const maxScan = Math.max(...rows.map((r) => r.scan_s));
  const body = $("benchBody");
  body.innerHTML = "";

  for (const r of rows) {
    const pct = maxScan > 0 ? (r.scan_s / maxScan) * 100 : 0;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${r.label}${r.measured ? " <span style='color:var(--muted)'>(medido)</span>" : ""}</td>` +
      `<td class="seeds">${fmtSeeds(r.span)}</td>` +
      `<td class="time">${fmtTime(r.scan_s)}</td>` +
      `<td class="time">${fmtTime(r.expected_find_s)}</td>` +
      `<td><div class="bartrack"><div class="barfill" style="width:${pct.toFixed(1)}%"></div></div></td>`;
    body.appendChild(tr);
  }

  // Linha de contraste: espaço completo do AES-256.
  const aes = document.createElement("tr");
  aes.className = "aes";
  aes.innerHTML =
    `<td>AES-256 (completo)</td>` +
    `<td class="seeds">2^256 ≈ ${d.aes256.space_sci}</td>` +
    `<td class="time">${fmtTime(d.aes256.scan_s)}</td>` +
    `<td class="time">—</td>` +
    `<td><div class="bartrack"><div class="barfill" style="width:100%"></div></div></td>`;
  body.appendChild(aes);

  const universe = 1.38e10; // idade do universo em anos
  const ratio = d.aes256.scan_s / SECONDS_PER_YEAR / universe;
  $("benchNote").innerHTML =
    `Débito medido: <strong>${fmtInt(Math.round(d.avg_rate))} seeds/s</strong>. ` +
    `Varrer o espaço completo do AES-256 levaria cerca de ${ratio.toExponential(0).replace("e+", "×10^")} ` +
    `vezes a idade do universo — é isso que torna o AES seguro quando a chave é bem gerada. ` +
    `A barra do AES está ao mesmo nível das outras apenas para caber na tabela; na realidade é incomparavelmente maior.`;
  $("benchResult").hidden = false;
}

$("runBench").addEventListener("click", runBenchmark);
