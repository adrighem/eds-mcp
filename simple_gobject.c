#include <glib.h>
#include <libedataserver/libedataserver.h>

typedef struct {
    GObject parent;
} MyObj;

typedef struct {
    GObjectClass parent_class;
} MyObjClass;

G_DEFINE_DYNAMIC_TYPE (MyObj, my_obj, G_TYPE_OBJECT)

static void my_obj_init(MyObj *self) {}
static void my_obj_class_init(MyObjClass *klass) {}
static void my_obj_class_finalize(MyObjClass *klass) {}

G_MODULE_EXPORT void
e_module_load (GTypeModule *type_module)
{
    my_obj_register_type (type_module);
    g_message ("Simple GObject module loaded");
}

G_MODULE_EXPORT void
e_module_unload (GTypeModule *type_module) {}
