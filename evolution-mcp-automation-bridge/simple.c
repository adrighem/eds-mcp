#include <glib.h>
#include <libedataserver/libedataserver.h>

typedef struct {
    EExtension parent;
} MyExt;

typedef struct {
    EExtensionClass parent_class;
} MyExtClass;

static void my_ext_init(MyExt *self) {}
static void my_ext_class_init(MyExtClass *klass) {
    E_EXTENSION_CLASS(klass)->extensible_type = g_type_from_name("EMailBackend");
}

G_MODULE_EXPORT void
e_module_load (GTypeModule *type_module)
{
    static const GTypeInfo info = {
        sizeof (MyExtClass),
        NULL, NULL,
        (GClassInitFunc) my_ext_class_init,
        NULL, NULL,
        sizeof (MyExt),
        0,
        (GInstanceInitFunc) my_ext_init,
    };
    g_type_module_register_type (type_module, E_TYPE_EXTENSION, "MyExt", &info, 0);
}

G_MODULE_EXPORT void
e_module_unload (GTypeModule *type_module) {}
