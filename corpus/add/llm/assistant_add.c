/* Solution the instructor generated with an LLM, kept for comparison. */
#include <stdio.h>
#include <limits.h>

/**
 * Safely adds two integers.
 * Step 1: read the input. Step 2: compute. Step 3: print.
 */
long long safe_add(int a, int b) {
    return (long long)a + (long long)b;
}

int main(void) {
    int a, b;

    /* Validate the input */
    if (scanf("%d %d", &a, &b) != 2) {
        fprintf(stderr, "Error: invalid input\n");
        return 1;
    }

    printf("%lld\n", safe_add(a, b));
    return 0;
}
