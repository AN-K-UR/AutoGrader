/* Sample: crashes with a null pointer write on every input. */
#include <stdio.h>

int main(void) {
    long long first_value, second_value;
    volatile int *nowhere = NULL;

    if (scanf("%lld %lld", &first_value, &second_value) != 2) {
        return 1;
    }
    *nowhere = 1;
    printf("%lld\n", first_value + second_value);
    return 0;
}
