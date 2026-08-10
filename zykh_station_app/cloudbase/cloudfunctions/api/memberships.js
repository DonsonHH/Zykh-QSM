const crypto = require("crypto");

function textList(value) {
  return Array.isArray(value)
    ? value.map(item => String(item || "").trim()).filter(Boolean)
    : [];
}

function sha256(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest("hex");
}

function expiryTime(value) {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return Number.isFinite(value) ? value : NaN;
  const text = String(value || "").trim();
  if (!text) return NaN;
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)
    ? `${text.replace(" ", "T")}+08:00`
    : text;
  return Date.parse(normalized);
}

function createMembershipModule({ db, collections, nowText }) {
  async function documentOrNull(collection, id) {
    try {
      const result = await collection.doc(id).get();
      return result && result.data ? result.data : null;
    } catch (error) {
      return null;
    }
  }

  async function listMyDevices({ openId }) {
    const normalizedOpenId = String(openId || "").trim();
    if (!normalizedOpenId) throw new Error("miniprogram identity required");
    const rows = [];
    for (let offset = 0; ; offset += 100) {
      const result = await db.collection(collections.deviceMemberships)
        .where({ openid: normalizedOpenId, status: "ACTIVE" })
        .skip(offset)
        .limit(100)
        .get();
      const page = result.data || [];
      rows.push(...page);
      if (page.length < 100) break;
    }

    const uniqueMemberships = new Map();
    rows.forEach(membership => {
      const deviceId = String(membership.deviceId || "").trim();
      if (deviceId && !uniqueMemberships.has(deviceId)) {
        uniqueMemberships.set(deviceId, membership);
      }
    });
    const items = [];
    for (const [deviceId, membership] of uniqueMemberships) {
      const device = await documentOrNull(db.collection(collections.devices), deviceId);
      items.push({
        deviceId,
        name: String((device && (device.name || device.displayName)) || "家庭药箱"),
        online: Boolean(device && device.online),
        lastSeenAt: String((device && (device.lastSeenAt || device.updatedAt)) || ""),
        role: String(membership.role || "VIEWER").toUpperCase(),
        permissions: textList(membership.permissions),
        serviceUserScopes: textList(
          membership.service_user_scopes || membership.serviceUserScopes,
        ),
      });
    }
    items.sort((left, right) => left.deviceId.localeCompare(right.deviceId));
    return { ok: true, items };
  }

  async function redeemPairingCode({ openId, pairingCode }) {
    const normalizedOpenId = String(openId || "").trim();
    if (!normalizedOpenId) throw new Error("miniprogram identity required");
    const code = String(pairingCode || "").trim();
    if (code.length < 16 || code.length > 256) throw new Error("PAIRING_CODE_INVALID");
    if (typeof db.runTransaction !== "function") {
      throw new Error("database transaction is unavailable");
    }

    const codeHash = sha256(code);
    const pairingDocumentId = `pairing-${codeHash}`;
    return db.runTransaction(async transaction => {
      const pairingCollection = transaction.collection(collections.devicePairingCodes);
      const pairing = await documentOrNull(pairingCollection, pairingDocumentId);
      const invalid = (
        !pairing
        || String(pairing.codeHash || "") !== codeHash
        || String(pairing.status || "").toUpperCase() !== "UNUSED"
        || !Number.isFinite(expiryTime(pairing.expiresAt || pairing.expires_at))
        || expiryTime(pairing.expiresAt || pairing.expires_at) <= Date.now()
      );
      if (invalid) throw new Error("PAIRING_CODE_INVALID");

      const deviceId = String(pairing.deviceId || pairing.device_id || "").trim();
      const role = String(pairing.role || "").trim().toUpperCase();
      const permissions = textList(pairing.permissions);
      const serviceUserScopes = textList(
        pairing.service_user_scopes || pairing.serviceUserScopes,
      );
      const allowedRoles = new Set(["OWNER", "CAREGIVER", "VIEWER"]);
      const allowedPermissions = new Set([
        "READ_SAFETY",
        "READ_INQUIRY",
        "READ_PLAN",
        "READ_PROFILE",
        "READ_RECORD",
        "READ_VITALS",
        "READ_MEDICINE",
        "CREATE_COMMAND",
      ]);
      if (
        !deviceId
        || !allowedRoles.has(role)
        || permissions.some(permission => !allowedPermissions.has(permission))
      ) throw new Error("PAIRING_CODE_INVALID");

      const membershipCollection = transaction.collection(collections.deviceMemberships);
      const existingMemberships = await membershipCollection
        .where({ openid: normalizedOpenId, deviceId })
        .limit(1)
        .get();
      if ((existingMemberships.data || []).length) throw new Error("PAIRING_CODE_INVALID");

      const timestamp = nowText();
      const membershipId = `membership-${sha256(`${deviceId}\u0000${normalizedOpenId}`)}`;
      await membershipCollection.doc(membershipId).set({
        data: {
          membershipId,
          openid: normalizedOpenId,
          deviceId,
          role,
          permissions,
          service_user_scopes: serviceUserScopes,
          status: "ACTIVE",
          createdAt: timestamp,
          updatedAt: timestamp,
        },
      });

      const consumedPairing = Object.assign({}, pairing, {
        codeHash,
        deviceId,
        status: "CONSUMED",
        consumedAt: timestamp,
        consumedByOpenId: normalizedOpenId,
        membershipId,
        updatedAt: timestamp,
      });
      delete consumedPairing._id;
      delete consumedPairing._openid;
      delete consumedPairing.code;
      delete consumedPairing.pairingCode;
      await pairingCollection.doc(pairingDocumentId).set({ data: consumedPairing });

      return {
        ok: true,
        deviceId,
        role,
        permissions,
        serviceUserScopes,
      };
    });
  }

  async function listActiveMemberships(deviceId) {
    const rows = [];
    for (let offset = 0; ; offset += 100) {
      const result = await db.collection(collections.deviceMemberships)
        .where({ deviceId, status: "ACTIVE" })
        .skip(offset)
        .limit(100)
        .get();
      const page = result.data || [];
      rows.push(...page);
      if (page.length < 100) return rows;
    }
  }

  async function listSafetyRecipients({ deviceId, personId }) {
    const normalizedPersonId = String(personId || "").trim();
    const rows = await listActiveMemberships(deviceId);
    return rows
      .map(membership => ({
        membershipId: String(membership._id || membership.membership_id || membership.membershipId || "").trim(),
        openid: String(membership.openid || "").trim(),
        permissions: textList(membership.permissions),
        service_user_scopes: textList(
          membership.service_user_scopes || membership.serviceUserScopes,
        ),
      }))
      .filter(membership => membership.membershipId && membership.openid)
      .filter(membership => membership.permissions.includes("READ_SAFETY"))
      .filter(membership => (
        !membership.service_user_scopes.length
        || membership.service_user_scopes.includes(normalizedPersonId)
      ));
  }

  async function isCurrentSafetyRecipient({
    database,
    membershipId,
    openid,
    deviceId,
    personId,
  }) {
    const membership = await documentOrNull(
      database.collection(collections.deviceMemberships),
      membershipId,
    );
    if (
      !membership
      || String(membership.openid || "").trim() !== String(openid || "").trim()
      || String(membership.deviceId || "").trim() !== String(deviceId || "").trim()
      || String(membership.status || "").toUpperCase() !== "ACTIVE"
    ) return false;
    const permissions = textList(membership.permissions);
    if (!permissions.includes("READ_SAFETY")) return false;
    const scopes = textList(
      membership.service_user_scopes || membership.serviceUserScopes,
    );
    const normalizedPersonId = String(personId || "").trim();
    return !scopes.length || scopes.includes(normalizedPersonId);
  }

  async function requireMembership({ openId, deviceId, personId = "" }) {
    const normalizedOpenId = String(openId || "").trim();
    if (!normalizedOpenId) throw new Error("miniprogram identity required");
    const result = await db.collection(collections.deviceMemberships)
      .where({ openid: normalizedOpenId, deviceId, status: "ACTIVE" })
      .limit(1)
      .get();
    const membership = (result.data || [])[0];
    if (!membership) throw new Error("CAREGIVER_MEMBERSHIP_REQUIRED");

    const scopes = textList(
      membership.service_user_scopes || membership.serviceUserScopes,
    );
    const normalizedPersonId = String(personId || "").trim();
    if (normalizedPersonId && scopes.length && !scopes.includes(normalizedPersonId)) {
      throw new Error("NOT_FOUND");
    }
    return Object.assign({}, membership, {
      openid: normalizedOpenId,
      permissions: textList(membership.permissions),
      service_user_scopes: scopes,
    });
  }

  async function requireCaregiverAccess(input) {
    const membership = await requireMembership(input);
    if (!membership.permissions.includes("READ_SAFETY")) {
      throw new Error("CAREGIVER_PERMISSION_DENIED");
    }
    return membership;
  }

  async function requirePermission(input, permission) {
    const membership = await requireMembership(input);
    if (!membership.permissions.includes(permission)) {
      throw new Error("CAREGIVER_PERMISSION_DENIED");
    }
    return membership;
  }

  async function requireCommandAccess(input) {
    const membership = await requireMembership(input);
    if (
      String(membership.role || "").toUpperCase() === "VIEWER"
      || !membership.permissions.includes("CREATE_COMMAND")
    ) {
      throw new Error("CAREGIVER_PERMISSION_DENIED");
    }
    return membership;
  }

  return {
    isCurrentSafetyRecipient,
    listMyDevices,
    listSafetyRecipients,
    redeemPairingCode,
    requireCaregiverAccess,
    requireCommandAccess,
    requireMembership,
    requirePermission,
  };
}

module.exports = { createMembershipModule };
