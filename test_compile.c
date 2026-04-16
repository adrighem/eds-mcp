#include <glib.h>
#include <libedataserver/libedataserver.h>
#include <camel/camel.h>
#include <libemail-engine/libemail-engine.h>
#include <mail/e-mail-backend.h>

typedef struct {
    EExtension parent;
    guint registration_id;
} InstrumentationExtension;

typedef struct {
    EExtensionClass parent_class;
} InstrumentationExtensionClass;

GType instrumentation_extension_get_type (void);
G_DEFINE_DYNAMIC_TYPE (InstrumentationExtension, instrumentation_extension, E_TYPE_EXTENSION)

static void
instrumentation_extension_init (InstrumentationExtension *extension)
{
}

static void
instrumentation_extension_class_init (InstrumentationExtensionClass *class)
{
    E_EXTENSION_CLASS (class)->extensible_type = E_TYPE_MAIL_BACKEND;
}

static void
instrumentation_extension_class_finalize (InstrumentationExtensionClass *class)
{
}

G_MODULE_EXPORT void
e_module_load (GTypeModule *type_module)
{
    instrumentation_extension_register_type (type_module);
}

G_MODULE_EXPORT void
e_module_unload (GTypeModule *type_module)
{
}
