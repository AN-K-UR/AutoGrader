/* Instructor reference for sort_integers: the oracle for generated corner cases. */
#include <stdio.h>
#include <stdlib.h>

static int compare_ints(const void *left, const void *right) {
    int a = *(const int *)left;
    int b = *(const int *)right;
    return (a > b) - (a < b);
}

int main(void) {
    int count;
    if (scanf("%d", &count) != 1 || count < 0) {
        return 1;
    }
    int *values = malloc(sizeof(int) * (size_t)(count ? count : 1));
    if (values == NULL) {
        return 1;
    }
    for (int i = 0; i < count; i++) {
        if (scanf("%d", &values[i]) != 1) {
            free(values);
            return 1;
        }
    }
    qsort(values, (size_t)count, sizeof(int), compare_ints);
    for (int i = 0; i < count; i++) {
        printf(i + 1 < count ? "%d " : "%d", values[i]);
    }
    printf("\n");
    free(values);
    return 0;
}
