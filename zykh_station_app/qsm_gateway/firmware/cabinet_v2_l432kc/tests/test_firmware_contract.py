#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "main.c"
LINKER_PATH = ROOT / "linker.ld"
EXPECTED_SOURCE_SHA256 = "e8bf18ff9facc8986bef3ccbb38230e308efc330eff71f0ea2896429e3c86617"
EXPECTED_LINKER_SHA256 = "43d76886940e95a6f32d3c26ba888f6888a2472c4376095d5dd58642a99c4881"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def define(source: str, name: str) -> int:
    match = re.search(
        rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|[0-9]+)u?\s*$",
        source,
        re.MULTILINE,
    )
    assert match, f"missing integer define: {name}"
    return int(match.group(1), 0)


def require_tokens(source: str, description: str, *tokens: str) -> None:
    missing = [token for token in tokens if token not in source]
    assert not missing, f"{description}: missing {missing}"


def main() -> None:
    source = SOURCE_PATH.read_text(encoding="ascii")

    assert sha256(SOURCE_PATH) == EXPECTED_SOURCE_SHA256, "release source changed"
    assert sha256(LINKER_PATH) == EXPECTED_LINKER_SHA256, "linker script changed"

    assert define(source, "LED_COUNT") == 64
    assert define(source, "LEDS_PER_ROW") == 8
    assert define(source, "REAR_ROWS_FIRST_LED") == 40
    assert define(source, "PANEL_BRIGHTNESS") == 30
    assert define(source, "WS_PERIOD_TICKS") == 20
    assert define(source, "WS_T0H_TICKS") == 5
    assert define(source, "WS_T1H_TICKS") == 10
    assert define(source, "WS_DMA_TRIGGER_TICKS") == 11
    assert define(source, "WS_RESET_BITS") == 400
    require_tokens(
        source,
        "selected cabinet drives exactly one panel",
        "ws2812_send_panel(&TIM1_CCR1, selected == 1u);",
        "ws2812_send_panel(&TIM1_CCR2, selected == 2u);",
        "ws2812_send_panel(&TIM1_CCR3, selected == 3u);",
        "uint32_t cabinet_v2_pixel_brightness(uint32_t led, uint32_t enabled)",
        "uint32_t value = cabinet_v2_pixel_brightness(led, enabled);",
        "static inline __attribute__((always_inline))",
    )

    require_tokens(
        source,
        "TIM1 DMA waveform",
        "DMA1_CNDTR4 = WS_FRAME_BITS + 1u;",
        "DMA1_CPAR4 = (uint32_t)(uintptr_t)ccr;",
        "DMA1_CMAR4 = (uint32_t)(uintptr_t)&duties[0];",
        "TIM1_DIER = (1u << 12);",
        "while ((DMA1_ISR & (1u << 13)) == 0u) {}",
        "*ccr = 0u;",
    )
    assert "*ccr = duties[0]" not in source, "first bit must not be preloaded"

    require_tokens(
        source,
        "cabinet output pinout",
        "GPIOA_MODER = (GPIOA_MODER & ~(3u << 16)) | (2u << 16);",
        "GPIOA_AFRH = (GPIOA_AFRH & ~(0xFu << 0)) | (1u << 0);",
        "GPIOB_MODER = (GPIOB_MODER & ~((3u << 0) | (3u << 2))) |",
        "GPIOB_AFRL = (GPIOB_AFRL & ~((0xFu << 0) | (0xFu << 4))) |",
        "TIM1_CCER = (1u << 0) | (1u << 6) | (1u << 10);",
    )
    require_tokens(
        source,
        "ST-LINK VCP USART2 setup",
        "GPIOA_MODER & ~((3u << 4) | (3u << 30))",
        "GPIOA_AFRL = (GPIOA_AFRL & ~(0xFu << 8)) | (7u << 8);",
        "GPIOA_AFRH = (GPIOA_AFRH & ~(0xFu << 28)) | (3u << 28);",
        "*(volatile uint32_t *)(USART2_BASE + 0x0Cu) = 139u;",
    )

    for command in ("PING", "CABINET 1", "CABINET 2", "CABINET 3", "STATUS", "OFF"):
        assert f'"{command}"' in source, f"missing protocol command: {command}"
    for response_literal in (
        "PONG\\r\\n",
        "OK CABINET 1\\r\\n",
        "OK CABINET 2\\r\\n",
        "OK CABINET 3\\r\\n",
        "OK OFF\\r\\n",
        "STATUS CABINET 1\\r\\n",
        "STATUS CABINET 2\\r\\n",
        "STATUS CABINET 3\\r\\n",
        "STATUS OFF\\r\\n",
    ):
        assert f'"{response_literal}"' in source, f"missing protocol response: {response_literal}"
    require_tokens(
        source,
        "fail-closed parser and safe boot",
        'uart_write(base, "ERR COMMAND\\r\\n");',
        "uint8_t selected = 0u;",
        "show_cabinet(0u);",
    )

    period_ns = define(source, "WS_PERIOD_TICKS") * 62.5
    reset_us = define(source, "WS_RESET_BITS") * period_ns / 1000
    assert period_ns == 1250.0
    assert reset_us == 500.0
    print(
        "FIRMWARE_CONTRACT PASS "
        "cabinet_outputs=PA8,PB0,PB1 active_led_ranges=0-7,40-63 "
        "active_leds=32 brightness=30 "
        "uart=/dev/ttyACM0@115200 protocol=PING,CABINET,STATUS,OFF "
        f"source_sha256={sha256(SOURCE_PATH)}"
    )


if __name__ == "__main__":
    main()
