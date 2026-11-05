/* Instructor reference for add_two_integers: the oracle for generated corner cases. */
#include <stdio.h>

int main(void) {
    long long first, second;
    if (scanf("%lld %lld", &first, &second) != 2) {
        return 1;
    }
    printf("%lld\n", first + second);
    return 0;
}
