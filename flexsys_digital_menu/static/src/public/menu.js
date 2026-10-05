(() => {
    "use strict";

    const body = document.body;
    const slug = body.dataset.menuSlug;
    const defaultLanguage = body.dataset.defaultLanguage || "ar";
    const dataUrl = body.dataset.dataUrl || `/menu/${encodeURIComponent(slug)}/data`;
    if (!slug) return;
    const initialParams = new URLSearchParams(window.location.search);
    const requestedLanguage = initialParams.get("lang");
    const requestedOffer = initialParams.get("offer") || "";

    const el = (id) => document.getElementById(id);
    const state = {
        language: (["ar", "en"].includes(requestedLanguage) ? requestedLanguage : "") || localStorage.getItem(`fsm:${slug}:lang`) || defaultLanguage,
        branch: localStorage.getItem(`fsm:${slug}:branch`) || "",
        query: "",
        category: "all",
        offer: requestedOffer,
        offerIndex: 0,
        bannerIndex: 0,
        data: null,
    };

    const strings = {
        ar: {
            search: "ابحث في المنيو",
            all: "الكل",
            featured: "الأكثر تميزًا",
            featuredBadge: "مميز",
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
            featuredBadge: "Featured",
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
        const decimals = Math.max(0, Math.min(4, Number(state.data?.currency?.decimal_places ?? 2)));
        const numeric = Number(amount || 0);
        try {
            return new Intl.NumberFormat(locale, {
                style: "currency",
                currency,
                minimumFractionDigits: 0,
                maximumFractionDigits: decimals,
            }).format(numeric);
        } catch (_) {
            const fixed = numeric.toFixed(decimals);
            const plain = decimals ? fixed.replace(/\.?0+$/, "") : fixed;
            return `${plain} ${state.data?.currency?.symbol || currency}`;
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
        if (state.offer) {
            const requestedIndex = (state.data.offers || []).findIndex((item) => item.key === state.offer);
            if (requestedIndex >= 0) state.offerIndex = requestedIndex;
            else state.offer = "";
        }
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
            const img = node("img", `fsm-card-image${product.image_is_fallback ? " is-fallback" : ""}`);
            img.src = product.image_url;
            img.loading = "lazy";
            img.decoding = "async";
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
        // Featured is a ranking signal only. Visual marketing treatment is controlled
        // exclusively by the configured Badge, preserving the pre-0.21 card design.
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

    function plainProductGrid(products) {
        const wrapper = node("section", "fsm-section fsm-section-all");
        const inner = node("div", "fsm-section-inner");
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
            requestAnimationFrame(() => {
                el("fsm-category-nav")?.querySelector(".fsm-category-chip.is-active")?.scrollIntoView({
                    behavior: "smooth",
                    block: "nearest",
                    inline: "center",
                });
            });
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
                requestAnimationFrame(() => {
                    el("fsm-category-nav")?.querySelector(".fsm-category-chip.is-active")?.scrollIntoView({
                        behavior: "smooth",
                        block: "nearest",
                        inline: "center",
                    });
                });
                window.scrollTo({ top: el("fsm-control-slab")?.offsetTop || 0, behavior: "smooth" });
            });
            nav.appendChild(button);
        });
    }

    function renderBanners() {
        const container = el("fsm-banners");
        if (!container) return;
        container.textContent = "";
        const banners = state.data?.banners || [];
        if (!banners.length || !state.data.menu.active_now) {
            container.hidden = true;
            state.bannerIndex = 0;
            return;
        }
        if (state.bannerIndex >= banners.length) state.bannerIndex = 0;
        const banner = banners[state.bannerIndex];
        const isMobileViewport = window.matchMedia("(max-width: 760px)").matches;
        const hasMobileOverride = Boolean(banner.mobile_media_url);
        const effectiveMediaUrl = isMobileViewport && hasMobileOverride ? banner.mobile_media_url : banner.media_url;
        // A desktop creative used as mobile fallback must never be cropped by default.
        const effectiveFit = isMobileViewport && !hasMobileOverride ? "contain" : (banner.fit || "contain");
        const inner = node("div", "fsm-banners-inner");
        const frame = node("div", `fsm-banner-frame is-${effectiveFit}${isMobileViewport && !hasMobileOverride ? " is-mobile-fallback" : ""}`);
        const mediaHost = banner.click_url ? document.createElement("a") : document.createElement("div");
        mediaHost.className = "fsm-banner-media-link";
        if (banner.click_url) {
            mediaHost.href = banner.click_url;
            if (banner.open_new_tab) {
                mediaHost.target = "_blank";
                mediaHost.rel = "noopener";
            }
            mediaHost.addEventListener("click", () => trackEvent("banner_open", { reference: banner.key }));
        }

        if (banner.media_type === "video") {
            const video = document.createElement("video");
            video.className = "fsm-banner-media";
            video.muted = true;
            video.loop = true;
            video.autoplay = true;
            video.playsInline = true;
            video.setAttribute("playsinline", "");
            video.setAttribute("webkit-playsinline", "");
            video.preload = "metadata";
            video.src = effectiveMediaUrl;
            video.setAttribute("aria-label", banner.alt_text || banner.name || "Promotional video");
            mediaHost.appendChild(video);
            video.play().catch(() => {});
        } else {
            const image = node("img", "fsm-banner-media");
            image.src = effectiveMediaUrl;
            image.alt = banner.alt_text || banner.name || "";
            image.loading = "lazy";
            image.decoding = "async";
            mediaHost.appendChild(image);
        }
        frame.appendChild(mediaHost);

        if (banners.length > 1) {
            const navigation = node("div", "fsm-banner-nav");
            const previous = node("button", "fsm-banner-nav-button", document.documentElement.dir === "rtl" ? "›" : "‹");
            previous.type = "button";
            previous.setAttribute("aria-label", "Previous banner");
            previous.addEventListener("click", () => {
                state.bannerIndex = (state.bannerIndex - 1 + banners.length) % banners.length;
                renderBanners();
            });
            const next = node("button", "fsm-banner-nav-button", document.documentElement.dir === "rtl" ? "‹" : "›");
            next.type = "button";
            next.setAttribute("aria-label", "Next banner");
            next.addEventListener("click", () => {
                state.bannerIndex = (state.bannerIndex + 1) % banners.length;
                renderBanners();
            });
            navigation.appendChild(previous);
            navigation.appendChild(next);
            frame.appendChild(navigation);

            const dots = node("div", "fsm-banner-dots");
            banners.forEach((item, index) => {
                const dot = node("button", `fsm-banner-dot${index === state.bannerIndex ? " is-active" : ""}`);
                dot.type = "button";
                dot.setAttribute("aria-label", item.name || `${index + 1}`);
                dot.addEventListener("click", () => { state.bannerIndex = index; renderBanners(); });
                dots.appendChild(dot);
            });
            frame.appendChild(dots);
        }
        inner.appendChild(frame);
        container.appendChild(inner);
        container.hidden = false;
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
            image.decoding = "async";
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
            // "All" stays one continuous grid. Featured products are surfaced first
            // without duplicating them into a second section.
            const ordered = [...filtered].sort((a, b) => {
                if (Boolean(a.featured) !== Boolean(b.featured)) return a.featured ? -1 : 1;
                if (a.featured && b.featured) {
                    const featuredDelta = (a.featured_sequence || 10) - (b.featured_sequence || 10);
                    if (featuredDelta) return featuredDelta;
                }
                return (a.sequence || 10) - (b.sequence || 10);
            });
            sections.appendChild(plainProductGrid(ordered));
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
        const mode = product.recommendation_mode || "disabled";
        if (mode === "disabled") return null;

        const candidates = (state.data?.products || []).filter((item) =>
            item.key !== product.key && item.availability !== "sold_out"
        );

        if (mode === "manual") {
            if (!product.recommended_key) return null;
            return candidates.find((item) => item.key === product.recommended_key) || null;
        }

        if (mode !== "automatic") return null;
        return candidates.find((item) => item.category_key === product.category_key)
            || candidates.find((item) => item.featured)
            || candidates.sort((a, b) => (a.sequence || 10) - (b.sequence || 10))[0]
            || null;
    }

    function recommendationCard(product) {
        const card = node("button", "fsm-recommendation-card");
        card.type = "button";
        if (product.image_url) {
            const image = node("img", `fsm-recommendation-image${product.image_is_fallback ? " is-fallback" : ""}`);
            image.src = product.image_url;
            image.alt = product.name;
            image.loading = "lazy";
            image.decoding = "async";
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
            const image = node("img", `fsm-sheet-image${product.image_is_fallback ? " is-fallback" : ""}`);
            image.src = product.image_url;
            image.alt = product.name;
            image.decoding = "async";
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
        renderBanners();
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
