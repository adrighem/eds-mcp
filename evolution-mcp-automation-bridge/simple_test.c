#include <glib.h>
#include <libedataserver/libedataserver.h>
#include <mail/e-mail-backend.h>

typedef struct {
    EExtension parent;
} MyExt;

typedef struct {
    EExtensionClass parent_class;
} MyExtClass;

G_DEFINE_DYNAMIC_TYPE (MyExt, my_ext, E_TYPE_EXTENSION)
static void my_ext_init(MyExt *self) {}
static void my_ext_class_init(MyExtClass *klass) {
    E_EXTENSION_CLASS(klass)->extensible_type = E_TYPE_MAIL_BACKEND;
}
static void my_ext_class_finalize(MyExtClass *klass) {}
G_MODULE_EXPORT void e_module_load (GTypeModule *m) { my_ext_register_type(m); }
G_MODULE_EXPORT void e_module_unload (GTypeModule *m) {}
