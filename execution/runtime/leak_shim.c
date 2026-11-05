/* Allocation tracker used by the memory-safety analyzer.
 *
 * LeakSanitizer is unavailable with Apple clang on arm64 and the Seatbelt profile
 * stops dyld injection, so the submission is compiled with -Dmalloc=ag_malloc and
 * friends and linked with this file. At exit it reports what was never freed.
 *
 * This reports memory "not freed at exit", which includes blocks still reachable
 * at exit. Allocations made inside libc (for example by fopen) are not tracked.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    size_t size;
    size_t pad; /* keeps the payload 16-byte aligned */
} Header;

static unsigned long long live_blocks;
static unsigned long long live_bytes;

void *ag_malloc(size_t size) {
    Header *header = malloc(sizeof(Header) + size);
    if (header == NULL) {
        return NULL;
    }
    header->size = size;
    live_blocks++;
    live_bytes += size;
    return header + 1;
}

void *ag_calloc(size_t count, size_t size) {
    size_t total = count * size;
    void *memory;
    if (size != 0 && total / size != count) {
        return NULL;
    }
    memory = ag_malloc(total);
    if (memory != NULL) {
        memset(memory, 0, total);
    }
    return memory;
}

void ag_free(void *memory) {
    Header *header;
    if (memory == NULL) {
        return;
    }
    header = (Header *)memory - 1;
    live_blocks--;
    live_bytes -= header->size;
    free(header);
}

void *ag_realloc(void *memory, size_t size) {
    void *replacement;
    size_t keep;
    if (memory == NULL) {
        return ag_malloc(size);
    }
    replacement = ag_malloc(size);
    if (replacement == NULL) {
        return NULL;
    }
    keep = ((Header *)memory - 1)->size;
    memcpy(replacement, memory, keep < size ? keep : size);
    ag_free(memory);
    return replacement;
}

char *ag_strdup(const char *text) {
    size_t size = strlen(text) + 1;
    char *copy = ag_malloc(size);
    if (copy != NULL) {
        memcpy(copy, text, size);
    }
    return copy;
}

__attribute__((destructor)) static void report_live_memory(void) {
    char line[96];
    int length = snprintf(line, sizeof line, "\n@@AG_LEAK:%llu:%llu@@\n", live_blocks, live_bytes);
    if (length > 0) {
        (void)!write(2, line, (size_t)length);
    }
}
