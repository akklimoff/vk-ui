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

// пока открыт поток событий бота, частый поллинг не нужен: новое приходит сигналом, редкий тик — подстраховка
function imLive() {
  return window.imEvents?.readyState === EventSource.OPEN;
}

function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

document.addEventListener("alpine:init", () => {
  Alpine.data("im", (sel, markRead) => ({
    sel, markRead, pane: sel ? "chat" : "list", filter: "", unreadOnly: false, loading: false,
    question: "", confirmed: null, warmTimer: 0, warmedAt: {}, warming: false, deduping: false, edge: null,
    init() {
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
      this.$el.addEventListener("im-close", () => this.close());
      this.listen();
      // запрос открытия чата уходит от ссылки в списке слева, поэтому слушаем весь мессенджер, а не колонку чата
      this.$el.addEventListener("htmx:beforeRequest", (e) => { if (e.detail.target.id === "chat") this.loading = true; });
      this.$el.addEventListener("htmx:afterRequest", (e) => {
        if (e.detail.target.id === "chat") this.loading = false;
        const version = e.detail.xhr?.getResponseHeader("X-Dialogs-Version");
        if (e.detail.elt.id === "dialog-list" && version) e.detail.elt.dataset.version = version;
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        if (e.detail.target.id === "search-results") this.dropShownHits(e.detail.target);
        // пока грузилась следующая страница, новое сообщение могло поднять диалог и сдвинуть offset;
        // после outerHTML событие приходит от каждого вставленного ряда — чистим один раз
        if (e.detail.pathInfo?.requestPath?.startsWith("/im/dialogs/more") && !this.deduping) {
          this.deduping = true;
          queueMicrotask(() => { this.deduping = false; this.dropRepeatedDialogs(); });
        }
      });
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
      events.addEventListener("changed", () => {
        if (document.getElementById("chat-poll")) htmx.trigger("#chat-poll", "poke");
        htmx.trigger("#dialog-list", "poke");
      });
      // 502 во время деплоя или редирект на /login браузер не переподключает сам: поток закрыт навсегда
      events.addEventListener("error", () => {
        if (events.readyState !== EventSource.CLOSED) return;
        window.imEvents = null;
        setTimeout(() => this.listen(Math.min(delay * 2, 60000)), delay);
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
    // наведение на диалог заранее просит у VK его историю: клик откроет чат без ожидания
    // по одному прогреву за раз: VK пропускает ~3 запроса в секунду, и очередь прогревов задержала бы сам клик
    warm(id) {
      clearTimeout(this.warmTimer);
      if (id === this.sel || Date.now() - (this.warmedAt[id] || 0) < 10000) return;
      this.warmTimer = setTimeout(() => {
        if (id === this.sel || this.warming) return;
        this.warmedAt[id] = Date.now();
        this.warming = true;
        fetch(`/im/${id}/warm`, { method: "POST", headers: { "HX-Request": "true" } })
          .catch(() => {}).finally(() => { this.warming = false; });
      }, 250);
    },
    unwarm() { clearTimeout(this.warmTimer); },
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

  Alpine.data("chat", (peerId, outRead, unread) => ({
    peerId, outRead, unread, fromBottom: 0, stick: true, readUpTo: 0, settling: false, panel: null, viewer: null,
    atBottom: true, pending: 0, before: 0, raf: 0, olderSwap: false, swipeFrom: 0, swiped: false,
    init() {
      // синхронно, а не в $nextTick: иначе IntersectionObserver успевает увидеть сентинел
      // вверху ещё не прокрученного списка и зря грузит страницу старых
      const list = this.$el.querySelector(".im-messages");
      list.scrollTop = list.scrollHeight;
      // измеряем до свопа: после вставки старых рядов над экраном браузер оставляет scrollTop
      // (у верхнего края scroll anchoring не срабатывает), и видимый сентинел тянул бы всю историю
      this.$el.addEventListener("htmx:beforeSwap", (e) => {
        const el = this.$refs.list;
        this.fromBottom = el.scrollHeight - el.scrollTop;
        this.stick = this.nearBottom();
        this.before = Number(lastRendered().after);
        // сентинел есть и у панели фотографий: скролл ленты правится только за её собственные старые страницы
        this.olderSwap = e.detail.target.classList.contains("im-more") && el.contains(e.detail.target);
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        const target = e.detail.target;
        if (target.id === "messages") this.settleMessages();
        if (this.olderSwap) {
          this.dedupeDays();
          this.$refs.list.scrollTop = this.$refs.list.scrollHeight - this.fromBottom;
          this.markStuck();
        }
      });
      this.$nextTick(() => this.noteRead());
    },
    // afterSwap приходит на каждый вставленный элемент — разбираем ленту один раз за своп
    settleMessages() {
      if (this.settling) return;
      this.settling = true;
      queueMicrotask(() => {
        this.settling = false;
        this.dedupe();
        if (this.$refs.list.querySelector("[data-id]")) this.$refs.list.querySelector(".im-empty")?.remove();
        if (this.stick) this.scrollBottom();
        else this.pending += this.arrived();
        this.noteRead();
        this.markStuck();
      });
    },
    // счётчик на кнопке «вниз»: входящие, вставленные поллингом, пока лента отмотана вверх
    arrived() {
      return [...this.$refs.list.querySelectorAll(".msg:not(.out)")].filter((el) => Number(el.dataset.id) > this.before).length;
    },
    // поллинг, ушедший до отправки, может вернуть уже вставленное отправкой сообщение
    dedupe() {
      const seen = new Set();
      this.$refs.list.querySelectorAll("[data-id]").forEach((el) => {
        if (seen.has(el.dataset.id)) el.remove();
        else seen.add(el.dataset.id);
      });
    },
    // страница старых заканчивается чипом того же дня, с которого начиналась лента
    dedupeDays() {
      let prev = null;
      this.$refs.list.querySelectorAll(".im-day").forEach((chip) => {
        if (chip.textContent === prev) chip.remove();
        else prev = chip.textContent;
      });
    },
    lastIncoming() {
      return Math.max(0, ...[...this.$refs.list.querySelectorAll(".msg:not(.out)")].map((el) => Number(el.dataset.id)));
    },
    // markRead — настройка из runtime.json: выключена — открытый чат не отмечается прочитанным
    noteRead() {
      const last = this.lastIncoming();
      if (last <= this.readUpTo || document.visibilityState !== "visible" || !this.markRead) return;
      this.readNow(last);
    },
    readNow(last = this.lastIncoming()) {
      this.readUpTo = last;
      fetch(`/im/${this.peerId}/read`, { method: "POST", headers: { "HX-Request": "true" } })
        .then((r) => { if (r.ok) this.unread = 0; });
    },
    onScroll() {
      if (this.raf) return;
      this.raf = requestAnimationFrame(() => {
        this.raf = 0;
        this.atBottom = this.nearBottom();
        if (this.atBottom) this.pending = 0;
        this.markStuck();
      });
    },
    // sticky сам не сообщает, что упёрся в край: подложку получает последний чип выше кромки прокрутки
    markStuck() {
      const list = this.$refs.list;
      let stuck = null;
      list.querySelectorAll(".im-day").forEach((chip) => {
        chip.classList.remove("stuck");
        if (list.scrollTop > 0 && chip.offsetTop <= list.scrollTop) stuck = chip;
      });
      stuck?.classList.add("stuck");
    },
    // листает фото той же ленты или панели, откуда открыт снимок, — как в VK
    view(el) {
      const items = [...el.closest("[data-gallery]").querySelectorAll("[data-full]")];
      this.viewer = { urls: items.map((a) => a.dataset.full), i: Math.max(0, items.indexOf(el)) };
    },
    get shown() { return this.viewer ? this.viewer.urls[this.viewer.i] : ""; },
    step(delta) {
      if (!this.viewer) return;
      const i = this.viewer.i + delta;
      if (i < 0 || i >= this.viewer.urls.length) return;
      this.viewer.i = i;
      const next = this.viewer.urls[i + delta];
      if (next) new Image().src = next;
    },
    typing(e) { return ["INPUT", "TEXTAREA"].includes(e.target.tagName); },
    // после свайпа по снимку браузер шлёт ещё и click — без флага он перелистнул бы второй раз
    swipe(x) {
      const dx = x - this.swipeFrom;
      this.swiped = Math.abs(dx) > 50;
      if (this.swiped) this.step(dx < 0 ? 1 : -1);
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom(smooth = false) {
      this.$refs.list.scrollTo({ top: this.$refs.list.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    },
  }));

  Alpine.data("voice", (url, duration) => ({
    playing: false, pos: 0, open: false, audio: null,
    get pct() { return duration ? Math.min(100, (this.pos / duration) * 100) : 0; },
    get time() { return mmss(this.playing || this.pos ? this.pos : duration); },
    ensure() {
      if (this.audio) return;
      this.audio = new Audio(url);
      this.audio.preload = "none";
      this.audio.addEventListener("timeupdate", () => { this.pos = this.audio.currentTime; });
      this.audio.addEventListener("ended", () => { this.playing = false; this.pos = 0; });
      this.audio.addEventListener("error", () => { this.playing = false; toast("Не удалось загрузить голосовое", "bad"); });
    },
    toggle() { this.playing ? this.pause() : this.play(); },
    play() {
      this.ensure();
      window.dispatchEvent(new CustomEvent("im-voice-play", { detail: this.$el }));
      this.audio.play();
      this.playing = true;
    },
    pause() { this.audio?.pause(); this.playing = false; },
    seek(e) {
      const box = e.currentTarget.getBoundingClientRect();
      this.ensure();
      this.audio.currentTime = this.pos = ((e.clientX - box.left) / box.width) * duration;
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
      list.scrollTop = list.scrollHeight;
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
