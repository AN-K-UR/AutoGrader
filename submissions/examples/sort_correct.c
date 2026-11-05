/* Sorts integers with merge sort, which is O(n log n) on every input. */
#include <stdio.h>
#include <stdlib.h>

/* Merges the sorted ranges [low, middle) and [middle, high). */
static void merge(int *values, int *scratch, int low, int middle, int high) {
    int left = low, right = middle, output = low;

    while (left < middle && right < high) {
        scratch[output++] = values[left] <= values[right] ? values[left++] : values[right++];
    }
    while (left < middle) {
        scratch[output++] = values[left++];
    }
    while (right < high) {
        scratch[output++] = values[right++];
    }
    for (output = low; output < high; output++) {
        values[output] = scratch[output];
    }
}

/* Sorts the range [low, high) recursively. */
static void merge_sort(int *values, int *scratch, int low, int high) {
    if (high - low < 2) {
        return;
    }
    int middle = low + (high - low) / 2;
    merge_sort(values, scratch, low, middle);
    merge_sort(values, scratch, middle, high);
    merge(values, scratch, low, middle, high);
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
    size_t cells = (size_t)(count ? count : 1);
    int *values = malloc(cells * sizeof(int));
    int *scratch = malloc(cells * sizeof(int));
    if (values == NULL || scratch == NULL) {
        return 1;
    }
    for (int index = 0; index < count; index++) {
        if (scanf("%d", &values[index]) != 1) {
            return 1;
        }
    }
    merge_sort(values, scratch, 0, count);
    print_values(values, count);
    free(values);
    free(scratch);
    return 0;
}
