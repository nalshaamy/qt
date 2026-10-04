(() => {
    "use strict";

    const body = document.body;
    const slug = body.dataset.menuSlug;
    const defaultLanguage = body.dataset.defaultLanguage || "ar";
    const dataUrl = body.dataset.dataUrl || `/menu/${encodeURIComponent(slug)}/data`;
    if (!slug) return;
    const requestedLanguage = new URLSearchParams(window.location.search).get("lang");

    const el = (id) => document.getElementById(id);
    const state = {
        language: (["ar", "en"].includes(requestedLanguage) ? requestedLanguage : "") || localStorage.getItem(`fsm:${slug}:lang`) || defaultLanguage,
        branch: localStorage.getItem(`fsm:${slug}:branch`) || "",
        query: "",
        category: "all",
        offer: "",
        offerIndex: 0,
        data: null,
    };

    const strings = {
        ar: {
            search: "ابحث في المنيو",
            all: "الكل",
            featured: "الأكثر تميزًا",
            unavailable: "المنيو غير متاح حاليًا",
            noResults: "لا توجد منتجات مطابقة لبحثك",
            soldOut: "غير متوفر حاليًا",
            calories: "السعرات",
            allergens: "الحساسية",
            ingredients: "المكونات",
            variants: "الخيارات",
            from: "يبدأ من",
            branch: "الفرع",
            vegetarian: "نباتي",
            vegan: "نباتي بالكامل",
            spicy: "حار",
            description: "الوصف",
            recommended: "قد يعجبك أيضًا",
            readMore: "اقرأ عني أكثر",
            rightsReserved: "جميع الحقوق محفوظة لـ",
            offers: "العروض",
            viewOffer: "عرض المنتجات",
            showAll: "عرض الكل",
        },
        en: {
            search: "Search the menu",
            all: "All",
            featured: "Featured",
            unavailable: "This menu is currently unavailable",
            noResults: "No products match your search",
            soldOut: "Sold out",
            calories: "Calories",
            allergens: "Allergens",
            ingredients: "Ingredients",
            variants: "Options",
            from: "From",
            branch: "Branch",
            vegetarian: "Vegetarian",
            vegan: "Vegan",
            spicy: "Spicy",
            description: "Description",
            recommended: "You may also like",
            readMore: "Read more about me",
            rightsReserved: "All rights reserved to",
            offers: "Offers",
            viewOffer: "View products",
            showAll: "View all",
        },
    };

    function t(key) {
        return (strings[state.language] || strings.en)[key] || key;
    }

    function node(tag, className, text) {
        const item = document.createElement(tag);
        if (className) item.className = className;
        if (text !== undefined && text !== null) item.textContent = text;
        return item;
    }

    function formatPrice(amount) {
        const currency = state.data?.currency?.code || "SAR";
        const locale = state.language === "ar" ? "ar-SA" : "en-US";
        try {
            return new Intl.NumberFormat(locale, {
                style: "currency",
                currency,
                minimumFractionDigits: state.data?.currency?.decimal_places ?? 2,
                maximumFractionDigits: state.data?.currency?.decimal_places ?? 2,
            }).format(Number(amount || 0));
        } catch (_) {
            return `${Number(amount || 0).toFixed(2)} ${state.data?.currency?.symbol || currency}`;
        }
    }

    function activeOffer() {
        return state.offer ? (state.data?.offers || []).find((item) => item.key === state.offer) : null;
    }

    function effectiveProductPrice(product) {
        const offer = activeOffer();
        const override = offer?.product_prices?.[product.key];
        return override !== undefined && override !== null ? override : product.price;
    }

    function effectiveVariantPrice(variant) {
        const offer = activeOffer();
        const override = offer?.variant_prices?.[variant.key];
        return override !== undefined && override !== null ? override : variant.price;
    }

    const analyticsSessionKey = `fsm:${slug}:analytics-session`;
    let analyticsSession = localStorage.getItem(analyticsSessionKey);
    if (!analyticsSession) {
        analyticsSession = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`).slice(0, 96);
        localStorage.setItem(analyticsSessionKey, analyticsSession);
    }
    let trackedView = false;
    let searchTrackTimer = null;

    function trackEvent(eventType, extra = {}) {
        if (!state.data?.menu?.analytics || dataUrl.includes("/digital-menu/preview-data/")) return;
        const payload = {
            event_type: eventType,
            language: state.language,
            branch: state.branch || "",
            session: analyticsSession,
            ...extra,
        };
        fetch(`/menu/${encodeURIComponent(slug)}/event`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            credentials: "same-origin",
            keepalive: true,
            body: JSON.stringify(payload),
        }).catch(() => {});
    }

    async function loadData() {
        const params = new URLSearchParams({ lang: state.language });
        if (state.branch) params.set("branch", state.branch);
        const separator = dataUrl.includes("?") ? "&" : "?";
        const response = await fetch(`${dataUrl}${separator}${params.toString()}`, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        });
        if (!response.ok) throw new Error("Unable to load menu");
        state.data = await response.json();
        if (state.data.menu.branch?.key) state.branch = state.data.menu.branch.key;
        render();
        if (!trackedView) {
            trackedView = true;
            trackEvent("menu_view");
        }
    }

    function renderNavigation(items = []) {
        const nav = el("fsm-brand-nav");
        const toggle = el("fsm-nav-toggle");
        if (!nav) return;
        nav.textContent = "";
        items.forEach((item) => {
            const link = node("a", `fsm-brand-nav-link${item.active ? " is-active" : ""}`, item.label);
            link.href = item.url;
            link.addEventListener("click", () => {
                nav.classList.remove("is-open");
                if (toggle) toggle.setAttribute("aria-expanded", "false");
            });
            nav.appendChild(link);
        });
        const hasNavigation = items.length > 1;
        nav.hidden = !hasNavigation;
        if (toggle) {
            toggle.hidden = !hasNavigation;
            if (!hasNavigation) {
                nav.classList.remove("is-open");
                toggle.setAttribute("aria-expanded", "false");
            }
        }
    }

    function renderHeader() {
        const data = state.data.menu;
        document.documentElement.lang = state.language;
        document.documentElement.dir = state.language === "ar" ? "rtl" : "ltr";
        body.classList.remove("fsm-layout-cards", "fsm-layout-compact", "fsm-layout-image_focus");
        body.classList.add(`fsm-layout-${data.layout || "cards"}`);
        el("fsm-menu-title").textContent = data.brand_name || data.company_name || data.name || "";
        const tagline = el("fsm-menu-tagline");
        tagline.textContent = data.tagline || "";
        tagline.hidden = !data.tagline;
        el("fsm-footer-name").textContent = `${t("rightsReserved")} ${data.company_name || data.name || ""}`.trim();
        el("fsm-search").placeholder = t("search");
        el("fsm-language-toggle").textContent = state.language === "ar" ? "EN" : "ع";
        renderNavigation(data.navigation || []);

        const select = el("fsm-branch-select");
        select.textContent = "";
        if (data.branches.length > 1) {
            const placeholder = node("option", "", t("branch"));
            placeholder.value = "";
            select.appendChild(placeholder);
            data.branches.forEach((branch) => {
                const option = node("option", "", branch.name);
                option.value = branch.key;
                option.selected = branch.key === state.branch;
                select.appendChild(option);
            });
            select.hidden = false;
        } else {
            select.hidden = true;
        }
        el("fsm-language-toggle").hidden = data.languages.length < 2;
    }

    function productMatches(product) {
        if (!state.query) return true;
        const q = state.query.toLocaleLowerCase();
        return (product.search_text || "").toLocaleLowerCase().includes(q);
    }

    function makeBadge(text, muted = false, pulse = false) {
        return node("span", `fsm-badge${muted ? " muted" : ""}${pulse ? " pulse" : ""}`, text);
    }

    function productCard(product) {
        const card = node("article", "fsm-card");
        card.tabIndex = 0;
        card.dataset.productKey = product.key;

        const imageWrap = node("div", "fsm-card-image-wrap");
        if (product.image_url) {
            const img = node("img", "fsm-card-image");
            img.src = product.image_url;
            img.loading = "lazy";
            img.alt = product.name;
            imageWrap.appendChild(img);
        } else {
            imageWrap.appendChild(node("div", "fsm-card-placeholder", "✦"));
        }
        card.appendChild(imageWrap);

        if (product.availability === "sold_out") {
            card.appendChild(node("span", "fsm-sold-out", t("soldOut")));
        }

        const content = node("div", "fsm-card-content");
        const top = node("div", "fsm-card-top");
        top.appendChild(node("h3", "fsm-card-name", product.name));
        if (state.data.display?.prices !== false) top.appendChild(node("span", "fsm-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(effectiveProductPrice(product))}`));
        content.appendChild(top);
        if (product.description) {
            const descriptionPreview = node("div", "fsm-description-preview");
            descriptionPreview.appendChild(node("p", "fsm-description", product.description));
            const readMore = node("button", "fsm-read-more", t("readMore"));
            readMore.type = "button";
            readMore.addEventListener("click", (event) => {
                event.stopPropagation();
                openProduct(product);
            });
            descriptionPreview.appendChild(readMore);
            content.appendChild(descriptionPreview);
        }

        const meta = node("div", "fsm-meta");
        if (product.badge) meta.appendChild(makeBadge(product.badge, false, Boolean(product.badge_pulse)));
        if (product.calories) meta.appendChild(makeBadge(`${product.calories} kcal`, true));
        if (product.vegetarian) meta.appendChild(makeBadge(t("vegetarian"), true));
        if (product.vegan) meta.appendChild(makeBadge(t("vegan"), true));
        if (product.spicy_level && product.spicy_level !== "none") meta.appendChild(makeBadge(t("spicy"), true));
        if (meta.childNodes.length) content.appendChild(meta);
        card.appendChild(content);

        card.addEventListener("click", () => openProduct(product));
        card.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") openProduct(product);
        });
        return card;
    }

    function section(title, products, key, slabBackground = "", categoryImage = "") {
        const wrapper = node("section", "fsm-section");
        wrapper.id = `category-${key}`;
        if (slabBackground) wrapper.style.background = slabBackground;
        const inner = node("div", "fsm-section-inner");
        const header = node("div", "fsm-section-header");
        const titleWrap = node("div", "fsm-section-title-wrap");
        if (categoryImage) {
            const image = node("img", "fsm-section-icon");
            image.src = categoryImage;
            image.alt = "";
            image.loading = "lazy";
            titleWrap.appendChild(image);
        }
        titleWrap.appendChild(node("h2", "fsm-section-title", title));
        header.appendChild(titleWrap);
        if (key === "featured") {
            const showAll = node("button", "fsm-section-action", `${t("showAll")} ${document.documentElement.dir === "rtl" ? "←" : "→"}`);
            showAll.type = "button";
            showAll.addEventListener("click", () => {
                state.category = "all";
                state.offer = "";
                renderOffers();
                renderProducts();
                requestAnimationFrame(() => el("fsm-sections")?.scrollIntoView({ behavior: "smooth", block: "start" }));
            });
            header.appendChild(showAll);
        }
        inner.appendChild(header);
        const grid = node("div", "fsm-grid");
        products.forEach((product) => grid.appendChild(productCard(product)));
        inner.appendChild(grid);
        wrapper.appendChild(inner);
        return wrapper;
    }

    function renderCategories(searchProducts) {
        const nav = el("fsm-category-nav");
        nav.textContent = "";

        const allButton = node("button", `fsm-category-chip${state.category === "all" ? " is-active" : ""}`, t("all"));
        allButton.type = "button";
        allButton.addEventListener("click", () => {
            state.category = "all";
            state.offer = "";
            trackEvent("category_filter", { reference: "all" });
            renderOffers();
            renderProducts();
        });
        nav.appendChild(allButton);

        state.data.categories.forEach((category) => {
            if (!searchProducts.some((product) => product.category_key === category.key)) return;
            const button = node(
                "button",
                `fsm-category-chip${state.category === category.key ? " is-active" : ""}`,
                `${category.icon ? `${category.icon} ` : ""}${category.name}`
            );
            button.type = "button";
            button.addEventListener("click", () => {
                state.category = category.key;
                state.offer = "";
                trackEvent("category_filter", { reference: category.key });
                renderOffers();
                renderProducts();
                window.scrollTo({ top: el("fsm-control-slab")?.offsetTop || 0, behavior: "smooth" });
            });
            nav.appendChild(button);
        });
    }

    function renderOffers() {
        const container = el("fsm-offers");
        container.textContent = "";
        const offers = state.data?.offers || [];
        if (!offers.length || !state.data.menu.active_now) {
            container.hidden = true;
            state.offerIndex = 0;
            return;
        }
        if (state.offerIndex >= offers.length) state.offerIndex = 0;
        const offer = offers[state.offerIndex];
        const inner = node("div", "fsm-offers-inner");
        inner.appendChild(node("h2", "fsm-offers-title", t("offers")));

        const hero = node("article", `fsm-offer-hero${state.offer === offer.key ? " is-active" : ""}`);
        if (offer.image_url) {
            const media = node("div", "fsm-offer-hero-media");
            const image = node("img", "fsm-offer-hero-image");
            image.src = offer.image_url;
            image.alt = offer.name;
            image.loading = "lazy";
            media.appendChild(image);
            hero.appendChild(media);
        }
        hero.appendChild(node("div", "fsm-offer-hero-shade"));
        const content = node("div", "fsm-offer-hero-content");
        content.appendChild(node("p", "fsm-offer-kicker", t("offers")));
        content.appendChild(node("h3", "fsm-offer-name", offer.name));
        if (offer.subtitle) content.appendChild(node("p", "fsm-offer-subtitle", offer.subtitle));
        if (offer.description) content.appendChild(node("p", "fsm-offer-description", offer.description));
        if (offer.price !== null && offer.price !== undefined && state.data.display?.prices !== false) {
            const pricing = node("div", "fsm-offer-pricing");
            pricing.appendChild(node("strong", "fsm-offer-price", formatPrice(offer.price)));
            if (offer.original_price !== null && offer.original_price !== undefined && Number(offer.original_price) > Number(offer.price)) {
                pricing.appendChild(node("span", "fsm-offer-original-price", formatPrice(offer.original_price)));
            }
            content.appendChild(pricing);
        }
        if (offer.product_keys?.length) {
            const button = node("button", "fsm-offer-action", t("viewOffer"));
            button.type = "button";
            button.addEventListener("click", () => {
                trackEvent("offer_open", { reference: offer.key });
                if (offer.product_keys.length === 1) {
                    state.offer = offer.key;
                    state.category = "all";
                    renderOffers();
                    renderProducts();
                    const product = state.data.products.find((item) => item.key === offer.product_keys[0]);
                    if (product) openProduct(product);
                    return;
                }
                state.offer = state.offer === offer.key ? "" : offer.key;
                state.category = "all";
                renderOffers();
                renderProducts();
                requestAnimationFrame(() => el("fsm-featured")?.scrollIntoView({ behavior: "smooth", block: "start" }));
            });
            content.appendChild(button);
        }
        hero.appendChild(content);

        if (offers.length > 1) {
            const navigation = node("div", "fsm-offer-nav");
            const previous = node("button", "fsm-offer-nav-button", document.documentElement.dir === "rtl" ? "›" : "‹");
            previous.type = "button";
            previous.setAttribute("aria-label", "Previous offer");
            previous.addEventListener("click", () => {
                state.offerIndex = (state.offerIndex - 1 + offers.length) % offers.length;
                renderOffers();
            });
            const next = node("button", "fsm-offer-nav-button", document.documentElement.dir === "rtl" ? "‹" : "›");
            next.type = "button";
            next.setAttribute("aria-label", "Next offer");
            next.addEventListener("click", () => {
                state.offerIndex = (state.offerIndex + 1) % offers.length;
                renderOffers();
            });
            navigation.appendChild(previous);
            navigation.appendChild(next);
            hero.appendChild(navigation);

            const dots = node("div", "fsm-offer-dots");
            offers.forEach((item, index) => {
                const dot = node("button", `fsm-offer-dot${index === state.offerIndex ? " is-active" : ""}`);
                dot.type = "button";
                dot.setAttribute("aria-label", item.name || `${index + 1}`);
                dot.addEventListener("click", () => { state.offerIndex = index; renderOffers(); });
                dots.appendChild(dot);
            });
            hero.appendChild(dots);
        }
        inner.appendChild(hero);
        container.appendChild(inner);
        container.hidden = false;
    }

    function renderProducts() {
        const status = el("fsm-status");
        const featured = el("fsm-featured");
        const sections = el("fsm-sections");
        sections.textContent = "";
        featured.textContent = "";
        featured.hidden = true;
        status.hidden = true;

        if (!state.data.menu.active_now) {
            status.textContent = t("unavailable");
            status.hidden = false;
            renderCategories([]);
            return;
        }

        let searchProducts = state.data.products.filter(productMatches);
        if (state.offer) {
            const offer = (state.data.offers || []).find((item) => item.key === state.offer);
            if (offer) {
                const keys = new Set(offer.product_keys || []);
                searchProducts = searchProducts.filter((product) => keys.has(product.key));
            } else {
                state.offer = "";
            }
        }
        if (state.category !== "all" && !state.data.categories.some((category) => category.key === state.category)) {
            state.category = "all";
        }
        renderCategories(searchProducts);

        const filtered = state.category === "all"
            ? searchProducts
            : searchProducts.filter((product) => product.category_key === state.category);

        if (!filtered.length) {
            status.textContent = t("noResults");
            status.hidden = false;
            return;
        }

        if (state.category === "all") {
            const featuredProducts = filtered.filter((product) => product.featured).sort((a, b) => (a.featured_sequence || 10) - (b.featured_sequence || 10));
            if (featuredProducts.length) {
                featured.appendChild(section(t("featured"), featuredProducts, "featured"));
                featured.hidden = false;
            }

            state.data.categories.forEach((category) => {
                const products = filtered.filter((product) => product.category_key === category.key);
                if (products.length) sections.appendChild(section(category.name, products, category.key, category.slab_background, category.image_url));
            });
        } else {
            const category = state.data.categories.find((item) => item.key === state.category);
            if (category) {
                sections.appendChild(section(category.name, filtered, category.key, category.slab_background, category.image_url));
            }
        }
    }

    function detailRow(label, value) {
        const row = node("div", "fsm-detail-row");
        row.appendChild(node("span", "fsm-detail-label", label));
        row.appendChild(node("div", "", value));
        return row;
    }

    function recommendedProduct(product) {
        const candidates = (state.data?.products || []).filter((item) => (
            item.key !== product.key && item.availability === "available"
        ));
        if (!candidates.length) return null;

        const sameCategory = candidates
            .filter((item) => item.category_key === product.category_key)
            .sort((a, b) => (a.sequence || 10) - (b.sequence || 10));
        if (sameCategory.length) return sameCategory[0];

        const featured = candidates
            .filter((item) => item.featured)
            .sort((a, b) => (a.featured_sequence || 10) - (b.featured_sequence || 10));
        if (featured.length) return featured[0];

        return candidates.sort((a, b) => (a.sequence || 10) - (b.sequence || 10))[0];
    }

    function recommendationCard(product) {
        const card = node("button", "fsm-recommendation-card");
        card.type = "button";
        if (product.image_url) {
            const image = node("img", "fsm-recommendation-image");
            image.src = product.image_url;
            image.alt = product.name;
            image.loading = "lazy";
            card.appendChild(image);
        } else {
            card.appendChild(node("div", "fsm-recommendation-placeholder", "✦"));
        }
        const copy = node("div", "fsm-recommendation-copy");
        copy.appendChild(node("strong", "fsm-recommendation-name", product.name));
        if (state.data.display?.prices !== false) {
            copy.appendChild(node("span", "fsm-recommendation-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(effectiveProductPrice(product))}`));
        }
        card.appendChild(copy);
        card.appendChild(node("span", "fsm-recommendation-arrow", document.documentElement.dir === "rtl" ? "‹" : "›"));
        card.addEventListener("click", () => openProduct(product));
        return card;
    }

    function openProduct(product) {
        trackEvent("product_open", { reference: product.key });
        const content = el("fsm-sheet-content");
        content.textContent = "";
        if (product.image_url) {
            const image = node("img", "fsm-sheet-image");
            image.src = product.image_url;
            image.alt = product.name;
            content.appendChild(image);
        }
        const bodyContent = node("div", "fsm-sheet-body");
        bodyContent.appendChild(node("h2", "", product.name));
        if (state.data.display?.prices !== false) bodyContent.appendChild(node("div", "fsm-sheet-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(effectiveProductPrice(product))}`));

        if (product.description) {
            const descriptionBox = node("section", "fsm-description-box");
            descriptionBox.appendChild(node("span", "fsm-description-box-label", t("description")));
            descriptionBox.appendChild(node("p", "fsm-description-full", product.description));
            bodyContent.appendChild(descriptionBox);
        }

        const details = node("div", "fsm-detail-list");
        if (product.calories) details.appendChild(detailRow(t("calories"), `${product.calories} kcal`));
        if (product.ingredients) details.appendChild(detailRow(t("ingredients"), product.ingredients));
        if (product.allergens) details.appendChild(detailRow(t("allergens"), product.allergens));
        if (details.childNodes.length) bodyContent.appendChild(details);
        if (product.variants?.length > 1) {
            bodyContent.appendChild(node("h3", "", t("variants")));
            const list = node("div", "fsm-variant-list");
            product.variants.forEach((variant) => {
                const row = node("div", "fsm-variant");
                row.appendChild(node("span", "", variant.name));
                if (state.data.display?.prices !== false) row.appendChild(node("strong", "", formatPrice(effectiveVariantPrice(variant))));
                list.appendChild(row);
            });
            bodyContent.appendChild(list);
        }

        const recommended = recommendedProduct(product);
        if (recommended) {
            const recommendation = node("section", "fsm-recommendation");
            recommendation.appendChild(node("h3", "fsm-recommendation-title", t("recommended")));
            recommendation.appendChild(recommendationCard(recommended));
            bodyContent.appendChild(recommendation);
        }

        content.appendChild(bodyContent);
        const backdrop = el("fsm-sheet-backdrop");
        const sheet = el("fsm-product-sheet");
        backdrop.hidden = false;
        sheet.hidden = false;
        sheet.setAttribute("aria-hidden", "false");
        document.body.classList.add("fsm-modal-open");
        document.documentElement.classList.add("fsm-modal-open");
        sheet.scrollTop = 0;
        requestAnimationFrame(() => {
            backdrop.classList.add("is-open");
            sheet.classList.add("is-open");
            try {
                sheet.focus({ preventScroll: true });
            } catch (_) {
                sheet.focus();
            }
        });
        history.replaceState(null, "", `#product=${encodeURIComponent(product.key)}`);
    }

    function closeProduct() {
        const backdrop = el("fsm-sheet-backdrop");
        const sheet = el("fsm-product-sheet");
        backdrop.classList.remove("is-open");
        sheet.classList.remove("is-open");
        sheet.setAttribute("aria-hidden", "true");
        document.body.classList.remove("fsm-modal-open");
        document.documentElement.classList.remove("fsm-modal-open");
        window.setTimeout(() => {
            if (!sheet.classList.contains("is-open")) {
                backdrop.hidden = true;
                sheet.hidden = true;
            }
        }, 180);
        history.replaceState(null, "", window.location.pathname + window.location.search);
    }

    function render() {
        renderHeader();
        renderOffers();
        renderProducts();
        const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
        const productKey = hash.get("product");
        if (productKey) {
            const product = state.data.products.find((item) => item.key === productKey);
            if (product) openProduct(product);
        }
    }

    el("fsm-search").addEventListener("input", (event) => {
        state.query = event.target.value.trim();
        state.offer = "";
        renderOffers();
        renderProducts();
        window.clearTimeout(searchTrackTimer);
        if (state.query.length >= 2) {
            searchTrackTimer = window.setTimeout(() => trackEvent("search", { term: state.query }), 700);
        }
    });
    el("fsm-language-toggle").addEventListener("click", async () => {
        state.language = state.language === "ar" ? "en" : "ar";
        localStorage.setItem(`fsm:${slug}:lang`, state.language);
        trackEvent("language_change");
        await loadData();
    });
    el("fsm-branch-select").addEventListener("change", async (event) => {
        state.branch = event.target.value;
        localStorage.setItem(`fsm:${slug}:branch`, state.branch);
        trackEvent("branch_change");
        await loadData();
    });
    const navToggle = el("fsm-nav-toggle");
    if (navToggle) {
        navToggle.addEventListener("click", () => {
            const nav = el("fsm-brand-nav");
            const isOpen = nav.classList.toggle("is-open");
            navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });
    }
    document.addEventListener("click", (event) => {
        const nav = el("fsm-brand-nav");
        if (!nav || !nav.classList.contains("is-open")) return;
        if (nav.contains(event.target) || navToggle?.contains(event.target)) return;
        nav.classList.remove("is-open");
        navToggle?.setAttribute("aria-expanded", "false");
    });
    el("fsm-sheet-close").addEventListener("click", closeProduct);
    el("fsm-sheet-backdrop").addEventListener("click", closeProduct);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !el("fsm-product-sheet").hidden) closeProduct();
    });

    loadData().catch(() => {
        const status = el("fsm-status");
        status.textContent = state.language === "ar" ? "تعذر تحميل المنيو." : "Unable to load the menu.";
        status.hidden = false;
    });
})();
