export const INQUIRY_DRAFT_KEY = "zykh-inquiry-draft";
export const INQUIRY_CHAT_DRAFT_KEY = "zykh-inquiry-chat-draft";
export const INQUIRY_BACKEND_SESSION_KEY = "zykh-inquiry-backend-session";

export function clearInquirySession() {
  try {
    [INQUIRY_DRAFT_KEY, INQUIRY_CHAT_DRAFT_KEY, INQUIRY_BACKEND_SESSION_KEY].forEach((key) => {
      window.sessionStorage.removeItem(key);
    });
  } catch {
    // Session storage is optional.
  }
}
