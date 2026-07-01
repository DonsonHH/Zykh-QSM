source visual truth: user-provided chat image for Jetson 1280x720 UI plus /home/jetson/.codex/attachments/879a4506-a534-42b6-9acb-6b26e6878e8d/pasted-text.txt
implementation screenshot path: /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-terminal-1280-final2.png and /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-admin-1280-final.png
viewport: Chromium headless requested 1280x720; Jetson kiosk desktop screenshot also captured at /tmp/zykh-terminal-ui-fixed.png
state: terminal home and admin overview
full-view comparison evidence: terminal home and admin overview render with the requested dark control-screen style, glass cards, large touch controls, bottom navigation, QSM status, and separated admin console
focused region comparison evidence: checked terminal top status row, home card grid, bottom nav, admin device cards, admin log/quick-action panels

**2026-07-01 Polish Pass**
- Added demo data seeding for competition display: 张三 profile, chronic disease/allergy context, 8 stocked cabinet slots, 3 medication plans, vitals and operation records.
- Home: clarified enabled/disabled dispense state, renamed plan metric to 启用计划, and changed the bottom stats into clearer small cards.
- Cabinet: strengthened touch target sizes, selected-slot glow, and stock-state borders for good/warn/danger/empty.
- Scan: replaced backend-like pause/refresh controls with 重新识别 / 拍照识别, added a camera connection badge, guide text and stronger focus corners, and shows a successful 连花清瘟胶囊 demo confirmation state.
- AI chat: prefilled a realistic consultation exchange, made quick prompts more visible, and exposed chronic disease/allergy context in the right panel.
- Admin: added a second confirmation before 测试开仓 triggers QSM UART8 dispense.
- Kiosk: added `jetson_app/scripts/start_kiosk_720p.sh` to switch to 1280x720 for Chromium kiosk and restore the previous display mode on exit.
- Reliability: `loadSnapshot()` now loads Jetson local profile, cabinet, plans, records and vitals even when `/api/status` is slow because QSM/ADB is offline.
- Layout: terminal/admin shells are fixed to the target `1280x720` kiosk canvas, matching the deployment script.

**Verification 2026-07-01**
- `npm run build`: passed.
- `jetson_app/backend/.venv/bin/python -m pytest`: 5 passed, 2 FastAPI deprecation warnings.
- Temporary unsandboxed route smoke: `/api/profile`, `/api/medicines`, `/api/plans`, `/`, `/terminal`, `/admin` all returned HTTP 200.
- Current Jetson local DB was seeded through `jetson_app/scripts/seed_demo_data.sh`; the previous DB was backed up under `jetson_app/data/backups/`.
- Chromium headless screenshots generated under ignored `jetson_app/data/`: `zykh-home-fixed720.png`, `zykh-cabinet-fixed720.png`, `zykh-scan-fixed720.png`, `zykh-ai-fixed720.png`, `zykh-profile-fixed720.png`, `zykh-admin-fixed720.png`.
- Chromium snap headless reports a shorter visible viewport when `--window-size=1280,720`; a compensation screenshot `zykh-home-qa807.png` confirmed the full 1280x720 terminal canvas has no overlap. Physical kiosk should use `start_kiosk_720p.sh`.

**Findings**
- No remaining P0/P1/P2 findings.

**Open Questions**
- None.

**Implementation Checklist**
- Split default terminal UI and admin UI routes.
- Rebuild terminal pages in the dark 1280x720 control-screen style.
- Keep QSM-dependent actions disabled when QSM is offline.
- Verify terminal and admin screenshots render without React runtime errors or overlapping controls.

**Follow-up Polish**
- [P3] Chromium snap headless screenshots reserve a black band below the app content because its headless content viewport is shorter than the requested outer window. The visible kiosk desktop screenshot shows the terminal shell centered as intended; this does not block acceptance.
- [P3] After reviewing on the physical touch screen, tune final card density and typography if the user wants the design even closer to the reference mock.

patches made since previous QA pass: fixed missing React imports that caused a blank screen, compacted the terminal home grid to prevent bottom nav/status overlap, and regenerated terminal/admin screenshots
final result: passed
