/* Sample: right answers through needless branching, for complexity feedback. */
#include <stdio.h>

static long long add_by_cases(long long first, long long second) {
    long long total = 0;
    if (first > 0) {
        if (second > 0) {
            if (first > 100) {
                if (second > 100) {
                    total = first + second;
                } else if (second > 50) {
                    total = first + second;
                } else {
                    total = first + second;
                }
            } else if (first > 50) {
                total = first + second;
            } else {
                total = first + second;
            }
        } else if (second < 0) {
            total = first + second;
        } else {
            total = first;
        }
    } else if (first < 0) {
        if (second > 0) {
            total = first + second;
        } else if (second < 0) {
            total = first + second;
        } else {
            total = first;
        }
    } else {
        if (second > 0) {
            total = second;
        } else if (second < 0) {
            total = second;
        } else {
            total = 0;
        }
    }
    return total;
}

int main(void) {
    long long first_value, second_value;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    printf("%lld\n", add_by_cases(first_value, second_value));
    return 0;
}
