const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  let body = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const detail = body?.detail || body?.error || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return body;
}

export const api = {
  incidents: (params = {}) => {
    const query = new URLSearchParams(params);
    return request(`/incidents?${query}`);
  },
  incident: (id) => request(`/incidents/${id}`),
  updateIncidentStatus: (id, status) =>
    request(`/incidents/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status })
    }),
  signals: (params = {}) => {
    const query = new URLSearchParams(params);
    return request(`/signals?${query}`);
  },
  signalStats: () => request("/signals/stats/summary"),
  getRca: (incidentId) => request(`/rca/${incidentId}`),
  submitRca: (incidentId, payload) =>
    request(`/rca/${incidentId}`, {
      method: "POST",
      body: JSON.stringify(payload)
    })
};

export async function rootRequest(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(response.statusText);
  }
  return response.json();
}
