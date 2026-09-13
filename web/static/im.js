function readOnOpen() {
  try {
    return localStorage.getItem("im.readOnOpen") !== "off";
  } catch {
    return true;
  }
}

document.addEventListener("alpine:init", () => {
  Alpine.data("im", (sel) => ({
    sel, pane: sel ? "chat" : "list", filter: "", unreadOnly: false,
    init() {
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
    },
    open(id) { this.sel = id; this.pane = "chat"; },
    matches(li) {
      const byTitle = !this.filter || li.dataset.title.includes(this.filter.toLowerCase());
      const byUnread = !this.unreadOnly || Number(li.dataset.unread) > 0;
      return byTitle && byUnread;
    },
  }));

  Alpine.data("chat", (peerId, outRead) => ({
    peerId, outRead, fromBottom: 0, stick: true, readUpTo: 0, settling: false, panel: false,
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
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        const target = e.detail.target;
        if (target.id === "messages") this.settleMessages();
        if (target.classList.contains("im-more")) this.$refs.list.scrollTop = this.$refs.list.scrollHeight - this.fromBottom;
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
        if (this.stick) this.scrollBottom();
        this.markRead();
      });
    },
    // поллинг, ушедший до отправки, может вернуть уже вставленное отправкой сообщение
    dedupe() {
      const seen = new Set();
      this.$refs.list.querySelectorAll("[data-id]").forEach((el) => {
        if (seen.has(el.dataset.id)) el.remove();
        else seen.add(el.dataset.id);
      });
    },
    markRead() {
      const incoming = [...this.$refs.list.querySelectorAll(".msg:not(.out)")].map((el) => Number(el.dataset.id));
      const last = Math.max(0, ...incoming);
      if (last <= this.readUpTo || document.visibilityState !== "visible" || !readOnOpen()) return;
      this.readUpTo = last;
      fetch(`/im/${this.peerId}/read`, { method: "POST", headers: { "HX-Request": "true" } });
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom() { this.$refs.list.scrollTop = this.$refs.list.scrollHeight; },
  }));

  Alpine.data("composer", () => ({
    text: "", reply: null, file: null,
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
    draft(t) {
      this.text = t;
      this.$nextTick(() => { this.grow(); this.$refs.t.focus(); });
    },
    grow() { const t = this.$refs.t; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; },
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
