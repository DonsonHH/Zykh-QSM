const crypto = require("crypto");
const { serviceUserDocumentId, serviceUserIdentity } = require("./serviceUserIdentity");

function textList(value) {
  return Array.isArray(value)
    ? value.map(item => String(item || "").trim()).filter(Boolean)
    : [];
}

function generationMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value)
    .map(([key, generation]) => [String(key || "").trim(), String(generation || "").trim()])
    .filter(([key, generation]) => key && generation));
}

function sameGenerationMap(scopes, left, right) {
  const expectedKeys = new Set(scopes);
  return Object.keys(left).length === expectedKeys.size
    && Object.keys(right).length === expectedKeys.size
    && scopes.every(scope => left[scope] === right[scope]);
}

function isArchived(row = {}) {
  return row.archived === true
    || Number(row.archived) === 1
    || String(row.archived || "").toLowerCase() === "true";
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

function requireDatabaseSuccess(result, failureCode = "DATABASE_REQUEST_FAILED") {
  const code = result && (result.errCode ?? result.code);
  const failedCode = (
    code !== undefined
    && code !== null
    && code !== 0
    && code !== "0"
    && String(code).toUpperCase() !== "OK"
  );
  const message = String((result && (result.errMsg || result.message)) || "");
  if (failedCode || /:fail\b/i.test(message)) {
    throw new Error(failureCode);
  }
  return result;
}

function documentNotFound(value) {
  const code = String((value && (value.errCode ?? value.code)) || "").toUpperCase();
  const message = String((value && (value.errMsg || value.message)) || value || "");
  return (
    code === "DATABASE_DOCUMENT_NOT_EXIST"
    || code === "DOCUMENT_NOT_EXIST"
    || /document(?:\s+with\s+_id\s+\S+)?\s+(?:does\s+)?not\s+exist|document\s+not\s+found|missing\s+document|文档不存在/i.test(message)
  );
}

const CAREGIVER_READ_PERMISSIONS = Object.freeze([
  "READ_SAFETY",
  "READ_INQUIRY",
  "READ_PLAN",
  "READ_PROFILE",
  "READ_RECORD",
  "READ_VITALS",
  "READ_MEDICINE",
]);

function createMembershipModule({ db, collections, nowText, nowEpochMs = () => Date.now() }) {
  function allowsPersona(membership, personId, personaGeneration) {
    const normalizedPersonId = String(personId || "").trim();
    const scopes = textList(
      membership.service_user_scopes || membership.serviceUserScopes,
    );
    if (normalizedPersonId && scopes.length && !scopes.includes(normalizedPersonId)) {
      return false;
    }
    const generations = generationMap(
      membership.service_user_generations || membership.serviceUserGenerations,
    );
    if (!Object.keys(generations).length) return true;
    if (!normalizedPersonId) return false;
    const expectedGeneration = generations[normalizedPersonId];
    const actualGeneration = String(personaGeneration || "").trim();
    return Boolean(expectedGeneration && actualGeneration === expectedGeneration);
  }

  async function documentOrNull(collection, id) {
    try {
      const result = await collection.doc(id).get();
      if (documentNotFound(result)) return null;
      requireDatabaseSuccess(result);
      return result && result.data ? result.data : null;
    } catch (error) {
      if (documentNotFound(error)) return null;
      throw new Error("DATABASE_REQUEST_FAILED");
    }
  }

  async function listMyDevices({ openId }) {
    const normalizedOpenId = String(openId || "").trim();
    if (!normalizedOpenId) throw new Error("miniprogram identity required");
    const rows = [];
    for (let offset = 0; ; offset += 100) {
      const result = requireDatabaseSuccess(await db.collection(collections.deviceMemberships)
        .where({ openid: normalizedOpenId, status: "ACTIVE" })
        .skip(offset)
        .limit(100)
        .get());
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

  async function currentServiceUserGenerations(deviceId, scopes) {
    const wanted = new Set(scopes);
    const matches = new Map(scopes.map(scope => [scope, []]));
    for (let offset = 0; ; offset += 100) {
      const result = requireDatabaseSuccess(await db.collection(collections.serviceUsers)
        .where({ deviceId })
        .skip(offset)
        .limit(100)
        .get());
      const page = result.data || [];
      page.forEach(row => {
        const personId = String(row.id || row.user_id || row.userId || "").trim();
        const generation = String(row.persona_generation || row.personaGeneration || "").trim();
        if (wanted.has(personId) && generation && !isArchived(row)) {
          matches.get(personId).push(generation);
        }
      });
      if (page.length < 100) break;
    }
    const resolved = {};
    for (const scope of scopes) {
      const generations = Array.from(new Set(matches.get(scope) || []));
      if (generations.length !== 1) throw new Error("PAIRING_CODE_ISSUE_INVALID");
      resolved[scope] = generations[0];
    }
    return resolved;
  }

  async function requireCurrentMembershipGeneration(membership, deviceId, personId) {
    const normalizedPersonId = String(personId || "").trim();
    if (!normalizedPersonId) return "";
    let current;
    try {
      current = await currentServiceUserGenerations(deviceId, [normalizedPersonId]);
    } catch (error) {
      throw new Error("NOT_FOUND");
    }
    const currentGeneration = current[normalizedPersonId];
    const generations = generationMap(
      membership.service_user_generations || membership.serviceUserGenerations,
    );
    if (!Object.keys(generations).length) return currentGeneration;
    const expectedGeneration = generations[normalizedPersonId];
    if (!expectedGeneration) throw new Error("NOT_FOUND");
    if (currentGeneration !== expectedGeneration) {
      throw new Error("NOT_FOUND");
    }
    return currentGeneration;
  }

  async function issuePairingCode(data = {}) {
    const deviceId = String(data.deviceId || "").trim();
    const codeHash = String(data.codeHash || "").trim();
    const ttlSeconds = Number(data.ttlSeconds);
    const serviceUserScopes = Array.from(new Set(textList(data.serviceUserScopes)));
    const expectedGenerations = generationMap(data.serviceUserGenerations);
    const hasCallerSelectedCredentials = [
      "role",
      "permissions",
      "pairingCode",
      "code",
      "expiresAt",
    ].some(field => Object.prototype.hasOwnProperty.call(data, field));
    if (
      !deviceId
      || !/^[a-f0-9]{64}$/.test(codeHash)
      || !Number.isInteger(ttlSeconds)
      || ttlSeconds < 300
      || ttlSeconds > 900
      || !serviceUserScopes.length
      || serviceUserScopes.length > 8
      || hasCallerSelectedCredentials
    ) throw new Error("PAIRING_CODE_ISSUE_INVALID");

    if (typeof db.runTransaction !== "function") {
      throw new Error("PAIRING_CODE_ISSUE_INVALID");
    }
    const serviceUserGenerations = await currentServiceUserGenerations(deviceId, serviceUserScopes);
    if (
      Object.keys(expectedGenerations).length
      && !sameGenerationMap(serviceUserScopes, expectedGenerations, serviceUserGenerations)
    ) throw new Error("PAIRING_CODE_ISSUE_INVALID");
    const pairingDocumentId = `pairing-${codeHash}`;
    return db.runTransaction(async transaction => {
      const pairingCollection = transaction.collection(collections.devicePairingCodes);
      if (await documentOrNull(pairingCollection, pairingDocumentId)) {
        throw new Error("PAIRING_CODE_ISSUE_INVALID");
      }

      const serviceUserCollection = transaction.collection(collections.serviceUsers);
      for (const scope of serviceUserScopes) {
        const row = await documentOrNull(
          serviceUserCollection,
          serviceUserDocumentId(deviceId, {
            id: scope,
            persona_generation: serviceUserGenerations[scope],
          }),
        );
        let identity = null;
        try {
          identity = row ? serviceUserIdentity(row) : null;
        } catch (error) {
          identity = null;
        }
        if (
          !row
          || String(row.deviceId || "").trim() !== deviceId
          || !identity
          || identity.personId !== scope
          || identity.generation !== serviceUserGenerations[scope]
          || isArchived(row)
        ) throw new Error("PAIRING_CODE_ISSUE_INVALID");
      }

      const timestamp = nowText();
      const issuedAt = Number(nowEpochMs());
      if (!Number.isFinite(issuedAt)) throw new Error("PAIRING_CODE_ISSUE_INVALID");
      const expiresAt = new Date(issuedAt + ttlSeconds * 1000).toISOString();
      requireDatabaseSuccess(
        await pairingCollection.doc(pairingDocumentId).set({
          data: {
            codeHash,
            deviceId,
            role: "CAREGIVER",
            permissions: [...CAREGIVER_READ_PERMISSIONS],
            service_user_scopes: serviceUserScopes,
            service_user_generations: serviceUserGenerations,
            status: "UNUSED",
            expiresAt,
            createdAt: timestamp,
            updatedAt: timestamp,
          },
        }),
        "PAIRING_CODE_ISSUE_INVALID",
      );
      return {
        ok: true,
        deviceId,
        role: "CAREGIVER",
        permissions: [...CAREGIVER_READ_PERMISSIONS],
        serviceUserScopes,
        serviceUserGenerations,
        status: "UNUSED",
        expiresAt,
      };
    });
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
    const pairingBeforeTransaction = await documentOrNull(
      db.collection(collections.devicePairingCodes),
      pairingDocumentId,
    );
    const initialDeviceId = String(
      (pairingBeforeTransaction && (pairingBeforeTransaction.deviceId || pairingBeforeTransaction.device_id))
      || "",
    ).trim();
    if (!initialDeviceId) throw new Error("PAIRING_CODE_INVALID");
    const initialScopes = textList(
      pairingBeforeTransaction.service_user_scopes || pairingBeforeTransaction.serviceUserScopes,
    );
    const initialGenerations = generationMap(
      pairingBeforeTransaction.service_user_generations || pairingBeforeTransaction.serviceUserGenerations,
    );
    if (Object.keys(initialGenerations).length) {
      let currentGenerations;
      try {
        currentGenerations = await currentServiceUserGenerations(initialDeviceId, initialScopes);
      } catch (error) {
        throw new Error("PAIRING_CODE_INVALID");
      }
      if (!sameGenerationMap(initialScopes, currentGenerations, initialGenerations)) {
        throw new Error("PAIRING_CODE_INVALID");
      }
    }
    const existingMemberships = requireDatabaseSuccess(await db
      .collection(collections.deviceMemberships)
      .where({ openid: normalizedOpenId, deviceId: initialDeviceId })
      .limit(1)
      .get());
    if ((existingMemberships.data || []).length) throw new Error("PAIRING_CODE_INVALID");

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
      const serviceUserGenerations = generationMap(
        pairing.service_user_generations || pairing.serviceUserGenerations,
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
        || deviceId !== initialDeviceId
        || !allowedRoles.has(role)
        || permissions.some(permission => !allowedPermissions.has(permission))
      ) throw new Error("PAIRING_CODE_INVALID");

      const membershipCollection = transaction.collection(collections.deviceMemberships);
      const membershipId = `membership-${sha256(`${deviceId}\u0000${normalizedOpenId}`)}`;
      if (await documentOrNull(membershipCollection, membershipId)) {
        throw new Error("PAIRING_CODE_INVALID");
      }

      const timestamp = nowText();
      const membershipData = {
          membershipId,
          openid: normalizedOpenId,
          deviceId,
          role,
          permissions,
          service_user_scopes: serviceUserScopes,
          status: "ACTIVE",
          createdAt: timestamp,
          updatedAt: timestamp,
      };
      if (Object.keys(serviceUserGenerations).length) {
        membershipData.service_user_generations = serviceUserGenerations;
      }
      requireDatabaseSuccess(await membershipCollection.doc(membershipId).set({
        data: membershipData,
      }));

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
      requireDatabaseSuccess(
        await pairingCollection.doc(pairingDocumentId).set({ data: consumedPairing }),
      );

      const response = {
        ok: true,
        deviceId,
        role,
        permissions,
        serviceUserScopes,
      };
      if (Object.keys(serviceUserGenerations).length) {
        response.serviceUserGenerations = serviceUserGenerations;
      }
      return response;
    });
  }

  async function listActiveMemberships(deviceId) {
    const rows = [];
    for (let offset = 0; ; offset += 100) {
      const result = requireDatabaseSuccess(await db.collection(collections.deviceMemberships)
        .where({ deviceId, status: "ACTIVE" })
        .skip(offset)
        .limit(100)
        .get());
      const page = result.data || [];
      rows.push(...page);
      if (page.length < 100) return rows;
    }
  }

  async function listSafetyRecipients({ deviceId, personId, personaGeneration }) {
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
        service_user_generations: generationMap(
          membership.service_user_generations || membership.serviceUserGenerations,
        ),
      }))
      .filter(membership => membership.membershipId && membership.openid)
      .filter(membership => membership.permissions.includes("READ_SAFETY"))
      .filter(membership => allowsPersona(
        membership,
        normalizedPersonId,
        personaGeneration,
      ));
  }

  async function isCurrentSafetyRecipient({
    database,
    membershipId,
    openid,
    deviceId,
    personId,
    personaGeneration,
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
    return allowsPersona(membership, personId, personaGeneration);
  }

  async function requireMembership({
    openId,
    deviceId,
    personId = "",
    personaGeneration = null,
  }) {
    const normalizedOpenId = String(openId || "").trim();
    if (!normalizedOpenId) throw new Error("miniprogram identity required");
    const result = requireDatabaseSuccess(await db.collection(collections.deviceMemberships)
      .where({ openid: normalizedOpenId, deviceId, status: "ACTIVE" })
      .limit(1)
      .get());
    const membership = (result.data || [])[0];
    if (!membership) throw new Error("CAREGIVER_MEMBERSHIP_REQUIRED");

    const scopes = textList(
      membership.service_user_scopes || membership.serviceUserScopes,
    );
    const normalizedPersonId = String(personId || "").trim();
    if (normalizedPersonId && scopes.length && !scopes.includes(normalizedPersonId)) {
      throw new Error("NOT_FOUND");
    }
    if (
      normalizedPersonId
      && personaGeneration !== null
      && !allowsPersona(membership, normalizedPersonId, personaGeneration)
    ) {
      throw new Error("NOT_FOUND");
    }
    return Object.assign({}, membership, {
      openid: normalizedOpenId,
      permissions: textList(membership.permissions),
      service_user_scopes: scopes,
      service_user_generations: generationMap(
        membership.service_user_generations || membership.serviceUserGenerations,
      ),
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
    const currentPersonaGeneration = await requireCurrentMembershipGeneration(
      membership,
      input.deviceId,
      input.personId,
    );
    return Object.assign({}, membership, {
      current_persona_generation: currentPersonaGeneration,
    });
  }

  return {
    allowsPersona,
    issuePairingCode,
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
