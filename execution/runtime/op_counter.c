/* Deterministic operation counter for the complexity estimator.
 *
 * Linked into a build made with -fsanitize-coverage=trace-pc: the compiler calls
 * __sanitizer_cov_trace_pc once per basic block of the submission. The total is
 * written to stderr at exit. Same program + same input = same count, on any
 * machine load, which wall-clock timing cannot offer.
 *
 * Not counted: time spent inside libc (strlen, memcpy, qsort's own loop). This is
 * a documented limitation.
 */
#include <stdio.h>
#include <unistd.h>

static unsigned long long operation_count;

void __sanitizer_cov_trace_pc(void) { operation_count++; }

__attribute__((destructor)) static void report_operation_count(void) {
    char line[64];
    int length = snprintf(line, sizeof line, "\n@@AG_OPS:%llu@@\n", operation_count);
    if (length > 0) {
        (void)!write(2, line, (size_t)length);
    }
}
