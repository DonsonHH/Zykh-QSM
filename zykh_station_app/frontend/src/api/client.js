import { markNetworkActivity } from "../utils/networkActivity.js";

export async function apiGet(path) {
  return request(path, { headers: { Accept: "application/json" } });
}

export async function apiPost(path, payload) {
  return request(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function apiPatch(path, payload) {
  return request(path, {
    method: "PATCH",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function apiDelete(path) {
  return request(path, {
    method: "DELETE",
    headers: { Accept: "application/json" }
  });
}

async function request(path, options) {
  markNetworkActivity("upload");
  const response = await fetch(path, options);
  markNetworkActivity("download");
  return readJsonResponse(response);
}

async function readJsonResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `请求失败：${response.status}`);
  }
  return data;
}
