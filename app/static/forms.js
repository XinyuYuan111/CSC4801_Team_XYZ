// Use inline English feedback regardless of the browser's own language.
function showFieldError(field, message) {
  const id = field.id + "-error";
  let error = document.getElementById(id);
  if (!error) {
    error = document.createElement("p");
    error.id = id;
    error.className = "error-text";
    error.setAttribute("role", "alert");
    field.insertAdjacentElement("afterend", error);
    field.setAttribute("aria-errormessage", id);
  }
  error.textContent = message;
  field.setAttribute("aria-invalid", "true");
}

function clearFieldError(field) {
  document.getElementById(field.id + "-error")?.remove();
  field.removeAttribute("aria-errormessage");
  field.removeAttribute("aria-invalid");
}

function validationMessage(field) {
  if (field.validity.customError) return field.validationMessage;
  if (field.type === "email" && (field.validity.typeMismatch || field.validity.badInput)) return "Enter a valid email address.";
  if (field.validity.badInput) return "Enter a valid date and time.";
  if (field.validity.rangeUnderflow && field.type === "date") return "Choose a future start time (UTC).";
  if (field.validity.valueMissing) return "This field is required.";
  if (field.validity.tooShort) return `Use at least ${field.minLength} characters.`;
  if (field.autocomplete === "new-password" && /^ +$/.test(field.value)) return "A password cannot contain only spaces.";
  return field.dataset.patternError || "Enter a valid value.";
}

for (const form of document.querySelectorAll("form[novalidate]")) {
  form.addEventListener("input", event => clearFieldError(event.target));
  form.addEventListener("submit", event => {
    const field = Array.from(form.elements).find(item => item.willValidate && !item.validity.valid);
    if (field) {
      event.preventDefault();
      showFieldError(field, validationMessage(field));
      field.focus();
    }
  });
}

const registration = document.getElementById("registration");
if (registration) {
  const roles = registration.elements.role;
  const syncRole = () => {
    for (const section of registration.querySelectorAll("[data-role]")) {
      const field = section.querySelector("input");
      field.disabled = section.dataset.role !== roles.value;
      if (field.disabled) clearFieldError(field);
    }
  };
  for (const radio of roles) radio.addEventListener("change", syncRole);
  window.addEventListener("pageshow", syncRole);
  syncRole();

  const password = registration.elements.password;
  const unsupported = /[^ -~]/;
  function rejectInsertion(event, text) {
    if (event.cancelable && text && unsupported.test(text)) {
      event.preventDefault();
      // Avoid registering the old value after an entire paste or insertion was rejected.
      password.setCustomValidity("That input was not added. Edit your password using English keyboard characters.");
      showFieldError(password, password.validationMessage);
    }
  }
  password.addEventListener("beforeinput", event => rejectInsertion(event, event.data));
  password.addEventListener("paste", event => rejectInsertion(event, event.clipboardData?.getData("text")));
  // Some input methods and autofill can insert text without a cancelable beforeinput.
  registration.addEventListener("input", event => {
    if (event.target === password) {
      password.setCustomValidity("");
      if (unsupported.test(password.value)) showFieldError(password, password.dataset.patternError);
    }
  });
}
