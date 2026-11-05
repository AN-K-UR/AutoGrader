/* Peer submission: insertion sort. */
#include <stdio.h>

int main(void) {
    int count, values[100000];

    if (scanf("%d", &count) != 1) {
        return 1;
    }
    for (int position = 0; position < count; position++) {
        int incoming, slot = position;
        scanf("%d", &incoming);
        while (slot > 0 && values[slot - 1] > incoming) {
            values[slot] = values[slot - 1];
            slot--;
        }
        values[slot] = incoming;
    }
    for (int position = 0; position < count; position++) {
        printf("%d ", values[position]);
    }
    printf("\n");
    return 0;
}
