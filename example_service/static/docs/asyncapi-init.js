(() => {
  const targetId = 'asyncapi';

  const renderMessage = (message, error = false) => {
    const target = document.getElementById(targetId);
    if (target) {
      target.className = `docs-container ${error ? 'docs-error' : 'docs-loading'}`;
      target.textContent = message;
    }
  };

  const loadSchema = async () => {
    const target = document.getElementById(targetId);
    if (!target) {
      return;
    }

    if (typeof window.AsyncApiStandalone === 'undefined') {
      renderMessage('AsyncAPI assets failed to load.', true);
      return;
    }

    const configData = document.body.dataset.asyncapiConfig;
    let renderConfig = {};

    if (configData) {
      try {
        renderConfig = JSON.parse(configData);
      } catch (error) {
        renderMessage('AsyncAPI configuration is invalid.', true);
        return;
      }
    }

    const schemaUrl = `${window.location.pathname}.json`;

    try {
      const response = await fetch(schemaUrl, { credentials: 'same-origin' });
      if (!response.ok) {
        throw new Error(`status ${response.status}`);
      }

      const schema = await response.json();
      target.className = 'docs-container';
      window.AsyncApiStandalone.render({ schema, config: renderConfig }, target);
    } catch (error) {
      renderMessage(`Unable to load AsyncAPI schema: ${error.message}`, true);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadSchema);
  } else {
    loadSchema();
  }
})();
