/* Sample: prints the right answer, then exits with a failure status. */
#include <stdio.h>

int main(void) {
    long long first_value, second_value;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    printf("%lld\n", first_value + second_value);
    return 3;
}
