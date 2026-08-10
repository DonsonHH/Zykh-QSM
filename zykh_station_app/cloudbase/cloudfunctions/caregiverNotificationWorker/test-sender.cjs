const assert = require("node:assert/strict");
const test = require("node:test");

const { createSubscribeMessageSender } = require("./subscribeMessageSender");

test("a missing template configuration rejects locally without provider access", async () => {
  let providerCalls = 0;
  const sender = createSubscribeMessageSender({
    templateIds: {},
    async sendSubscribeMessage() {
      providerCalls += 1;
      return { errCode: 0 };
    },
  });

  const result = await sender.send({
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
  });

  assert.deepEqual(result, { outcome: "REJECTED", code: "TEMPLATE_NOT_CONFIGURED" });
  assert.equal(providerCalls, 0);
});

test("a configured send replaces caller content with the fixed privacy-safe template", async () => {
  const providerRequests = [];
  const sender = createSubscribeMessageSender({
    templateIds: { MEDICATION_SAFETY_ALERT: "template-123" },
    async sendSubscribeMessage(request) {
      providerRequests.push(request);
      return { errCode: 0 };
    },
  });

  const result = await sender.send({
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
    content: {
      person: "王奶奶",
      medicine: "布洛芬缓释胶囊",
      condition: "胃溃疡",
    },
  });

  assert.deepEqual(result, { outcome: "SENT", code: "OK" });
  assert.deepEqual(providerRequests, [{
    touser: "openid-1",
    templateId: "template-123",
    page: "pages/records/index",
    data: {
      thing1: { value: "家庭药箱新增一条取药核查记录" },
      thing2: { value: "请打开小程序查看" },
    },
  }]);
  const serialized = JSON.stringify(providerRequests);
  for (const sensitiveText of ["王奶奶", "布洛芬缓释胶囊", "胃溃疡"]) {
    assert.equal(serialized.includes(sensitiveText), false);
  }
});

test("a provider response that denies subscription authorization is an explicit rejection", async () => {
  const sender = createSubscribeMessageSender({
    templateIds: { MEDICATION_SAFETY_ALERT: "template-123" },
    async sendSubscribeMessage() {
      return { errCode: 43101, errMsg: "user refuse to accept the msg" };
    },
  });

  const result = await sender.send({
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
  });

  assert.deepEqual(result, { outcome: "REJECTED", code: "USER_NOT_AUTHORIZED" });
});

test("a provider exception returns unknown without leaking transport details", async () => {
  const sender = createSubscribeMessageSender({
    templateIds: { MEDICATION_SAFETY_ALERT: "template-123" },
    async sendSubscribeMessage() {
      throw new Error("socket timeout with private infrastructure hostname");
    },
  });

  const result = await sender.send({
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
  });

  assert.deepEqual(result, { outcome: "UNKNOWN", code: "DELIVERY_RESULT_UNKNOWN" });
  assert.equal(JSON.stringify(result).includes("hostname"), false);
});

test("a provider response without a result code is unknown rather than rejected", async () => {
  const sender = createSubscribeMessageSender({
    templateIds: { MEDICATION_SAFETY_ALERT: "template-123" },
    async sendSubscribeMessage() {
      return {};
    },
  });

  const result = await sender.send({
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
  });

  assert.deepEqual(result, { outcome: "UNKNOWN", code: "DELIVERY_RESULT_UNKNOWN" });
});
