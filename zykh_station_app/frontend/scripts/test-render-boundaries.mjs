import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { millisecondsUntilNextMinute } from "../src/hooks/useMinuteClock.js";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const app = await readFile(`${frontendRoot}src/App.jsx`, "utf8");
const topBar = await readFile(`${frontendRoot}src/components/TopBar.jsx`, "utf8");
const idleScreen = await readFile(`${frontendRoot}src/pages/IdleScreen.jsx`, "utf8");
const records = await readFile(`${frontendRoot}src/pages/Records.jsx`, "utf8");
const medicines = await readFile(`${frontendRoot}src/pages/Medicines.jsx`, "utf8");
const dispenseModal = await readFile(`${frontendRoot}src/components/DispenseConfirmModal.jsx`, "utf8");
const medicationTaskPicker = await readFile(`${frontendRoot}src/components/MedicationTaskPicker.jsx`, "utf8");

assert.equal(
  millisecondsUntilNextMinute(new Date("2026-08-05T15:21:12.345Z")),
  47_675,
  "clock refresh is not aligned just after the next minute boundary"
);
assert.doesNotMatch(app, /setNow|now=\{now\}/, "the app shell still rerenders every page for clock updates");
assert.doesNotMatch(app, /startTransition/, "page navigation is still deferred as low-priority rendering work");
assert.match(
  app,
  /commitViewChange\(transitionKind\(currentPage, nextPage, options\.transition\), \(\) => \{\s*applyNavigation\(\);/,
  "page navigation does not commit directly after transition feedback"
);
assert.match(app, /const handleNav = useCallback\(/, "polling can still replace the navigation callback and rerender the active page");
assert.match(app, /const pageRef = useRef\(initialPage\)/, "navigation still recreates its callback for every current page");
assert.match(app, /home-page-cache/, "the repeatedly visited home page is still remounted on every return");
assert.match(app, /medicines-page-cache/, "the medicine surface is still rebuilt and rerasterized on every visit");
assert.match(
  app,
  /useState\(initialPage === "medicines"\)/,
  "the hidden medicine cache still mounts during the initial home render"
);
assert.match(
  app,
  /if \(idle \|\| page === "admin"\) \{\s*setMedicinesMounted\(false\)/,
  "the medicine cache remounts in the background after sleep or admin mode tears it down"
);
assert.match(
  app,
  /dashboard=\{visibleHomeDashboard\}/,
  "the hidden home page still receives periodic dashboard snapshots and rerenders in the background"
);
assert.match(
  app,
  /visibleHomeDashboardRef\.current = dashboard/,
  "the last committed home dashboard snapshot is not retained while the page is hidden"
);
for (const page of ["Home", "Medicines", "Inquiry", "Records", "Scan", "Vitals", "Settings"]) {
  assert.match(app, new RegExp(`memo\\(${page}\\)`), `${page} is not isolated from unrelated app-shell polling renders`);
}
assert.match(topBar, /useMinuteClock\(\)/, "the top bar does not own its minute-level clock refresh");
assert.match(idleScreen, /useMinuteClock\(\)/, "the idle screen does not own its minute-level clock refresh");
assert.match(records, /RECORDS_REFRESH_INTERVAL_MS\s*=\s*3000/, "records no longer preserves its three-second data freshness");
assert.match(records, /const snapshotRef = useRef\(""\)/, "records does not retain the last rendered data snapshot");
assert.match(
  records,
  /if \(signature === snapshotRef\.current\) return;/,
  "unchanged records polling still reaches React state setters"
);
assert.match(medicines, /function VirtualMedicineGrid\(/, "the 23-slot medicine list still paints every row at once");
assert.match(
  medicines,
  /medicines\.slice\(firstRow \* 2, renderedLastRow \* 2\)/,
  "the medicine list does not limit rendering to visible rows"
);
assert.match(medicines, /role="listbox"/, "the virtual medicine list has no accessible composite role");
assert.match(medicines, /handleOptionKeyDown/, "off-screen medicine rows are unreachable by keyboard");
assert.match(
  medicines,
  /params\.get\("dispenseModal"\) === "1"[\s\S]*setConfirmMedicine\(selectedMedicine\)/,
  "the direct dispense-modal entry does not freeze its selected medicine"
);
assert.match(dispenseModal, /createPortal\(/, "the dispense modal remains trapped below cached page navigation");
assert.match(medicationTaskPicker, /createPortal\(/, "the home task picker remains trapped below cached page navigation");

console.log("render ownership boundaries: ok");
