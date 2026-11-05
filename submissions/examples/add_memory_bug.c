/* Sample: right output, but overflows a heap block by one element and leaks it. */
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    long long first_value, second_value;
    long long *values = malloc(2 * sizeof(long long));

    if (values == NULL || scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    values[0] = first_value;
    values[1] = second_value;
    values[2] = first_value + second_value;
    printf("%lld\n", values[2]);
    return 0;
}
