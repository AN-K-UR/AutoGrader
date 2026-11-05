/* Sample: never halts. Harmless; the time limit stops it. */
#include <stdio.h>

int main(void) {
    long long first_value, second_value;
    volatile int keep_going = 1;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    while (keep_going) {
        first_value++;
    }
    printf("%lld\n", first_value + second_value);
    return 0;
}
