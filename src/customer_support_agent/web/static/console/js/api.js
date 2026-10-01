// The only file that talks to the backend (docs/CONSOLE_API.md). Every POST/PATCH carries the CSRF header;
// the session is an HttpOnly cookie the page never sees. A 401 anywhere sends the user to the sign-in screen.

const BASE = "/console/api";
const CSRF = { "X-Requested-With": "relaypay-console" };

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || "Something went wrong. Please try again.");
    this.status = status;
    this.code = body?.error || "unknown";
    this.fields = body?.fields || {};
  }
}

let onSignedOut = () => {};
export function whenSignedOut(handler) {
  onSignedOut = handler;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (method !== "GET") Object.assign(headers, CSRF, { "Content-Type": "application/json" });
  let response;
  try {
    response = await fetch(BASE + path, {
      method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { error: "network", detail: "Can't reach the server. Check your connection and try again." });
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (response.status === 401 && !path.startsWith("/login") && !path.startsWith("/invites")) onSignedOut();
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

export const post = (path, body = {}) => api(path, { method: "POST", body });
export const patch = (path, body) => api(path, { method: "PATCH", body });
export const query = (params) => {
  const search = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined));
  const text = search.toString();
  return text ? `?${text}` : "";
};
