/* Peer submission that reads digits by hand. */
#include <stdio.h>
#include <ctype.h>

static int read_number(long long *destination) {
    int character = getchar();
    int sign = 1;
    long long total = 0;

    while (character != EOF && isspace(character)) {
        character = getchar();
    }
    if (character == '-') {
        sign = -1;
        character = getchar();
    }
    if (character == EOF || !isdigit(character)) {
        return 0;
    }
    while (character != EOF && isdigit(character)) {
        total = total * 10 + (character - '0');
        character = getchar();
    }
    *destination = sign * total;
    return 1;
}

int main(void) {
    long long left, right;

    if (!read_number(&left) || !read_number(&right)) {
        return 1;
    }
    printf("%lld\n", left + right);
    return 0;
}
