/* ReachSwim dashboard — small, dependency-free behaviours wired by data attributes. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ── Sidebar (mobile) ─────────────────────────────────────────────── */
  const sidebar = $("#sidebar");
  const scrim = $("#scrim");
  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("is-open", open);
    scrim && scrim.classList.toggle("is-open", open);
  }
  $$("[data-sidebar-toggle]").forEach((b) => b.addEventListener("click", () => setSidebar(!sidebar.classList.contains("is-open"))));
  scrim && scrim.addEventListener("click", () => setSidebar(false));

  /* ── Sidebar collapse (desktop): icon rail, remembered per browser ── */
  const collapseBtn = $("[data-sidebar-collapse]");
  function applyCollapsed(collapsed) {
    if (collapsed) root.dataset.sidebar = "collapsed";
    else delete root.dataset.sidebar;
    // Tooltips only matter when the labels are hidden.
    $$(".sidebar [data-tip]").forEach((el) => {
      if (collapsed) el.title = el.dataset.tip;
      else el.removeAttribute("title");
    });
    if (collapseBtn) {
      collapseBtn.setAttribute("aria-expanded", String(!collapsed));
      $(".nav-link__text", collapseBtn).textContent = collapsed ? "Expand menu" : "Collapse menu";
    }
  }
  const root = document.documentElement;
  applyCollapsed(root.dataset.sidebar === "collapsed");
  collapseBtn && collapseBtn.addEventListener("click", () => {
    const collapsed = root.dataset.sidebar !== "collapsed";
    applyCollapsed(collapsed);
    try { localStorage.setItem("rs-dash-sidebar", collapsed ? "collapsed" : "expanded"); } catch (e) {}
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "\\") { e.preventDefault(); collapseBtn && collapseBtn.click(); }
  });

  /* Keep the nav where the user left it, and always show the active link. */
  const nav = $(".sidebar__nav");
  if (nav) {
    const KEY = "dash-nav-scroll";
    try {
      const saved = sessionStorage.getItem(KEY);
      if (saved !== null) nav.scrollTop = +saved;
    } catch (e) {}
    const active = $(".nav-link.is-active", nav);
    if (active) {
      const top = active.getBoundingClientRect().top - nav.getBoundingClientRect().top + nav.scrollTop;
      const bottom = top + active.offsetHeight;
      if (top < nav.scrollTop || bottom > nav.scrollTop + nav.clientHeight) {
        nav.scrollTop = top - (nav.clientHeight - active.offsetHeight) / 2;
      }
    }
    window.addEventListener("pagehide", () => {
      try { sessionStorage.setItem(KEY, nav.scrollTop); } catch (e) {}
    });
  }

  /* ── Theme toggle (per-viewer convenience) ────────────────────────── */
  $$("[data-theme-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("rs-dash-theme", root.dataset.theme); } catch (e) {}
    })
  );

  /* ── Toasts ───────────────────────────────────────────────────────── */
  function dismiss(t) {
    t.classList.add("is-leaving");
    setTimeout(() => t.remove(), 200);
  }
  $$(".toast").forEach((t) => {
    const close = $(".toast__close", t);
    close && close.addEventListener("click", () => dismiss(t));
    if (!t.classList.contains("toast--error")) setTimeout(() => dismiss(t), 6000);
  });

  /* ── Confirm dialog: <form data-confirm="..."> or <button data-confirm> ── */
  const modal = $("#confirm-modal");
  let pending = null;
  function askConfirm(message, opts, onYes) {
    if (!modal || typeof modal.showModal !== "function") {
      if (window.confirm(message)) onYes();
      return;
    }
    $("#confirm-title", modal).textContent = opts.title || "Are you sure?";
    $("#confirm-text", modal).textContent = message;
    const yes = $("#confirm-yes", modal);
    yes.textContent = opts.label || "Confirm";
    yes.className = "btn " + (opts.danger === false ? "btn--primary" : "btn--danger");
    pending = onYes;
    modal.showModal();
    yes.focus();
  }
  if (modal) {
    $("#confirm-yes", modal).addEventListener("click", () => {
      modal.close();
      const fn = pending;
      pending = null;
      fn && fn();
    });
    $("#confirm-no", modal).addEventListener("click", () => modal.close());
  }
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const submitter = e.submitter;
    const msg = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
    if (!msg || form.dataset.confirmed === "1") return;
    e.preventDefault();
    const src = submitter && submitter.dataset.confirm ? submitter.dataset : form.dataset;
    askConfirm(msg, { title: src.confirmTitle, label: src.confirmLabel, danger: src.confirmDanger !== "false" }, () => {
      form.dataset.confirmed = "1";
      if (submitter && submitter.name) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = submitter.name;
        h.value = submitter.value;
        form.appendChild(h);
      }
      form.submit();
    });
  });

  /* ── Clickable rows ───────────────────────────────────────────────── */
  $$("tr[data-href]").forEach((tr) =>
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input, select, textarea, label, form")) return;
      if (e.metaKey || e.ctrlKey) window.open(tr.dataset.href, "_blank");
      else window.location = tr.dataset.href;
    })
  );

  /* ── Bulk selection ───────────────────────────────────────────────── */
  $$("[data-bulk]").forEach((scope) => {
    const all = $("[data-bulk-all]", scope);
    const bar = $("[data-bulk-bar]", scope);
    const count = $("[data-bulk-count]", scope);
    const boxes = () => $$("[data-bulk-item]", scope);
    function sync() {
      const checked = boxes().filter((b) => b.checked);
      boxes().forEach((b) => b.closest("tr") && b.closest("tr").classList.toggle("is-selected", b.checked));
      if (bar) bar.classList.toggle("is-visible", checked.length > 0);
      if (count) count.textContent = checked.length + " selected";
      if (all) {
        all.checked = checked.length > 0 && checked.length === boxes().length;
        all.indeterminate = checked.length > 0 && checked.length < boxes().length;
      }
    }
    all && all.addEventListener("change", () => { boxes().forEach((b) => (b.checked = all.checked)); sync(); });
    scope.addEventListener("change", (e) => { if (e.target.matches("[data-bulk-item]")) sync(); });
    $$("[data-bulk-clear]", scope).forEach((b) => b.addEventListener("click", () => { boxes().forEach((x) => (x.checked = false)); sync(); }));
    sync();
  });

  /* ── Tabs: [data-tabs] with buttons[data-tab] and .tab-panel#tab-<id> ── */
  $$("[data-tabs]").forEach((tabs) => {
    const buttons = $$("[data-tab]", tabs);
    function show(id, push) {
      if (!$("#tab-" + id)) id = buttons[0].dataset.tab;
      buttons.forEach((b) => {
        const on = b.dataset.tab === id;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-selected", on);
      });
      $$(".tab-panel").forEach((p) => p.classList.toggle("is-active", p.id === "tab-" + id));
      if (push) history.replaceState(null, "", "#" + id);
    }
    buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.tab, true)));
    show(location.hash.replace("#", "") || tabs.dataset.defaultTab || buttons[0].dataset.tab, false);
  });

  /* ── Slug auto-fill: <input data-slug-from="id_name"> ─────────────── */
  $$("[data-slug-from]").forEach((slug) => {
    const src = document.getElementById(slug.dataset.slugFrom);
    if (!src) return;
    let touched = slug.value.trim() !== "";
    slug.addEventListener("input", () => (touched = true));
    src.addEventListener("input", () => {
      if (touched) return;
      slug.value = src.value.toLowerCase().trim().replace(/[^a-z0-9\s-]/g, "").replace(/\s+/g, "-").replace(/-+/g, "-");
    });
  });

  /* ── Dirty-tracking inline forms (e.g. stock) ─────────────────────── */
  $$("[data-dirty]").forEach((input) => {
    const btn = $("[data-dirty-btn]", input.form);
    if (!btn) return;
    const original = input.value;
    btn.disabled = true;
    input.addEventListener("input", () => (btn.disabled = input.value === original));
  });

  /* ── Image preview: <input type=file data-preview="#img"> ─────────── */
  $$("input[type=file][data-preview]").forEach((input) => {
    const zone = input.closest(".dropzone-wrap");
    const dz = zone && $(".dropzone", zone);
    if (dz) {
      dz.addEventListener("click", () => input.click());
      dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    }
    input.addEventListener("change", () => {
      const file = input.files[0];
      const img = $(input.dataset.preview);
      if (!file || !img) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        img.src = e.target.result;
        img.hidden = false;
        const ph = zone && $(".dropzone__placeholder", zone);
        if (ph) ph.hidden = true;
      };
      reader.readAsDataURL(file);
    });
  });

  /* ── Pence preview: <input data-pence-preview="#out"> ─────────────── */
  $$("[data-pence-preview]").forEach((input) => {
    const out = $(input.dataset.pencePreview);
    const sym = input.dataset.symbol || "£";
    const update = () => {
      const v = parseInt(input.value, 10);
      out.textContent = isNaN(v) ? "" : "= " + sym + (v / 100).toFixed(2);
    };
    input.addEventListener("input", update);
    update();
  });

  /* ── Formset "add row": <button data-formset-add="prefix"> ─────────── */
  $$("[data-formset-add]").forEach((btn) => {
    const prefix = btn.dataset.formsetAdd;
    btn.addEventListener("click", () => {
      const total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
      const tpl = document.getElementById(prefix + "-empty");
      const list = document.getElementById(prefix + "-rows");
      if (!total || !tpl || !list) return;
      const idx = parseInt(total.value, 10);
      const wrap = document.createElement("div");
      wrap.innerHTML = tpl.innerHTML.replace(/__prefix__/g, String(idx)).trim();
      const row = wrap.firstElementChild;
      list.appendChild(row);
      total.value = idx + 1;
      const empty = document.getElementById(prefix + "-none");
      if (empty) empty.hidden = true;
      const first = row.querySelector("input:not([type=hidden]), select, textarea");
      first && first.focus();
    });
  });

  /* ── Auto-submit filters: <select data-autosubmit> ────────────────── */
  $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.submit()));

  /* ── Command palette ──────────────────────────────────────────────── */
  const palette = $("#palette");
  if (palette) {
    const input = $(".palette__input", palette);
    const list = $(".palette__results", palette);
    const searchUrl = palette.dataset.searchUrl;
    const pages = $$(".sidebar a.nav-link").map((a) => ({
      label: a.textContent.trim().replace(/\s+\d+$/, ""),
      url: a.getAttribute("href"),
      sub: "Go to page",
    }));
    const actions = $$("[data-palette-action]").map((a) => ({ label: a.dataset.paletteAction, url: a.getAttribute("href"), sub: "Action" }));
    let items = [];
    let active = 0;
    let timer = null;
    let seq = 0;

    function render(groups) {
      items = [];
      list.innerHTML = "";
      groups.forEach(([name, rows]) => {
        if (!rows.length) return;
        const g = document.createElement("li");
        g.className = "palette__group";
        g.textContent = name;
        list.appendChild(g);
        rows.forEach((r) => {
          const li = document.createElement("li");
          const a = document.createElement("a");
          a.className = "palette__item";
          a.href = r.url;
          a.textContent = r.label;
          if (r.sub) {
            const s = document.createElement("span");
            s.className = "palette__item-sub";
            s.textContent = r.sub;
            a.appendChild(s);
          }
          li.appendChild(a);
          list.appendChild(li);
          items.push(a);
        });
      });
      if (!items.length) {
        const li = document.createElement("li");
        li.className = "palette__empty";
        li.textContent = "Nothing matches “" + input.value + "”. Try a client name, email, or order number.";
        list.appendChild(li);
      }
      highlight(0);
    }
    function highlight(i) {
      active = Math.max(0, Math.min(i, items.length - 1));
      items.forEach((a, n) => a.classList.toggle("is-active", n === active));
      items[active] && items[active].scrollIntoView({ block: "nearest" });
    }
    function filterLocal(q) {
      q = q.toLowerCase();
      const m = (r) => r.label.toLowerCase().includes(q);
      return [["Pages", pages.filter(m)], ["Actions", actions.filter(m)]];
    }
    function update() {
      const q = input.value.trim();
      const local = q ? filterLocal(q) : [["Pages", pages], ["Actions", actions]];
      render(local);
      clearTimeout(timer);
      if (q.length < 2 || !searchUrl) return;
      const mine = ++seq;
      timer = setTimeout(() => {
        fetch(searchUrl + "?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" } })
          .then((r) => (r.ok ? r.json() : { groups: [] }))
          .then((data) => {
            if (mine !== seq) return;
            render(local.concat(data.groups.map((g) => [g.name, g.results])));
          })
          .catch(() => {});
      }, 180);
    }
    function open() {
      input.value = "";
      update();
      palette.showModal();
      input.focus();
    }
    $$("[data-palette-open]").forEach((b) => b.addEventListener("click", open));
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        palette.open ? palette.close() : open();
      } else if (e.key === "/" && !palette.open && !e.target.closest("input, textarea, select, [contenteditable]")) {
        e.preventDefault();
        open();
      }
    });
    input.addEventListener("input", update);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active - 1); }
      else if (e.key === "Enter" && items[active]) { e.preventDefault(); window.location = items[active].href; }
    });
    palette.addEventListener("click", (e) => { if (e.target === palette) palette.close(); });
  }
})();
