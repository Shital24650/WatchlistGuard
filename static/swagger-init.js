/* Swagger UI bootstrap kept in a same-origin asset for the app's CSP. */
window.addEventListener("load", () => {
  if (typeof window.SwaggerUIBundle !== "function") return;
  window.SwaggerUIBundle({
    url: "/api/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true
  });
});
