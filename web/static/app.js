document.addEventListener("alpine:init", () => {
  Alpine.store("toasts", {
    items: [],
    seq: 0,
    show(text, kind = "ok") {
      const id = ++this.seq;
      this.items.push({ id, text, kind });
      setTimeout(() => this.dismiss(id), kind === "bad" ? 6000 : 2500);
    },
    dismiss(id) {
      this.items = this.items.filter((t) => t.id !== id);
    },
  });

  const grow = (el) => {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + 2 + "px";
  };

  Alpine.data("autogrow", () => ({
    init() { grow(this.$el); },
    grow() { grow(this.$el); },
  }));

  Alpine.data("editor", () => ({
    n: 0,
    init() { this.input(); },
    input() {
      this.n = this.$refs.t.value.length;
      grow(this.$refs.t);
    },
  }));
});

function toast(text, kind) {
  if (window.Alpine) Alpine.store("toasts").show(text, kind);
}

document.addEventListener("toast", (e) => {
  const d = e.detail;
  d.text ? toast(d.text, d.kind) : toast(d.value);
});

document.addEventListener("htmx:responseError", (e) => {
  const xhr = e.detail.xhr;
  let text = xhr.responseText;
  try {
    text = JSON.parse(text).detail || text;
  } catch (_) {}
  toast(`Ошибка ${xhr.status}: ${text}`.slice(0, 300), "bad");
});

document.addEventListener("htmx:sendError", () => toast("Нет связи с сервером", "bad"));

function localTime(ts) {
  return new Date(Number(ts) * 1000).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}
