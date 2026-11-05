/* Sample: correct output from an O(n^2) algorithm; the rules require O(n log n). */
#include <stdio.h>
#include <stdlib.h>

/* Repeatedly swaps adjacent values that are out of order. */
static void bubble_sort(int *values, int count) {
    for (int pass = 0; pass < count; pass++) {
        for (int index = 0; index + 1 < count - pass; index++) {
            if (values[index] > values[index + 1]) {
                int held = values[index];
                values[index] = values[index + 1];
                values[index + 1] = held;
            }
        }
    }
}

static void print_values(const int *values, int count) {
    for (int index = 0; index < count; index++) {
        printf(index + 1 < count ? "%d " : "%d", values[index]);
    }
    printf("\n");
}

int main(void) {
    int count;

    if (scanf("%d", &count) != 1 || count < 0) {
        return 1;
    }
    int *values = malloc((size_t)(count ? count : 1) * sizeof(int));
    if (values == NULL) {
        return 1;
    }
    for (int index = 0; index < count; index++) {
        if (scanf("%d", &values[index]) != 1) {
            return 1;
        }
    }
    bubble_sort(values, count);
    print_values(values, count);
    free(values);
    return 0;
}
