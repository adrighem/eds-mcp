#include <glib.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>

typedef struct _EBookClientView EBookClientView;
typedef struct _EBookClient EBookClient;
typedef struct _EBookQuery EBookQuery;
typedef struct _EContact EContact;
typedef struct _EDestination EDestination;

#include <libedataserver/libedataserver.h>
#include <camel/camel.h>
#include <libemail-engine/libemail-engine.h>
#include <shell/e-shell.h>
#include <mail/e-mail-backend.h>

static GDBusNodeInfo *introspection_data = NULL;
static guint registration_id = 0;
static GDBusConnection *global_conn = NULL;

static const gchar xml[] = 
    "<node>"
    "  <interface name='org.gnome.Evolution.McpAutomationBridge'>"
    "    <method name='MoveMessage'>"
    "      <arg type='s' name='account_uid' direction='in'/>"
    "      <arg type='s' name='message_uid' direction='in'/>"
    "      <arg type='s' name='source_folder' direction='in'/>"
    "      <arg type='s' name='dest_folder' direction='in'/>"
    "      <arg type='b' name='success' direction='out'/>"
    "      <arg type='s' name='message' direction='out'/>"
    "    </method>"
    "    <method name='DeleteMessage'>"
    "      <arg type='s' name='account_uid' direction='in'/>"
    "      <arg type='s' name='message_uid' direction='in'/>"
    "      <arg type='s' name='folder_name' direction='in'/>"
    "      <arg type='b' name='success' direction='out'/>"
    "      <arg type='s' name='message' direction='out'/>"
    "    </method>"
    "    <method name='GetMessage'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='message_uid' direction='in'/>\n"
    "      <arg type='s' name='folder_name' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='content' direction='out'/>\n"
    "    </method>\n"
    "    <method name='ListAttachments'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='message_uid' direction='in'/>\n"
    "      <arg type='s' name='folder_name' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='attachments_json' direction='out'/>\n"
    "    </method>\n"
    "    <method name='SaveAttachment'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='message_uid' direction='in'/>\n"
    "      <arg type='s' name='folder_name' direction='in'/>\n"
    "      <arg type='s' name='attachment_name' direction='in'/>\n"
    "      <arg type='s' name='dest_path' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='message' direction='out'/>\n"
    "    </method>\n"
    "  </interface>\n"
    "</node>";

static void
handle_move_message (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *source_folder, *dest_folder;
    CamelService *service;
    CamelFolder *src_folder_obj = NULL;
    CamelFolder *dst_folder_obj = NULL;
    GPtrArray *uids;
    GError *error = NULL;
    gboolean success;

    g_print ("McpAutomationBridge: MoveMessage called\n");

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return;
    }

    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);

    g_variant_get (parameters, "(&s&s&s&s)", &account_uid, &message_uid, &source_folder, &dest_folder);

    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found or is not a store"));
        if (service) g_object_unref (service);
        return;
    }

    src_folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), source_folder, 0, NULL, &error);
    if (!src_folder_obj) {
        gchar *msg = g_strdup_printf ("Source folder not found: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (service);
        return;
    }

    dst_folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), dest_folder, 0, NULL, &error);
    if (!dst_folder_obj) {
        gchar *msg = g_strdup_printf ("Destination folder not found: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (src_folder_obj);
        g_object_unref (service);
        return;
    }

    uids = g_ptr_array_new_with_free_func (g_free);
    g_ptr_array_add (uids, g_strdup (message_uid));

    success = camel_folder_transfer_messages_to_sync (src_folder_obj, uids, dst_folder_obj, TRUE, NULL, NULL, &error);

    if (success) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Message moved successfully"));
    } else {
        gchar *msg = g_strdup_printf ("Move failed: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
    }

    g_ptr_array_unref (uids);
    g_object_unref (src_folder_obj);
    g_object_unref (dst_folder_obj);
    g_object_unref (service);
}

static void
handle_delete_message (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service;
    CamelFolder *folder_obj = NULL;
    GError *error = NULL;

    g_print ("McpAutomationBridge: DeleteMessage called\n");

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return;
    }

    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);

    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found or is not a store"));
        if (service) g_object_unref (service);
        return;
    }

    folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), folder_name, 0, NULL, &error);
    if (!folder_obj) {
        gchar *msg = g_strdup_printf ("Folder not found: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (service);
        return;
    }

    camel_folder_set_message_flags (folder_obj, message_uid, CAMEL_MESSAGE_DELETED | CAMEL_MESSAGE_SEEN, CAMEL_MESSAGE_DELETED | CAMEL_MESSAGE_SEEN);
    camel_folder_synchronize_sync (folder_obj, FALSE, NULL, NULL);

    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Message deleted successfully"));

    g_object_unref (folder_obj);
    g_object_unref (service);
}


static void
handle_get_message (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    CamelDataWrapper *dw = NULL;
    CamelStream *stream = NULL;
    GByteArray *byte_array = NULL;
    GError *error = NULL;

    g_print ("McpAutomationBridge: GetMessage called\n");

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return;
    }

    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);

    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found or is not a store"));
        if (service) g_object_unref (service);
        return;
    }

    folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), folder_name, 0, NULL, &error);
    if (!folder_obj) {
        gchar *msg = g_strdup_printf ("Folder not found: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (service);
        return;
    }

    message = camel_folder_get_message_sync (folder_obj, message_uid, NULL, &error);
    if (!message) {
        gchar *msg = g_strdup_printf ("Failed to get message: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (folder_obj);
        g_object_unref (service);
        return;
    }

    dw = CAMEL_DATA_WRAPPER (message);
    byte_array = g_byte_array_new ();
    stream = camel_stream_mem_new_with_byte_array (byte_array);
    camel_data_wrapper_write_to_stream_sync (dw, stream, NULL, &error);
    
    if (error) {
        gchar *msg = g_strdup_printf ("Failed to write message to stream: %s", error->message);
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
    } else {
        gchar *valid_utf8 = g_utf8_make_valid ((const gchar *)byte_array->data, byte_array->len);
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, valid_utf8));
        g_free (valid_utf8);
    }

    g_object_unref (stream);
    g_byte_array_free (byte_array, TRUE);
    g_object_unref (message);
    g_object_unref (folder_obj);
    g_object_unref (service);
}

typedef struct {
    JsonArray *array;
} ListAttachmentsData;

static void
list_attachments_cb (CamelMimePart *part, gpointer user_data)
{
    ListAttachmentsData *data = user_data;
    const gchar *filename;
    
    filename = camel_mime_part_get_filename (part);
    if (filename) {
        JsonObject *obj = json_object_new ();
        CamelDataWrapper *dw = camel_medium_get_content (CAMEL_MEDIUM (part));
        const gchar *mime_type = camel_data_wrapper_get_mime_type (dw);
        
        json_object_set_string_member (obj, "filename", filename);
        json_object_set_string_member (obj, "mime_type", mime_type);
        
        json_array_add_object_element (data->array, obj);
    }
}

static void
handle_list_attachments (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    g_print ("McpAutomationBridge: ListAttachments called\n");

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);

    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found"));
        if (service) g_object_unref (service);
        return;
    }

    folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), folder_name, 0, NULL, &error);
    if (!folder_obj) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Folder not found"));
        g_clear_error (&error);
        g_object_unref (service);
        return;
    }

    message = camel_folder_get_message_sync (folder_obj, message_uid, NULL, &error);
    if (!message) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Message not found"));
        g_clear_error (&error);
        g_object_unref (folder_obj);
        g_object_unref (service);
        return;
    }

    ListAttachmentsData data;
    data.array = json_array_new ();
    
    camel_mime_message_foreach_part (message, (CamelForeachPartFunc) list_attachments_cb, &data);

    JsonNode *root = json_node_new (JSON_NODE_ARRAY);
    json_node_take_array (root, data.array);
    
    JsonGenerator *generator = json_generator_new ();
    json_generator_set_root (generator, root);
    gchar *json_str = json_generator_to_data (generator, NULL);
    
    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, json_str));
    
    g_free (json_str);
    g_object_unref (generator);
    json_node_free (root);
    g_object_unref (message);
    g_object_unref (folder_obj);
    g_object_unref (service);
}

typedef struct {
    const gchar *target_name;
    const gchar *dest_path;
    gboolean found;
    GError *error;
} SaveAttachmentData;

static void
save_attachment_cb (CamelMimePart *part, gpointer user_data)
{
    SaveAttachmentData *data = user_data;
    const gchar *filename;
    
    if (data->found) return;

    filename = camel_mime_part_get_filename (part);
    if (filename && g_strcmp0 (filename, data->target_name) == 0) {
        CamelDataWrapper *dw = camel_medium_get_content (CAMEL_MEDIUM (part));
        CamelStream *stream;
        
        stream = camel_stream_fs_new_with_name (data->dest_path, O_CREAT | O_WRONLY | O_TRUNC, 0666, &data->error);
        if (stream) {
            camel_data_wrapper_decode_to_stream_sync (dw, stream, NULL, &data->error);
            g_object_unref (stream);
            if (!data->error)
                data->found = TRUE;
        }
    }
}

static void
handle_save_attachment (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *folder_name, *attachment_name, *dest_path;
    CamelService *service;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    g_print ("McpAutomationBridge: SaveAttachment called\n");

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);

    g_variant_get (parameters, "(&s&s&s&s&s)", &account_uid, &message_uid, &folder_name, &attachment_name, &dest_path);

    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found"));
        if (service) g_object_unref (service);
        return;
    }

    folder_obj = camel_store_get_folder_sync (CAMEL_STORE (service), folder_name, 0, NULL, &error);
    if (!folder_obj) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Folder not found"));
        g_clear_error (&error);
        g_object_unref (service);
        return;
    }

    message = camel_folder_get_message_sync (folder_obj, message_uid, NULL, &error);
    if (!message) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Message not found"));
        g_clear_error (&error);
        g_object_unref (folder_obj);
        g_object_unref (service);
        return;
    }

    SaveAttachmentData data;
    data.target_name = attachment_name;
    data.dest_path = dest_path;
    data.found = FALSE;
    data.error = NULL;
    
    camel_mime_message_foreach_part (message, (CamelForeachPartFunc) save_attachment_cb, &data);

    if (data.found) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Attachment saved successfully"));
    } else {
        gchar *msg = g_strdup_printf ("Attachment '%s' not found or save failed: %s", attachment_name, data.error ? data.error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&data.error);
    }

    g_object_unref (message);
    g_object_unref (folder_obj);
    g_object_unref (service);
}

static void
handle_method_call (GDBusConnection *connection,
                    const gchar *sender,
                    const gchar *object_path,
                    const gchar *interface_name,
                    const gchar *method_name,
                    GVariant *parameters,
                    GDBusMethodInvocation *invocation,
                    gpointer user_data)
{
    if (g_strcmp0 (method_name, "MoveMessage") == 0) {
        handle_move_message (parameters, invocation);
    } else if (g_strcmp0 (method_name, "DeleteMessage") == 0) {
        handle_delete_message (parameters, invocation);
    } else if (g_strcmp0 (method_name, "GetMessage") == 0) {
        handle_get_message (parameters, invocation);
    } else if (g_strcmp0 (method_name, "ListAttachments") == 0) {
        handle_list_attachments (parameters, invocation);
    } else if (g_strcmp0 (method_name, "SaveAttachment") == 0) {
        handle_save_attachment (parameters, invocation);
    }
}

static const GDBusInterfaceVTable vtable = {
    handle_method_call, NULL, NULL
};

G_MODULE_EXPORT gboolean
e_plugin_ui_init (gpointer ui_manager, gpointer user_data)
{
    const gchar *prgname = g_get_prgname ();
    GError *error = NULL;

    if (g_strcmp0 (prgname, "org.gnome.Evolution") != 0 && g_strcmp0 (prgname, "evolution") != 0)
        return TRUE;

    g_print ("CUSTOM INSTRUMENTATION PLUGIN LOADING in %s (PID %d)\n", prgname, (int)getpid());

    if (!global_conn) {
        global_conn = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &error);
        if (!global_conn) {
            g_printerr ("Failed to get bus: %s\n", error->message);
            g_error_free (error);
            return TRUE;
        }
    }

    if (!introspection_data)
        introspection_data = g_dbus_node_info_new_for_xml (xml, NULL);

    registration_id = g_dbus_connection_register_object (global_conn,
        "/org/gnome/evolution/McpAutomationBridge",
        introspection_data->interfaces[0],
        &vtable,
        NULL, NULL, NULL);

    if (registration_id > 0)
        g_print ("Registered D-Bus object at /org/gnome/evolution/McpAutomationBridge (PID %d)\n", (int)getpid());
    else
        g_printerr ("Failed to register D-Bus object (PID %d)\n", (int)getpid());

    return TRUE;
}
