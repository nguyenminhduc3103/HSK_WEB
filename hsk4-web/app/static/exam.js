// Trang làm đề: đồng hồ + chip điền từ + ghép cụm + autosave nháp.
document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.classList.remove("no-js");
  document.documentElement.classList.add("js");
  const submitBar = document.getElementById("submit-bar");
  if (submitBar) submitBar.hidden = false;

  const body = document.body;
  const examId = body.dataset.examId;
  const nQuestions = parseInt(body.dataset.nQuestions || "0", 10);
  const form = document.getElementById("exam-form");
  const saveStatusText = document.getElementById("save-status-text");
  const answeredCount = document.getElementById("answered-count");
  const timerEl = document.getElementById("timer");
  const timerPill = document.getElementById("timer-pill");
  const timerHint = document.getElementById("timer-hint");

  // ---- Đồng hồ tham khảo (không blocking) + cảnh báo gần hết giờ ----
  const REF_MIN = 65; // Đọc 40 + Viết 25
  if (timerEl) {
    let s = 0;
    const tick = () => {
      s += 1;
      timerEl.textContent =
        String(Math.floor(s / 60)).padStart(2, "0") + ":" +
        String(s % 60).padStart(2, "0");
      if (s === REF_MIN * 60 && timerPill) {
        timerPill.classList.add("nearly");
        if (timerHint) timerHint.textContent = "— đã qua mốc tham khảo 65 phút";
      }
    };
    setInterval(tick, 1000);
  }

  // ---- Đọc 1: chip chọn từ → điền vào câu ----
  // Mỗi câu (.fillq) có 1 slot; bấm câu để chọn (highlight), bấm chip để gán chữ.
  // Hidden input name="a_<qid>" lưu LABEL (A/B/...) — đúng hợp đồng chấm.
  const fillGroups = document.querySelectorAll(".choices");
  let activeSlot = null; // .fillq đang chọn

  // Khôi phục hiển thị chữ (draft lưu label "A" → tra chữ từ word bank)
  document.querySelectorAll(".choices").forEach((groupEl) => {
    const words = {};
    groupEl.querySelectorAll(".choice-btn").forEach((c) => { words[c.dataset.choice] = c.dataset.word; });
    // fillq nằm trong cùng .group với .choices
    groupEl.closest(".group")?.querySelectorAll(".fillq").forEach((slot) => {
      const input = slot.querySelector("input[name^='a_']");
      const lab = input.value;
      if (lab && words[lab]) {
        const blank = slot.querySelector(".blank");
        blank.textContent = words[lab];
        blank.classList.add("filled");
        slot.classList.add("answered");
        slot.dataset.prevChoice = lab;
        const chip = groupEl.querySelector(`.choice-btn[data-choice="${lab}"]`);
        if (chip) chip.classList.add("in-use");
      }
    });
  });

  document.querySelectorAll(".fillq").forEach((slot) => {
    slot.addEventListener("click", () => {
      document.querySelectorAll(".fillq.active").forEach((o) => o.classList.remove("active"));
      slot.classList.add("active");
      activeSlot = slot;
    });
  });

  fillGroups.forEach((groupEl) => {
    groupEl.querySelectorAll(".choice-btn").forEach((chip) => {
      chip.addEventListener("click", () => {
        let target = activeSlot;
        // Không chọn câu nào: gán cho câu chưa điền gần nhất trong nhóm này
        if (!target) {
          const unfilled = [...(groupEl.closest(".group") || groupEl.parentElement).querySelectorAll(".fillq")];
          target = unfilled.find((o) => !o.querySelector("input").value) || unfilled[0];
        }
        if (!target) return;
        const input = target.querySelector("input[name^='a_']");
        input.value = chip.dataset.choice; // label "A"
        target.querySelector(".blank").textContent = chip.dataset.word;
        target.querySelector(".blank").classList.add("filled");
        target.classList.add("answered");
        markChoiceUsed(groupEl, chip, target);
        updateProgress();
        scheduleSave();
      });
    });
  });

  function markChoiceUsed(groupEl, chip, target) {
    // chip dùng cho câu khác → gỡ; dùng cho câu này → giữ
    groupEl.querySelectorAll(".choice-btn").forEach((c) => c.classList.remove("in-use"));
    chip.classList.add("in-use");
    // giải phóng chữ đang gán cho target trước đó (nếu có)
    const prev = target.dataset.prevChoice;
    if (prev && prev !== chip.dataset.choice) {
      const other = groupEl.querySelector(`.choice-btn[data-choice="${prev}"]`);
      if (other) other.classList.remove("in-use");
    }
    target.dataset.prevChoice = chip.dataset.choice;
  }

  // ---- Viết 1: ghép cụm ----
  document.querySelectorAll(".build").forEach((box) => {
    const answer = box.querySelector("[data-answer]");
    const chunks = [...box.querySelectorAll(".chunk")];
    const hidden = box.querySelector("input[type=hidden]");
    // khôi phục nháp: parse "c1|c2" và đánh dấu chunk đã dùng
    let picked = hidden.value ? hidden.value.split("|").filter(Boolean) : [];
    answer.textContent = picked.join(" ");
    chunks.forEach((c) => c.classList.toggle("used", picked.includes(c.dataset.chunk)));

    const sync = () => {
      answer.textContent = picked.join(" ");
      chunks.forEach((c) => c.classList.toggle("used", picked.includes(c.dataset.chunk)));
      hidden.value = picked.join("|");
      updateProgress();
      scheduleSave();
    };

    chunks.forEach((c) => c.addEventListener("click", () => {
      const v = c.dataset.chunk;
      if (picked.includes(v)) picked = picked.filter((x) => x !== v);
      else picked.push(v);
      sync();
    }));

    box.querySelector("[data-clear]").addEventListener("click", () => {
      picked = [];
      sync();
    });
  });

  // ---- Các field thường: input/textarea/radio → progress + autosave ----
  form.addEventListener("input", (e) => {
    if (e.target.matches("input, textarea")) {
      updateProgress();
      scheduleSave();
    }
  });
  form.addEventListener("change", (e) => {
    if (e.target.type === "radio") {
      updateProgress();
      scheduleSave();
    }
  });

  // ---- Bộ đếm ký tự (Viết 2) ----
  form.querySelectorAll("textarea[name^='a_']").forEach((ta) => {
    const counter = document.querySelector(`.char-count[data-count-for="${ta.name.slice(2)}"]`);
    const refresh = () => { if (counter) counter.textContent = ta.value.length + " ký tự"; };
    ta.addEventListener("input", refresh);
    refresh();
  });

  // ---- Progress đã trả lời ----
  function countAnswered() {
    let n = 0;
    form.querySelectorAll("input[name^='a_']").forEach((inp) => {
      if (inp.type === "hidden") {
        const box = inp.closest(".build");
        if (box && inp.value) n += 1; // build_sentence
        // fill_blank: hidden trong .fillslot được đếm ở bên dưới
      } else if (inp.type === "radio") {
        if (inp.checked) n += 1;
      } else if (inp.type === "text") {
        if (inp.value.trim()) n += 1;
      }
    });
    form.querySelectorAll("textarea[name^='a_']").forEach((ta) => {
      if (ta.value.trim()) n += 1;
    });
    form.querySelectorAll(".fillslot").forEach((slotEl) => {
      if (slotEl.querySelector("input").value) n += 1;
    });
    return n;
  }

  function updateProgress() {
    if (!answeredCount) return;
    const n = countAnswered();
    answeredCount.textContent = `Đã trả lời ${n}/${nQuestions}`;
  }
  updateProgress();

  // ---- Autosave nháp về server (debounce 1.5s) ----
  let saveTimer = null;
  let saving = false;

  function collectAnswers() {
    const answers = {};
    form.querySelectorAll("input[name^='a_']").forEach((inp) => {
      if (inp.type === "radio") {
        if (inp.checked) answers[inp.name] = inp.value;
        else if (answers[inp.name] === undefined) answers[inp.name] = "";
        return;
      }
      answers[inp.name] = inp.value;
    });
    form.querySelectorAll("textarea[name^='a_']").forEach((ta) => {
      answers[ta.name] = ta.value;
    });
    // key thành question id
    const qids = {};
    Object.entries(answers).forEach(([k, v]) => { qids[k.slice(2)] = v; });
    return qids;
  }

  function setSaveState(state, text) {
    if (!saveStatusText) return;
    saveStatusText.textContent = text;
    const dot = document.querySelector(".save-dot");
    if (dot) dot.dataset.state = state;
  }

  async function doSave() {
    if (saving) return;
    saving = true;
    setSaveState("saving", "Đang lưu…");
    try {
      const resp = await fetch(`/exams/${examId}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: collectAnswers() }),
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json().catch(() => ({}));
      const t = new Date((data.saved_at ? new Date(data.saved_at) : new Date())).toLocaleTimeString(
        "vi-VN", { hour: "2-digit", minute: "2-digit" });
      setSaveState("saved", "Đã lưu lúc " + t);
    } catch (err) {
      setSaveState("error", "Lưu thất bại — sẽ thử lại khi bạn sửa bài");
    } finally {
      saving = false;
    }
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(doSave, 1500);
  }

  // lưu nháp khi rời trang
  window.addEventListener("pagehide", () => {
    if (saveTimer) {
      // fetch không kịp hoàn tất khi đóng tab — gửi navigate-beacon như best-effort
      const answers = collectAnswers();
      const blob = new Blob([JSON.stringify({ answers })], { type: "application/json" });
      navigator.sendBeacon && navigator.sendBeacon(`/exams/${examId}/draft`, blob);
    }
  });

  // ---- Nút submit (thanh sticky) ----
  const submitBtn = document.getElementById("submit-btn");
  if (submitBtn) {
    submitBtn.addEventListener("click", async () => {
      // flush nháp cuối trước khi nộp (không chặn nếu lỗi)
      if (saveTimer) { clearTimeout(saveTimer); await doSave(); }
      if (form) form.submit();
    });
  }
});
