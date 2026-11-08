// для hx-vals поллера и отправки: курсор — последний отрисованный ряд, а не число с сервера,
// так запоздавший ответ не сдвинет его ни назад, ни вперёд; с этим же рядом сервер склеивает серию и день
function lastRendered() {
  let row = document.getElementById("messages")?.lastElementChild;
  while (row && !row.dataset.ts) row = row.previousElementSibling;
  return row ? { after: row.dataset.id, last_from: row.dataset.from, last_ts: row.dataset.ts } : { after: 0 };
}

// перерисовка списка просит столько диалогов, сколько уже подгружено, и версию — на неизменный список сервер ответит 204
function dialogsState() {
  const list = document.getElementById("dialog-list");
  return { count: Math.max(1, list.querySelectorAll(":scope > li.dlg").length), v: list.dataset.version || "" };
}

// пока открыт поток событий long poll, частый поллинг не нужен: новое приходит сигналом, редкий тик — подстраховка
function imLive() {
  return window.imEvents?.readyState === EventSource.OPEN;
}

function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const dayFormats = {};

function dayMonth(ts, tz) {
  try {
    dayFormats[tz] ||= new Intl.DateTimeFormat("ru", { timeZone: tz, day: "numeric", month: "numeric" });
  } catch (_) {
    dayFormats[tz] = new Intl.DateTimeFormat("ru", { day: "numeric", month: "numeric" });
  }
  const parts = dayFormats[tz].formatToParts(new Date(ts * 1000));
  const day = parts.find((p) => p.type === "day").value;
  return `${day} ${MONTHS_SHORT[Number(parts.find((p) => p.type === "month").value) - 1]}`;
}

// то же, что short_since на сервере: неизменный список сервер не перерисовывает, и «5м» в нём стареет здесь
function since(ts, now, tz) {
  const ago = Math.max(0, now - ts);
  if (ago < 3600) return `${Math.max(1, Math.floor(ago / 60))}м`;
  if (ago < 86400) return `${Math.floor(ago / 3600)}ч`;
  if (ago < 7 * 86400) return `${Math.floor(ago / 86400)}д`;
  return dayMonth(ts, tz);
}

// лента — flex column-reverse: scrollTop отсчитывается от низа и при прокрутке вверх уходит в минус
const fromBottom = (s) => Math.abs(s.scrollTop);
const fromTop = (s) => s.scrollHeight - s.clientHeight - Math.abs(s.scrollTop);

// просмотрщик и плеер закрываются кнопкой «назад», как в мобильном VK: на время показа в истории лишняя запись.
// Её popstate перехватывается до htmx — иначе он восстановил бы из истории страницу чата целиком
const overlay = {
  hide: null,
  // сколько своих записей убрано history.back(), а их popstate ещё не пришёл
  skip: 0,
  open(hide) {
    if (!this.hide) history.pushState({ imOverlay: true }, "");
    this.hide = hide;
    document.documentElement.classList.add("im-modal");
  },
  // закрыто кнопкой на странице: окно прячется сразу, своя запись истории убирается следом
  dismiss() {
    if (!this.hide) return;
    this.fire();
    if (history.state?.imOverlay) {
      this.skip++;
      history.back();
    }
  },
  fire() {
    const hide = this.hide;
    this.hide = null;
    document.documentElement.classList.remove("im-modal");
    hide?.();
  },
};
window.addEventListener("popstate", (e) => {
  if (overlay.skip) {
    overlay.skip--;
    e.stopImmediatePropagation();
    return;
  }
  if (!overlay.hide) return;
  e.stopImmediatePropagation();
  overlay.fire();
}, true);

document.addEventListener("alpine:init", () => {
  Alpine.data("im", (sel) => ({
    sel, pane: sel ? "chat" : "list", filter: "", unreadOnly: false, loading: false,
    question: "", confirmed: null, edge: null,
    init() {
      const list = document.getElementById("dialog-list");
      const warm = { timer: 0, at: {}, busy: false };
      let settling = false;
      this.tz = list.dataset.tz;
      this.skew = Number(list.dataset.now || 0) ? Number(list.dataset.now) - Date.now() / 1000 : 0;
      this.$watch("filter", () => this.applyFilter());
      this.$watch("unreadOnly", () => this.applyFilter());
      this.$watch("sel", () => this.markActive());
      this.markActive();
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
      this.$el.addEventListener("im-close", () => this.close());
      this.listen();
      // строки списка без своих обработчиков: их сотни, и каждая перерисовка списка заводила бы их заново
      const dialogs = document.getElementById("dialogs");
      dialogs.addEventListener("click", (e) => {
        const li = e.target.closest("li[data-peer]");
        if (li && e.target.closest("a")) this.open(Number(li.dataset.peer));
      });
      // наведение на диалог заранее просит у VK его историю: клик откроет чат без ожидания;
      // по одному прогреву за раз — у VK ~3 запроса в секунду, и очередь прогревов задержала бы сам клик
      dialogs.addEventListener("mouseover", (e) => {
        const a = e.target.closest("li[data-peer] > a");
        if (!a || a.contains(e.relatedTarget)) return;
        const id = Number(a.parentElement.dataset.peer);
        clearTimeout(warm.timer);
        if (id === this.sel || Date.now() - (warm.at[id] || 0) < 10000) return;
        warm.timer = setTimeout(() => {
          if (id === this.sel || warm.busy) return;
          warm.at[id] = Date.now();
          warm.busy = true;
          fetch(`/im/${id}/warm`, { method: "POST", headers: { "HX-Request": "true" } })
            .catch(() => {}).finally(() => { warm.busy = false; });
        }, 250);
      });
      dialogs.addEventListener("mouseout", (e) => {
        const a = e.target.closest("li[data-peer] > a");
        if (a && !a.contains(e.relatedTarget)) clearTimeout(warm.timer);
      });
      // запрос открытия чата уходит от ссылки в списке слева, поэтому слушаем весь мессенджер, а не колонку чата
      this.$el.addEventListener("htmx:beforeRequest", (e) => { if (e.detail.target.id === "chat") this.loading = true; });
      this.$el.addEventListener("htmx:afterRequest", (e) => {
        if (e.detail.target.id === "chat") this.loading = false;
        const version = e.detail.xhr?.getResponseHeader("X-Dialogs-Version");
        if (e.detail.elt.id === "dialog-list" && version) e.detail.elt.dataset.version = version;
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const target = e.detail.target;
        if (target.id === "search-results") {
          this.dropShownHits(target);
          this.markActive();
          return;
        }
        const more = e.detail.pathInfo?.requestPath?.startsWith("/im/dialogs/more");
        if (target.id !== "dialog-list" && !more) return;
        // после outerHTML событие приходит от каждого вставленного ряда — разбираем список один раз
        if (settling) return;
        settling = true;
        queueMicrotask(() => {
          settling = false;
          // пока грузилась следующая страница, новое сообщение могло поднять диалог и сдвинуть offset
          this.dropRepeatedDialogs();
          this.applyFilter();
          this.markActive();
          this.refreshTimes();
        });
      });
      clearInterval(window.imClock);
      window.imClock = setInterval(() => { if (document.visibilityState === "visible") this.refreshTimes(); }, 30000);
      // htmx при восстановлении истории заново запускает init: старый слушатель держал бы отсоединённый диалог
      if (window.imConfirm) document.removeEventListener("htmx:confirm", window.imConfirm);
      window.imConfirm = (e) => {
        if (!e.detail.question) return;
        e.preventDefault();
        this.question = e.detail.question;
        this.confirmed = () => e.detail.issueRequest(true);
        // returnValue переживает закрытие: без сброса Esc повторил бы прошлое «Удалить»
        this.$refs.confirm.returnValue = "";
        this.$refs.confirm.showModal();
      };
      document.addEventListener("htmx:confirm", window.imConfirm);
    },
    listen(delay = 3000) {
      if (!window.EventSource || window.imEvents) return;
      const events = window.imEvents = new EventSource("/im/events");
      events.addEventListener("open", () => { delay = 3000; });
      // peers — чаты, в которых что-то изменилось; null — неизвестно какие
      events.addEventListener("changed", (e) => {
        let peers = null;
        try { peers = JSON.parse(e.data).peers; } catch (_) {}
        const poll = document.getElementById("chat-poll");
        if (poll && (!peers || peers.includes(Number(poll.dataset.peer)))) htmx.trigger(poll, "poke");
        htmx.trigger("#dialog-list", "poke");
      });
      // 502 во время деплоя или редирект на /login браузер не переподключает сам: поток закрыт навсегда
      events.addEventListener("error", () => {
        if (events.readyState !== EventSource.CLOSED) return;
        window.imEvents = null;
        setTimeout(() => this.listen(Math.min(delay * 2, 60000)), delay);
      });
    },
    applyFilter() {
      document.querySelectorAll("#dialog-list > li[data-peer]").forEach((li) => {
        const hide = !this.matches(li);
        if (li.hidden !== hide) li.hidden = hide;
      });
    },
    markActive() {
      document.querySelectorAll("#dialogs li.active").forEach((li) => li.classList.remove("active"));
      if (this.sel != null) document.querySelectorAll(`#dialogs li[data-peer="${this.sel}"]`).forEach((li) => li.classList.add("active"));
    },
    refreshTimes() {
      const now = Date.now() / 1000 + this.skew;
      document.querySelectorAll("#dialogs time[data-ts]").forEach((t) => {
        const text = since(Number(t.dataset.ts), now, this.tz);
        if (t.textContent !== text) t.textContent = text;
      });
    },
    // скрытое локальным фильтром (он не знает ё/е и раскладок) остаётся в поиске VK
    dropShownHits(results) {
      const shown = new Set([...document.querySelectorAll("#dialog-list > li[data-peer]")]
        .filter((li) => this.matches(li)).map((li) => li.dataset.peer));
      results.querySelectorAll("li[data-peer]").forEach((li) => shown.has(li.dataset.peer) && li.remove());
    },
    dropRepeatedDialogs() {
      const seen = new Set();
      document.querySelectorAll("#dialog-list > li[data-peer]").forEach((li) => {
        if (seen.has(li.dataset.peer)) li.remove();
        else seen.add(li.dataset.peer);
      });
    },
    answer(yes) {
      if (yes) this.confirmed?.();
      this.confirmed = null;
    },
    open(id) { this.sel = id; this.pane = "chat"; },
    close() {
      this.sel = null;
      this.pane = "list";
      document.getElementById("chat").innerHTML = document.getElementById("im-empty").innerHTML;
      history.pushState({}, "", "/im");
    },
    // свайп от левого края открытого чата возвращает к списку, как «назад» в мобильном VK
    edgeFrom(e) {
      const t = e.touches[0];
      this.edge = this.pane === "chat" && t.clientX < 24 ? { x: t.clientX, y: t.clientY } : null;
    },
    edgeTo(e) {
      const t = e.changedTouches[0];
      if (this.edge && t.clientX - this.edge.x > 80 && Math.abs(t.clientY - this.edge.y) < 60) this.pane = "list";
      this.edge = null;
    },
    hotkey(e) {
      // code, а не key: в русской раскладке key — «л»
      if (!(e.ctrlKey || e.metaKey) || e.code !== "KeyK") return;
      e.preventDefault();
      this.pane = "list";
      this.$nextTick(() => this.$refs.search.focus());
    },
    matches(li) {
      const byTitle = !this.filter || li.dataset.title.includes(this.filter.toLowerCase());
      const byUnread = !this.unreadOnly || Number(li.dataset.unread) > 0;
      return byTitle && byUnread;
    },
  }));

  Alpine.data("chat", (peerId, outRead, unread) => {
    let anchor = null;
    let settling = false;
    let raf = 0;
    let stuckChip = null;
    let picked = null;
    return {
      peerId, outRead, unread, panel: null, atBottom: true, pending: 0,
      init() {
        this.$el.addEventListener("htmx:beforeSwap", (e) => this.remember(e));
        this.$el.addEventListener("htmx:afterSwap", (e) => this.settle(e));
        // сентинел старых страниц подхватывает htmx; просим страницу, как только он готов, если верх ленты уже близко
        this.$el.addEventListener("htmx:afterProcessNode", (e) => {
          if (e.target.classList?.contains("im-more")) requestAnimationFrame(() => this.prefetch());
        });
        this.$el.addEventListener("click", (e) => this.pick(e));
        requestAnimationFrame(() => { this.markStuck(); this.prefetch(); });
      },
      // своп в ленте: поллинг и отправка дописывают снизу, сентинел — старые сверху; сентинел заменяется
      // целиком, поэтому после свопа своп узнаётся по запомненной цели, а не по месту в документе
      remember(e) {
        const target = e.detail.target;
        const list = this.$refs.list;
        const older = target.classList.contains("im-more") && list.contains(target);
        if (!e.detail.shouldSwap || (target !== list && !older)) return;
        anchor = { target, older, stick: !older && this.nearBottom(), before: Number(lastRendered().after), row: null, top: 0 };
        if (anchor.stick) return;
        const row = this.firstVisible();
        if (row) { anchor.row = row; anchor.top = row.getBoundingClientRect().top; }
      },
      settle(e) {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        if (!anchor || e.detail.target !== anchor.target || settling) return;
        settling = true;
        const done = anchor;
        // afterSwap приходит на каждый вставленный элемент — разбираем ленту один раз за своп
        queueMicrotask(() => {
          settling = false;
          anchor = null;
          const list = this.$refs.list;
          const scroller = this.$refs.scroller;
          this.dedupe();
          if (done.older) this.dedupeDays();
          if (list.querySelector(":scope > [data-id]")) list.querySelector(":scope > .im-empty")?.remove();
          // браузер держит отступ от низа ленты: дописанное снизу сдвинуло бы читаемое, если лента отмотана вверх
          if (done.stick) scroller.scrollTop = 0;
          else if (done.row?.isConnected) {
            const shift = done.row.getBoundingClientRect().top - done.top;
            if (shift) scroller.scrollTop += shift;
          }
          if (!done.stick && !done.older) this.pending += this.arrived(done.before);
          this.markTicks();
          this.markStuck();
          this.prefetch();
        });
      },
      firstVisible() {
        const box = this.$refs.scroller.getBoundingClientRect();
        for (const y of [box.top + 48, box.top + box.height / 2]) {
          const row = document.elementFromPoint(box.left + box.width / 2, y)?.closest("#messages > [data-id]");
          if (row) return row;
        }
        return [...this.$refs.list.children].find((el) => el.dataset.id && el.getBoundingClientRect().bottom > box.top) || null;
      },
      // счётчик на кнопке «вниз»: входящие, вставленные поллингом, пока лента отмотана вверх
      arrived(before) {
        let n = 0;
        for (let el = this.$refs.list.lastElementChild; el; el = el.previousElementSibling) {
          if (el.dataset.id && Number(el.dataset.id) <= before) break;
          if (el.matches(".msg:not(.out):not(.draft)")) n++;
        }
        return n;
      },
      // поллинг, ушедший до отправки, может вернуть уже вставленное отправкой сообщение
      dedupe() {
        const seen = new Set();
        this.$refs.list.querySelectorAll(":scope > [data-id]").forEach((el) => {
          if (seen.has(el.dataset.id)) el.remove();
          else seen.add(el.dataset.id);
        });
      },
      // страница старых заканчивается чипом того же дня, с которого начиналась лента
      dedupeDays() {
        let prev = null;
        this.$refs.list.querySelectorAll(":scope > .im-day").forEach((chip) => {
          if (chip.textContent === prev) chip.remove();
          else prev = chip.textContent;
        });
      },
      markTicks() {
        this.$refs.list.querySelectorAll(".msg.out .ticks:not(.read)").forEach((t) => {
          if (Number(t.closest(".msg").dataset.id) <= this.outRead) t.classList.add("read");
        });
      },
      // мессенджер сам ничего прочитанным не отмечает: VK и собеседник видят прочтение только по этой кнопке
      readNow() {
        fetch(`/im/${this.peerId}/read`, { method: "POST", headers: { "HX-Request": "true" } })
          .then((r) => { if (r.ok) this.unread = 0; });
      },
      onScroll() {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = 0;
          const bottom = this.nearBottom();
          if (bottom !== this.atBottom) this.atBottom = bottom;
          if (bottom && this.pending) this.pending = 0;
          this.markStuck();
          this.prefetch();
        });
      },
      // старые сообщения просятся за пару экранов до верха: пока лента докрутится, они уже на месте
      prefetch() {
        const scroller = this.$refs.scroller;
        // скрытая лента (на телефоне открыт список) имеет нулевую высоту и «всегда у верха» — грузила бы всю историю
        if (!scroller.clientHeight || fromTop(scroller) > 2 * scroller.clientHeight) return;
        const more = this.$refs.list.querySelector(":scope > .im-more");
        if (more) htmx.trigger(more, "near");
      },
      // sticky сам не сообщает, что упёрся в край: подложку получает последний чип у кромки, а прошлые чипы,
      // которые лежат под ним стопкой, прячутся — иначе их края торчат из-под более короткой даты
      markStuck() {
        const scroller = this.$refs.scroller;
        if (!scroller.clientHeight) return;
        const top = scroller.getBoundingClientRect().top + 1;
        const chips = this.$refs.list.querySelectorAll(":scope > .im-day");
        let stuck = null;
        let index = -1;
        if (fromTop(scroller) > 0) {
          for (const chip of chips) {
            if (chip.getBoundingClientRect().top > top) break;
            stuck = chip;
            index++;
          }
        }
        if (stuck === stuckChip) return;
        stuckChip = stuck;
        chips.forEach((chip, i) => {
          chip.classList.toggle("stuck", i === index);
          chip.classList.toggle("past", i < index);
        });
      },
      // на тач-экране наведения нет: панель действий над сообщением открывает тап по нему
      pick(e) {
        if (!matchMedia("(hover: none)").matches || e.target.closest("a, button, input, textarea, label, .voice")) return;
        const msg = e.target.closest(".msg");
        if (picked && picked !== msg) picked.classList.remove("picked");
        picked = msg && msg.classList.toggle("picked") ? msg : null;
      },
      // листает фото той же ленты или панели, откуда открыт снимок, — как в VK
      view(el) {
        const shots = [...el.closest("[data-gallery]").querySelectorAll("[data-full]")];
        window.dispatchEvent(new CustomEvent("im-view", { detail: { shots, i: Math.max(0, shots.indexOf(el)) } }));
      },
      nearBottom() {
        return fromBottom(this.$refs.scroller) < 120;
      },
      scrollBottom(smooth = false) {
        this.$refs.scroller.scrollTo({ top: 0, behavior: smooth ? "smooth" : "auto" });
      },
    };
  });

  Alpine.data("viewer", () => {
    let shots = [];
    let slowTimer = 0;
    let tapTimer = 0;
    // жесты — вне реактивных данных Alpine: pointermove приходит каждый кадр
    const g = { s: 1, x: 0, y: 0, pts: new Map(), start: null, pinch: null, moved: false, lastTap: 0 };
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    return {
      open: false, items: [], i: 0, cur: {}, hi: "", loaded: false, slow: false, chrome: true, zoomed: false,
      show(detail) {
        shots = detail.shots;
        this.items = shots.map(() => 0);
        overlay.open(() => this.hide());
        this.open = true;
        this.chrome = true;
        this.go(detail.i);
      },
      close() { overlay.dismiss(); },
      hide() {
        this.open = false;
        this.hi = "";
        this.cur = {};
        clearTimeout(slowTimer);
        this.reset();
      },
      item(k) {
        const a = shots[k];
        if (!a) return null;
        let sizes = [];
        try { sizes = JSON.parse(a.dataset.sizes || "[]"); } catch (_) {}
        const thumb = a.querySelector("img");
        return { full: a.dataset.full, save: a.dataset.save || "", preview: thumb?.currentSrc || thumb?.src || "", sizes };
      },
      // снимок под ширину экрана, а не оригинал: на телефоне оригинал в 2560 px грузится секунды и греет его
      fit(item, zoomed) {
        const sizes = item.sizes;
        if (!sizes.length) return item.full;
        if (zoomed) return sizes[sizes.length - 1][1];
        const need = window.innerWidth * Math.min(window.devicePixelRatio || 1, 2);
        return (sizes.find(([w]) => w >= need) || sizes[sizes.length - 1])[1];
      },
      go(k) {
        const item = this.item(k);
        if (!item) return;
        this.i = k;
        this.cur = item;
        this.reset();
        const hi = this.fit(item, false);
        this.loaded = hi === this.hi && this.loaded;
        this.slow = false;
        this.hi = hi;
        clearTimeout(slowTimer);
        slowTimer = setTimeout(() => { this.slow = true; }, 300);
        [k + 1, k - 1].forEach((n) => {
          const near = this.item(n);
          if (near) new Image().src = this.fit(near, false);
        });
      },
      step(delta) { this.go(this.i + delta); },
      typing(e) { return ["INPUT", "TEXTAREA"].includes(e.target.tagName); },
      // при приближении снимок подменяется самым крупным: прежний остаётся на экране, пока новый не загрузится
      upgrade() {
        if (g.s <= 1.2 || this.zoomed) return;
        this.zoomed = true;
        const best = this.fit(this.cur, true);
        if (best !== this.hi) this.hi = best;
      },
      apply(animate = false) {
        const shot = this.$refs.shot;
        shot.style.transition = animate ? "transform .2s" : "none";
        shot.style.transform = g.s === 1 && !g.x && !g.y ? "" : `translate3d(${g.x}px, ${g.y}px, 0) scale(${g.s})`;
      },
      reset(animate = false) {
        g.s = 1;
        g.x = 0;
        g.y = 0;
        this.zoomed = false;
        if (this.$refs.shot) this.apply(animate);
      },
      // точка (px, py) экрана остаётся под пальцем или курсором при смене масштаба с from.s на s
      zoomTo(s, px, py, from) {
        const box = this.$refs.stage.getBoundingClientRect();
        const cx = box.left + box.width / 2;
        const cy = box.top + box.height / 2;
        const lx = (from.px - cx - from.x) / from.s;
        const ly = (from.py - cy - from.y) / from.s;
        g.s = Math.min(4, Math.max(1, s));
        g.x = px - cx - lx * g.s;
        g.y = py - cy - ly * g.s;
        if (g.s === 1) { g.x = 0; g.y = 0; }
        this.apply();
        this.upgrade();
      },
      clampPan() {
        const box = this.$refs.stage.getBoundingClientRect();
        const mx = (box.width * (g.s - 1)) / 2;
        const my = (box.height * (g.s - 1)) / 2;
        g.x = Math.min(mx, Math.max(-mx, g.x));
        g.y = Math.min(my, Math.max(-my, g.y));
        this.apply(true);
      },
      down(e) {
        if (e.button) return;
        e.currentTarget.setPointerCapture?.(e.pointerId);
        g.pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (g.pts.size === 1) {
          g.start = { x: e.clientX, y: e.clientY, gx: g.x, gy: g.y };
          g.moved = false;
        } else if (g.pts.size === 2) {
          const [a, b] = [...g.pts.values()];
          g.pinch = { d: dist(a, b) || 1, s: g.s, x: g.x, y: g.y, px: (a.x + b.x) / 2, py: (a.y + b.y) / 2 };
          g.moved = true;
        }
      },
      move(e) {
        if (!g.pts.has(e.pointerId)) return;
        g.pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (g.pinch && g.pts.size >= 2) {
          const [a, b] = [...g.pts.values()];
          this.zoomTo(g.pinch.s * (dist(a, b) / g.pinch.d), (a.x + b.x) / 2, (a.y + b.y) / 2, g.pinch);
          return;
        }
        const dx = e.clientX - g.start.x;
        const dy = e.clientY - g.start.y;
        if (Math.abs(dx) > 6 || Math.abs(dy) > 6) g.moved = true;
        if (!g.moved) return;
        if (g.s > 1) {
          g.x = g.start.gx + dx;
          g.y = g.start.gy + dy;
        } else if (Math.abs(dx) >= Math.abs(dy)) {
          g.x = dx;
          g.y = 0;
        } else {
          g.x = 0;
          g.y = Math.max(0, dy);
        }
        this.apply();
      },
      up(e) {
        if (!g.pts.has(e.pointerId)) return;
        g.pts.delete(e.pointerId);
        if (g.pts.size === 1) {
          const [p] = g.pts.values();
          g.start = { x: p.x, y: p.y, gx: g.x, gy: g.y };
          g.pinch = null;
          return;
        }
        if (g.pts.size) return;
        const wasPinch = !!g.pinch;
        g.pinch = null;
        if (e.type === "pointercancel") { if (g.s === 1) this.reset(true); return; }
        if (!g.moved) { this.tap(e); return; }
        if (g.s > 1 || wasPinch) { if (g.s > 1) this.clampPan(); else this.reset(true); return; }
        const dx = e.clientX - g.start.x;
        const dy = e.clientY - g.start.y;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) && shots[this.i + (dx < 0 ? 1 : -1)]) this.step(dx < 0 ? 1 : -1);
        else if (dy > 100 && dy > Math.abs(dx)) this.close();
        else this.reset(true);
      },
      // мышь: щелчок мимо снимка закрывает, по снимку — следующий, приближает колесо; палец: тап прячет панели,
      // двойной тап приближает
      tap(e) {
        if (e.pointerType === "mouse") {
          if (!this.onImage(e)) this.close();
          else if (g.s === 1 && shots[this.i + 1]) this.step(1);
          return;
        }
        clearTimeout(tapTimer);
        if (Date.now() - g.lastTap < 300) {
          g.lastTap = 0;
          this.toggleZoom(e.clientX, e.clientY);
          return;
        }
        g.lastTap = Date.now();
        tapTimer = setTimeout(() => { this.chrome = !this.chrome; }, 300);
      },
      onImage(e) {
        const img = this.$refs.lo;
        const box = img.getBoundingClientRect();
        const ratio = img.naturalWidth && img.naturalHeight ? img.naturalWidth / img.naturalHeight : box.width / box.height;
        let w = box.width;
        let h = w / ratio;
        if (h > box.height) { h = box.height; w = h * ratio; }
        const left = box.left + (box.width - w) / 2;
        const top = box.top + (box.height - h) / 2;
        return e.clientX >= left && e.clientX <= left + w && e.clientY >= top && e.clientY <= top + h;
      },
      toggleZoom(px, py) {
        if (g.s > 1) { this.reset(true); return; }
        this.zoomTo(2.5, px, py, { s: g.s, x: g.x, y: g.y, px, py });
        this.apply(true);
      },
      wheel(e) {
        const s = g.s * Math.exp(-e.deltaY * 0.002);
        this.zoomTo(s, e.clientX, e.clientY, { s: g.s, x: g.x, y: g.y, px: e.clientX, py: e.clientY });
      },
    };
  });

  Alpine.data("player", () => ({
    open: false, round: false,
    show(detail) {
      this.round = !!detail?.round;
      document.getElementById("player-slot").innerHTML = '<span class="spin" aria-hidden="true"></span>';
      overlay.open(() => this.hide());
      this.open = true;
    },
    close() { overlay.dismiss(); },
    // iframe убирается целиком: скрытый плеер VK продолжал бы играть
    hide() {
      this.open = false;
      document.getElementById("player-slot").innerHTML = "";
    },
  }));

  Alpine.data("voice", (url, duration) => ({
    playing: false, loading: false, pos: 0, open: false, audio: null,
    get pct() { return duration ? Math.min(100, (this.pos / duration) * 100) : 0; },
    get time() { return mmss(this.playing || this.pos ? this.pos : duration); },
    ensure() {
      if (this.audio) return this.audio;
      const audio = this.audio = new Audio();
      audio.preload = "auto";
      audio.addEventListener("timeupdate", () => { this.pos = audio.currentTime; });
      audio.addEventListener("waiting", () => { this.loading = true; });
      audio.addEventListener("playing", () => { this.loading = false; });
      audio.addEventListener("ended", () => { this.playing = false; this.pos = 0; });
      audio.addEventListener("error", () => {
        this.playing = false;
        this.loading = false;
        // следующий щелчок попробует заново, а не будет молча жать на сломанный плеер
        this.audio = null;
        toast("Не удалось загрузить голосовое", "bad");
      });
      audio.src = url;
      return audio;
    },
    toggle() { this.playing ? this.pause() : this.play(); },
    play() {
      const audio = this.ensure();
      window.dispatchEvent(new CustomEvent("im-voice-play", { detail: this.$el }));
      this.playing = true;
      if (audio.readyState < 3) this.loading = true;
      audio.play().catch(() => {
        if (this.audio !== audio || audio.error) return;
        this.playing = false;
        this.loading = false;
      });
    },
    pause() {
      this.audio?.pause();
      this.playing = false;
      this.loading = false;
    },
    seek(e) {
      const box = e.currentTarget.getBoundingClientRect();
      const at = Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)) * duration;
      const audio = this.ensure();
      this.pos = at;
      if (audio.readyState >= 1) audio.currentTime = at;
      else audio.addEventListener("loadedmetadata", () => { audio.currentTime = at; }, { once: true });
      if (!this.playing) this.play();
    },
  }));

  Alpine.data("composer", () => ({
    text: "", reply: null, file: null, photos: [], draft: null, stash: null,
    destroy() { [...this.photos, ...(this.stash?.photos || [])].forEach((p) => URL.revokeObjectURL(p.url)); },
    get ready() { return this.text.trim().length > 0 || !!this.file || this.photos.length > 0; },
    get size() {
      if (!this.file) return "";
      const kb = this.file.size / 1024;
      return kb < 1024 ? Math.ceil(kb) + " КБ" : (kb / 1024).toFixed(1) + " МБ";
    },
    pick() {
      const f = this.$refs.f.files[0];
      this.file = f || null;
      if (f && !/\.(ogg|mp3)$/i.test(f.name)) {
        toast("Нужен .ogg или .mp3", "bad");
        this.clearFile();
      }
    },
    clearFile() { this.file = null; this.$refs.f.value = ""; },
    addPhotos(files) {
      const images = [...files].filter((f) => /^image\/(jpeg|png|gif|webp)$/.test(f.type));
      if (images.length < files.length) toast("Фото нужно в JPEG, PNG, GIF или WebP", "bad");
      const room = 10 - this.photos.length;
      if (images.length > room) toast("За раз не больше 10 фото", "bad");
      this.photos.push(...images.slice(0, Math.max(0, room)).map((file) => ({ file, url: URL.createObjectURL(file) })));
      this.syncPhotos();
    },
    dropPhoto(i) {
      URL.revokeObjectURL(this.photos[i].url);
      this.photos.splice(i, 1);
      this.syncPhotos();
    },
    // форма отправляет то, что лежит в input, — список превью переносим туда через DataTransfer
    syncPhotos() {
      const dt = new DataTransfer();
      this.photos.forEach((p) => dt.items.add(p.file));
      this.$refs.p.files = dt.files;
    },
    // Office и таблицы кладут рядом с текстом его картинку: такую вставку оставляем текстом
    paste(e) {
      const files = [...(e.clipboardData?.files || [])];
      if (!files.length || e.clipboardData.getData("text/plain")) return;
      e.preventDefault();
      this.addPhotos(files);
    },
    grow() { const t = this.$refs.t; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 216) + "px"; },
    quote(d) { this.reply = d; this.$refs.t.focus(); },
    // тело запроса уже собрано: композер очищается сразу, а в ленте встаёт черновик до ответа сервера
    sending() {
      this.stash = { text: this.text, reply: this.reply, photos: this.photos, file: this.file };
      this.draft = this.draftBubble(this.text, this.photos, this.file);
      const list = document.getElementById("messages");
      list.append(this.draft);
      list.closest(".im-scroll").scrollTop = 0;
      this.text = "";
      this.reply = null;
      this.photos = [];
      this.$refs.p.value = "";
      this.clearFile();
      this.$nextTick(() => this.grow());
    },
    sent(ok) {
      this.draft?.remove();
      this.draft = null;
      const stash = this.stash;
      this.stash = null;
      if (!stash) return;
      if (ok) {
        stash.photos.forEach((p) => URL.revokeObjectURL(p.url));
        document.getElementById("composer-error").textContent = "";
        return;
      }
      // за время запроса могли набрать новое: неотправленное встаёт перед ним, а не вместо
      this.text = [stash.text, this.text].filter(Boolean).join("\n");
      this.reply = this.reply || stash.reply;
      const photos = [...stash.photos, ...this.photos];
      photos.slice(10).forEach((p) => URL.revokeObjectURL(p.url));
      this.photos = photos.slice(0, 10);
      this.syncPhotos();
      if (stash.file && !this.file) {
        const dt = new DataTransfer();
        dt.items.add(stash.file);
        this.$refs.f.files = dt.files;
        this.file = stash.file;
      }
      this.$nextTick(() => this.grow());
    },
    draftBubble(text, photos, file) {
      const el = document.createElement("article");
      el.className = "msg out draft";
      const body = document.createElement("p");
      body.className = "text";
      body.textContent = text;
      const note = document.createElement("small");
      note.className = "draft-note";
      const parts = [photos.length && `фото: ${photos.length}`, file && "голосовое"].filter(Boolean);
      note.textContent = ["Отправка…", ...parts].join(" · ");
      if (text) el.append(body);
      el.append(note);
      return el;
    },
  }));
});
