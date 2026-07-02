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

**2026-07-02 Image Reference + Hardware Link Pass**
- Rebuilt the terminal home closer to the latest user reference: larger 1280x720 topbar, three hero cards, three 3D-style shortcut tiles, stronger orange/purple/blue card emphasis, and full-width touch bottom nav.
- Added local visual assets for the AI robot, camera, calendar, and profile folder so the home screen no longer depends on flat placeholder icons.
- Added light touch feedback: ripple press states, hero-card status glow, robot float/aura motion, shortcut image press response, and primary-button light sweep. Existing reduced-motion CSS disables these for users who request it.
- Added `/api/admin/hardware_check` and a management-page "外设检查" panel for non-mechanical checks: ADB/forward/status, camera capture, vitals read, speaker test, and ASR recording.
- Fixed external-device HTTP calls to ignore system proxy variables (`trust_env=False`), which prevented `127.0.0.1:18080` from working when a local SOCKS proxy was configured.

**Verification 2026-07-02 Image Reference + Hardware Link**
- `npm run build`: passed.
- `PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests`: 7 passed, 2 FastAPI deprecation warnings.
- `python3 -m py_compile jetson_app/backend/app/main.py`: passed.
- Chromium QA screenshot generated under ignored `jetson_app/data/`: `qsm-home-image-to-code-qa4.png`; because snap Chromium reports a shorter CSS viewport than its requested outer window, the QA capture used `--window-size=1280,807` to show the true 1280x720 kiosk canvas.
- Real external-device link:
  - `adb devices -l`: connected `product:rk3568-linux model:Nexus_4 device:mako`.
  - `adb forward --list`: `tcp:18080 tcp:8080`.
  - `curl http://127.0.0.1:18080/api/status`: passed, external device returned Buildroot/aarch64 status plus I2C/UART/video inventories.
  - Camera capture: passed, `/api/camera/capture` returned `ok:true` and captured 1280x720 JPEG via `/dev/video23`.
  - Speaker test: passed, `/api/audio/speak` returned `ok:true`.
  - Microphone/ASR: recording passed on `plughw:2,0`; no clear speech detected in the test environment, so ASR text was empty.
  - Vitals: external API call passed; GY-614 temperature returned about 36.48C, MAX30102 currently reports `write reg 0x09 failed` and `finger_detected:false`, so heart-rate/SPO2 require sensor/I2C/power/finger-placement troubleshooting.
final result: passed

**2026-07-02 Peripheral Recheck + Fix Pass**
- Rechecked peripherals one by one under the QSM main + external-device architecture.
- Fixed GY-614 script behavior: `read_gy614_uart4.pl` now uses non-blocking UART reads so its internal deadline works instead of hanging until `timeout` kills the process.
- Fixed stale sensor false positives: `zykh_app/server.pl` now removes old sensor JSON before each read and only reports a sensor script as ok when its exit code is 0. Failed scripts can still return diagnostic `data`, but no longer masquerade as successful hardware reads.
- Fixed camera preview/capture contention for the terminal scan flow:
  - QSM main now exposes `POST /api/camera/stream/stop`.
  - Camera capture and medicine scan stop the external camera stream before taking a still image.
  - Scan UI pauses stream, calls stop, waits briefly, then starts recognition.
  - External `server.pl` waits longer after stopping stream/preview and force-cleans stale stream processes.
- Fixed QSM main MJPEG proxy: `QsmClient.stream_bytes()` now uses `trust_env=False`, matching normal JSON and image requests, so local SOCKS proxy settings do not break `/api/camera/stream`.

**Peripheral Results 2026-07-02**
- ADB/forward: passed. External device visible as `product:rk3568-linux model:Nexus_4`; `tcp:18080 tcp:8080` present.
- External status API: passed. `/api/status` returns Buildroot/aarch64 device inventory.
- Camera still capture: passed. Captured 1280x720 JPEG and visually confirmed real scene.
- Camera stream: passed at the byte-stream level. A 5-second stream pull produced about 4.2MB of MJPEG data.
- Scan flow: after stream-stop fix, QSM main `/api/medicine/scan` returns ok with camera capture fallback when no clear barcode is visible. A real barcode/QR needs to be placed in frame for recognition success.
- GY-614 forehead temperature: fixed and passed. Direct script returned `RC=0` with realtime UART4 frame and `body_temp_c` around 35.3-35.8C.
- MAX30102 heart-rate/SPO2: failed at hardware/I2C level. `i2cdetect -y 3` does not show address `0x57`; direct script fails at `write reg 0x09 failed`. This points to sensor power/wiring/bus/address rather than QSM main UI/backend.
- Speaker: passed by API. `/api/audio/speak` and `/api/audio/beep` returned ok.
- Microphone: passed for recording. Pulled WAV is 3.0s, mono 8000Hz PCM, non-zero amplitude; ASR returned empty text because no clear speech was captured during the test.
- UART8 dispense: passed. `/api/dispense slot=1` returned `UART8 已发送仓位 1 控制字节 0x00`.

**Current limitation**
- The latest QSM main stream proxy fix requires restarting `zykh-qsm.service` before the running browser sees it. Runtime restart and Git push were blocked by the current sandbox approval/usage limit; code-level checks passed.
final result: partial-pass

**2026-07-02 Live Peripheral Repair Follow-up**
- Restarted the local QSM main backend and the external-device Perl gateway, then rechecked the live ADB/forward path.
- Fixed microphone recording after finding ALSA `Capture MIC Path` was `MIC OFF`; `record_audio()` now initializes the external device to `Main Mic` before `arecord`.
- Verified microphone repair by resetting `Capture MIC Path` back to `MIC OFF`, calling `/api/audio/asr`, then pulling the WAV: 3.0s mono 8000Hz PCM with non-zero amplitude (`peak` around 6449, `avg_abs` around 657).
- Hardened camera failure handling for the current external-device state:
  - Avoids scanning every `/dev/video*` node because some ISP nodes block.
  - Uses the known QSM CSI camera node `/dev/video5`.
  - Adds a fast `v4l2-ctl` preflight before still capture and MJPEG stream so disconnected camera hardware returns a clear error instead of hanging.
  - Lowers default CSI capture size from 1280x720 to 800x600, matching the external camera node's reported capability.
- Current camera result: failed at hardware/media-link level, not UI/backend. `/api/camera/capture` and `/api/camera/stream` now return quickly with `摄像头硬件链路不可用`; preflight detail is `VIDIOC_STREAMON returned -1 (No such device)`.
- Kernel/media evidence for camera: `dmesg` reports `rockchip-csi2-dphy1: No link between dphy and sensor` and `rkisp-vir0: update sensor info failed -19`. Check camera ribbon cable, sensor power, and media pipeline before expecting live preview.
- Current GY-614 result: passed. `/api/admin/hardware_check action=vitals` returns `gy614.ok=true` and realtime body temperature around 35.8C.
- Current MAX30102 result: still failed at I2C/hardware level. `/api/admin/hardware_check action=vitals` returns `write reg 0x09 failed`; `i2cdetect -y 3` previously showed no `0x57`.
- Current speaker result: passed. `/api/audio/speak` and `/api/audio/beep` returned ok.
- Current UART8 dispense result: not re-triggered in this follow-up because it is a real mechanical action. Earlier same-day test returned ok for slot 1; repeat testing should be done only with explicit on-site confirmation.

**Verification 2026-07-02 Live Peripheral Repair Follow-up**
- `perl -c zykh_app/server.pl`: passed.
- External-device gateway restart: passed, service started with new PID.
- QSM main `/api/status`: passed; external device online through ADB forward.
- `/api/audio/asr`: passed for recording after automatic mic setup; ASR text empty when no clear speech was spoken.
- `/api/camera/capture`: failed fast with hardware-link diagnostic instead of timing out.
- `/api/camera/stream`: failed fast with hardware-link diagnostic instead of timing out.
final result: partial-pass
