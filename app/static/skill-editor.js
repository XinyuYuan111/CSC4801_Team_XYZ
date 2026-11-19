(() => {
  const draft = document.getElementById("skills");
  const addButton = document.getElementById("add-skill");
  const tags = document.getElementById("skill-tags");
  const names = new Set();
  const lineBreak = /[\r\n]/;
  let composing = false;

  function addSkill(value) {
    const name = value.trim();
    const key = name.toLowerCase();
    if (!name || names.has(key)) return;
    names.add(key);

    const item = document.createElement("li");
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = "skill";
    field.value = name;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "skill-tag";
    remove.setAttribute("aria-label", `Remove ${name}`);
    remove.title = `Remove ${name}`;
    const label = document.createElement("span");
    label.textContent = name;
    const cross = document.createElement("span");
    cross.textContent = "×";
    cross.setAttribute("aria-hidden", "true");
    remove.append(label, cross);
    remove.addEventListener("click", () => {
      const next = item.nextElementSibling?.querySelector("button");
      names.delete(key);
      item.remove();
      (next || draft).focus();
    });
    item.append(field, remove);
    tags.append(item);
  }

  function commitDraft() {
    for (const line of draft.value.split(lineBreak)) addSkill(line);
    draft.value = "";
  }

  function commitSeparatedDraft() {
    if (lineBreak.test(draft.value)) commitDraft();
  }

  // Saved values are already individual skills, including names from older forms.
  const saved = Array.from(tags.querySelectorAll("input:checked"), input => input.value);
  tags.replaceChildren();
  saved.forEach(addSkill);
  addButton.hidden = false;
  document.getElementById("skill-help").textContent =
    "Press Enter or select Add skill. To paste multiple skills, use one per line.";

  draft.addEventListener("compositionstart", () => { composing = true; });
  draft.addEventListener("compositionend", () => {
    composing = false;
    commitSeparatedDraft();
  });
  draft.addEventListener("input", event => {
    if (!composing && !event.isComposing) commitSeparatedDraft();
  });
  draft.addEventListener("keydown", event => {
    if (event.key === "Enter" && !composing && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      commitDraft();
    }
  });
  addButton.addEventListener("click", () => {
    commitDraft();
    draft.focus();
  });
  // The textarea is also a form field: Save includes the final unfinished entry.
})();
