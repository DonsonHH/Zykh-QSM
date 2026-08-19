#include <stdint.h>

#define RCC_BASE        0x40021000u
#define RCC_CR          (*(volatile uint32_t *)(RCC_BASE + 0x00u))
#define RCC_CFGR        (*(volatile uint32_t *)(RCC_BASE + 0x08u))
#define RCC_AHB1ENR     (*(volatile uint32_t *)(RCC_BASE + 0x48u))
#define RCC_AHB2ENR     (*(volatile uint32_t *)(RCC_BASE + 0x4Cu))
#define RCC_APB1ENR1    (*(volatile uint32_t *)(RCC_BASE + 0x58u))
#define RCC_APB2ENR     (*(volatile uint32_t *)(RCC_BASE + 0x60u))

#define GPIOA_BASE      0x48000000u
#define GPIOA_MODER     (*(volatile uint32_t *)(GPIOA_BASE + 0x00u))
#define GPIOA_OTYPER    (*(volatile uint32_t *)(GPIOA_BASE + 0x04u))
#define GPIOA_OSPEEDR   (*(volatile uint32_t *)(GPIOA_BASE + 0x08u))
#define GPIOA_PUPDR     (*(volatile uint32_t *)(GPIOA_BASE + 0x0Cu))
#define GPIOA_AFRL      (*(volatile uint32_t *)(GPIOA_BASE + 0x20u))
#define GPIOA_AFRH      (*(volatile uint32_t *)(GPIOA_BASE + 0x24u))

#define GPIOB_BASE      0x48000400u
#define GPIOB_MODER     (*(volatile uint32_t *)(GPIOB_BASE + 0x00u))
#define GPIOB_OTYPER    (*(volatile uint32_t *)(GPIOB_BASE + 0x04u))
#define GPIOB_OSPEEDR   (*(volatile uint32_t *)(GPIOB_BASE + 0x08u))
#define GPIOB_PUPDR     (*(volatile uint32_t *)(GPIOB_BASE + 0x0Cu))
#define GPIOB_AFRL      (*(volatile uint32_t *)(GPIOB_BASE + 0x20u))

#define TIM1_BASE       0x40012C00u
#define TIM1_CR1        (*(volatile uint32_t *)(TIM1_BASE + 0x00u))
#define TIM1_DIER       (*(volatile uint32_t *)(TIM1_BASE + 0x0Cu))
#define TIM1_SR         (*(volatile uint32_t *)(TIM1_BASE + 0x10u))
#define TIM1_EGR        (*(volatile uint32_t *)(TIM1_BASE + 0x14u))
#define TIM1_CCMR1      (*(volatile uint32_t *)(TIM1_BASE + 0x18u))
#define TIM1_CCMR2      (*(volatile uint32_t *)(TIM1_BASE + 0x1Cu))
#define TIM1_CCER       (*(volatile uint32_t *)(TIM1_BASE + 0x20u))
#define TIM1_PSC        (*(volatile uint32_t *)(TIM1_BASE + 0x28u))
#define TIM1_ARR        (*(volatile uint32_t *)(TIM1_BASE + 0x2Cu))
#define TIM1_CCR1       (*(volatile uint32_t *)(TIM1_BASE + 0x34u))
#define TIM1_CCR2       (*(volatile uint32_t *)(TIM1_BASE + 0x38u))
#define TIM1_CCR3       (*(volatile uint32_t *)(TIM1_BASE + 0x3Cu))
#define TIM1_CCR4       (*(volatile uint32_t *)(TIM1_BASE + 0x40u))
#define TIM1_BDTR       (*(volatile uint32_t *)(TIM1_BASE + 0x44u))

#define DMA1_BASE       0x40020000u
#define DMA1_ISR        (*(volatile uint32_t *)(DMA1_BASE + 0x00u))
#define DMA1_IFCR       (*(volatile uint32_t *)(DMA1_BASE + 0x04u))
#define DMA1_CCR4       (*(volatile uint32_t *)(DMA1_BASE + 0x44u))
#define DMA1_CNDTR4     (*(volatile uint32_t *)(DMA1_BASE + 0x48u))
#define DMA1_CPAR4      (*(volatile uint32_t *)(DMA1_BASE + 0x4Cu))
#define DMA1_CMAR4      (*(volatile uint32_t *)(DMA1_BASE + 0x50u))
#define DMA1_CSELR      (*(volatile uint32_t *)(DMA1_BASE + 0xA8u))

#define USART1_BASE     0x40013800u
#define USART1_CR1      (*(volatile uint32_t *)(USART1_BASE + 0x00u))
#define USART1_BRR      (*(volatile uint32_t *)(USART1_BASE + 0x0Cu))
#define USART1_ISR      (*(volatile uint32_t *)(USART1_BASE + 0x1Cu))
#define USART1_RDR      (*(volatile uint32_t *)(USART1_BASE + 0x24u))
#define USART1_TDR      (*(volatile uint32_t *)(USART1_BASE + 0x28u))

#define USART2_BASE     0x40004400u

#define USART_CR1_UE    (1u << 0)
#define USART_CR1_RE    (1u << 2)
#define USART_CR1_TE    (1u << 3)
#define USART_ISR_RXNE  (1u << 5)
#define USART_ISR_TXE   (1u << 7)

#define LED_COUNT        64u
#define ACTIVE_LED_COUNT 24u
#define PANEL_BRIGHTNESS 30u
#define WS_PERIOD_TICKS  20u
#define WS_T0H_TICKS     5u
#define WS_T1H_TICKS     10u
#define WS_DMA_TRIGGER_TICKS 11u
#define WS_RESET_BITS    400u
#define WS_FRAME_BITS    (LED_COUNT * 24u)

typedef struct {
    char data[24];
    uint32_t length;
} command_parser_t;

void Reset_Handler(void);
void Default_Handler(void);

__attribute__((section(".isr_vector"), used))
const uintptr_t vector_table[16] = {
    0x2000C000u,
    (uintptr_t)Reset_Handler,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
    0u, 0u, 0u, 0u,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
    0u,
    (uintptr_t)Default_Handler,
    (uintptr_t)Default_Handler,
};

static void clock_init_16mhz(void) {
    RCC_CR |= (1u << 8);
    while ((RCC_CR & (1u << 10)) == 0u) {}
    RCC_CFGR = (RCC_CFGR & ~0x3u) | 0x1u;
    while ((RCC_CFGR & (0x3u << 2)) != (0x1u << 2)) {}
}

static void usart1_init(void) {
    RCC_AHB2ENR |= (1u << 0);
    RCC_APB2ENR |= (1u << 14);
    (void)RCC_AHB2ENR;
    (void)RCC_APB2ENR;

    GPIOA_MODER = (GPIOA_MODER & ~((3u << 18) | (3u << 20))) |
                   (2u << 18) | (2u << 20);
    GPIOA_OTYPER &= ~((1u << 9) | (1u << 10));
    GPIOA_OSPEEDR |= (3u << 18) | (3u << 20);
    GPIOA_PUPDR = (GPIOA_PUPDR & ~((3u << 18) | (3u << 20))) |
                  (1u << 20);
    GPIOA_AFRH = (GPIOA_AFRH & ~((0xFu << 4) | (0xFu << 8))) |
                  (7u << 4) | (7u << 8);

    USART1_CR1 = 0u;
    USART1_BRR = 139u;
    USART1_CR1 = USART_CR1_UE | USART_CR1_RE | USART_CR1_TE;
}

static void usart2_vcp_init(void) {
    RCC_AHB2ENR |= (1u << 0);
    RCC_APB1ENR1 |= (1u << 17);
    (void)RCC_AHB2ENR;
    (void)RCC_APB1ENR1;

    GPIOA_MODER = (GPIOA_MODER & ~((3u << 4) | (3u << 30))) |
                   (2u << 4) | (2u << 30);
    GPIOA_OTYPER &= ~((1u << 2) | (1u << 15));
    GPIOA_OSPEEDR |= (3u << 4) | (3u << 30);
    GPIOA_PUPDR = (GPIOA_PUPDR & ~((3u << 4) | (3u << 30))) |
                  (1u << 30);
    GPIOA_AFRL = (GPIOA_AFRL & ~(0xFu << 8)) | (7u << 8);
    GPIOA_AFRH = (GPIOA_AFRH & ~(0xFu << 28)) | (3u << 28);

    *(volatile uint32_t *)(USART2_BASE + 0x00u) = 0u;
    *(volatile uint32_t *)(USART2_BASE + 0x0Cu) = 139u;
    *(volatile uint32_t *)(USART2_BASE + 0x00u) =
        USART_CR1_UE | USART_CR1_RE | USART_CR1_TE;
}

static void ws2812_init(void) {
    RCC_AHB1ENR |= (1u << 0);
    RCC_AHB2ENR |= (1u << 0) | (1u << 1);
    RCC_APB2ENR |= (1u << 11);
    (void)RCC_AHB1ENR;
    (void)RCC_AHB2ENR;
    (void)RCC_APB2ENR;

    GPIOA_MODER = (GPIOA_MODER & ~(3u << 16)) | (2u << 16);
    GPIOA_OTYPER &= ~(1u << 8);
    GPIOA_OSPEEDR |= (3u << 16);
    GPIOA_PUPDR &= ~(3u << 16);
    GPIOA_AFRH = (GPIOA_AFRH & ~(0xFu << 0)) | (1u << 0);

    GPIOB_MODER = (GPIOB_MODER & ~((3u << 0) | (3u << 2))) |
                   (2u << 0) | (2u << 2);
    GPIOB_OTYPER &= ~((1u << 0) | (1u << 1));
    GPIOB_OSPEEDR |= (3u << 0) | (3u << 2);
    GPIOB_PUPDR &= ~((3u << 0) | (3u << 2));
    GPIOB_AFRL = (GPIOB_AFRL & ~((0xFu << 0) | (0xFu << 4))) |
                  (1u << 0) | (1u << 4);

    TIM1_CR1 = 0u;
    TIM1_PSC = 0u;
    TIM1_ARR = WS_PERIOD_TICKS - 1u;
    TIM1_CCMR1 = (6u << 4) | (1u << 3) |
                  (6u << 12) | (1u << 11);
    TIM1_CCMR2 = (6u << 4) | (1u << 3);
    TIM1_CCR1 = 0u;
    TIM1_CCR2 = 0u;
    TIM1_CCR3 = 0u;
    TIM1_CCR4 = WS_DMA_TRIGGER_TICKS;
    TIM1_CCER = (1u << 0) | (1u << 6) | (1u << 10);
    TIM1_BDTR = (1u << 15);
    DMA1_CCR4 = 0u;
    DMA1_CSELR = (DMA1_CSELR & ~(0xFu << 12)) | (7u << 12);
    TIM1_EGR = 1u;
    TIM1_SR = 0u;
    TIM1_CR1 = 0u;
}

static void tim1_wait_update(void) {
    TIM1_SR = 0u;
    while ((TIM1_SR & 1u) == 0u) {}
}

static uint32_t ws2812_duty_for_bit(uint32_t bit_index, uint32_t enabled) {
    uint32_t led = bit_index / 24u;
    uint32_t component_bit = bit_index % 24u;
    uint32_t value = 0u;
    if (enabled && led < ACTIVE_LED_COUNT) {
        value = PANEL_BRIGHTNESS;
    }
    return (value & (0x80u >> (component_bit & 7u))) != 0u
               ? WS_T1H_TICKS
               : WS_T0H_TICKS;
}

static void ws2812_send_panel(volatile uint32_t *ccr, uint32_t enabled) {
    uint32_t bit;
    uint32_t duties[WS_FRAME_BITS + 1u];
    for (bit = 0u; bit < WS_FRAME_BITS; ++bit) {
        duties[bit] = ws2812_duty_for_bit(bit, enabled);
    }
    duties[WS_FRAME_BITS] = 0u;

    TIM1_CR1 = 0u;
    *ccr = 0u;
    TIM1_CCR4 = WS_DMA_TRIGGER_TICKS;
    TIM1_EGR = 1u;
    TIM1_SR = 0u;

    DMA1_CCR4 = 0u;
    DMA1_IFCR = (0xFu << 12);
    DMA1_CNDTR4 = WS_FRAME_BITS + 1u;
    DMA1_CPAR4 = (uint32_t)(uintptr_t)ccr;
    DMA1_CMAR4 = (uint32_t)(uintptr_t)&duties[0];
    DMA1_CCR4 = (2u << 12) | (2u << 10) | (2u << 8) |
                (1u << 7) | (1u << 4) | 1u;
    TIM1_DIER = (1u << 12);
    TIM1_CR1 = 1u;

    while ((DMA1_ISR & (1u << 13)) == 0u) {}
    DMA1_CCR4 = 0u;
    TIM1_DIER = 0u;
    tim1_wait_update();
    for (bit = 0u; bit < WS_RESET_BITS; ++bit) {
        tim1_wait_update();
    }
    TIM1_CR1 = 0u;
}

static void show_cabinet(uint8_t selected) {
    ws2812_send_panel(&TIM1_CCR1, selected == 1u);
    ws2812_send_panel(&TIM1_CCR2, selected == 2u);
    ws2812_send_panel(&TIM1_CCR3, selected == 3u);
}

static int uart_try_read(uintptr_t base, uint8_t *byte) {
    volatile uint32_t *isr = (volatile uint32_t *)(base + 0x1Cu);
    volatile uint32_t *rdr = (volatile uint32_t *)(base + 0x24u);
    if ((*isr & USART_ISR_RXNE) == 0u) {
        return 0;
    }
    *byte = (uint8_t)*rdr;
    return 1;
}

static void uart_write(uintptr_t base, const char *text) {
    volatile uint32_t *isr = (volatile uint32_t *)(base + 0x1Cu);
    volatile uint32_t *tdr = (volatile uint32_t *)(base + 0x28u);
    while (*text != '\0') {
        while ((*isr & USART_ISR_TXE) == 0u) {}
        *tdr = (uint8_t)*text;
        ++text;
    }
}

static int text_equal(const char *left, const char *right) {
    while (*left != '\0' && *right != '\0') {
        if (*left != *right) {
            return 0;
        }
        ++left;
        ++right;
    }
    return *left == *right;
}

static void process_command(uintptr_t base, command_parser_t *parser,
                            uint8_t byte, uint8_t *selected) {
    if (byte == '\r') {
        return;
    }
    if (byte != '\n') {
        if (parser->length < (sizeof(parser->data) - 1u)) {
            parser->data[parser->length++] = (char)byte;
        } else {
            parser->length = 0u;
        }
        return;
    }

    parser->data[parser->length] = '\0';
    if (text_equal(parser->data, "PING")) {
        uart_write(base, "PONG\r\n");
    } else if (text_equal(parser->data, "CABINET 1")) {
        *selected = 1u;
        show_cabinet(*selected);
        uart_write(base, "OK CABINET 1\r\n");
    } else if (text_equal(parser->data, "CABINET 2")) {
        *selected = 2u;
        show_cabinet(*selected);
        uart_write(base, "OK CABINET 2\r\n");
    } else if (text_equal(parser->data, "CABINET 3")) {
        *selected = 3u;
        show_cabinet(*selected);
        uart_write(base, "OK CABINET 3\r\n");
    } else if (text_equal(parser->data, "OFF")) {
        *selected = 0u;
        show_cabinet(*selected);
        uart_write(base, "OK OFF\r\n");
    } else if (text_equal(parser->data, "STATUS")) {
        if (*selected == 1u) {
            uart_write(base, "STATUS CABINET 1\r\n");
        } else if (*selected == 2u) {
            uart_write(base, "STATUS CABINET 2\r\n");
        } else if (*selected == 3u) {
            uart_write(base, "STATUS CABINET 3\r\n");
        } else {
            uart_write(base, "STATUS OFF\r\n");
        }
    } else {
        uart_write(base, "ERR COMMAND\r\n");
    }
    parser->length = 0u;
}

void Reset_Handler(void) {
    command_parser_t usart1_parser = {{0}, 0u};
    command_parser_t usart2_parser = {{0}, 0u};
    uint8_t selected = 0u;
    uint8_t byte;

    clock_init_16mhz();
    usart1_init();
    usart2_vcp_init();
    ws2812_init();
    show_cabinet(0u);
    for (;;) {
        if (uart_try_read(USART1_BASE, &byte)) {
            process_command(USART1_BASE, &usart1_parser, byte, &selected);
        }
        if (uart_try_read(USART2_BASE, &byte)) {
            process_command(USART2_BASE, &usart2_parser, byte, &selected);
        }
    }
}

void Default_Handler(void) {
    for (;;) {}
}
