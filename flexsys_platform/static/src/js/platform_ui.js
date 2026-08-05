/** @odoo-module **/
document.addEventListener("DOMContentLoaded", () => {
  const cards=[...document.querySelectorAll(".fs-app-card[data-health]")];
  document.querySelectorAll("[data-fs-app-filter]").forEach((trigger)=>trigger.addEventListener("click",()=>{
    const filter=trigger.dataset.fsAppFilter||"all";
    cards.forEach((card)=>{const h=card.dataset.health; card.hidden=!(filter==="all"||h===filter||(filter==="attention"&&["degraded","unavailable"].includes(h)));});
  }));
});
