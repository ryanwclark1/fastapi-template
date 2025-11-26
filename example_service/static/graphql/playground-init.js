(() => {
  function parseConfig() {
    try {
      const data = document.body.dataset.playgroundConfig;
      return data ? JSON.parse(data) : {};
    } catch (error) {
      console.error("Invalid GraphQL Playground configuration", error);
      return {};
    }
  }

  function initPlayground() {
    if (typeof GraphQLPlayground === "undefined") {
      console.error("GraphQLPlayground global is not available");
      return;
    }

    const container = document.getElementById("graphql-playground");
    if (!container) {
      console.error("Missing #graphql-playground container");
      return;
    }

    container.classList.remove("docs-loading");
    const config = parseConfig();
    GraphQLPlayground.init(container, config);
  }

  if (document.readyState === "loading") {
    window.addEventListener("load", initPlayground, { once: true });
  } else {
    initPlayground();
  }
})();
