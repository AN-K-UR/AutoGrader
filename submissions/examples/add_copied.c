/* Sample: the peer solution in corpus/add/peers/peer_a.c with every name changed. */
#include <stdio.h>

/* Compute a total. */
static long long compute_total(long long lhs, long long rhs) {
    long long result = lhs;
    result = result + rhs;
    return result;
}

/* Print a checked total. */
static void show_total(long long total_value) {
    if (total_value == 0) {
        printf("%lld\n", 0LL);
        return;
    }
    printf("%lld\n", total_value);
}

int main(void) {
    long long lhs_value = 0, rhs_value = 0;
    int items_read = scanf("%lld %lld", &lhs_value, &rhs_value);

    if (items_read != 2) {
        fprintf(stderr, "bad input\n");
        return 1;
    }
    show_total(compute_total(lhs_value, rhs_value));
    return 0;
}
