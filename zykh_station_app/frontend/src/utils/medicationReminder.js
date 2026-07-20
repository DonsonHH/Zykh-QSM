const DEFAULT_WINDOW_MINUTES = 60;
const DEFAULT_NEARBY_MINUTES = 60;

function reminderState(minutesUntil) {
  return minutesUntil > 0 ? "soon" : minutesUntil < 0 ? "overdue" : "now";
}

export function getMedicationReminders(
  medication,
  now = new Date(),
  windowMinutes = DEFAULT_WINDOW_MINUTES,
  nearbyMinutes = DEFAULT_NEARBY_MINUTES
) {
  const candidates = (medication?.plans || [])
    .filter((plan) => plan.status === "待执行" && /^\d{2}:\d{2}$/.test(plan.time || ""))
    .map((plan) => {
      const [hours, minutes] = plan.time.split(":").map(Number);
      const scheduled = new Date(now);
      scheduled.setHours(hours, minutes, 0, 0);
      const minutesUntil = Math.round((scheduled.getTime() - now.getTime()) / 60000);
      return {
        plan,
        minutesUntil,
        scheduledAt: scheduled.getTime(),
        state: reminderState(minutesUntil)
      };
    })
    .filter(({ minutesUntil }) => Math.abs(minutesUntil) <= windowMinutes)
    .sort((left, right) => {
      const distance = Math.abs(left.minutesUntil) - Math.abs(right.minutesUntil);
      return distance || left.scheduledAt - right.scheduledAt;
    });

  if (!candidates.length) return [];
  const nearest = candidates[0];
  return candidates.filter(
    (candidate) => Math.abs(candidate.scheduledAt - nearest.scheduledAt) <= nearbyMinutes * 60000
  );
}

export function getMedicationReminder(medication, now = new Date(), windowMinutes = DEFAULT_WINDOW_MINUTES) {
  return getMedicationReminders(medication, now, windowMinutes)[0] || null;
}

export function getDueMedicationAnnouncements(medication, now = new Date(), graceMinutes = 5) {
  return (medication?.plans || [])
    .filter((plan) => plan.status === "待执行" && /^\d{2}:\d{2}$/.test(plan.time || ""))
    .map((plan) => {
      const [hours, minutes] = plan.time.split(":").map(Number);
      const scheduled = new Date(now);
      scheduled.setHours(hours, minutes, 0, 0);
      return { plan, elapsed: Math.floor((now.getTime() - scheduled.getTime()) / 60000) };
    })
    .filter(({ elapsed }) => elapsed >= 0 && elapsed <= graceMinutes)
    .sort((left, right) => left.plan.time.localeCompare(right.plan.time))
    .map(({ plan }) => plan);
}

export function buildMedicationReminderSpeech(plan) {
  const name = String(plan?.target_user || "家庭成员").trim() || "家庭成员";
  return `${name}，请服药了。`;
}

export function medicationAnnouncementKey(plan, now = new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}:${plan?.id || plan?.medicine_id || plan?.medicine || "plan"}:${plan?.time || ""}`;
}
