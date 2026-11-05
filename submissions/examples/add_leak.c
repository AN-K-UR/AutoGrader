/* Sample: right output, but one heap block is never freed. */
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    long long *total = malloc(sizeof(long long));
    long long first_value, second_value;

    if (total == NULL || scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    *total = first_value + second_value;
    printf("%lld\n", *total);
    return 0;
}
