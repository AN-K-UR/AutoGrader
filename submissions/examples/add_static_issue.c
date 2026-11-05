/* Sample: passes the tests but has code Cppcheck objects to. */
#include <stdio.h>

static long long add_values(long long first, long long second) {
    long long unused_total;
    int buffer[4];
    int index;
    for (index = 0; index <= 4; index++) {
        buffer[index] = index;
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
