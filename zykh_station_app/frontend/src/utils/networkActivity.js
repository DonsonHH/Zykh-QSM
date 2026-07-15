export const NETWORK_ACTIVITY_EVENT = "zykh:network-activity";

export function markNetworkActivity(direction) {
  if (typeof window === "undefined" || !["upload", "download"].includes(direction)) {
    return;
  }
  window.dispatchEvent(
    new CustomEvent(NETWORK_ACTIVITY_EVENT, {
      detail: { direction, at: Date.now() }
    })
  );
}
