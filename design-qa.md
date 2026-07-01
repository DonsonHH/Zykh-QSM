source visual truth: user-provided chat image for QSM 1280x720 UI plus /home/jetson/.codex/attachments/879a4506-a534-42b6-9acb-6b26e6878e8d/pasted-text.txt
implementation screenshot path: /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-terminal-1280-final2.png and /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-admin-1280-final.png
viewport: Chromium headless requested 1280x720; QSM kiosk desktop screenshot also captured at /tmp/zykh-terminal-ui-fixed.png
state: terminal home and admin overview
full-view comparison evidence: terminal home and admin overview render with the requested dark control-screen style, glass cards, large touch controls, bottom navigation, device connection status, and separated admin console
focused region comparison evidence: checked terminal top status row, home card grid, bottom nav, admin device cards, admin log/quick-action panels

**2026-07-01 Polish Pass**
- Added demo data seeding for competition display: 张三 profile, chronic disease/allergy context, 8 stocked cabinet slots, 3 medication plans, vitals and operation records.
- Home: clarified enabled/disabled dispense state, renamed plan metric to 启用计划, and changed the bottom stats into clearer small cards.
- Cabinet: strengthened touch target sizes, selected-slot glow, and stock-state borders for good/warn/danger/empty.
- Scan: replaced backend-like pause/refresh controls with 重新识别 / 拍照识别, added a camera connection badge, guide text and stronger focus corners, and shows a successful 连花清瘟胶囊 demo confirmation state.
- AI chat: prefilled a realistic consultation exchange, made quick prompts more visible, and exposed chronic disease/allergy context in the right panel.
- Admin: added a second confirmation before 测试开仓 triggers 外设设备 UART8 dispense.
- Kiosk: added `jetson_app/scripts/start_kiosk_720p.sh` to switch to 1280x720 for Chromium kiosk and restore the previous display mode on exit.
- Reliability: `loadSnapshot()` now loads QSM local profile, cabinet, plans, records and vitals even when `/api/status` is slow because the external device or ADB is offline.
- Layout: terminal/admin shells are fixed to the target `1280x720` kiosk canvas, matching the deployment script.

**Verification 2026-07-01**
- `npm run build`: passed.
- `jetson_app/backend/.venv/bin/python -m pytest`: 5 passed, 2 FastAPI deprecation warnings.
- Temporary unsandboxed route smoke: `/api/profile`, `/api/medicines`, `/api/plans`, `/`, `/terminal`, `/admin` all returned HTTP 200.
- Current QSM local DB was seeded through `jetson_app/scripts/seed_demo_data.sh`; the previous DB was backed up under `jetson_app/data/backups/`.
- Chromium headless screenshots generated under ignored `jetson_app/data/`: `zykh-home-fixed720.png`, `zykh-cabinet-fixed720.png`, `zykh-scan-fixed720.png`, `zykh-ai-fixed720.png`, `zykh-profile-fixed720.png`, `zykh-admin-fixed720.png`.
- Chromium snap headless reports a shorter visible viewport when `--window-size=1280,720`; a compensation screenshot `zykh-home-qa807.png` confirmed the full 1280x720 terminal canvas has no overlap. Physical kiosk should use `start_kiosk_720p.sh`.

**Findings**
- No remaining P0/P1/P2 findings.

**Open Questions**
- None.

**Implementation Checklist**
- Split default terminal UI and admin UI routes.
- Rebuild terminal pages in the dark 1280x720 control-screen style.
- Keep external-device-dependent actions disabled when the external device is offline.
- Verify terminal and admin screenshots render without React runtime errors or overlapping controls.

**Follow-up Polish**
- [P3] Chromium snap headless screenshots reserve a black band below the app content because its headless content viewport is shorter than the requested outer window. The visible kiosk desktop screenshot shows the terminal shell centered as intended; this does not block acceptance.
- [P3] After reviewing on the physical touch screen, tune final card density and typography if the user wants the design even closer to the reference mock.

patches made since previous QA pass: fixed missing React imports that caused a blank screen, compacted the terminal home grid to prevent bottom nav/status overlap, and regenerated terminal/admin screenshots
final result: passed

**2026-07-01 Design-System Pass**
- Rebased the visual system on explicit design tokens: 1280x720 shell, 88px header, 76px bottom nav, Noto CJK font stack, tabular numerals, 20/16/14px radius scale, stricter color tokens and softer card borders.
- Upgraded `GlassCard`, status chips, primary buttons, metric rows, cabinet cards, scan result confidence pill, AI chat bubbles and admin cards toward one shared visual language.
- Restored the homepage hierarchy: stronger 今日用药 button, clearer AI/体征 secondary focus, and controlled quick-entry colors.
- Added `/style-preview` as a non-kiosk design-system preview for buttons, forms, status chips and color swatches.
- Tightened cabinet right-side density so the plan editor is less likely to be clipped in 720p.

**Verification 2026-07-01 Design-System**
- `npm run build`: passed.
- `jetson_app/backend/.venv/bin/python -m pytest`: 6 passed, 2 FastAPI deprecation warnings.
- Chromium QA screenshots generated under ignored `jetson_app/data/`: `zykh-home-system-qa.png`, `zykh-cabinet-system-qa2.png`, `zykh-scan-system-qa.png`, `zykh-ai-system-qa.png`, `zykh-style-preview-qa.png`.
final result: passed

**2026-07-01 Refinement Pass**
- Added a shared 1280x720 kiosk scale hook for terminal and admin views so the canvas scales as a unit instead of each component reflowing independently.
- Tightened the global type system: Noto CJK font stack, anti-aliasing, shared font/line-height tokens, tabular numeric rendering and clearer disabled button styling.
- Reduced elderly-terminal technical wording: external-device and ADB details stay in admin; terminal shows "设备连接中 / 硬件功能暂不可用" style messages.
- Added admin demo controls backed by `POST /api/demo/seed` and `POST /api/demo/clear`.
- Fixed scan-page camera stream failure state: no browser broken-image icon, disabled capture while the stream is unavailable, and labels cached data as the latest result.
- Clarified admin device status by separating cached vitals from current external-device dependency.

**Verification 2026-07-01 Refinement**
- `npm run build`: passed.
- `jetson_app/backend/.venv/bin/python -m pytest`: 6 passed, 2 FastAPI deprecation warnings.
- Chromium QA screenshots generated under ignored `jetson_app/data/`: `zykh-home-refine-qa.png`, `zykh-cabinet-refine-qa2.png`, `zykh-scan-refine-qa2.png`, `zykh-ai-refine-qa.png`, `zykh-admin-refine-qa.png`.
- Remaining accepted limitation: Chromium snap headless still needs the same height compensation for screenshots; the physical kiosk path remains `start_kiosk_720p.sh`.
final result: passed

**2026-07-01 Home Reference Pass**
- Rebuilt the terminal home around the reference layout: 88px header, three large hero cards, three 96px shortcut cards, and no elderly-home statistics strip.
- Strengthened the home visual hierarchy: brighter take-medicine button, centered AI robot focal point, aligned vitals rows, and stronger green/blue/purple shortcut cards.
- Unified display naming: the main terminal is shown as QSM, while the connected hardware board is shown as 外设设备 / 外设网关 in terminal, admin, logs and docs.
- Added `qsm_main` to `/api/status`, removed the old public main-device status key, and covered that with a regression test.
- Added `start_qsm_app.sh`; kiosk and systemd scripts now use the QSM-named entry point.

**Verification 2026-07-01 Home Reference**
- `npm run build`: passed.
- `PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests`: 7 passed, 2 FastAPI deprecation warnings.
- Demo data seeded into the default QSM database through `jetson_app/scripts/seed_demo_data.sh`.
- Chromium QA screenshot generated under ignored `jetson_app/data/`: `zykh-home-qsm-main-qa.png`.
final result: passed

**2026-07-02 UI/UX + Review Pass**
- Applied the `ui-ux-pro-max` critical checks that fit this product: visible async feedback, no hover-only interactions, 44px+ touch targets, reduced-motion handling, and stable press feedback that does not shift layout.
- Added `useAsyncAction()` to centralize request-in-progress state and prevent repeated hardware/API actions from rapid taps.
- Wired busy states into terminal dispense, vitals read, cabinet save/open/plan, scan/confirm, AI chat/send/voice input/speak, and admin save/open/demo/reset actions.
- Review findings fixed:
  - Kept QSM display naming while restoring upgrade compatibility for old environment variables and existing `zykh_jetson.db` files.
  - Updated `jetson_app/.env.example` to the QSM variable names.
  - Updated user-service installation to disable the old `zykh-jetson.service` before enabling `zykh-qsm.service`.
- Standards review result: no hard documented-standard violations; judgement risk accepted because elderly-home cabinet stats moved out of the home screen to keep the reference-style terminal clean.

**Verification 2026-07-02 UI/UX + Review**
- `npm run build`: passed.
- `PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests`: 7 passed, 2 FastAPI deprecation warnings.
- `sh -n` passed for `start_qsm_app.sh`, `seed_demo_data.sh`, and `install_user_service.sh`.
- Chromium QA screenshot generated under ignored `jetson_app/data/`: `zykh-home-ui-pro-qa.png`.
final result: passed

**2026-07-02 Creative Tim Inspiration Pass**
- Reviewed `creativetimofficial/ui` as a component/block inspiration source, but did not add shadcn/Tailwind dependencies because the QSM terminal is a fixed 1280x720 touch kiosk.
- Borrowed the useful ideas only: production-style card polish, status badges, subtle component motion, and clearer feedback surfaces.
- Added glass-card light edge treatment, status LED dots, shortcut-card light sweep feedback, AI assistant pulse, and live-only camera scan sweep.
- Kept elderly-touch constraints intact: no extra navigation layer, no hover-only dependency, no decorative animation when reduced motion is requested.

**Verification 2026-07-02 Creative Tim Inspiration**
- `npm run build`: passed.
- `PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests`: 7 passed, 2 FastAPI deprecation warnings.
- Chromium QA screenshots generated under ignored `jetson_app/data/`: `zykh-home-creative-tim-qa.png`, `zykh-scan-creative-tim-qa.png`.
final result: passed
