/* Sample: compiles and runs, but multiplies instead of adding. */
#include <stdio.h>

static long long combine(long long first, long long second) {
    return first * second;
}

int main(void) {
    long long first_value, second_value;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    printf("%lld\n", combine(first_value, second_value));
    return 0;
}
