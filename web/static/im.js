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
    peerId, outRead, fromBottom: 0, stick: true,
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
        if (target.id === "messages" && this.stick) this.scrollBottom();
        if (target.classList.contains("im-more")) this.$refs.list.scrollTop = this.$refs.list.scrollHeight - this.fromBottom;
      });
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom() { this.$refs.list.scrollTop = this.$refs.list.scrollHeight; },
  }));
});
