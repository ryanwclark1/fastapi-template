(() => {
  const renderError = (message) => {
    const container = document.getElementById('redoc-container');
    if (container) {
      container.classList.add('docs-error');
      container.textContent = message;
    }
  };

  const init = () => {
    const specUrl = document.body.dataset.redocSpecUrl;
    const container = document.getElementById('redoc-container');

    if (!specUrl || !container) {
      renderError('ReDoc configuration is missing.');
      return;
    }

    if (typeof window.Redoc === 'undefined') {
      renderError('Redoc assets failed to load.');
      return;
    }

    container.classList.remove('docs-loading', 'docs-error');
    window.Redoc.init(specUrl, {}, container);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
