// Loading state for synchronous exam generation. No fake percentage.
document.addEventListener("DOMContentLoaded", () => {
  const forms = [...document.querySelectorAll(".generation-form")];
  const state = document.getElementById("generation-state");
  const message = document.getElementById("generation-message");
  const elapsed = document.getElementById("generation-elapsed");
  if (!forms.length || !state || !message || !elapsed) return;

  let startedAt = 0;
  let timer = null;
  let busy = false;
  forms.forEach((form) => form.addEventListener("submit", () => {
    if (busy) return;
    busy = true;
    startedAt = Date.now();
    state.hidden = false;
    const buttons = document.querySelectorAll(".generation-form button");
    buttons.forEach((button) => { button.disabled = true; });
    const selected = form.querySelector("input[name='mode']")?.value;
    message.textContent = selected === "mini" ? "Đang tạo đề mini…" : "Đang tạo đề đầy đủ…";
    const update = () => {
      const seconds = Math.floor((Date.now() - startedAt) / 1000);
      elapsed.textContent = seconds + (seconds === 1 ? " giây" : " giây");
      if (seconds > 0 && seconds % 5 === 0) {
        message.textContent = `Đang tạo đề… đã chờ ${seconds} giây`;
      }
    };
    update();
    timer = setInterval(update, 1000);
  }));
  window.addEventListener("pagehide", () => { if (timer) clearInterval(timer); });
});
