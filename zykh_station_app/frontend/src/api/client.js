export async function apiGet(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`);
  }
  return response.json();
}
