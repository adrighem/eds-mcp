#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>
#include <sys/stat.h>

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

#define MAX_ATTACHMENT_COUNT 10
#define MAX_ATTACHMENT_TOTAL_BYTES (20 * 1024 * 1024)

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
    "    </method>\n"
    "    <method name='MarkAsRead'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='message_uid' direction='in'/>\n"
    "      <arg type='s' name='folder_name' direction='in'/>\n"
    "      <arg type='b' name='read' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='message' direction='out'/>\n"
    "    </method>\n"
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
    "    <method name='SendMail'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='to' direction='in'/>\n"
    "      <arg type='s' name='subject' direction='in'/>\n"
    "      <arg type='s' name='body' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='message' direction='out'/>\n"
    "    </method>\n"
    "    <method name='SendMailWithAttachments'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='to' direction='in'/>\n"
    "      <arg type='s' name='subject' direction='in'/>\n"
    "      <arg type='s' name='body' direction='in'/>\n"
    "      <arg type='as' name='attachment_paths' direction='in'/>\n"
    "      <arg type='s' name='in_reply_to' direction='in'/>\n"
    "      <arg type='s' name='references' direction='in'/>\n"
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
handle_mark_as_read (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    const gchar *account_uid, *message_uid, *folder_name;
    gboolean read_flag;
    CamelService *service;
    CamelFolder *folder_obj = NULL;
    GError *error = NULL;

    g_print ("McpAutomationBridge: MarkAsRead called\n");

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

    g_variant_get (parameters, "(&s&s&sb)", &account_uid, &message_uid, &folder_name, &read_flag);

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

    camel_folder_set_message_flags (folder_obj, message_uid, CAMEL_MESSAGE_SEEN, read_flag ? CAMEL_MESSAGE_SEEN : 0);
    camel_folder_synchronize_sync (folder_obj, FALSE, NULL, NULL);

    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, read_flag ? "Message marked as read" : "Message marked as unread"));

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
    stream = camel_stream_mem_new ();
    camel_data_wrapper_write_to_stream_sync (dw, stream, NULL, &error);
    
    if (error) {
        gchar *msg = g_strdup_printf ("Failed to write message to stream: %s", error->message);
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
    } else {
        byte_array = camel_stream_mem_get_byte_array (CAMEL_STREAM_MEM (stream));
        if (!byte_array) {
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Message stream did not produce data"));
        } else {
            gchar *valid_utf8 = g_utf8_make_valid ((const gchar *)byte_array->data, byte_array->len);
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, valid_utf8));
            g_free (valid_utf8);
        }
    }

    g_object_unref (stream);
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
        const gchar *mime_type = dw ? camel_data_wrapper_get_mime_type (dw) : "application/octet-stream";
        
        json_object_set_string_member (obj, "filename", filename);
        json_object_set_string_member (obj, "mime_type", mime_type ? mime_type : "application/octet-stream");
        
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
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return;
    }

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
    
    if (data->found || data->error) return;

    filename = camel_mime_part_get_filename (part);
    if (filename && g_strcmp0 (filename, data->target_name) == 0) {
        CamelDataWrapper *dw = camel_medium_get_content (CAMEL_MEDIUM (part));
        CamelStream *stream;

        if (!dw) {
            data->error = g_error_new_literal (G_IO_ERROR, G_IO_ERROR_FAILED, "Attachment has no content");
            return;
        }
        
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
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return;
    }

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

static gboolean
header_value_is_safe (const gchar *value)
{
    return value == NULL || (strchr (value, '\r') == NULL && strchr (value, '\n') == NULL);
}

static gboolean
set_message_content (CamelMimeMessage *message,
                     const gchar *body,
                     gchar **attachment_paths,
                     GError **error)
{
    guint attachment_count;
    guint64 total_bytes = 0;
    CamelMultipart *multipart;
    CamelMimePart *part;

    if (!attachment_paths || !attachment_paths[0]) {
        camel_mime_part_set_content (
            CAMEL_MIME_PART (message), body, strlen (body), "text/plain; charset=utf-8");
        return TRUE;
    }

    attachment_count = g_strv_length (attachment_paths);
    if (attachment_count > MAX_ATTACHMENT_COUNT) {
        g_set_error (
            error,
            G_IO_ERROR,
            G_IO_ERROR_INVALID_ARGUMENT,
            "At most %u attachments are allowed.",
            MAX_ATTACHMENT_COUNT);
        return FALSE;
    }

    for (guint index = 0; index < attachment_count; index++) {
        GStatBuf stat_buffer;
        gchar *basename = g_path_get_basename (attachment_paths[index]);

        if (g_stat (attachment_paths[index], &stat_buffer) != 0 ||
            !S_ISREG (stat_buffer.st_mode) ||
            g_access (attachment_paths[index], R_OK) != 0) {
            g_set_error (
                error,
                G_IO_ERROR,
                G_IO_ERROR_INVALID_ARGUMENT,
                "Attachment '%s' is not a readable regular file.",
                basename);
            g_free (basename);
            return FALSE;
        }

        if (stat_buffer.st_size < 0 ||
            (guint64) stat_buffer.st_size > MAX_ATTACHMENT_TOTAL_BYTES - total_bytes) {
            g_set_error_literal (
                error,
                G_IO_ERROR,
                G_IO_ERROR_INVALID_ARGUMENT,
                "Attachments exceed the 20 MiB total size limit.");
            g_free (basename);
            return FALSE;
        }

        total_bytes += (guint64) stat_buffer.st_size;
        g_free (basename);
    }

    multipart = camel_multipart_new ();
    camel_data_wrapper_set_mime_type (CAMEL_DATA_WRAPPER (multipart), "multipart/mixed");
    camel_multipart_set_boundary (multipart, NULL);

    part = camel_mime_part_new ();
    camel_mime_part_set_content (part, body, strlen (body), "text/plain; charset=utf-8");
    camel_multipart_add_part (multipart, part);
    g_object_unref (part);

    for (guint index = 0; index < attachment_count; index++) {
        gchar *contents = NULL;
        gsize contents_length = 0;
        gchar *basename = g_path_get_basename (attachment_paths[index]);
        gchar *content_type;
        gchar *mime_type;
        gboolean uncertain = FALSE;
        GError *read_error = NULL;

        if (!g_file_get_contents (
                attachment_paths[index], &contents, &contents_length, &read_error)) {
            g_set_error (
                error,
                G_IO_ERROR,
                G_IO_ERROR_FAILED,
                "Could not read attachment '%s'.",
                basename);
            g_clear_error (&read_error);
            g_free (basename);
            g_object_unref (multipart);
            return FALSE;
        }

        content_type = g_content_type_guess (
            basename,
            (const guchar *) contents,
            MIN (contents_length, (gsize) 512),
            &uncertain);
        mime_type = content_type ? g_content_type_get_mime_type (content_type) : NULL;
        if (!mime_type)
            mime_type = g_strdup ("application/octet-stream");

        part = camel_mime_part_new ();
        camel_mime_part_set_content (
            part, contents, (gint) contents_length, mime_type);
        camel_mime_part_set_filename (part, basename);
        camel_mime_part_set_disposition (part, "attachment");
        camel_mime_part_set_encoding (part, CAMEL_TRANSFER_ENCODING_BASE64);
        camel_multipart_add_part (multipart, part);

        g_object_unref (part);
        g_free (mime_type);
        g_free (content_type);
        g_free (basename);
        g_free (contents);
    }

    camel_medium_set_content (CAMEL_MEDIUM (message), CAMEL_DATA_WRAPPER (multipart));
    g_object_unref (multipart);
    return TRUE;
}

static void
send_mail (const gchar *account_uid,
           const gchar *to_str,
           const gchar *subject_str,
           const gchar *body_str,
           gchar **attachment_paths,
           const gchar *in_reply_to,
           const gchar *references,
           GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    ESourceRegistry *registry;
    ESource *source = NULL;
    ESourceMailSubmission *submission = NULL;
    ESourceMailIdentity *identity = NULL;
    const gchar *transport_uid = NULL;
    const gchar *from_name = NULL;
    const gchar *from_address = NULL;
    CamelService *service = NULL;
    CamelTransport *transport = NULL;
    CamelMimeMessage *message = NULL;
    CamelInternetAddress *from_addr = NULL;
    CamelInternetAddress *to_addr = NULL;
    gboolean success = FALSE;
    GError *error = NULL;

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
    registry = e_shell_get_registry (shell);

    if (!header_value_is_safe (in_reply_to) || !header_value_is_safe (references)) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, "Reply headers contain invalid characters"));
        return;
    }

    source = e_source_registry_ref_source (registry, account_uid);
    if (!source) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account source not found in registry"));
        return;
    }

    // 1. Resolve Transport (Submission) UID (checking account, parents, and siblings)
    if (e_source_has_extension (source, E_SOURCE_EXTENSION_MAIL_SUBMISSION)) {
        submission = e_source_get_extension (source, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
        transport_uid = e_source_mail_submission_get_transport_uid (submission);
    }
    if (!transport_uid) {
        const gchar *parent_uid = e_source_get_parent (source);
        if (parent_uid) {
            ESource *parent_source = e_source_registry_ref_source (registry, parent_uid);
            if (parent_source) {
                if (e_source_has_extension (parent_source, E_SOURCE_EXTENSION_MAIL_SUBMISSION)) {
                    submission = e_source_get_extension (parent_source, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
                    transport_uid = e_source_mail_submission_get_transport_uid (submission);
                }
                g_object_unref (parent_source);
            }
            if (!transport_uid) {
                GList *sources = e_source_registry_list_sources (registry, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
                for (GList *l = sources; l != NULL; l = l->next) {
                    ESource *s = E_SOURCE (l->data);
                    if (g_strcmp0 (e_source_get_parent (s), parent_uid) == 0) {
                        submission = e_source_get_extension (s, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
                        transport_uid = e_source_mail_submission_get_transport_uid (submission);
                        break;
                    }
                }
                g_list_free (sources);
            }
        }
    }

    if (!transport_uid) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Could not resolve transport (submission) UID for account"));
        g_object_unref (source);
        return;
    }

    // 2. Resolve Sender Identity details (checking account, parents, and siblings)
    if (e_source_has_extension (source, E_SOURCE_EXTENSION_MAIL_IDENTITY)) {
        identity = e_source_get_extension (source, E_SOURCE_EXTENSION_MAIL_IDENTITY);
        from_name = e_source_mail_identity_get_name (identity);
        from_address = e_source_mail_identity_get_address (identity);
    }
    if (!from_address) {
        const gchar *parent_uid = e_source_get_parent (source);
        if (parent_uid) {
            ESource *parent_source = e_source_registry_ref_source (registry, parent_uid);
            if (parent_source) {
                if (e_source_has_extension (parent_source, E_SOURCE_EXTENSION_MAIL_IDENTITY)) {
                    identity = e_source_get_extension (parent_source, E_SOURCE_EXTENSION_MAIL_IDENTITY);
                    from_name = e_source_mail_identity_get_name (identity);
                    from_address = e_source_mail_identity_get_address (identity);
                }
                g_object_unref (parent_source);
            }
            if (!from_address) {
                GList *sources = e_source_registry_list_sources (registry, E_SOURCE_EXTENSION_MAIL_IDENTITY);
                for (GList *l = sources; l != NULL; l = l->next) {
                    ESource *s = E_SOURCE (l->data);
                    if (g_strcmp0 (e_source_get_parent (s), parent_uid) == 0) {
                        identity = e_source_get_extension (s, E_SOURCE_EXTENSION_MAIL_IDENTITY);
                        from_name = e_source_mail_identity_get_name (identity);
                        from_address = e_source_mail_identity_get_address (identity);
                        break;
                    }
                }
                g_list_free (sources);
            }
        }
    }

    if (!from_address) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Could not resolve sender from-address for account"));
        g_object_unref (source);
        return;
    }

    // 3. Retrieve Camel Transport service
    service = camel_session_ref_service (CAMEL_SESSION (session), transport_uid);
    if (!service || !CAMEL_IS_TRANSPORT (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Transport service not found or invalid"));
        if (service) g_object_unref (service);
        g_object_unref (source);
        return;
    }
    transport = CAMEL_TRANSPORT (service);

    // 4. Create and populate message
    message = camel_mime_message_new ();
    camel_mime_message_set_subject (message, subject_str);

    if (!set_message_content (message, body_str, attachment_paths, &error)) {
        gchar *message_error = g_strdup_printf (
            "Failed to build message: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, message_error));
        g_free (message_error);
        g_clear_error (&error);
        g_object_unref (message);
        g_object_unref (service);
        g_object_unref (source);
        return;
    }

    if (in_reply_to && *in_reply_to)
        camel_medium_set_header (CAMEL_MEDIUM (message), "In-Reply-To", in_reply_to);
    if (references && *references)
        camel_medium_set_header (CAMEL_MEDIUM (message), "References", references);

    // Setup Addresses (from, to)
    from_addr = camel_internet_address_new ();
    camel_internet_address_add (from_addr, from_name, from_address);
    camel_mime_message_set_from (message, from_addr);

    to_addr = camel_internet_address_new ();
    camel_internet_address_add (to_addr, NULL, to_str);
    camel_mime_message_set_recipients (message, CAMEL_RECIPIENT_TYPE_TO, to_addr);

    // 5. Connect and send
    if (!camel_service_connect_sync (service, NULL, &error)) {
        gchar *msg_err = g_strdup_printf ("Failed to connect to transport service: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg_err));
        g_free (msg_err);
        g_clear_error (&error);
    } else {
        gboolean out_sent_message_saved = FALSE;
        success = camel_transport_send_to_sync (transport, message, CAMEL_ADDRESS (from_addr), CAMEL_ADDRESS (to_addr), &out_sent_message_saved, NULL, &error);
        if (success) {
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Email sent successfully"));
        } else {
            gchar *msg_err = g_strdup_printf ("Failed to send email: %s", error ? error->message : "Unknown error");
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg_err));
            g_free (msg_err);
            g_clear_error (&error);
        }
        camel_service_disconnect_sync (service, TRUE, NULL, NULL);
    }

    // Clean up
    g_object_unref (from_addr);
    g_object_unref (to_addr);
    g_object_unref (message);
    g_object_unref (service);
    g_object_unref (source);
}

static void
handle_send_mail (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *to_str, *subject_str, *body_str;

    g_print ("McpAutomationBridge: SendMail called\n");
    g_variant_get (
        parameters,
        "(&s&s&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str);
    send_mail (
        account_uid, to_str, subject_str, body_str, NULL, "", "", invocation);
}

static void
handle_send_mail_with_attachments (GVariant *parameters,
                                   GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *to_str, *subject_str, *body_str;
    const gchar *in_reply_to, *references;
    GVariant *attachment_paths_variant;
    gchar **attachment_paths;

    g_print ("McpAutomationBridge: SendMailWithAttachments called\n");
    g_variant_get (
        parameters,
        "(&s&s&s&s@as&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str,
        &attachment_paths_variant,
        &in_reply_to,
        &references);
    attachment_paths = g_variant_dup_strv (attachment_paths_variant, NULL);

    send_mail (
        account_uid,
        to_str,
        subject_str,
        body_str,
        attachment_paths,
        in_reply_to,
        references,
        invocation);

    g_strfreev (attachment_paths);
    g_variant_unref (attachment_paths_variant);
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
    } else if (g_strcmp0 (method_name, "MarkAsRead") == 0) {
        handle_mark_as_read (parameters, invocation);
    } else if (g_strcmp0 (method_name, "GetMessage") == 0) {
        handle_get_message (parameters, invocation);
    } else if (g_strcmp0 (method_name, "ListAttachments") == 0) {
        handle_list_attachments (parameters, invocation);
    } else if (g_strcmp0 (method_name, "SaveAttachment") == 0) {
        handle_save_attachment (parameters, invocation);
    } else if (g_strcmp0 (method_name, "SendMail") == 0) {
        handle_send_mail (parameters, invocation);
    } else if (g_strcmp0 (method_name, "SendMailWithAttachments") == 0) {
        handle_send_mail_with_attachments (parameters, invocation);
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

    if (registration_id > 0)
        return TRUE;

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
