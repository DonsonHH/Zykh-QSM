export async function apiGet(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" }
  });
  return readJsonResponse(response);
}

export async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return readJsonResponse(response);
}

export async function apiPatch(path, payload) {
  const response = await fetch(path, {
    method: "PATCH",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return readJsonResponse(response);
}

export async function apiDelete(path) {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" }
  });
  return readJsonResponse(response);
}

async function readJsonResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `请求失败：${response.status}`);
  }
  return data;
}
