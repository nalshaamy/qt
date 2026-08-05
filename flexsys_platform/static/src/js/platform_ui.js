/** @odoo-module **/
document.addEventListener("DOMContentLoaded", () => {
  const cards=[...document.querySelectorAll(".fs-app-card[data-health]")];
  document.querySelectorAll("[data-fs-app-filter]").forEach((trigger)=>trigger.addEventListener("click",()=>{
    const filter=trigger.dataset.fsAppFilter||"all";
    cards.forEach((card)=>{const h=card.dataset.health; card.hidden=!(filter==="all"||h===filter||(filter==="attention"&&["degraded","unavailable"].includes(h)));});
  }));
});

// Login v2: local password visibility toggle, no server-side state.
document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-fs-password-toggle]");
    if (!button) return;
    const field = button.closest(".fs-login-field");
    const input = field && field.querySelector('input[type="password"], input[type="text"]');
    if (!input) return;
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    const icon = button.querySelector(".fa");
    if (icon) {
        icon.classList.toggle("fa-eye", !reveal);
        icon.classList.toggle("fa-eye-slash", reveal);
    }
    button.setAttribute("aria-label", reveal ? (button.dataset.hideLabel || "Hide password") : (button.dataset.showLabel || "Show password"));
});

// Login v2.1: loading feedback and preserved language selection.
document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-fs-login-form]");
    if (!form) return;
    form.addEventListener("submit", () => {
        const button = form.querySelector("[data-fs-login-submit]");
        if (!button || button.disabled) return;
        button.disabled = true;
        button.classList.add("is-loading");
        button.setAttribute("aria-busy", "true");
        const label = button.querySelector("[data-fs-login-label]");
        const icon = button.querySelector("[data-fs-login-icon]");
        if (label) label.textContent = button.dataset.loadingLabel || "Signing in...";
        if (icon) icon.className = "fa fa-circle-o-notch fa-spin";
    });
});
