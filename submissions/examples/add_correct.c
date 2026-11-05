/* Adds two integers read from standard input.
 * A 64-bit type holds every possible sum of two 32-bit values. */
#include <stdio.h>

/* Returns the sum of two values without overflowing. */
static long long add_values(long long first, long long second) {
    return first + second;
}

int main(void) {
    long long first_value;
    long long second_value;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        fprintf(stderr, "expected two integers\n");
        return 1;
    }
    printf("%lld\n", add_values(first_value, second_value));
    return 0;
}
