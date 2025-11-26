(() => {
  const targetId = 'swagger-ui';

  const renderError = (message) => {
    const target = document.getElementById(targetId);
    if (target) {
      target.classList.add('docs-error');
      target.textContent = message;
    }
  };

  const mountSwaggerUI = (config) => {
    if (typeof window.SwaggerUIBundle === 'undefined') {
      renderError('Swagger UI assets failed to load.');
      return;
    }

    const swaggerConfig = {
      url: config.openapiUrl,
      dom_id: `#${targetId}`,
      ...config.swaggerUiParameters,
    };

    if (config.oauth2RedirectUrl) {
      swaggerConfig.oauth2RedirectUrl = config.oauth2RedirectUrl;
    }

    const ui = window.SwaggerUIBundle(swaggerConfig);

    if (config.initOAuth) {
      ui.initOAuth(config.initOAuth);
    }
  };

  const fetchConfig = () => {
    const configUrl = document.body.dataset.swaggerConfigUrl;
    if (!configUrl) {
      renderError('Swagger UI configuration is missing.');
      return;
    }

    fetch(configUrl, { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load Swagger UI configuration (status ${response.status}).`);
        }
        return response.json();
      })
      .then(mountSwaggerUI)
      .catch((error) => {
        renderError(`Unable to initialize Swagger UI. ${error.message}`);
      });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fetchConfig);
  } else {
    fetchConfig();
  }
})();
