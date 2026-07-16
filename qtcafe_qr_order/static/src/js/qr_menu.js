/** @odoo-module **/

let cart = [];
let activeCategory = 'all';
let searchTerm = '';

function money(value) {
    return Number(value || 0).toFixed(2);
}

function getCartTotals() {
    const totalQty = cart.reduce((sum, line) => sum + line.qty, 0);
    const totalAmount = cart.reduce((sum, line) => sum + (line.qty * line.price), 0);
    return { totalQty, totalAmount };
}

function openCart() {
    const drawer = document.querySelector('#cart-drawer');
    if (drawer) {
        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
    }
}

function closeCart() {
    const drawer = document.querySelector('#cart-drawer');
    if (drawer) {
        drawer.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
    }
}

function updateCartIndicators() {
    const { totalQty, totalAmount } = getCartTotals();
    ['#cart-count', '#floating-count'].forEach(selector => {
        const node = document.querySelector(selector);
        if (node) node.innerText = totalQty;
    });
    const floatingTotal = document.querySelector('#floating-total');
    const cartTotal = document.querySelector('#cart-total');
    if (floatingTotal) floatingTotal.innerText = money(totalAmount);
    if (cartTotal) cartTotal.innerText = money(totalAmount);
    const floating = document.querySelector('#floating-cart');
    if (floating) floating.classList.toggle('show', totalQty > 0);
}

function renderCart() {
    const box = document.querySelector('#cart-lines');
    if (!box) return;
    box.innerHTML = '';

    if (!cart.length) {
        box.innerHTML = '<div class="qt-empty-cart">السلة فارغة حالياً</div>';
        updateCartIndicators();
        return;
    }

    cart.forEach((line, index) => {
        const div = document.createElement('div');
        div.className = 'qt-cart-line';
        div.innerHTML = `
            <div>
                <strong>${line.name}</strong>
                <small>${money(line.price)} ر.س للقطعة</small>
            </div>
            <div class="qt-qty-control">
                <button type="button" data-action="dec" data-index="${index}">−</button>
                <span>${line.qty}</span>
                <button type="button" data-action="inc" data-index="${index}">+</button>
            </div>
            <strong>${money(line.qty * line.price)} ر.س</strong>
            <button class="qt-remove-line" type="button" data-action="remove" data-index="${index}">حذف</button>
        `;
        box.appendChild(div);
    });

    box.querySelectorAll('button[data-action]').forEach(btn => {
        btn.addEventListener('click', () => {
            const index = parseInt(btn.dataset.index);
            const action = btn.dataset.action;
            if (!cart[index]) return;
            if (action === 'inc') cart[index].qty += 1;
            if (action === 'dec') cart[index].qty -= 1;
            if (action === 'remove' || cart[index].qty <= 0) cart.splice(index, 1);
            renderCart();
        });
    });
    updateCartIndicators();
}

function applyProductFilters() {
    document.querySelectorAll('.qt-product-card').forEach(card => {
        const matchCategory = activeCategory === 'all' || card.dataset.category === activeCategory;
        const matchSearch = !searchTerm || (card.dataset.name || '').toLowerCase().includes(searchTerm);
        card.style.display = (matchCategory && matchSearch) ? '' : 'none';
    });
}

function bindFilters() {
    document.querySelectorAll('.category-filter').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.category-filter').forEach(x => x.classList.remove('active'));
            btn.classList.add('active');
            activeCategory = btn.dataset.category;
            applyProductFilters();
        });
    });

    const search = document.querySelector('#menu-search');
    if (search) {
        search.addEventListener('input', () => {
            searchTerm = search.value.trim().toLowerCase();
            applyProductFilters();
        });
    }
}

function bindCartButtons() {
    ['#open-cart', '#floating-cart'].forEach(selector => {
        const btn = document.querySelector(selector);
        if (btn) btn.addEventListener('click', openCart);
    });
    ['#close-cart', '#close-cart-backdrop'].forEach(selector => {
        const btn = document.querySelector(selector);
        if (btn) btn.addEventListener('click', closeCart);
    });
}


function selectedValue(name) {
    return document.querySelector(`input[name="${name}"]:checked`)?.value || "";
}

function updateOrderTypeFields() {
    const type = selectedValue("order_type");
    const dine = document.querySelector("#dine-in-fields");
    const car = document.querySelector("#car-fields");
    const delivery = document.querySelector("#delivery-fields");
    if (dine) dine.hidden = type !== "dine_in";
    if (car) car.hidden = type !== "car";
    if (delivery) delivery.hidden = type !== "delivery";
}

function distanceKm(lat1, lon1, lat2, lon2) {
    const toRad = (value) => value * Math.PI / 180;
    const radius = 6371;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2
        + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return radius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bindCheckoutOptions() {
    document.querySelectorAll('input[name="order_type"]').forEach((input) => {
        input.addEventListener("change", updateOrderTypeFields);
    });
    updateOrderTypeFields();

    const locate = document.querySelector("#share-delivery-location");
    if (locate) {
        locate.addEventListener("click", () => {
            const result = document.querySelector("#delivery-location-result");
            const box = document.querySelector("#delivery-fields");
            if (!navigator.geolocation) {
                result.innerText = "المتصفح لا يدعم مشاركة الموقع.";
                return;
            }
            result.innerText = "جاري تحديد موقعك...";
            navigator.geolocation.getCurrentPosition((position) => {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                document.querySelector("#delivery-latitude").value = lat;
                document.querySelector("#delivery-longitude").value = lon;
                const branchLat = Number(box.dataset.branchLatitude || 0);
                const branchLon = Number(box.dataset.branchLongitude || 0);
                const limit = Number(box.dataset.deliveryLimit || 0);
                const distance = branchLat && branchLon ? distanceKm(branchLat, branchLon, lat, lon) : 0;
                if (limit && distance > limit) {
                    result.innerText = `الموقع خارج نطاق التوصيل. المسافة ${distance.toFixed(1)} كم والحد ${limit.toFixed(1)} كم.`;
                    result.classList.add("is-error");
                } else {
                    result.innerText = distance
                        ? `تم تحديد الموقع — المسافة التقريبية ${distance.toFixed(1)} كم.`
                        : "تم تحديد الموقع.";
                    result.classList.remove("is-error");
                }
            }, () => {
                result.innerText = "تعذر تحديد الموقع. اسمح للمتصفح بالوصول إلى موقعك.";
                result.classList.add("is-error");
            }, {enableHighAccuracy: true, timeout: 12000, maximumAge: 30000});
        });
    }
}


async function submitOrder() {
    const sendBtn = document.querySelector('#send-order');
    const result = document.querySelector('#order-result');
    if (!sendBtn || !result) return;

    if (!cart.length) {
        result.innerText = 'السلة فارغة';
        return;
    }

    sendBtn.disabled = true;
    result.innerText = 'جاري إرسال الطلب...';
    try {
        const response = await fetch('/qtcafe/order/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    lines: cart,
                    customer_name: document.querySelector('#customer-name')?.value || '',
                    customer_mobile: document.querySelector('#customer-mobile')?.value || '',
                    note: document.querySelector('#customer-note')?.value || '',
                    pos_config_id: document.querySelector('#qtcafe-pos-config-id')?.value || new URLSearchParams(window.location.search).get('pos_config_id') || '',
                    payment_method: selectedValue('payment_method'),
                    order_type: selectedValue('order_type'),
                    table_id: document.querySelector('#order-table-id')?.value || '',
                    car_details: document.querySelector('#car-details')?.value || '',
                    delivery_latitude: document.querySelector('#delivery-latitude')?.value || '',
                    delivery_longitude: document.querySelector('#delivery-longitude')?.value || '',
                },
            }),
        });
        const data = await response.json();
        if (data.result && data.result.success) {
            const orderName = data.result.order.name;
            document.querySelector('#success-order-name').innerText = orderName;
            const orderTypeLabels = {dine_in: 'محلي', takeaway: 'سفري', car: 'طلب سيارة', delivery: 'توصيل'};
            const paymentLabels = {cash: 'نقدًا', card: 'بطاقة', wallet: 'محفظة إلكترونية'};
            const successType = document.querySelector('#success-order-type');
            const successPayment = document.querySelector('#success-payment-method');
            if (successType) successType.innerText = orderTypeLabels[selectedValue('order_type')] || '';
            if (successPayment) successPayment.innerText = paymentLabels[selectedValue('payment_method')] || '';
            document.querySelector('#success-screen').classList.add('show');
            document.querySelector('#success-screen').setAttribute('aria-hidden', 'false');
            closeCart();
            cart = [];
            renderCart();
            const customerNameInput = document.querySelector('#customer-name');
            const customerMobileInput = document.querySelector('#customer-mobile');
            if (customerNameInput && customerNameInput.type !== 'hidden') customerNameInput.value = '';
            if (customerMobileInput && customerMobileInput.type !== 'hidden') customerMobileInput.value = '';
            const customerNoteInput = document.querySelector('#customer-note');
            if (customerNoteInput) customerNoteInput.value = '';
            result.innerText = '';
        } else {
            result.innerText = (data.result && data.result.error) || 'تعذر إرسال الطلب';
        }
    } catch (error) {
        result.innerText = 'تعذر الاتصال بالخادم، حاول مرة أخرى';
    } finally {
        sendBtn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    bindFilters();
    bindCartButtons();
    bindCheckoutOptions();
    renderCart();

    document.querySelectorAll('.add-to-cart').forEach(btn => {
        btn.addEventListener('click', () => {
            const card = btn.closest('.qt-product-card');
            const productId = parseInt(card.dataset.productId);
            const existing = cart.find(line => line.product_id === productId);
            if (existing) {
                existing.qty += 1;
            } else {
                cart.push({
                    product_id: productId,
                    name: card.dataset.name || card.querySelector('h3').innerText,
                    qty: 1,
                    price: parseFloat(card.dataset.price || 0),
                    note: '',
                });
            }
            renderCart();
        });
    });

    const sendBtn = document.querySelector('#send-order');
    if (sendBtn) sendBtn.addEventListener('click', submitOrder);

    const newOrder = document.querySelector('#new-order');
    if (newOrder) {
        newOrder.addEventListener('click', () => {
            document.querySelector('#success-screen').classList.remove('show');
            document.querySelector('#success-screen').setAttribute('aria-hidden', 'true');
            window.scrollTo({top: 0, behavior: 'smooth'});
        });
    }
});
