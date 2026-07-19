'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const filters = Array.from(document.querySelectorAll('.fs-column-filter'));
    filters.forEach((filter) => {
        filter.addEventListener('toggle', () => {
            if (!filter.open) return;
            filters.forEach((other) => {
                if (other !== filter) other.removeAttribute('open');
            });
        });
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.fs-column-filter')) {
            filters.forEach((filter) => filter.removeAttribute('open'));
        }
    });

    document.querySelectorAll('.fs-filter-clear').forEach((button) => {
        button.addEventListener('click', () => {
            const form = button.closest('form');
            const names = (button.dataset.clearFields || '').split(',').filter(Boolean);
            names.forEach((name) => {
                form.querySelectorAll(`[name="${CSS.escape(name)}"]`).forEach((field) => {
                    if (field.type === 'radio' || field.type === 'checkbox') field.checked = false;
                    else if (field.tagName === 'SELECT') field.value = name === 'balance' ? 'all' : '';
                    else field.value = '';
                });
            });
            const page = form.querySelector('[name="page"]');
            if (page) page.value = '1';
            form.submit();
        });
    });
});
