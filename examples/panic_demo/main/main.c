/* panic_demo —— 故意制造一个干净的 panic backtrace。
 *
 * 用途:验证第 1 步(本地 ESP32 环境)和 symbolize 工具链。
 * 烧录后串口会打印一行提示,1 秒后崩溃,产生 4 层 Backtrace:
 *
 *     app_main -> step_one -> step_two -> trigger_crash
 *
 * 把串口里 "Backtrace:" 那行的十六进制地址喂给
 *   xtensa-esp32s3-elf-addr2line -pfiaC -e build/panic_demo.elf <addr...>
 * 应当还原出上面 4 个函数名 —— 这一步通了,symbolizer 的依赖就算就位。
 *
 * 硬件:立创·实战派 szpi-esp32s3 (ESP32-S3),USB-Serial-JTAG 烧录。
 */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/* noinline 保证每个调用各占一栈帧,backtrace 才有多层可还原 */
__attribute__((noinline))
static void trigger_crash(void)
{
    /* 写地址 0 —— ESP32-S3 的内存保护会立即触发 StoreProhibited panic */
    volatile int *bad = (volatile int *)0;
    *bad = 0xdead;
}

__attribute__((noinline))
static void step_two(void)
{
    trigger_crash();
}

__attribute__((noinline))
static void step_one(void)
{
    step_two();
}

void app_main(void)
{
    printf("panic_demo: about to crash in 1s...\n");
    vTaskDelay(pdMS_TO_TICKS(1000));
    step_one();
    /* 不会到达 */
}
