const API = window.API_BASE ?? "";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

// Fucking Donkey ass chigga 🫏🫏🫏
const auth = {
  get token() {
    return localStorage.getItem("at");
  },
  set(t) {
    localStorage.setItem("at", t.access_token);
    localStorage.setItem("rt", t.refresh_token);
  },
  clear() {
    localStorage.removeItem("at");
    localStorage.removeItem("rt");
  },
};

async function api(path, { method = "GET", body, form, raw } = {}) {
  const headers = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  let payload;
  if (form) {
    payload = new URLSearchParams(form);
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(API + path, { method, headers, body: payload });
  if (res.status === 401 && auth.token) {
    logout();
    throw new Error("Sesión expirada");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return raw ? res : res.json();
}

function logout() {
  auth.clear();
  boot();
}

async function mediaSrc(kind, hash) {
  const res = await api(`/${kind}/${hash}`, { raw: true });
  return URL.createObjectURL(await res.blob());
}

let currentUrl = null;
async function play(item) {
  const hash = item.hash ?? item.id;
  const known = ["video", "music"].includes(item.media_type)
    ? item.media_type
    : null;
  const order = known
    ? [known, known === "video" ? "music" : "video"]
    : ["video", "music"];
  $("#player").hidden = false;
  $("#player-title").textContent = `Cargando… ${item.title ?? ""}`;
  try {
    let src, kind, lastErr;
    for (const k of order) {
      try {
        src = await mediaSrc(k, hash);
        kind = k;
        break;
      } catch (e) {
        lastErr = e;
      }
    }
    if (!src) throw lastErr;
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = src;
    const tag = kind === "video" ? "video" : "audio";
    $("#player-media").innerHTML =
      `<${tag} controls autoplay src="${src}"></${tag}>`;
    $("#player-title").textContent =
      `${item.title ?? ""} ${item.uploader ? "— " + item.uploader : ""}`;
  } catch (e) {
    $("#player-title").innerHTML =
      `<span class="error">${esc(e.message)}</span>`;
  }
}

function itemRow(it) {
  const hash = it.hash ?? it.id;
  return `
    <div class="item" data-hash="${esc(hash)}">
      <img loading="lazy" src="${API}/thumbnail/${esc(hash)}" alt="">
      <div class="info">
        <div class="title">${esc(it.title)}</div>
        <div class="muted">${esc(it.uploader)} · ${esc(it.media_type ?? "")}</div>
      </div>
      <div class="actions">
        <button data-act="play">▶</button>
        <button data-act="fav" title="Favorito">★</button>
      </div>
    </div>`;
}

function wireItems(root, store) {
  root.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const hash = btn.closest(".item").dataset.hash;
    const item = store.find((i) => (i.hash ?? i.id) === hash);
    if (btn.dataset.act === "play") play(item);
    if (btn.dataset.act === "fav") {
      try {
        await api(`/users/me/favorites/${hash}`, { method: "POST" });
        btn.textContent = "✔";
      } catch (err) {
        alert(err.message);
      }
    }
  });
}

function fmtDur(s) {
  if (!s) return "";
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const views = {
  async feed(el) {
    el.innerHTML = `
      <div class="row">
        <select id="mt"><option value="all">Todo</option><option value="video">Video</option><option value="music">Música</option></select>
      </div>
      <div id="list"></div><button id="more" hidden>Cargar más</button>`;
    const store = [];
    let skip = 0;
    wireItems(el, store);
    const load = async (reset) => {
      if (reset) {
        skip = 0;
        store.length = 0;
        $("#list", el).innerHTML = "";
      }
      const d = await api(
        `/feed?media_type=${$("#mt", el).value}&skip=${skip}&limit=50`,
      );
      store.push(...d.feed);
      $("#list", el).insertAdjacentHTML(
        "beforeend",
        d.feed.map(itemRow).join(""),
      );
      skip = d.next_skip ?? skip;
      $("#more", el).hidden = d.next_skip == null;
    };
    $("#mt", el).onchange = () => load(true);
    $("#more", el).onclick = () => load(false);
    await load(true);
  },

  async search(el) {
    el.innerHTML = `
      <form class="row"><input name="q" type="search" placeholder="Buscar en la biblioteca…" required>
      <button>Buscar</button></form><div id="list"></div>`;
    const store = [];
    wireItems(el, store);
    $("form", el).onsubmit = async (e) => {
      e.preventDefault();
      const q = new FormData(e.target).get("q");
      const rows = await api(`/search?q=${encodeURIComponent(q)}`);
      store.length = 0;
      store.push(...rows);
      $("#list", el).innerHTML =
        rows.map(itemRow).join("") || `<p class="muted">Sin resultados</p>`;
    };
  },

  async discover(el) {
    el.innerHTML = `
      <form class="row"><input name="q" type="search" placeholder="Buscar en YouTube…" required>
      <button>Buscar</button></form><div id="list"></div><button id="more" hidden>Más</button>`;
    let page = 1,
      q = "",
      results = [];
    const draw = (rows) =>
      rows
        .map(
          (r, i) => `
      <div class="item" data-url="${esc(r.url)}">
        <img loading="lazy" src="${esc(r.thumbnail)}" alt="">
        <div class="info">
          <div class="title">${esc(r.title)}</div>
          <div class="muted">${esc(r.uploader)} · ${fmtDur(r.duration)} <span class="status"></span></div>
        </div>
        <div class="actions">
          <button data-dl="music">⬇ Música</button>
          <button data-dl="videos">⬇ Video</button>
        </div>
      </div>`,
        )
        .join("");

    const load = async () => {
      const d = await api(
        `/discover?q=${encodeURIComponent(q)}&page=${page}&limit=20`,
      );
      results.push(...d.results);
      $("#list", el).insertAdjacentHTML("beforeend", draw(d.results));
      $("#more", el).hidden = !d.has_more;
    };
    $("form", el).onsubmit = async (e) => {
      e.preventDefault();
      q = new FormData(e.target).get("q");
      page = 1;
      results = [];
      $("#list", el).innerHTML = "";
      await load();
    };
    $("#more", el).onclick = () => {
      page++;
      load();
    };

    el.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-dl]");
      if (!btn) return;
      const row = btn.closest(".item"),
        status = $(".status", row);
      try {
        const { task_id } = await api(
          `/${btn.dataset.dl}?url=${encodeURIComponent(row.dataset.url)}`,
          { method: "POST" },
        );
        pollTask(task_id, status);
      } catch (err) {
        status.textContent = err.message;
      }
    });
  },

  async favorites(el) {
    const { favorites } = await api("/users/me/favorites");
    el.innerHTML =
      favorites.map(itemRow).join("") ||
      `<p class="muted">Aún no tienes favoritos</p>`;
    wireItems(el, favorites);
  },

  async playlists(el) {
    const render = async () => {
      const { playlists } = await api("/users/me/playlists");
      el.innerHTML = `
        <form class="row"><input name="name" placeholder="Nueva playlist" required><button>Crear</button></form>
        ${playlists
          .map(
            (p) => `
          <div class="item" data-id="${p.id}">
            <img src="${p.cover_url ? API + p.cover_url : ""}" alt="">
            <div class="info"><div class="title">${esc(p.name)}</div><div class="muted">${p.item_count} items</div></div>
            <div class="actions"><button data-act="open">Abrir</button><button data-act="del">🗑</button></div>
          </div>`,
          )
          .join("")}`;
      $("form", el).onsubmit = async (e) => {
        e.preventDefault();
        await api("/users/me/playlists", {
          method: "POST",
          body: { name: new FormData(e.target).get("name") },
        });
        render();
      };
    };
    el.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-act]");
      const id = btn?.closest(".item")?.dataset.id;
      if (
        !id ||
        !["open", "del"].includes(btn.dataset.act) ||
        btn.closest("#pl-items")
      )
        return;
      if (btn.dataset.act === "del") {
        await api(`/users/me/playlists/${id}`, { method: "DELETE" });
        return render();
      }
      const pl = await api(`/users/me/playlists/${id}`);
      el.innerHTML = `<button id="back" class="ghost">← Volver</button><h2>${esc(pl.name)}</h2>
        <div id="pl-items">${pl.items.map(itemRow).join("")}</div>`;
      wireItems($("#pl-items", el), pl.items);
      $("#back", el).onclick = render;
    });
    await render();
  },
};

async function pollTask(id, statusEl) {
  const tick = async () => {
    try {
      const t = await api(`/videos/progress/${id}`);
      statusEl.textContent = `${t.status} ${t.percent ?? ""}`;
      if (
        !["finished", "completed", "done", "error", "failed"].includes(
          String(t.status).toLowerCase(),
        )
      )
        setTimeout(tick, 1500);
    } catch (e) {
      statusEl.textContent = e.message;
    }
  };
  tick();
}

const NAV = [
  ["feed", "Biblioteca"],
  ["search", "Buscar"],
  ["discover", "Descubrir"],
  ["favorites", "Favoritos"],
  ["playlists", "Playlists"],
];

async function show(name) {
  const el = $("#view");
  el.replaceWith(el.cloneNode(false));
  const fresh = $("#view");
  document
    .querySelectorAll("#nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.v === name));
  location.hash = name;
  try {
    await views[name](fresh);
  } catch (e) {
    fresh.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

function loginView() {
  $("#topbar").hidden = true;
  $("#view").innerHTML = `
    <form class="auth" id="login">
      <h2>Omnicast</h2>
      <input name="username" placeholder="Usuario" required autocomplete="username">
      <input name="password" type="password" placeholder="Contraseña" required autocomplete="current-password">
      <button>Entrar</button>
      <button type="button" id="reg" class="ghost">Crear cuenta</button>
      <div class="error" id="err"></div>
    </form>`;
  const form = $("#login"),
    err = $("#err");
  const creds = () => Object.fromEntries(new FormData(form));
  form.onsubmit = async (e) => {
    e.preventDefault();
    err.textContent = "";
    try {
      auth.set(await api("/token", { method: "POST", form: creds() }));
      boot();
    } catch (ex) {
      err.textContent = ex.message;
    }
  };
  $("#reg").onclick = async () => {
    err.textContent = "";
    try {
      await api("/register", { method: "POST", body: creds() });
      auth.set(await api("/token", { method: "POST", form: creds() }));
      boot();
    } catch (ex) {
      err.textContent = ex.message;
    }
  };
}

function boot() {
  if (!auth.token) {
    $("#player").hidden = true;
    return loginView();
  }
  $("#topbar").hidden = false;
  $("#nav").innerHTML = NAV.map(
    ([k, label]) => `<button data-v="${k}">${label}</button>`,
  ).join("");
  $("#nav").onclick = (e) => {
    const v = e.target.dataset.v;
    if (v) show(v);
  };
  $("#logout").onclick = logout;
  const start = location.hash.slice(1);
  show(views[start] ? start : "feed");
}

boot();
