/* Sample for the limitations section: a heap overflow only one input reaches. */
#include <stdio.h>
#include <stdlib.h>

static long long add_values(long long first, long long second) {
    int *slots = malloc(4 * sizeof(int));
    if (slots != NULL) {
        if (first == 31337) {
            slots[40] = 1;
        }
        free(slots);
    }
    return first + second;
}

int main(void) {
    long long first_value, second_value;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    printf("%lld\n", add_values(first_value, second_value));
    return 0;
}
