'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const filters = Array.from(document.querySelectorAll('.fs-column-filter'));

    const positionFilterMenu = (filter) => {
        const summary = filter.querySelector(':scope > summary');
        const menu = filter.querySelector(':scope > .fs-filter-menu');
        if (!summary || !menu || !filter.open) return;

        menu.classList.add('fs-filter-menu-floating');
        const rect = summary.getBoundingClientRect();
        const viewportPadding = 12;
        const menuWidth = Math.min(270, window.innerWidth - (viewportPadding * 2));
        let left = rect.right - menuWidth;
        left = Math.max(viewportPadding, Math.min(left, window.innerWidth - menuWidth - viewportPadding));

        menu.style.width = `${menuWidth}px`;
        menu.style.left = `${left}px`;
        menu.style.right = 'auto';
        menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 80)}px`;
    };

    const closeFilter = (filter) => {
        const menu = filter.querySelector(':scope > .fs-filter-menu');
        if (menu) {
            menu.classList.remove('fs-filter-menu-floating');
            menu.removeAttribute('style');
        }
        filter.removeAttribute('open');
    };
    filters.forEach((filter) => {
        filter.addEventListener('toggle', () => {
            if (!filter.open) {
                const menu = filter.querySelector(':scope > .fs-filter-menu');
                if (menu) {
                    menu.classList.remove('fs-filter-menu-floating');
                    menu.removeAttribute('style');
                }
                return;
            }
            filters.forEach((other) => {
                if (other !== filter) closeFilter(other);
            });
            positionFilterMenu(filter);
        });
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.fs-column-filter')) {
            filters.forEach(closeFilter);
        }
    });


    window.addEventListener('resize', () => {
        filters.filter((filter) => filter.open).forEach(positionFilterMenu);
    });

    document.querySelectorAll('.fs-table-wrap').forEach((wrapper) => {
        wrapper.addEventListener('scroll', () => {
            filters.filter((filter) => filter.open).forEach(positionFilterMenu);
        }, {passive: true});
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
