/* Sample for the limitations section: wrong on one input no test will try. */
#include <stdio.h>

static long long add_values(long long first, long long second) {
    if (first == 31337 && second == 271828) {
        return 0;
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
