const { FIXED_NOTIFICATION_CONTENT } = require("./worker");

function text(value) {
  return String(value || "").trim();
}

function createSubscribeMessageSender({ templateIds = {}, sendSubscribeMessage }) {
  if (typeof sendSubscribeMessage !== "function") throw new Error("subscribe message adapter required");

  async function send(request = {}) {
    const templateId = text(templateIds[text(request.templateKey)]);
    if (!templateId) return { outcome: "REJECTED", code: "TEMPLATE_NOT_CONFIGURED" };
    const recipientOpenId = text(request.recipientOpenId);
    if (!recipientOpenId) return { outcome: "REJECTED", code: "RECIPIENT_NOT_CONFIGURED" };
    const page = text(request.page);
    if (!page) return { outcome: "REJECTED", code: "PAGE_NOT_CONFIGURED" };
    let response;
    try {
      response = await sendSubscribeMessage({
        touser: recipientOpenId,
        templateId,
        page,
        data: {
          thing1: { value: FIXED_NOTIFICATION_CONTENT.summary },
          thing2: { value: FIXED_NOTIFICATION_CONTENT.instruction },
        },
      });
    } catch (error) {
      return { outcome: "UNKNOWN", code: "DELIVERY_RESULT_UNKNOWN" };
    }
    const providerCode = response && (response.errCode ?? response.errcode);
    if (providerCode === undefined || providerCode === null || providerCode === "") {
      return { outcome: "UNKNOWN", code: "DELIVERY_RESULT_UNKNOWN" };
    }
    if (Number(providerCode) === 0) return { outcome: "SENT", code: "OK" };
    if (Number(providerCode) === 43101) {
      return { outcome: "REJECTED", code: "USER_NOT_AUTHORIZED" };
    }
    return { outcome: "REJECTED", code: "PROVIDER_REJECTED" };
  }

  return Object.freeze({ send });
}

module.exports = { createSubscribeMessageSender };
