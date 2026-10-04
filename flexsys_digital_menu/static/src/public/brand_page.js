(() => {
    "use strict";

    const languageToggle = document.getElementById("fsm-language-toggle");
    const navToggle = document.getElementById("fsm-nav-toggle");
    const nav = document.getElementById("fsm-brand-nav");

    if (languageToggle) {
        languageToggle.addEventListener("click", () => {
            const current = document.documentElement.lang === "ar" ? "ar" : "en";
            const next = current === "ar" ? "en" : "ar";
            const slug = document.body.dataset.menuSlug || "";
            if (slug) localStorage.setItem(`fsm:${slug}:lang`, next);
            const url = new URL(window.location.href);
            url.searchParams.set("lang", next);
            window.location.assign(url.toString());
        });
    }

    if (navToggle && nav) {
        navToggle.hidden = nav.querySelectorAll(".fsm-brand-nav-link").length <= 1;
        navToggle.addEventListener("click", () => {
            const isOpen = nav.classList.toggle("is-open");
            navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });
        document.addEventListener("click", (event) => {
            if (!nav.classList.contains("is-open")) return;
            if (nav.contains(event.target) || navToggle.contains(event.target)) return;
            nav.classList.remove("is-open");
            navToggle.setAttribute("aria-expanded", "false");
        });
    }
})();
