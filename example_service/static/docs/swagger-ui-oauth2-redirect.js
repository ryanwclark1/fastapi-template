(() => {
  'use strict';

  const finalize = () => {
    window.close();
  };

  const run = () => {
    const oauth2 = window.opener && window.opener.swaggerUIRedirectOauth2;
    if (!oauth2) {
      finalize();
      return;
    }

    const sentState = oauth2.state;
    const redirectUrl = oauth2.redirectUrl;

    let queryString;
    if (/code|token|error/.test(window.location.hash)) {
      queryString = window.location.hash.substring(1).replace('?', '&');
    } else {
      queryString = window.location.search.substring(1);
    }

    const keyValuePairs = queryString ? queryString.split('&') : [];
    const params = keyValuePairs.reduce((acc, entry) => {
      const [key, value = ''] = entry.split('=');
      if (key) {
        acc[key] = decodeURIComponent(value);
      }
      return acc;
    }, {});

    const isValid = params.state === sentState;

    const authFlow = oauth2.auth.schema.get('flow');
    const requiresCode = [
      'accessCode',
      'authorizationCode',
      'authorization_code',
    ].includes(authFlow);

    if (requiresCode && !oauth2.auth.code) {
      if (!isValid) {
        oauth2.errCb({
          authId: oauth2.auth.name,
          source: 'auth',
          level: 'warning',
          message:
            "Authorization may be unsafe, passed state was changed in server. The passed state wasn't returned from auth server.",
        });
      }

      if (params.code) {
        delete oauth2.state;
        oauth2.auth.code = params.code;
        oauth2.callback({ auth: oauth2.auth, redirectUrl });
      } else {
        const oauthErrorMsg = params.error
          ? `[${params.error}]: ${
              params.error_description
                ? `${params.error_description}. `
                : 'no accessCode received from the server. '
            }${params.error_uri ? `More info: ${params.error_uri}` : ''}`
          : '[Authorization failed]: no accessCode received from the server.';

        oauth2.errCb({
          authId: oauth2.auth.name,
          source: 'auth',
          level: 'error',
          message: oauthErrorMsg,
        });
      }
    } else {
      oauth2.callback({
        auth: oauth2.auth,
        token: params,
        isValid,
        redirectUrl,
      });
    }

    finalize();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
