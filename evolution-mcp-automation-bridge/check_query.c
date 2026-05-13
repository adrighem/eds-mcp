#include <libedataserver/libedataserver.h>
#include <stdio.h>
int main() {
    GTypeQuery query;
    g_type_query(E_TYPE_EXTENSION, &query);
    printf("Class size: %u\n", query.class_size);
    return 0;
}
