# 三分类柜 STM32L432KC 固件

这是 2.0 硬件基线的最小、可复现固件资料。它把 QSM 主机发来的文本命令转换为三块 WS2812B 面板的指示灯状态；取药动作由用户自行开柜完成，固件不控制柜门。

本目录只跟踪源码、链接脚本、测试和构建说明。历史实验产物及设备 flash 快照仍保存在本机快照中，不纳入 Git；尤其不要提交 256 KiB 的整片 flash dump。

## 硬件与接线

目标板为 STM32L432KC（Nucleo-32）。QSM 通过 ST-LINK Virtual COM Port 连接 USART2，在 Linux 上实测为 `/dev/ttyACM0`，串口参数为 115200、8N1、无流控，命令以 CRLF 结束。

| 用途 | MCU 引脚 | Nucleo 标记 | 外设 |
| --- | --- | --- | --- |
| 分类柜 1 灯带 | PA8 | D9 | TIM1_CH1 |
| 分类柜 2 灯带 | PB0 | D3 | TIM1_CH2N |
| 分类柜 3 灯带 | PB1 | D6 | TIM1_CH3N |
| ST-LINK VCP TX | PA2 | — | USART2_TX, AF7 |
| ST-LINK VCP RX | PA15 | — | USART2_RX, AF3 |

三块灯板和控制板必须共地。每块面板按 8×8、共 64 颗像素发送数据；选中柜只点亮第一排和最后三排，即像素 `0–7` 与 `40–63`，共 32 颗白灯（GRB 三通道同为 30）。中间四排、其余像素及另外两柜保持熄灭。固件上电后默认执行全灭。

## 串口协议

每次请求和响应均为一行 ASCII 文本，以 `\r\n` 结束。选择新的柜会自动熄灭另外两柜；固件没有自动熄灯计时，应用在用户确认取药后必须发送 `OFF`。

| 请求 | 成功响应 | 行为 |
| --- | --- | --- |
| `PING` | `PONG` | 连通性检查，不改变灯态 |
| `CABINET 1` | `OK CABINET 1` | 仅点亮分类柜 1 |
| `CABINET 2` | `OK CABINET 2` | 仅点亮分类柜 2 |
| `CABINET 3` | `OK CABINET 3` | 仅点亮分类柜 3 |
| `STATUS` | `STATUS OFF` 或 `STATUS CABINET n` | 查询当前灯态 |
| `OFF` | `OK OFF` | 熄灭三柜 |

未知或格式错误的命令返回 `ERR COMMAND`，不改变当前选择。

## 构建与校验

经验证的工具链为 `arm-none-eabi-gcc 10.3.1` 与 GNU binutils `2.38`。构建脚本关闭 build-id，并在生成后强制核对固件哈希：

```sh
TOOLCHAIN=/path/to/arm-none-eabi/bin ./build.sh
```

也可在工具链已经位于 `PATH` 时直接运行 `./build.sh`。输出位于未跟踪的 `build/`：

- `main.c` SHA-256：`e8bf18ff9facc8986bef3ccbb38230e308efc330eff71f0ea2896429e3c86617`
- `linker.ld` SHA-256：`43d76886940e95a6f32d3c26ba888f6888a2472c4376095d5dd58642a99c4881`
- `firmware.bin`：1504 字节
- `firmware.bin` SHA-256：`91776e0fac42163f7151fb0e1c4df6cf2c2bb81b8e80c17581a77523776813db`

这个构建结果对应“第一排 + 最后三排”的 32 灯版本；设备前 1504 字节 readback 已与上述固件 SHA-256 完全一致。此前 24 灯基线的设备前 1500 字节 readback SHA-256 为 `897129e7ec7b448e47af0c072e17bcc5fc511abda960f752867e4d250e408271`，整片 flash 快照 SHA-256 为 `8f869a1cb39eda1a3562f7f5cc766627feafd6ac219e009d5eb262fc14b56766`，二者只用于回滚核对，文件本身不在本目录中。

运行不接触硬件的合同测试：

```sh
./test.sh
```

同时执行可复现构建：

```sh
TOOLCHAIN=/path/to/arm-none-eabi/bin FIRMWARE_TEST_BUILD=1 ./test.sh
```

实机只读握手示例：

```sh
./tools/serial_command_test.sh /dev/ttyACM0 PING PONG
./tools/serial_command_test.sh /dev/ttyACM0 STATUS 'STATUS OFF'
```

单板点亮测试示例（此时只允许连接并供电一块 WS2812B 灯板）：

```sh
ALLOW_LIGHT_COMMANDS=1 LIGHT_HOLD_SECONDS=10 \
  ./tools/serial_command_test.sh /dev/ttyACM0 'CABINET 1' 'OK CABINET 1'
```

点亮脚本会先要求系统中恰好只有一个 `ttyACM` 控制器，并核对它与显式传入的设备一致；随后持有与 QSM 网关相同的硬件互斥锁，完整串行执行 `OFF → STATUS OFF → CABINET n → STATUS CABINET n → 限时观察 → OFF → STATUS OFF`。另一个并发点亮测试会在接触串口前被拒绝；错误或中断退出也会尽力再次执行 `OFF + STATUS OFF`，只有最终状态核对成功才认定测试已安全结束。`LIGHT_HOLD_SECONDS` 只允许 0–30 秒，默认 10 秒。实机测试一次只能选择一个 `CABINET n`，不得并行测试多块灯板。刷写前应先备份当前 flash、确认唯一目标设备，并确保 QSM 网关已停止占用串口；本目录不自动刷写固件。

STM32L4 在擦除首个 flash 页后可能暂时保留 `FLASH_SR.PEMPTY`，此时即使新向量已经写入，普通系统复位仍会进入系统 Boot ROM。烧录验收必须先确认 PC 位于 `0x08000000` 主 flash，并取得 `PONG`；若检测到 `PEMPTY`，应按 RM0394 清除该标志或执行断电/option-byte reload 后再复位。不得为了绕过此状态而改写 boot option bytes。

## 来源与许可状态

`main.c` 从项目本机已验证硬件基线演进；当前固件已完成构建与 readback 一致性校验，受控实机点亮只覆盖 `CABINET 1`，`CABINET 2/3` 仍待现场逐柜验收。`linker.ld` 保持该基线版本；本目录没有引入生成的 ELF、BIN、HEX、MAP 或历史实验源码。原文件没有许可证头，本仓库当前也没有独立 `LICENSE` 文件，因此本目录不另行推定或添加许可证；其使用和分发遵循仓库所有者确定的许可状态。
