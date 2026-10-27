// Form controls are progressive enhancements; all security checks run server-side.
(function () {
    'use strict';
    const form = document.getElementById('fs-career-form');
    if (!form) return;
    const file = form.querySelector('input[type="file"]');
    const status = document.getElementById('fs-form-status');
    const button = form.querySelector('button[type="submit"]');
    form.addEventListener('submit', function (event) {
        if (file && file.files.length && file.files[0].size > Number(file.dataset.maxBytes || 0)) {
            event.preventDefault();
            status.textContent = 'The selected document is too large.';
            file.focus();
            return;
        }
        if (!form.checkValidity()) {
            event.preventDefault();
            form.reportValidity();
            return;
        }
        button.disabled = true;
        button.textContent = 'Submitting…';
        status.textContent = 'Your application is being sent securely.';
    });
})();
