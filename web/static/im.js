function readOnOpen() {
  try {
    return localStorage.getItem("im.readOnOpen") !== "off";
  } catch {
    return true;
  }
}

// для hx-vals поллера и отправки: курсор — последний отрисованный ряд, а не число с сервера,
// так запоздавший ответ не сдвинет его ни назад, ни вперёд; с этим же рядом сервер склеивает серию и день
function lastRendered() {
  let row = document.getElementById("messages")?.lastElementChild;
  while (row && !row.dataset.ts) row = row.previousElementSibling;
  return row ? { after: row.dataset.id, last_from: row.dataset.from, last_ts: row.dataset.ts } : { after: 0 };
}

function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

document.addEventListener("alpine:init", () => {
  Alpine.data("im", (sel) => ({
    sel, pane: sel ? "chat" : "list", filter: "", unreadOnly: false,
    init() {
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
      this.$el.addEventListener("im-close", () => this.close());
    },
    open(id) { this.sel = id; this.pane = "chat"; },
    close() {
      this.sel = null;
      this.pane = "list";
      document.getElementById("chat").innerHTML = document.getElementById("im-empty").innerHTML;
      history.pushState({}, "", "/im");
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

  Alpine.data("chat", (peerId, outRead) => ({
    peerId, outRead, fromBottom: 0, stick: true, readUpTo: 0, settling: false, panel: false, viewer: null,
    atBottom: true, pending: 0, before: 0, raf: 0,
    init() {
      // синхронно, а не в $nextTick: иначе IntersectionObserver успевает увидеть сентинел
      // вверху ещё не прокрученного списка и зря грузит страницу старых
      const list = this.$el.querySelector(".im-messages");
      list.scrollTop = list.scrollHeight;
      // измеряем до свопа: после вставки старых рядов над экраном браузер оставляет scrollTop
      // (у верхнего края scroll anchoring не срабатывает), и видимый сентинел тянул бы всю историю
      this.$el.addEventListener("htmx:beforeSwap", () => {
        const el = this.$refs.list;
        this.fromBottom = el.scrollHeight - el.scrollTop;
        this.stick = this.nearBottom();
        this.before = Number(lastRendered().after);
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        const target = e.detail.target;
        if (target.id === "messages") this.settleMessages();
        if (target.classList.contains("im-more")) {
          this.dedupeDays();
          this.$refs.list.scrollTop = this.$refs.list.scrollHeight - this.fromBottom;
          this.markStuck();
        }
      });
      this.$nextTick(() => this.markRead());
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
        this.markRead();
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
    markRead() {
      const incoming = [...this.$refs.list.querySelectorAll(".msg:not(.out)")].map((el) => Number(el.dataset.id));
      const last = Math.max(0, ...incoming);
      if (last <= this.readUpTo || document.visibilityState !== "visible" || !readOnOpen()) return;
      this.readUpTo = last;
      fetch(`/im/${this.peerId}/read`, { method: "POST", headers: { "HX-Request": "true" } });
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

  Alpine.data("readMark", () => ({
    silent: !readOnOpen(),
    toggle(on) {
      this.silent = on;
      try {
        localStorage.setItem("im.readOnOpen", on ? "off" : "on");
      } catch {}
    },
  }));

  Alpine.data("composer", () => ({
    text: "", reply: null, file: null,
    get ready() { return this.text.trim().length > 0 || !!this.file; },
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
    grow() { const t = this.$refs.t; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 216) + "px"; },
    quote(d) { this.reply = d; this.$refs.t.focus(); },
    reset() {
      this.text = "";
      this.reply = null;
      this.clearFile();
      document.getElementById("composer-error").textContent = "";
      this.$nextTick(() => this.grow());
    },
  }));
});
