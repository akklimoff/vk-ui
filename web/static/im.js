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
    peerId, outRead,
    init() {
      this.$nextTick(() => this.scrollBottom());
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        if (e.detail.target.id === "messages" || e.detail.target.classList.contains("im-more")) this.keepScroll(e);
      });
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom() { this.$refs.list.scrollTop = this.$refs.list.scrollHeight; },
    keepScroll(e) { if (this.nearBottom()) this.scrollBottom(); },
  }));
});
