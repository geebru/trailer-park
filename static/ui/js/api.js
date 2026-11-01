/** JSON API client. Every mutating request sends Content-Type: application/json (SPEC D12). */
export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

async function request(method, path, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body ?? {});
  }
  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new ApiError(0, "network", "Can't reach Trailarr Parrk. Check that the container is running.");
  }
  let data = null;
  try { data = await response.json(); } catch { /* empty or non-JSON body */ }
  if (!response.ok) {
    const err = data && data.error;
    throw new ApiError(response.status, err?.code || "error", err?.message || `Request failed (${response.status}).`, data);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
};
