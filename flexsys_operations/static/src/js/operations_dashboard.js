/** @odoo-module **/

async function rpc(route, params = {}) {
    const response = await fetch(route, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({jsonrpc: '2.0', method: 'call', params}),
    });
    const data = await response.json();
    return data.result;
}

function lineHtml(line) {
    return `<li><span>${line.product}</span><b>× ${line.qty}</b>${line.note ? `<small>${line.note}</small>` : ''}</li>`;
}

function actionsHtml(screen, order) {
    if (screen === 'cashier') {
        if (order.state === 'new') {
            return `<button data-action="accept">قبول</button><button class="ghost" data-action="cancel">إلغاء</button>`;
        }
        if (order.state === 'accepted') {
            return `<button data-action="prepare">تحويل للتحضير</button>`;
        }
    }
    if (screen === 'kds') {
        if (order.state === 'accepted') return `<button data-action="prepare">بدء التحضير</button>`;
        if (order.state === 'preparing') return `<button data-action="ready">جاهز</button>`;
    }
    return '';
}

function renderOrders(screen, orders) {
    const box = document.querySelector('#flexsys-operations-orders');
    if (!box) return;
    if (!orders.length) {
        box.innerHTML = '<div class="empty">لا توجد طلبات حالياً</div>';
        return;
    }
    box.innerHTML = orders.map(order => `
        <article class="order-ticket" data-id="${order.id}">
            <div class="ticket-head"><strong>${order.name}</strong><span>${order.state}</span></div>
            <p>${order.customer_name || 'عميل QR'} ${order.customer_mobile ? ' - ' + order.customer_mobile : ''}</p>
            <ul>${order.lines.map(lineHtml).join('')}</ul>
            ${order.note ? `<div class="note">${order.note}</div>` : ''}
            <div class="ticket-foot"><b>${Number(order.amount_total || 0).toFixed(2)} ر.س</b><div>${actionsHtml(screen, order)}</div></div>
        </article>
    `).join('');
    box.querySelectorAll('button[data-action]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.closest('.order-ticket').dataset.id;
            await rpc('/operations/api/orders/action', {order_id: id, action: btn.dataset.action});
            await loadOrders();
        });
    });
}

async function loadOrders() {
    const body = document.querySelector('.flexsys-operations-screen-body');
    if (!body) return;
    const screen = body.dataset.screen;
    const states = screen === 'kds' ? ['accepted', 'preparing'] : ['new', 'accepted'];
    const result = await rpc('/operations/api/orders', {states});
    if (result && result.success) renderOrders(screen, result.orders);
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.flexsys-operations-screen-body')) {
        loadOrders();
        setInterval(loadOrders, 10000);
    }
});
