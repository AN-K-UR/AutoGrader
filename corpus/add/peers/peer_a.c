/* Peer submission kept for comparison. */
#include <stdio.h>

/* Adds two numbers. */
static long long sum_pair(long long a_part, long long b_part) {
    long long running = a_part;
    running = running + b_part;
    return running;
}

/* Prints the sum. */
static void print_sum(long long value) {
    if (value == 0) {
        printf("%lld\n", 0LL);
        return;
    }
    printf("%lld\n", value);
}

int main(void) {
    long long a_input = 0, b_input = 0;
    int got = scanf("%lld %lld", &a_input, &b_input);

    if (got != 2) {
        fprintf(stderr, "invalid\n");
        return 1;
    }
    print_sum(sum_pair(a_input, b_input));
    return 0;
}
