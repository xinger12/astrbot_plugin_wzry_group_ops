/**
 * 王者荣耀群运营作战台 · 视图逻辑
 * 通过 bridge 调用插件后端 API。
 *
 * 兼容说明：AstrBot 不同版本的 bridge 全局名不同——
 *   v4.26 ~ v4.28  → window.AstrBotPluginPage
 *   v4.29+         → window.AstrBotPluginView（AstrBotPluginPage 作为别名保留）
 * 这里按优先级取可用的那个，保证全版本都能通信。
 */

const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

if (!bridge) {
  // bridge 由 AstrBot 在返回 HTML 时自动注入；若这里为空，说明视图不是
  // 通过 AstrBot 的视图入口打开的（例如直接双击 HTML 文件）。
  const el = document.querySelector(".app") || document.body;
  el.innerHTML =
    '<div style="padding:32px;font:14px/1.7 system-ui,sans-serif;color:#b45309;background:#fffbeb;border:1px solid #fcd34d;border-radius:12px;margin:24px">' +
    "<b>未检测到 AstrBot 视图环境</b><br>" +
    "本页面需通过 AstrBot WebUI 的插件视图入口打开（插件卡片 → 运营作战台）。<br>" +
    "直接双击打开 HTML 文件无法连接后端，因此不显示数据。" +
    "</div>";
  throw new Error("AstrBot plugin bridge not found");
}

/** 缓存状态 */
const state = {
  groups: [],
  templates: [],
  schedule: [],
  currentTpl: "",
  automation: {},
  replyRules: [],
  featureLabels: {},
  welcomeText: "",
  ai: {},
  aiScenes: [],
  aiOverrides: {},
  aiProviderAvailable: false,
  aiProviders: [],
  pointsCfg: {},
  quizCfg: {},
  pointRuleMeta: [],
  redeemItems: [],
  inviteCfg: {},
  inviteRows: [],
};

/** 自动化任务元数据（key 与后端 automation 配置一致） */
const AUTO_TASKS = [
  { key: "auto_collect", icon: "📊", name: "自动数据采集",
    desc: "定时拉取群成员，自动算出新增/退群/活跃，无需手工录入" },
  { key: "auto_followup", icon: "🆕", name: "自动新人跟进",
    desc: "入群后 30分钟 / 24小时 / 72小时 三级自动跟进，已发言则停止" },
  { key: "auto_cold_rescue", icon: "🔥", name: "自动冷场救场",
    desc: "群内长时间无消息时，自动发话题激活（仅活跃时段）" },
  { key: "auto_wake", icon: "🔔", name: "自动沉睡唤醒",
    desc: "识别多日未发言成员，自动 @ 召回（带冷却与数量上限）" },
  { key: "auto_settle", icon: "💎", name: "自动积分结算",
    desc: "每天自动给当日发言过的成员结算活跃积分" },
  { key: "auto_daily_report", icon: "📋", name: "自动运营日报",
    desc: "每天定时输出运营日报（人数/新增/活跃/积分榜）" },
  { key: "auto_weekly_board", icon: "🏆", name: "自动周榜发布",
    desc: "每周定时在群内发布积分排行榜" },
  { key: "auto_reply", icon: "💬", name: "自动关键词应答",
    desc: "命中关键词自动回复（怎么进车队/群规/积分/找CP 等）" },
];

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ */
/* 工具函数                                                            */
/* ------------------------------------------------------------------ */

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function todayStr() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function num(id) { const v = $(id)?.value; return v === "" || v === undefined ? undefined : Number(v); }

function setResult(el, msg, isErr = false) {
  if (!el) return;
  el.textContent = msg;
  el.className = "result " + (isErr ? "err" : "ok");
  if (!isErr) setTimeout(() => { if (el.textContent === msg) { el.textContent = ""; el.className = "result"; } }, 3500);
}

/**
 * 页内轻提示。替代 alert()——视图运行在受限 iframe 中，
 * 原生 alert 可能被沙箱拦截，导致"操作无反馈"的错觉。
 */
function toast(msg, isErr = false) {
  let box = document.getElementById("__toast");
  if (!box) {
    box = document.createElement("div");
    box.id = "__toast";
    document.body.appendChild(box);
  }
  box.textContent = msg;
  box.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(box.__t);
  box.__t = setTimeout(() => { box.className = "toast"; }, 2600);
}

/**
 * 页内二次点击确认。替代 window.confirm()——视图运行在受限 iframe 中，
 * 原生 confirm 会被沙箱静默拦截并返回 false，表现为"点了完全没反应"。
 * 用法：inlineConfirm($("btn"), "确定执行？", () => doIt());
 */
function inlineConfirm(btn, message, onConfirm, ms = 8000) {
  if (!btn) {
    onConfirm();
    return;
  }
  if (btn.dataset.confirming === "1") {
    clearTimeout(Number(btn.dataset.timer || 0));
    btn.dataset.confirming = "0";
    if (btn.dataset.orig) btn.textContent = btn.dataset.orig;
    btn.classList.remove("confirming");
    onConfirm();
    return;
  }
  btn.dataset.confirming = "1";
  btn.dataset.orig = btn.textContent;
  btn.classList.add("confirming");
  btn.textContent = "确认？再点一次";
  toast(message);
  const t = setTimeout(() => {
    btn.dataset.confirming = "0";
    btn.classList.remove("confirming");
    if (btn.dataset.orig) btn.textContent = btn.dataset.orig;
  }, ms);
  btn.dataset.timer = String(t);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch { /* ignore */ }
    document.body.removeChild(ta);
    return true;
  }
}

/* ------------------------------------------------------------------ */
/* Tab 切换                                                            */
/* ------------------------------------------------------------------ */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const panel = $("p-" + tab.dataset.t);
    if (panel) panel.classList.add("active");
  });
});

/* ------------------------------------------------------------------ */
/* 下拉框填充                                                          */
/* ------------------------------------------------------------------ */

function fillGroupSelects() {
  const ids = ["pushGroup", "ptsGroup", "adjGroup", "stGroup", "actGroup", "qzGroup", "ivGroup"];
  const opts = state.groups.length
    ? state.groups.map((g) => `<option value="${escapeHtml(g.group_id)}">${escapeHtml(g.name)} (${escapeHtml(g.group_id)})</option>`).join("")
    : `<option value="">（暂无已绑定群）</option>`;
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.innerHTML = opts;
  });
}

function fillTemplateSelects() {
  const opts = state.templates
    .map((t) => `<option value="${escapeHtml(t.key)}">${escapeHtml(t.name)}${t.slot ? " · " + escapeHtml(t.slot) : ""}</option>`)
    .join("");
  const push = $("pushTpl");
  const sc = $("scTpl");
  if (push) push.innerHTML = opts;
  if (sc) sc.innerHTML = opts;
}

/* ------------------------------------------------------------------ */
/* 概览                                                                */
/* ------------------------------------------------------------------ */

async function loadStatus() {
  try {
    const s = await bridge.apiGet("status");
    const auto = s.automation || {};
    const onCount = Object.values(auto).filter(Boolean).length;

    $("kGroups").textContent = s.bound_groups ?? 0;
    $("kTpl").textContent = s.template_count ?? 0;
    $("kEngine").textContent = s.engine_running ? "运行中" : "已停止";
    $("kAutoOn").textContent = `${onCount}/${AUTO_TASKS.length}`;
    $("kWelcome").textContent = s.auto_welcome ? "开启" : "关闭";

    $("bGroups").textContent = `群 ${s.bound_groups ?? 0}`;
    $("bTpl").textContent = `模板 ${s.template_count ?? 0}`;
    $("bEngine").textContent = `引擎 ${s.engine_running ? "运行中" : "已停止"}`;

    $("cfgWelcome").checked = !!s.auto_welcome;
    $("cfgSchedule").checked = !!s.schedule_enabled;
  } catch (e) {
    console.error("加载状态失败:", e);
  }
}

async function loadGroups() {
  try {
    const d = await bridge.apiGet("groups");
    state.groups = d.groups || [];
    state.featureLabels = d.feature_labels || {};
    fillGroupSelects();
    renderGroupList();
    renderGroupMgmt();
  } catch (e) {
    console.error("加载群列表失败:", e);
  }
}

function renderGroupList() {
  const box = $("groupList");
  if (!box) return;
  if (!state.groups.length) {
    box.innerHTML = `<div class="empty">还没有绑定任何群。在 QQ 群里发送 <code>/运营 绑定</code> 即可。</div>`;
    return;
  }
  box.innerHTML = state.groups
    .map(
      (g) => `<div class="item">
        <div><b>${escapeHtml(g.name)}</b>
          <span class="badge-inline ${g.enabled ? "on" : "off"}">${g.enabled ? "运行中" : "已停用"}</span>
          <div class="meta">群号 ${escapeHtml(g.group_id)} · 绑定于 ${escapeHtml(g.bound_at || "—")}</div>
        </div>
      </div>`
    )
    .join("");
}

/* ------------------------------------------------------------------ */
/* 群管理：扫描 / 绑定 / 解绑（无需在群里发指令）                        */
/* ------------------------------------------------------------------ */

async function scanGroups(silent = false) {
  const box = $("scanList");
  const res = $("scanResult");
  if (!box) return;
  if (!silent) setResult(res, "扫描中…");
  try {
    const d = await bridge.apiGet("groups/scan");
    const rows = d.groups || [];
    state.scanRows = rows;
    if (!rows.length) {
      box.innerHTML = `<div class="empty">
        未扫描到任何群。<br>
        · 确认已配置 <code>aiocqhttp</code>（NapCat 等）适配器且机器人已登录<br>
        · 或先在目标群里发一条消息（机器人收到后会记录该群），再回来扫描
      </div>`;
      if (!silent) setResult(res, "未扫描到群", true);
      return;
    }
    box.innerHTML = rows
      .map((g) => {
        const src = g.source === "live" ? "实时" : g.source === "seen" ? "历史" : "已绑定";
        const mc = g.member_count ? `${g.member_count} 人` : "";
        return `<label class="scan-item ${g.bound ? "bound" : ""}">
          <input type="checkbox" data-scan="${escapeHtml(g.group_id)}" data-bound="${g.bound ? "1" : "0"}" />
          <div class="scan-main">
            <b>${escapeHtml(g.name)}</b>
            <span class="badge-inline ${g.bound ? "on" : "off"}">${g.bound ? "已绑定" : "未绑定"}</span>
            <div class="meta">群号 ${escapeHtml(g.group_id)}${mc ? " · " + mc : ""} · 来源 ${src}${g.bound ? " · 勾选后可解绑" : ""}</div>
          </div>
        </label>`;
      })
      .join("");
    if (!silent) {
      const unbound = rows.filter((g) => !g.bound).length;
      const bound = rows.length - unbound;
      setResult(
        res,
        `共 ${rows.length} 个群（${bound} 个已绑定 · 勾选后点「解绑选中」，${unbound} 个未绑定 · 勾选后点「绑定选中」）` +
          (d.live_available ? "" : " ｜ 提示：实时列表不可用，显示的是历史记录到的群")
      );
    }
  } catch (e) {
    if (!silent) setResult(res, "扫描失败：" + (e && e.message ? e.message : e), true);
  }
}

async function bindSelected() {
  const box = $("scanList");
  const res = $("scanResult");
  if (!box) return;
  const ids = [...box.querySelectorAll("[data-scan]")]
    .filter((el) => el.checked && el.dataset.bound !== "1")
    .map((el) => el.dataset.scan);
  if (!ids.length) {
    setResult(res, "请先勾选要绑定的群（已绑定的群请用「解绑选中」）", true);
    return;
  }
  let ok = 0;
  for (const gid of ids) {
    try {
      await bridge.apiPost("group/bind", { group_id: gid, action: "bind" });
      ok++;
    } catch (e) {
      console.error("绑定失败", gid, e);
    }
  }
  await loadGroups();
  await scanGroups(true);
  setResult(res, `✅ 已绑定 ${ok} / ${ids.length} 个群`);
}

/* 解绑确认状态（不使用 window.confirm —— AstrBot WebUI 的 iframe 会拦掉原生弹窗，
   导致点击后直接 return、看起来"没反应"。改用内联二次点击确认。） */
let _pendingUnbind = { ids: [], timer: null };

function _resetUnbindBtn() {
  const btn = $("unbindSelected");
  if (btn) {
    btn.classList.remove("confirming");
    btn.textContent = "解绑选中";
  }
  _pendingUnbind = { ids: [], timer: null };
}

async function unbindSelected() {
  const box = $("scanList");
  const res = $("scanResult");
  const btn = $("unbindSelected");
  if (!box) return;

  const ids = [...box.querySelectorAll("[data-scan]")]
    .filter((el) => el.checked && el.dataset.bound === "1")
    .map((el) => el.dataset.scan);

  if (!ids.length) {
    _resetUnbindBtn();
    setResult(res, "请先勾选要解绑的群（仅已绑定的群可解绑）", true);
    return;
  }

  // 第二次点击（且选中项未变）→ 真正执行
  if (_pendingUnbind.timer && _pendingUnbind.ids.join(",") === ids.join(",")) {
    clearTimeout(_pendingUnbind.timer);
    _resetUnbindBtn();
    await doUnbind(ids);
    return;
  }

  // 第一次点击 → 进入待确认状态
  _resetUnbindBtn();
  _pendingUnbind.ids = ids;
  if (btn) {
    btn.classList.add("confirming");
    btn.textContent = `确认解绑 ${ids.length} 个群（再点一次）`;
  }
  setResult(
    res,
    `⚠️ 即将解绑 ${ids.length} 个群，运营数据会保留但不再自动运营。` +
      `请在 8 秒内再点一次「确认解绑」按钮执行。`
  );
  _pendingUnbind.timer = setTimeout(() => {
    _resetUnbindBtn();
    setResult(res, "已取消解绑（超时未再次确认）。");
  }, 8000);
}

async function doUnbind(ids) {
  const res = $("scanResult");
  const failed = [];
  let ok = 0;
  for (const gid of ids) {
    try {
      const r = await bridge.apiPost("group/bind", { group_id: gid, action: "unbind" });
      if (r && r.ok === false) throw new Error(r.message || "解绑失败");
      ok++;
    } catch (e) {
      failed.push(gid);
      console.error("解绑失败", gid, e);
    }
  }
  await loadGroups();
  await scanGroups(true);
  setResult(
    res,
    `✅ 已解绑 ${ok} / ${ids.length} 个群` + (failed.length ? `，失败：${failed.join("、")}` : "")
  );
}

/* ------------------------------------------------------------------ */
/* 群管理：分群开关 + 功能开关 + 欢迎词                                 */
/* ------------------------------------------------------------------ */

function renderGroupMgmt() {
  const box = $("groupMgmt");
  if (!box) return;
  if (!state.groups.length) {
    box.innerHTML = `<div class="empty">还没有绑定任何群。在 QQ 群里发送 <code>/运营 绑定</code> 即可。</div>`;
    return;
  }
  const labels = state.featureLabels || {};
  box.innerHTML = state.groups
    .map((g) => {
      const feats = g.features || {};
      const featRows = Object.keys(labels)
        .map((k) => {
          const on = feats[k] !== false;
          return `<label class="sw feat-sw ${on ? "" : "off"}">
            <input type="checkbox" data-gfeat="${escapeHtml(g.group_id)}|${escapeHtml(k)}" ${on ? "checked" : ""} ${g.enabled ? "" : "disabled"} />
            <span>${escapeHtml(labels[k])}</span>
          </label>`;
        })
        .join("");
      return `<div class="gcard ${g.enabled ? "" : "off"}">
        <div class="gcard-head">
          <div>
            <b>${escapeHtml(g.name)}</b>
            <div class="meta">群号 ${escapeHtml(g.group_id)} · 绑定于 ${escapeHtml(g.bound_at || "—")}</div>
          </div>
          <label class="toggle" title="该群总开关">
            <input type="checkbox" data-genable="${escapeHtml(g.group_id)}" ${g.enabled ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>
        <div class="gcard-body">
          <div class="gcard-label">单项功能</div>
          <div class="feat-grid">${featRows}</div>
        </div>
      </div>`;
    })
    .join("");

  box.querySelectorAll("[data-genable]").forEach((el) => {
    el.addEventListener("change", async () => {
      const gid = el.dataset.genable;
      const want = el.checked;
      const g = state.groups.find((x) => x.group_id === gid);
      const card = el.closest(".gcard");
      el.disabled = true;
      try {
        const r = await bridge.apiPost("group/toggle", { group_id: gid, enabled: want });
        // 以服务端返回值为准，避免"点了回弹"
        const real = r && typeof r.enabled === "boolean" ? r.enabled : want;
        el.checked = real;
        if (g) g.enabled = real;
        card?.classList.toggle("off", !real);
        // 总开关关闭时，该群的单项功能一并置灰
        card?.querySelectorAll("[data-gfeat]").forEach((f) => {
          f.disabled = !real;
        });
        renderGroupList(); // 同步「状态概览」页的徽标
      } catch (e) {
        el.checked = !want;
        toast("切换失败：" + (e && e.message ? e.message : e), true);
      } finally {
        el.disabled = false;
      }
    });
  });

  box.querySelectorAll("[data-gfeat]").forEach((el) => {
    el.addEventListener("change", async () => {
      const [gid, feature] = el.dataset.gfeat.split("|");
      const want = el.checked;
      el.disabled = true;
      try {
        const r = await bridge.apiPost("group/toggle", { group_id: gid, feature, value: want });
        const real = r && r.features && typeof r.features[feature] === "boolean"
          ? r.features[feature]
          : want;
        el.checked = real;
        const g = state.groups.find((x) => x.group_id === gid);
        if (g && g.features) g.features[feature] = real;
        el.closest(".feat-sw")?.classList.toggle("off", !real);
      } catch (e) {
        el.checked = !want;
        el.closest(".feat-sw")?.classList.toggle("off", !el.checked);
        toast("切换失败：" + (e && e.message ? e.message : e), true);
      } finally {
        el.disabled = false;
      }
    });
  });
}

async function loadWelcome() {
  try {
    const d = await bridge.apiGet("welcome");
    state.welcomeText = d.welcome_text || "";
    $("welcomeText").value = state.welcomeText;
    $("welcomePreview").textContent = d.preview || "—";
  } catch (e) {
    console.error("加载欢迎词失败:", e);
  }
}

async function saveWelcome(reset = false) {
  const text = reset ? "" : $("welcomeText").value;
  if (!reset && !text.trim()) {
    setResult($("welcomeResult"), "欢迎词不能为空", true);
    return;
  }
  try {
    const r = await bridge.apiPost("welcome/save", reset ? { reset: true } : { welcome_text: text });
    state.welcomeText = r.welcome_text || "";
    $("welcomeText").value = state.welcomeText;
    $("welcomePreview").textContent = r.preview || "—";
    setResult($("welcomeResult"), reset ? "✅ 已恢复默认欢迎词" : "✅ 欢迎词已保存");
  } catch (e) {
    setResult($("welcomeResult"), "保存失败：" + e.message, true);
  }
}

/* ------------------------------------------------------------------ */
/* 内容推送                                                            */
/* ------------------------------------------------------------------ */

async function loadTemplates() {
  try {
    const d = await bridge.apiGet("templates");
    state.templates = d.templates || [];
    fillTemplateSelects();
    $("tplCount").textContent = state.templates.length;

    $("tplList").innerHTML = state.templates
      .map(
        (t) => `<div class="tpl">
          <div class="head">
            <span class="name">${escapeHtml(t.name)}${t.slot ? ` <span class="meta">${escapeHtml(t.slot)}</span>` : ""}</span>
            <button class="mini-btn" data-copy="${escapeHtml(t.key)}">复制</button>
          </div>
          <div class="body">${escapeHtml(t.content)}</div>
        </div>`
      )
      .join("");

    $("tplList").querySelectorAll("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const tpl = state.templates.find((x) => x.key === btn.dataset.copy);
        if (!tpl) return;
        await copyText(tpl.content);
        const old = btn.textContent;
        btn.textContent = "已复制 ✓";
        setTimeout(() => (btn.textContent = old), 1200);
      });
    });

    updatePreview();
  } catch (e) {
    console.error("加载模板失败:", e);
  }
}

function updatePreview() {
  const key = $("pushTpl")?.value;
  const tpl = state.templates.find((t) => t.key === key);
  const pre = $("pushPreview");
  if (!pre) return;
  if (!tpl) { pre.textContent = "选择模板后显示预览…"; state.currentTpl = ""; return; }
  state.currentTpl = tpl.content;
  pre.textContent = tpl.content;
}

/* ------------------------------------------------------------------ */
/* 积分管理                                                            */
/* ------------------------------------------------------------------ */

async function loadPoints() {
  const gid = $("ptsGroup")?.value || "";
  try {
    const d = await bridge.apiGet("points", { group_id: gid });
    const rows = d.leaderboard || [];
    const box = $("ptsTable");
    if (!rows.length) {
      box.innerHTML = `<div class="empty">暂无积分数据。群成员发送 <code>/签到</code> 即可开始攒分。</div>`;
      return;
    }
    const medals = ["🥇", "🥈", "🥉"];
    box.innerHTML = rows
      .map((r, i) => `<div class="item">
        <div><b>${i < 3 ? medals[i] + " " : (i + 1) + ". "}${escapeHtml(r.name)}</b>
        <div class="meta">QQ ${escapeHtml(r.user_id)} · 邀请 ${r.invites} 人</div></div>
        <div><b style="color:var(--brand);font-size:16px">${r.points}</b> 分</div>
      </div>`)
      .join("");
  } catch (e) {
    console.error("加载积分失败:", e);
  }
}

/* ------------------------------------------------------------------ */
/* 积分规则配置                                                        */
/* ------------------------------------------------------------------ */

async function loadPointsConfig() {
  try {
    const d = await bridge.apiGet("points/config");
    state.pointsCfg = d.config || {};
    state.pointRuleMeta = d.rule_meta || [];
    state.redeemItems = (state.pointsCfg.redeem_items || []).map((x) => ({ ...x }));
    renderPointRules();
    renderRedeemList();
    const limit = $("ptInviteLimit");
    if (limit) limit.value = state.pointsCfg.invite_daily_limit ?? 3;
    const note = $("ptRedeemNote");
    if (note) note.value = state.pointsCfg.redeem_note || "";
    renderPointRuleGrid();
  } catch (e) {
    console.error("加载积分配置失败:", e);
  }
}

function renderPointRules() {
  const box = $("pointRules");
  if (!box) return;
  const rules = state.pointsCfg.rules || {};
  box.innerHTML = state.pointRuleMeta
    .map((m) => `<div class="field">
      <label>${escapeHtml(m.label)}（${escapeHtml(m.desc)}）</label>
      <input type="number" data-rule="${escapeHtml(m.key)}" min="${m.min ?? 0}" max="${m.max ?? 999}" value="${rules[m.key] ?? 0}" />
    </div>`)
    .join("");
}

function renderRedeemList() {
  const box = $("ptRedeemList");
  if (!box) return;
  if (!state.redeemItems.length) {
    box.innerHTML = `<div class="empty">还没有兑换项。在下方添加，群成员发 <code>/兑换</code> 即可看到。</div>`;
    return;
  }
  box.innerHTML = state.redeemItems
    .map((it, i) => `<div class="redeem-item ${it.enabled === false ? "off" : ""}">
      <div class="ri-main">
        <b>${escapeHtml(it.name)}</b>
        <div class="ri-desc">${escapeHtml(it.desc || "—")}</div>
      </div>
      <span class="ri-cost">${it.cost} 分</span>
      <label class="sw"><input type="checkbox" data-rd-en="${i}" ${it.enabled !== false ? "checked" : ""}/><span>启用</span></label>
      <button class="del-btn" data-rd-del="${i}">删除</button>
    </div>`)
    .join("");
  box.querySelectorAll("[data-rd-en]").forEach((el) =>
    el.addEventListener("change", () => { state.redeemItems[+el.dataset.rdEn].enabled = el.checked; }));
  box.querySelectorAll("[data-rd-del]").forEach((el) =>
    el.addEventListener("click", () => { state.redeemItems.splice(+el.dataset.rdDel, 1); renderRedeemList(); }));
}

// 群内命令说明同步显示当前规则数值
function renderPointRuleGrid() {
  const box = $("ptRuleGrid");
  if (!box) return;
  const r = state.pointsCfg.rules || {};
  const limit = state.pointsCfg.invite_daily_limit ?? 0;
  const rows = [
    ["/签到", `每日签到 +${r.sign ?? 0}`],
    ["/积分", "查询自己的积分"],
    ["/积分榜", "查看群内排行"],
    ["/邀请", `记录邀请 +${r.invite ?? 0}${limit > 0 ? `（每天最多 ${limit} 次）` : "（不限次数）"}`],
    ["/兑换", `查看兑换表（共 ${(state.redeemItems || []).filter((x) => x.enabled !== false).length} 项）`],
  ];
  box.innerHTML = rows
    .map(([cmd, desc]) => `<div class="rule"><b>${escapeHtml(cmd)}</b><span>${escapeHtml(desc)}</span></div>`)
    .join("");
}

function addRedeemItem() {
  const name = $("ptRName")?.value?.trim();
  if (!name) { setResult($("ptCfgResult"), "请填写兑换项名称", true); return; }
  const cost = Number($("ptRCost")?.value) || 0;
  const desc = $("ptRDesc")?.value?.trim() || "";
  state.redeemItems.push({ name, cost, desc, enabled: true });
  $("ptRName").value = "";
  $("ptRCost").value = "";
  $("ptRDesc").value = "";
  renderRedeemList();
  renderPointRuleGrid();
}

async function savePointsConfig() {
  const rules = {};
  document.querySelectorAll("[data-rule]").forEach((el) => {
    rules[el.dataset.rule] = Number(el.value) || 0;
  });
  const payload = {
    rules,
    invite_daily_limit: Number($("ptInviteLimit")?.value) || 0,
    redeem_items: state.redeemItems,
    redeem_note: $("ptRedeemNote")?.value || "",
  };
  try {
    const r = await bridge.apiPost("points/config/save", payload);
    state.pointsCfg = r.config || state.pointsCfg;
    state.redeemItems = (state.pointsCfg.redeem_items || []).map((x) => ({ ...x }));
    renderPointRules();
    renderRedeemList();
    renderPointRuleGrid();
    setResult($("ptCfgResult"), "✅ 积分配置已保存，群内命令即时生效");
  } catch (e) {
    setResult($("ptCfgResult"), "保存失败：" + (e && e.message ? e.message : e), true);
  }
}

/* ------------------------------------------------------------------ */
/* 答题活动（v1.2.0：答对真实自动加分 + 防刷）                          */
/* ------------------------------------------------------------------ */

async function loadQuiz() {
  try {
    const d = await bridge.apiGet("quiz/config");
    const c = d.config || {};
    state.quizCfg = c;
    if ($("qzEnabled")) $("qzEnabled").checked = c.quiz_enabled !== false;
    if ($("qzAiJudge")) $("qzAiJudge").checked = !!c.quiz_ai_judge;
    if ($("qzReward")) $("qzReward").value = c.quiz_reward ?? 10;
    if ($("qzLimit")) $("qzLimit").value = c.quiz_limit ?? 3;
    if ($("qzTimeout")) $("qzTimeout").value = c.quiz_timeout ?? 600;
    const bank = $("qzBankSize");
    if (bank) bank.textContent = d.bank_size || 0;
    renderQuizRunning(d.running || {});
  } catch (e) {
    console.error("加载答题配置失败:", e);
  }
}

function renderQuizRunning(running) {
  const box = $("qzRunning");
  if (!box) return;
  const rows = Object.entries(running);
  if (!rows.length) {
    box.innerHTML = '<div class="empty">当前没有进行中的题目。点「立即出题」推一道到群里，或等每日午后互动自动出题。</div>';
    return;
  }
  box.innerHTML = rows
    .map(([gid, r]) => `<div class="item">
      <div><b>🧠 ${escapeHtml(r.q || "")}</b>
      <div class="meta">群 ${escapeHtml(gid)} · 答对 +${r.reward ?? 0} 分 · 已获奖 ${r.winners || 0}${r.limit > 0 ? ` / ${r.limit}` : "（不限人数）"}</div></div>
    </div>`)
    .join("");
}

async function saveQuizConfig() {
  const payload = {
    quiz_enabled: !!$("qzEnabled")?.checked,
    quiz_ai_judge: !!$("qzAiJudge")?.checked,
    quiz_reward: Number($("qzReward")?.value) || 0,
    quiz_limit: Number($("qzLimit")?.value) || 0,
    quiz_timeout: Number($("qzTimeout")?.value) || 600,
  };
  try {
    const r = await bridge.apiPost("quiz/config/save", payload);
    state.quizCfg = r.config || state.quizCfg;
    setResult($("qzCfgResult"), "✅ 答题配置已保存，群内即时生效");
    await loadQuiz();
  } catch (e) {
    setResult($("qzCfgResult"), "保存失败：" + (e && e.message ? e.message : e), true);
  }
}

async function startQuiz() {
  const gid = $("qzGroup")?.value || "";
  try {
    const r = await bridge.apiPost("quiz/start", { group_id: gid });
    if (r.started) {
      setResult($("qzStartResult"), "✅ 已推送到群，群友直接回答案即可");
      toast("出题成功，已推送到群");
    } else if (r.reason === "running") {
      setResult($("qzStartResult"), "⏳ 该群已有进行中的题目，等它结束再出下一题");
    } else {
      setResult($("qzStartResult"), "⚠️ 未能出题", true);
    }
    await loadQuiz();
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    setResult($("qzStartResult"), "出题失败：" + msg, true);
  }
}

/* ------------------------------------------------------------------ */
/* 邀请记录（自动捕获 / 认领 / 补录 / 撤销 / 导出）                     */
/* ------------------------------------------------------------------ */

const DEFAULT_INVITE_TPL =
  "🎉 感谢 {inviter} 拉来了新同学 {invitee}，邀请积分 +{points}！";

const INVITE_SRC_LABEL = {
  auto: "自动记录",
  manual: "手动补录",
  unclaimed: "待认领",
  limit: "超限未计分",
};

function renderInviteCfg() {
  const c = state.inviteCfg || {};
  if ($("ivAuto")) $("ivAuto").checked = c.auto_invite !== false;
  if ($("ivBroadcast")) $("ivBroadcast").checked = c.invite_broadcast !== false;
  if ($("ivCountApprove")) $("ivCountApprove").checked = !!c.count_on_approve;
  if ($("ivDefaultInviter")) $("ivDefaultInviter").value = c.default_inviter || "";
  if ($("ivTpl")) $("ivTpl").value = c.invite_broadcast_text || DEFAULT_INVITE_TPL;
}

async function loadInviteLog(silent) {
  const gid = $("ivGroup")?.value || "";
  try {
    const d = await bridge.apiGet("invite/log", { group_id: gid, limit: 100 });
    state.inviteCfg = d.config || {};
    state.inviteRows = d.entries || [];

    const sel = $("ivGroup");
    if (sel && Array.isArray(d.groups)) {
      const cur = d.group_id || "";
      sel.innerHTML = d.groups.length
        ? d.groups
            .map(
              (g) =>
                `<option value="${escapeHtml(g.group_id)}">${escapeHtml(g.name)}</option>`
            )
            .join("")
        : `<option value="">（暂无绑定群）</option>`;
      sel.value = cur;
    }
    renderInviteCfg();
    renderInviteTable(state.inviteRows);

    const sum = $("ivSummary");
    if (sum) {
      const top = (d.summary || [])
        .slice(0, 3)
        .map((s) => `${s.name}(${s.count})`)
        .join(" · ");
      sum.textContent =
        `共 ${d.total || 0} 条` +
        (d.unclaimed ? ` · ${d.unclaimed} 条待认领` : "") +
        (top ? ` · 邀请榜：${top}` : "");
    }
  } catch (e) {
    if (!silent) {
      setResult($("ivResult"), "加载邀请记录失败：" + (e && e.message ? e.message : e), true);
    }
  }
}

function renderInviteTable(rows) {
  const box = $("ivTable");
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = `<div class="empty">暂无邀请记录。开启「自动捕获入群邀请」后，新人入群会自动识别邀请人并计分。</div>`;
    return;
  }
  const head = `<div class="inv-row head">
    <span>时间</span><span>邀请人</span><span>新人</span><span>来源</span><span>积分</span><span>操作</span>
  </div>`;
  const body = rows
    .map((r) => {
      const ts = escapeHtml(String(r.ts));
      const who = r.inviter
        ? `${escapeHtml(r.inviter_name || r.inviter)}<div class="meta">QQ ${escapeHtml(r.inviter)}</div>`
        : `<span style="color:var(--text3)">—</span>`;
      const newbie = `${escapeHtml(r.invitee_name || r.invitee || "?")}<div class="meta">QQ ${escapeHtml(r.invitee || "")}</div>`;
      const src = INVITE_SRC_LABEL[r.source] || r.source || "—";
      const pts = r.counted
        ? `<span style="color:var(--brand)"><b>+${r.points || 0}</b></span>`
        : `<span style="color:var(--text3)">未计分</span>`;
      const ops = r.inviter
        ? `<button class="del-btn" data-inv-undo="${ts}">撤销</button>`
        : `<button class="btn sm" data-inv-claim="${ts}">认领</button>`;
      return `<div class="inv-row">
        <span class="meta" style="margin:0">${escapeHtml(r.time || r.date || "")}</span>
        <span>${who}</span>
        <span>${newbie}</span>
        <span>${escapeHtml(src)}</span>
        <span>${pts}</span>
        <span class="inv-ops">${ops}</span>
      </div>`;
    })
    .join("");
  box.innerHTML = head + body;

  box.querySelectorAll("[data-inv-undo]").forEach((el) =>
    el.addEventListener("click", () => {
      const ts = el.dataset.invUndo;
      inlineConfirm(el, "再点一次即撤销该邀请记录（已计分的会扣回）", async () => {
        try {
          await bridge.apiPost("invite/undo", { group_id: $("ivGroup").value, ts });
          await loadInviteLog(true);
          toast("✅ 已撤销该邀请记录");
        } catch (err) {
          toast("撤销失败：" + (err && err.message ? err.message : err), true);
        }
      });
    })
  );

  box.querySelectorAll("[data-inv-claim]").forEach((el) =>
    el.addEventListener("click", () => {
      const ts = el.dataset.invClaim;
      const cell = el.parentElement;
      cell.innerHTML = `<input type="text" class="inv-claim-input" placeholder="邀请人QQ" />
        <button class="btn sm primary" data-do-claim="${escapeHtml(ts)}">确定</button>`;
      const input = cell.querySelector("input");
      if (input) input.focus();
      cell.querySelector("[data-do-claim]").addEventListener("click", async () => {
        const inviter = (input && input.value.trim()) || "";
        if (!inviter) {
          toast("请输入邀请人 QQ", true);
          return;
        }
        try {
          await bridge.apiPost("invite/claim", {
            group_id: $("ivGroup").value,
            ts,
            inviter,
          });
          await loadInviteLog(true);
          toast("✅ 已认领并计分");
        } catch (err) {
          toast("认领失败：" + (err && err.message ? err.message : err), true);
        }
      });
    })
  );
}

async function saveInviteConfig() {
  const payload = {
    auto_invite: !!$("ivAuto")?.checked,
    invite_broadcast: !!$("ivBroadcast")?.checked,
    count_on_approve: !!$("ivCountApprove")?.checked,
    default_inviter: $("ivDefaultInviter")?.value || "",
    invite_broadcast_text: $("ivTpl")?.value || "",
  };
  try {
    const r = await bridge.apiPost("points/config/save", payload);
    state.inviteCfg = Object.assign({}, state.inviteCfg, r.config || {});
    renderInviteCfg();
    setResult($("ivCfgResult"), "✅ 邀请设置已保存");
  } catch (e) {
    setResult($("ivCfgResult"), "保存失败：" + (e && e.message ? e.message : e), true);
  }
}

async function addInviteManual() {
  const gid = $("ivGroup")?.value || "";
  const inviter = ($("ivInviter")?.value || "").trim();
  const invitee = ($("ivInvitee")?.value || "").trim();
  if (!gid) {
    setResult($("ivResult"), "请先选择群", true);
    return;
  }
  if (!inviter || !invitee) {
    setResult($("ivResult"), "请填写邀请人和新人的 QQ 号", true);
    return;
  }
  try {
    const r = await bridge.apiPost("invite/manual", { group_id: gid, inviter, invitee });
    if ($("ivInviter")) $("ivInviter").value = "";
    if ($("ivInvitee")) $("ivInvitee").value = "";
    await loadInviteLog(true);
    setResult(
      $("ivResult"),
      r.counted ? `✅ 已补录，邀请人 +${r.points} 分` : "✅ 已补录（超出每日上限，未计分）"
    );
  } catch (e) {
    setResult($("ivResult"), "补录失败：" + (e && e.message ? e.message : e), true);
  }
}

function exportInviteCsv() {
  const rows = state.inviteRows || [];
  if (!rows.length) {
    toast("没有可导出的邀请记录", true);
    return;
  }
  const head = ["时间", "邀请人QQ", "邀请人昵称", "新人QQ", "新人昵称", "来源", "积分", "是否计分"];
  const lines = [head.join(",")].concat(
    rows.map((r) =>
      [
        r.time || r.date || "",
        r.inviter || "",
        r.inviter_name || "",
        r.invitee || "",
        r.invitee_name || "",
        INVITE_SRC_LABEL[r.source] || r.source || "",
        r.points || 0,
        r.counted ? "是" : "否",
      ]
        .map((x) => `"${String(x).replace(/"/g, '""')}"`)
        .join(",")
    )
  );
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `邀请记录_${$("ivGroup")?.value || "群"}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  toast("✅ 已导出 CSV");
}

/* ------------------------------------------------------------------ */
/* 数据看板                                                            */
/* ------------------------------------------------------------------ */

async function loadStats() {
  const gid = $("stGroup")?.value || "";
  try {
    const d = await bridge.apiGet("stats", { group_id: gid });
    const rows = d.stats || [];
    const box = $("statsTable");
    if (!rows.length) {
      box.innerHTML = `<div class="empty">暂无历史数据，先在上方录入今天的运营数据。</div>`;
      return;
    }
    const head = `<div class="stats-row head">
      <span>日期</span><span>总人数</span><span>新增</span><span>退群</span>
      <span>发言</span><span>成团</span><span>日活率</span></div>`;
    const body = rows
      .slice()
      .reverse()
      .map((r) => {
        const rate = r.total ? Math.round((r.active / r.total) * 1000) / 10 : 0;
        return `<div class="stats-row">
          <span><b>${escapeHtml(r.date)}</b></span>
          <span>${r.total}</span>
          <span style="color:var(--green)">+${r.new}</span>
          <span style="color:var(--red)">-${r.leave}</span>
          <span>${r.active}</span>
          <span>${r.team}</span>
          <span><b>${rate}%</b></span>
        </div>`;
      })
      .join("");
    box.innerHTML = head + body;
  } catch (e) {
    console.error("加载数据失败:", e);
  }
}

/* ------------------------------------------------------------------ */
/* 推送计划                                                            */
/* ------------------------------------------------------------------ */

async function loadSchedule() {
  try {
    const d = await bridge.apiGet("schedule");
    state.schedule = d.schedule || [];
    renderSchedule();
    $("cfgSchedule").checked = !!d.enabled;
  } catch (e) {
    console.error("加载计划失败:", e);
  }
}

function renderSchedule() {
  const box = $("schedList");
  if (!state.schedule.length) {
    box.innerHTML = `<div class="empty">暂无推送计划，可在下方添加。</div>`;
    return;
  }
  box.innerHTML = state.schedule
    .map((s, i) => {
      const tpl = state.templates.find((t) => t.key === s.template);
      return `<div class="item">
        <div><b>${escapeHtml(s.time)}</b> · ${escapeHtml(tpl ? tpl.name : s.template)}
        <div class="meta">模板 ${escapeHtml(s.template)}</div></div>
        <div style="display:flex;gap:8px;align-items:center">
          <label class="sw"><input type="checkbox" data-sched-toggle="${i}" ${s.enabled ? "checked" : ""}/><span>启用</span></label>
          <button class="mini-btn" style="background:var(--red)" data-sched-del="${i}">删除</button>
        </div>
      </div>`;
    })
    .join("");

  box.querySelectorAll("[data-sched-toggle]").forEach((el) => {
    el.addEventListener("change", () => {
      const idx = Number(el.dataset.schedToggle);
      if (state.schedule[idx]) state.schedule[idx].enabled = el.checked;
    });
  });
  box.querySelectorAll("[data-sched-del]").forEach((el) => {
    el.addEventListener("click", () => {
      state.schedule.splice(Number(el.dataset.schedDel), 1);
      renderSchedule();
    });
  });
}

/* ------------------------------------------------------------------ */
/* 自动化引擎                                                          */
/* ------------------------------------------------------------------ */

async function loadAutomation() {
  try {
    const d = await bridge.apiGet("automation");
    state.automation = d.automation || {};
    state.replyRules = (d.reply_rules || []).map((r) => ({
      keywords: (r.keywords || []).join(","),
      reply: r.reply || "",
      enabled: r.enabled !== false,
    }));
    renderAutoGrid();
    renderAutoParams();
    renderReplyRules();
  } catch (e) {
    console.error("加载自动化配置失败:", e);
  }
}

function renderAutoGrid() {
  const box = $("autoGrid");
  if (!box) return;
  box.innerHTML = AUTO_TASKS.map((t) => {
    const on = state.automation[t.key] !== false;
    return `<div class="auto-item ${on ? "" : "off"}">
      <div class="info">
        <div class="t">${t.icon} ${escapeHtml(t.name)}
          <span class="st">${on ? "运行中" : "已暂停"}</span>
        </div>
        <div class="d">${escapeHtml(t.desc)}</div>
      </div>
      <label class="toggle">
        <input type="checkbox" data-auto="${t.key}" ${on ? "checked" : ""} />
        <span class="slider"></span>
      </label>
    </div>`;
  }).join("");

  box.querySelectorAll("[data-auto]").forEach((el) => {
    el.addEventListener("change", () => {
      const key = el.dataset.auto;
      state.automation[key] = el.checked;
      // 原地更新状态标签与卡片样式，避免整表重渲染（会丢滚动位置、视觉闪烁）
      const item = el.closest(".auto-item");
      item?.classList.toggle("off", !el.checked);
      const st = item?.querySelector(".st");
      if (st) st.textContent = el.checked ? "运行中" : "已暂停";
      toast(el.checked ? "已开启（记得点「保存配置」生效）" : "已暂停（记得点「保存配置」生效）");
    });
  });
}

function renderAutoParams() {
  const a = state.automation;
  const set = (id, v) => { const el = $(id); if (el && v !== undefined && v !== null) el.value = v; };
  set("aCollectInterval", a.collect_interval);
  set("aColdThreshold", a.cold_threshold);
  set("aColdCooldown", a.cold_cooldown);
  set("aWakeDays", a.wake_days);
  set("aWakeCooldown", a.wake_cooldown);
  set("aWakeMax", a.wake_max_per_round);
  set("aHourStart", a.active_hour_start);
  set("aHourEnd", a.active_hour_end);
  set("aReportTime", a.report_time);
  set("aReportAdmin", a.report_admin_qq);
  const rtg = $("aReportToGroup"); if (rtg) rtg.checked = !!a.report_to_group;
  const wtn = $("aWeeklyTopN"); if (wtn) wtn.value = (state.ai && state.ai.weekly_top_n) || 5;
  set("aWeeklyTime", a.weekly_board_time);
  set("aWeeklyWeekday", a.weekly_board_weekday);
}

function renderReplyRules() {
  const box = $("replyList");
  if (!box) return;
  if (!state.replyRules.length) {
    box.innerHTML = `<div class="empty">暂无应答规则，点击下方按钮添加。</div>`;
    return;
  }
  box.innerHTML = state.replyRules.map((r, i) => `
    <div class="rule-item">
      <div class="top">
        <input type="text" data-rule-kw="${i}" value="${escapeHtml(r.keywords)}" placeholder="关键词，逗号分隔，如：怎么进车队,开黑怎么" />
        <div style="display:flex;gap:8px;align-items:center;flex-shrink:0">
          <label class="sw"><input type="checkbox" data-rule-en="${i}" ${r.enabled ? "checked" : ""}/><span>启用</span></label>
          <button class="del-btn" data-rule-del="${i}">删除</button>
        </div>
      </div>
      <textarea data-rule-reply="${i}" placeholder="命中后自动回复的内容">${escapeHtml(r.reply)}</textarea>
    </div>`).join("");

  box.querySelectorAll("[data-rule-kw]").forEach((el) =>
    el.addEventListener("input", () => { state.replyRules[+el.dataset.ruleKw].keywords = el.value; }));
  box.querySelectorAll("[data-rule-reply]").forEach((el) =>
    el.addEventListener("input", () => { state.replyRules[+el.dataset.ruleReply].reply = el.value; }));
  box.querySelectorAll("[data-rule-en]").forEach((el) =>
    el.addEventListener("change", () => { state.replyRules[+el.dataset.ruleEn].enabled = el.checked; }));
  box.querySelectorAll("[data-rule-del]").forEach((el) =>
    el.addEventListener("click", () => {
      state.replyRules.splice(+el.dataset.ruleDel, 1);
      renderReplyRules();
    }));
}

async function saveAutomation() {
  const payload = {
    ...state.automation,
    collect_interval: num("aCollectInterval"),
    cold_threshold: num("aColdThreshold"),
    cold_cooldown: num("aColdCooldown"),
    wake_days: num("aWakeDays"),
    wake_cooldown: num("aWakeCooldown"),
    wake_max_per_round: num("aWakeMax"),
    active_hour_start: num("aHourStart"),
    active_hour_end: num("aHourEnd"),
    report_time: $("aReportTime")?.value,
    report_admin_qq: $("aReportAdmin")?.value,
    report_to_group: !!($("aReportToGroup")?.checked),
    weekly_board_time: $("aWeeklyTime")?.value,
    weekly_board_weekday: num("aWeeklyWeekday"),
  };
  Object.keys(payload).forEach((k) => payload[k] === undefined && delete payload[k]);
  try {
    await bridge.apiPost("automation/save", payload);
    // 周榜人数属于 AI 配置区，一并保存
    const wtn = num("aWeeklyTopN");
    if (wtn) await bridge.apiPost("ai/save", { weekly_top_n: wtn });
    setResult($("autoResult"), "✅ 自动化参数已保存");
    await loadStatus();
  } catch (e) {
    setResult($("autoResult"), "保存失败：" + e.message, true);
  }
}

// v2.6 新增设置的独立保存（日报接收人 / 同时发群 / 周榜展示人数）
async function saveNewSettings() {
  const payload = {
    report_admin_qq: $("aReportAdmin")?.value ?? "",
    report_to_group: !!($("aReportToGroup")?.checked),
  };
  const wtn = num("aWeeklyTopN");
  try {
    await bridge.apiPost("automation/save", payload);
    if (wtn) await bridge.apiPost("ai/save", { weekly_top_n: wtn });
    setResult($("newResult"), "✅ 新增设置已保存");
    await loadAutomation();
    await loadAI();
  } catch (e) {
    setResult($("newResult"), "保存失败：" + e.message, true);
  }
}

async function saveReplyRules() {
  const rules = state.replyRules.map((r) => ({
    keywords: r.keywords.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean),
    reply: r.reply,
    enabled: r.enabled,
  })).filter((r) => r.keywords.length);
  try {
    await bridge.apiPost("automation/save", { reply_rules: rules });
    setResult($("replyResult"), `✅ 已保存 ${rules.length} 条应答规则`);
    await loadAutomation();
  } catch (e) {
    setResult($("replyResult"), "保存失败：" + e.message, true);
  }
}

async function loadActivity() {
  const gid = $("actGroup")?.value || "";
  try {
    const d = await bridge.apiGet("activity", { group_id: gid });
    const s = d.summary || {};
    const members = d.members || [];

    const rate = s.total_members ? Math.round((s.today_active / s.total_members) * 1000) / 10 : 0;
    $("actSummary").innerHTML = `
      <div class="kpi"><div class="v">${s.total_members ?? 0}</div><div class="k">群总人数</div></div>
      <div class="kpi"><div class="v">${s.tracked_members ?? 0}</div><div class="k">已追踪成员</div></div>
      <div class="kpi"><div class="v">${s.today_active ?? 0}</div><div class="k">今日活跃</div></div>
      <div class="kpi"><div class="v">${rate}%</div><div class="k">日活率</div></div>
      <div class="kpi"><div class="v">${s.pending_followup ?? 0}</div><div class="k">待跟进新人</div></div>`;

    const box = $("actTable");
    if (!members.length) {
      box.innerHTML = `<div class="empty">暂无活跃度数据。引擎会在绑定后自动采集，也可点击上方「刷新」或去「手动触发」执行一次采集。</div>`;
      return;
    }
    const head = `<div class="act-row head">
      <span>成员</span><span>发言数</span>
      <span class="hide-sm">积分</span><span>空闲天数</span><span class="hide-sm">QQ</span></div>`;
    const rows = members.slice(0, 50).map((m) => {
      const idle = m.idle_days;
      const idleCls = idle !== null && idle >= 7 ? "idle-warn" : "";
      return `<div class="act-row">
        <span class="nm">${escapeHtml(m.name)}</span>
        <span>${m.msg_count}</span>
        <span class="hide-sm">${m.points}</span>
        <span class="${idleCls}">${idle === null ? "—" : idle + " 天"}</span>
        <span class="hide-sm">${escapeHtml(m.user_id)}</span>
      </div>`;
    }).join("");
    box.innerHTML = head + rows;
  } catch (e) {
    console.error("加载活跃度失败:", e);
  }
}

/* ------------------------------------------------------------------ */
/* AI 话术                                                             */
/* ------------------------------------------------------------------ */

async function loadAI() {
  try {
    const d = await bridge.apiGet("ai");
    state.ai = d.ai || {};
    state.aiScenes = d.scenes || [];
    state.aiOverrides = d.overrides || {};
    state.aiProviderAvailable = !!d.provider_available;

    $("aiEnabled").checked = !!state.ai.ai_enabled;
    $("aiForGenerate").checked = state.ai.ai_for_generate !== false;
    $("aiForRescue").checked = state.ai.ai_for_rescue !== false;
    $("aiForReply").checked = state.ai.ai_for_reply !== false;
    $("aiForWelcome").checked = !!state.ai.ai_for_welcome;
    $("aiForSchedule").checked = state.ai.ai_for_schedule !== false;
    $("aiTemp").value = state.ai.ai_temperature ?? 0.9;
    $("aiTimeout").value = state.ai.ai_timeout ?? 20;
    $("aiPersona").value = state.ai.ai_persona || d.default_persona || "";
    $("aiGuard").value = state.ai.ai_guard || d.default_guard || "";

    // 模型下拉（先拿到列表，再据此刷新"当前模型"蓝色标签）
    let provs = [];
    try {
      const pd = await bridge.apiGet("ai/providers");
      provs = pd.providers || [];
    } catch { /* 忽略 */ }
    state.aiProviders = provs;
    const sel = $("aiProvider");
    sel.innerHTML =
      `<option value="">（使用 AstrBot 当前默认模型）</option>` +
      provs.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
    sel.value = state.ai.ai_provider_id || "";
    renderProviderBadge(d, provs);

    // 场景下拉
    $("aiScene").innerHTML = state.aiScenes
      .map((s) => `<option value="${escapeHtml(s.key)}">${escapeHtml(s.label)}</option>`)
      .join("");

    renderAIOverrides();
  } catch (e) {
    console.error("加载 AI 配置失败:", e);
  }
}

// 刷新"当前模型"标签：优先显示用户自选的模型名，未自选才回退到默认模型
function renderProviderBadge(d, provs) {
  const badge = $("aiProviderBadge");
  if (!badge) return;
  const chosenId = $("aiProvider")?.value ?? "";
  const list = provs || state.aiProviders || [];
  const chosen = list.find((p) => String(p.id) === String(chosenId));
  if (chosenId && chosen) {
    badge.textContent = `模型：${chosen.name}`;
    badge.className = "badge-inline on";
  } else if (chosenId && !chosen) {
    badge.textContent = `模型：${chosenId}`;
    badge.className = "badge-inline on";
  } else if (d && d.provider_available) {
    badge.textContent = `模型：${d.provider_name || "已就绪"}`;
    badge.className = "badge-inline on";
  } else {
    badge.textContent = "未检测到可用模型";
    badge.className = "badge-inline off";
  }
}

function renderAIOverrides() {
  const box = $("aiOverrides");
  if (!box) return;
  const keys = Object.keys(state.aiOverrides || {});
  if (!keys.length) {
    box.innerHTML = `<div class="empty">暂无。生成满意的话术后点「采纳为正式内容」，它会替换内置模板。</div>`;
    return;
  }
  box.innerHTML = keys
    .map((k) => {
      const tpl = state.templates.find((t) => t.key === k);
      const name = tpl ? tpl.name : k;
      return `<div class="item">
        <div><b>${escapeHtml(name)}</b>
          <div class="meta">${escapeHtml(k)}</div></div>
        <button class="mini-btn" data-restore="${escapeHtml(k)}">还原内置</button>
      </div>`;
    })
    .join("");
  box.querySelectorAll("[data-restore]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await bridge.apiPost("ai/restore", { template: btn.dataset.restore });
        toast("已还原为内置模板");
        await loadAI();
        await loadTemplates();
      } catch (e) {
        toast("还原失败：" + (e && e.message ? e.message : e), true);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function saveAI() {
  const payload = {
    ai_enabled: $("aiEnabled").checked,
    ai_provider_id: $("aiProvider").value,
    ai_for_generate: $("aiForGenerate").checked,
    ai_for_rescue: $("aiForRescue").checked,
    ai_for_reply: $("aiForReply").checked,
    ai_for_welcome: $("aiForWelcome").checked,
    ai_for_schedule: $("aiForSchedule").checked,
    weekly_top_n: num("aWeeklyTopN"),
    ai_temperature: parseFloat($("aiTemp").value) || 0.9,
    ai_timeout: parseInt($("aiTimeout").value, 10) || 20,
    ai_persona: $("aiPersona").value,
    ai_guard: $("aiGuard").value,
  };
  try {
    const r = await bridge.apiPost("ai/save", payload);
    state.ai = r.ai || state.ai;
    renderProviderBadge(null, state.aiProviders);
    setResult($("aiResult"), "✅ AI 配置已保存");
  } catch (e) {
    setResult($("aiResult"), "保存失败：" + (e && e.message ? e.message : e), true);
  }
}

async function aiGenerate() {
  const key = $("aiScene").value;
  if (!key) return;
  const btn = $("aiGen");
  btn.disabled = true;
  setResult($("aiGenResult"), "🤖 正在生成…");
  try {
    const r = await bridge.apiPost("ai/generate", {
      template: key,
      hint: $("aiHint").value,
    });
    $("aiOutput").value = r.content || "";
    setResult($("aiGenResult"), "✅ 生成完成，可直接编辑后采纳");
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    setResult($("aiGenResult"), "生成失败：" + msg, true);
  } finally {
    btn.disabled = false;
  }
}

async function aiPolish() {
  const key = $("aiScene").value;
  const current = $("aiOutput").value.trim();
  if (!current) {
    setResult($("aiGenResult"), "请先「AI 生成」或粘贴要润色的内容", true);
    return;
  }
  const btn = $("aiPolish");
  btn.disabled = true;
  setResult($("aiGenResult"), "✍️ 正在润色…");
  try {
    const r = await bridge.apiPost("ai/polish", {
      template: key,
      content: current,
      instruction: $("aiHint").value,
    });
    $("aiOutput").value = r.content || "";
    setResult($("aiGenResult"), "✅ 润色完成");
  } catch (e) {
    setResult($("aiGenResult"), "润色失败：" + (e && e.message ? e.message : e), true);
  } finally {
    btn.disabled = false;
  }
}

async function aiApply() {
  const key = $("aiScene").value;
  const content = $("aiOutput").value.trim();
  if (!content) {
    setResult($("aiGenResult"), "内容为空，无法采纳", true);
    return;
  }
  try {
    await bridge.apiPost("ai/apply", { template: key, content });
    setResult($("aiGenResult"), "✅ 已采纳为正式内容，后续推送将使用它");
    await loadAI();
    await loadTemplates();
  } catch (e) {
    setResult($("aiGenResult"), "采纳失败：" + (e && e.message ? e.message : e), true);
  }
}

/* ------------------------------------------------------------------ */
/* 事件绑定                                                            */
/* ------------------------------------------------------------------ */

function bindEvents() {
  // ---- 群扫描 / 绑定 ----
  // 注意：必须用箭头函数包一层，否则点击事件对象会被当成 silent 参数传入
  $("scanGroups")?.addEventListener("click", () => scanGroups());
  $("bindSelected")?.addEventListener("click", () => bindSelected());
  $("unbindSelected")?.addEventListener("click", () => unbindSelected());

  // ---- 答题活动 ----
  $("saveQuizCfg")?.addEventListener("click", saveQuizConfig);
  $("doQuizStart")?.addEventListener("click", startQuiz);
  $("loadQuizStatus")?.addEventListener("click", loadQuiz);

  // ---- AI 话术 ----
  $("saveAi")?.addEventListener("click", saveAI);
  $("aiProvider")?.addEventListener("change", () => renderProviderBadge(null, state.aiProviders));
  $("aiGen")?.addEventListener("click", aiGenerate);
  $("aiPolish")?.addEventListener("click", aiPolish);
  $("aiApply")?.addEventListener("click", aiApply);
  $("aiCopy")?.addEventListener("click", async () => {
    const ok = await copyText($("aiOutput").value);
    toast(ok ? "已复制到剪贴板" : "复制失败，请手动选择复制", !ok);
  });
  $("aiRestore")?.addEventListener("click", async () => {
    const key = $("aiScene").value;
    if (!key) return;
    try {
      const r = await bridge.apiPost("ai/restore", { template: key });
      $("aiOutput").value = r.content || "";
      toast("已还原为内置模板");
      await loadAI();
      await loadTemplates();
    } catch (e) {
      toast("还原失败：" + (e && e.message ? e.message : e), true);
    }
  });
  // ---- 自动化引擎 ----
  $("saveAuto")?.addEventListener("click", saveAutomation);
  $("saveNew")?.addEventListener("click", saveNewSettings);
  $("saveReply")?.addEventListener("click", saveReplyRules);

  // ---- 群管理：欢迎词 ----
  $("saveWelcome")?.addEventListener("click", () => saveWelcome(false));
  $("resetWelcome")?.addEventListener("click", (e) => {
    inlineConfirm(e.currentTarget, "再点一次即恢复默认欢迎词（当前自定义内容会被覆盖）", () =>
      saveWelcome(true)
    );
  });
  $("previewWelcome")?.addEventListener("click", async () => {
    try {
      const r = await bridge.apiPost("welcome/save", { welcome_text: $("welcomeText").value });
      $("welcomePreview").textContent = r.preview || "—";
      setResult($("welcomeResult"), "✅ 已保存并刷新预览");
    } catch (e) {
      setResult($("welcomeResult"), "预览失败：" + e.message, true);
    }
  });
  $("addReply")?.addEventListener("click", () => {
    state.replyRules.push({ keywords: "", reply: "", enabled: true });
    renderReplyRules();
  });
  $("loadAct")?.addEventListener("click", loadActivity);
  $("actGroup")?.addEventListener("change", loadActivity);

  document.querySelectorAll("[data-job]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const job = btn.dataset.job;
      btn.disabled = true;
      setResult($("triggerResult"), `⏳ 正在执行「${job}」…`);
      try {
        const r = await bridge.apiPost("automation/trigger", { job });
        setResult($("triggerResult"), `✅ 已执行：${r.triggered}`);
        if (job === "collect") { await loadActivity(); await loadStats(); }
      } catch (e) {
        setResult($("triggerResult"), "执行失败：" + e.message, true);
      } finally {
        btn.disabled = false;
      }
    });
  });

  // 保存开关
  $("saveCfg")?.addEventListener("click", async () => {
    try {
      await bridge.apiPost("config/save", {
        auto_welcome: $("cfgWelcome").checked,
        schedule_enabled: $("cfgSchedule").checked,
      });
      setResult($("pushResult"), "✅ 开关已保存");
      await loadStatus();
    } catch (e) {
      setResult($("pushResult"), "保存失败：" + e.message, true);
    }
  });

  // 模板切换预览
  $("pushTpl")?.addEventListener("change", updatePreview);

  // 复制预览
  $("copyPreview")?.addEventListener("click", async () => {
    if (!state.currentTpl) return;
    await copyText(state.currentTpl);
    setResult($("pushResult"), "✅ 已复制到剪贴板");
  });

  // 立即推送
  $("doPush")?.addEventListener("click", async () => {
    const tpl = $("pushTpl").value;
    const gid = $("pushGroup").value;
    if (!tpl) return;
    if (!state.groups.length) {
      setResult($("pushResult"), "请先绑定群：在 QQ 群发送 /运营 绑定", true);
      return;
    }
    try {
      const r = await bridge.apiPost("send", { template: tpl, group_id: gid });
      setResult($("pushResult"), `✅ 推送完成：成功 ${r.sent} / 共 ${r.total} 个群` + (r.failed ? `，失败 ${r.failed}` : ""));
    } catch (e) {
      setResult($("pushResult"), "推送失败：" + e.message, true);
    }
  });

  // 积分
  $("loadPts")?.addEventListener("click", loadPoints);
  $("ptsGroup")?.addEventListener("change", loadPoints);
  $("addRedeem")?.addEventListener("click", addRedeemItem);
  $("savePointsCfg")?.addEventListener("click", savePointsConfig);

  // 邀请记录
  $("loadInvite")?.addEventListener("click", () => loadInviteLog());
  $("ivGroup")?.addEventListener("change", () => loadInviteLog());
  $("saveInviteCfg")?.addEventListener("click", saveInviteConfig);
  $("addInvite")?.addEventListener("click", addInviteManual);
  $("exportInvite")?.addEventListener("click", exportInviteCsv);
  $("resetPts")?.addEventListener("click", (e) => {
    const gid = $("ptsGroup").value;
    if (!gid) {
      toast("请先选择要清空的群", true);
      return;
    }
    inlineConfirm(e.currentTarget, "再点一次即清空该群所有成员积分（不可恢复）", async () => {
      try {
        await bridge.apiPost("points/reset", { group_id: gid });
        setResult($("adjResult"), "✅ 已清空该群积分");
        await loadPoints();
      } catch (err) {
        setResult($("adjResult"), "清空失败：" + err.message, true);
      }
    });
  });
  $("doAdj")?.addEventListener("click", async () => {
    const gid = $("adjGroup").value;
    const uid = $("adjUser").value.trim();
    const delta = Number($("adjDelta").value);
    if (!gid || !uid || !Number.isFinite(delta)) {
      setResult($("adjResult"), "请填写完整的群、QQ号和增减值", true);
      return;
    }
    try {
      const r = await bridge.apiPost("points/adjust", { group_id: gid, user_id: uid, delta });
      setResult($("adjResult"), `✅ 已调整，${uid} 当前 ${r.points} 分`);
      $("adjUser").value = ""; $("adjDelta").value = "";
      await loadPoints();
    } catch (e) {
      setResult($("adjResult"), "调整失败：" + e.message, true);
    }
  });

  // 数据录入
  $("stGroup")?.addEventListener("change", loadStats);
  $("doStat")?.addEventListener("click", async () => {
    const gid = $("stGroup").value;
    if (!gid) { setResult($("stResult"), "请先绑定群", true); return; }
    try {
      await bridge.apiPost("stats/add", {
        group_id: gid,
        date: $("stDate").value || todayStr(),
        total: Number($("stTotal").value) || 0,
        new: Number($("stNew").value) || 0,
        leave: Number($("stLeave").value) || 0,
        active: Number($("stActive").value) || 0,
        team: Number($("stTeam").value) || 0,
      });
      setResult($("stResult"), "✅ 数据已保存");
      ["stTotal", "stNew", "stLeave", "stActive", "stTeam"].forEach((id) => ($(id).value = ""));
      await loadStats();
    } catch (e) {
      setResult($("stResult"), "保存失败：" + e.message, true);
    }
  });

  // 推送计划
  $("addSched")?.addEventListener("click", () => {
    const time = $("scTime").value.trim();
    const tpl = $("scTpl").value;
    if (!/^\d{1,2}:\d{2}$/.test(time)) {
      toast("时间格式应为 HH:MM，例如 20:00", true);
      return;
    }
    const [h, m] = time.split(":").map(Number);
    const norm = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    state.schedule.push({ time: norm, template: tpl, enabled: true });
    state.schedule.sort((a, b) => a.time.localeCompare(b.time));
    $("scTime").value = "";
    renderSchedule();
  });
  $("saveSched")?.addEventListener("click", async () => {
    try {
      await bridge.apiPost("schedule/save", {
        schedule: state.schedule,
        enabled: $("cfgSchedule").checked,
      });
      toast("✅ 推送计划已保存");
      await loadSchedule();
    } catch (e) {
      toast("保存失败：" + e.message, true);
    }
  });
}

/* ------------------------------------------------------------------ */
/* 初始化                                                              */
/* ------------------------------------------------------------------ */

async function init() {
  try {
    await bridge.ready();
  } catch (e) {
    console.warn("bridge.ready 失败，继续尝试调用 API:", e);
  }

  $("stDate").value = todayStr();
  bindEvents();

  await loadStatus();
  await loadGroups();
  await loadTemplates();
  await loadSchedule();
  await loadPoints();
  await loadPointsConfig();
  await loadQuiz();
  await loadInviteLog(true);
  await loadStats();
  await loadAutomation();
  await loadActivity();
  await loadWelcome();
  await loadAI();

  // 主题变化时无需额外处理：bridge 自动维护 <html data-theme>
}

init();
