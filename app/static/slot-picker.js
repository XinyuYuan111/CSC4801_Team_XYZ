(() => {
  const picker = document.getElementById("slot-picker");
  const dateText = document.getElementById("slot-date");
  const calendar = document.getElementById("slot-calendar");
  const hour = document.getElementById("slot-hour");
  const minute = document.getElementById("slot-minute");
  const clockOffset = Number(picker.dataset.nowMs) - Date.now();
  const serverTime = () => Date.now() + clockOffset;

  function limitOptions(select, minimum) {
    for (const option of select.options) {
      option.disabled = option.value !== "" && option.value < minimum;
    }
    if (select.selectedOptions[0]?.disabled) select.value = "";
  }

  function refresh() {
    // The service requires strict futurity and the form accepts whole UTC minutes.
    const next = new Date(serverTime() + 60000).toISOString();
    const firstDate = next.slice(0, 10);
    calendar.min = firstDate;
    const iso = /^\d{4}\/\d{2}\/\d{2}$/.test(dateText.value) ? dateText.value.replaceAll("/", "-") : "";
    if (calendar.value !== iso) calendar.value = iso;
    const day = calendar.value; // The native date control clears impossible dates such as February 30.
    let dateError = "";
    if (dateText.value && !day) dateError = "Enter a valid date in yyyy/mm/dd format.";
    else if (calendar.validity.rangeUnderflow) dateError = "Choose a future start time (UTC).";
    dateText.setCustomValidity(dateError);
    const isFirstDate = day === firstDate;
    hour.disabled = !day || !dateText.validity.valid;
    limitOptions(hour, isFirstDate ? next.slice(11, 13) : "00");
    minute.disabled = hour.disabled || !hour.value;
    limitOptions(minute, isFirstDate && hour.value === next.slice(11, 13) ? next.slice(14, 16) : "00");
  }

  function useCalendarDate() {
    dateText.value = calendar.value.replaceAll("-", "/");
    dateText.dispatchEvent(new Event("input", {bubbles:true}));
  }
  calendar.addEventListener("input", useCalendarDate);
  calendar.addEventListener("change", useCalendarDate);
  calendar.addEventListener("keydown", event => {
    if ((event.key === "Enter" || event.key === " ") && calendar.showPicker) {
      event.preventDefault();
      calendar.showPicker();
    }
  });

  calendar.parentElement.hidden = false;
  for (const event of ["input", "change", "focusin", "pointerdown"]) {
    picker.addEventListener(event, refresh);
  }
  dateText.form.addEventListener("submit", refresh, {capture: true});
  window.addEventListener("pageshow", refresh);
  document.addEventListener("visibilitychange", refresh);
  function tick() {
    refresh();
    window.setTimeout(tick, 60000 - (serverTime() % 60000));
  }
  tick();
})();
