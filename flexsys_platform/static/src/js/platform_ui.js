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
    button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
});
