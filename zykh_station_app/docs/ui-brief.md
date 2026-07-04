# UI Brief

## Direction

The UI is a clean white medical home terminal for an 11-inch 1280x720 landscape touch display.

## Visual rules

- White or very light blue-gray background.
- Medical blue is the primary emphasis color, with teal, orange and soft purple accents.
- Orange is reserved for weak-network, risk or pending states.
- Large cards, large buttons, large text.
- Avoid dense tables, small technical labels and busy dashboard composition.
- Each screen should emphasize one or two core tasks.

## Navigation

Bottom navigation has exactly four items:

```text
首页 / 药品 / 问询 / 记录
```

首页、药品、问询、记录 are functional. 扫码识别 and 体征测量 are entered from home actions, not bottom tabs.

## Home structure

- Top: product name, home weak-network context, time, status chips.
- Main: 今日用药 and AI应急问询.
- Quick actions: 扫码识别, 身体状态测量, 服务记录.
