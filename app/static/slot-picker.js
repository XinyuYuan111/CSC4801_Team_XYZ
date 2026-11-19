(() => {
  const picker = document.getElementById("slot-picker");
  const date = document.getElementById("slot-date");
  const hour = document.getElementById("slot-hour");
  const minute = document.getElementById("slot-minute");
  const start = document.getElementById("start_utc");
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
    date.min = firstDate;
    const isFirstDate = date.value === firstDate;
    hour.disabled = !date.value || !date.validity.valid;
    limitOptions(hour, isFirstDate ? next.slice(11, 13) : "00");
    minute.disabled = hour.disabled || !hour.value;
    limitOptions(minute, isFirstDate && hour.value === next.slice(11, 13) ? next.slice(14, 16) : "00");
    start.value = !minute.disabled && minute.value ? `${date.value}T${hour.value}:${minute.value}` : "";
  }

  document.getElementById("slot-start-fallback").hidden = true;
  start.type = "hidden";
  picker.disabled = false;
  picker.hidden = false;
  for (const event of ["input", "change", "focusin", "pointerdown"]) {
    picker.addEventListener(event, refresh);
  }
  start.form.addEventListener("submit", refresh, {capture: true});
  window.addEventListener("pageshow", refresh);
  document.addEventListener("visibilitychange", refresh);
  function tick() {
    refresh();
    window.setTimeout(tick, 60000 - (serverTime() % 60000));
  }
  tick();
})();
