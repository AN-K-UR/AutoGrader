/* Sample: comparison by subtraction overflows for values far apart. */
#include <stdio.h>
#include <stdlib.h>

static int compare_ints(const void *left, const void *right) {
    return *(const int *)left - *(const int *)right;
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
    qsort(values, (size_t)count, sizeof(int), compare_ints);
    for (int index = 0; index < count; index++) {
        printf(index + 1 < count ? "%d " : "%d", values[index]);
    }
    printf("\n");
    free(values);
    return 0;
}
