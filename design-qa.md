source visual truth: user-provided chat image for Jetson 1280x720 UI plus /home/jetson/.codex/attachments/879a4506-a534-42b6-9acb-6b26e6878e8d/pasted-text.txt
implementation screenshot path: /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-terminal-1280-final2.png and /home/jetson/Documents/zykh/Zykh-QSM/jetson_app/data/zykh-admin-1280-final.png
viewport: Chromium headless requested 1280x720; Jetson kiosk desktop screenshot also captured at /tmp/zykh-terminal-ui-fixed.png
state: terminal home and admin overview
full-view comparison evidence: terminal home and admin overview render with the requested dark control-screen style, glass cards, large touch controls, bottom navigation, QSM status, and separated admin console
focused region comparison evidence: checked terminal top status row, home card grid, bottom nav, admin device cards, admin log/quick-action panels

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
