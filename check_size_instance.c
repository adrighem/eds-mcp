#include <libedataserver/libedataserver.h>
#include <stdio.h>
int main() {
    printf("Class: %zu, Instance: %zu\n", sizeof(EExtensionClass), sizeof(EExtension));
    return 0;
}
