#include <errno.h>
#include <fcntl.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>
#include <sys/stat.h>
#include <unistd.h>

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
#include <composer/e-msg-composer.h>
#include <gtk/gtk.h>

static GDBusNodeInfo *introspection_data = NULL;
static guint registration_id = 0;
static GDBusConnection *global_conn = NULL;

#ifndef BRIDGE_GIT_COMMIT
#define BRIDGE_GIT_COMMIT "unknown"
#endif
#ifndef BRIDGE_BUILD_DATE
#define BRIDGE_BUILD_DATE __DATE__ " " __TIME__
#endif

#define MAX_ATTACHMENT_COUNT 10
#define MAX_ATTACHMENT_TOTAL_BYTES (20 * 1024 * 1024)

static const gchar xml[] =
    "<node>"
    "  <interface name='org.gnome.Evolution.McpAutomationBridge'>"
    "    <method name='GetVersion'>"
    "      <arg type='s' name='git_commit' direction='out'/>"
    "      <arg type='s' name='build_date' direction='out'/>"
    "    </method>"
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
    "      <arg type='s' name='cc' direction='in'/>\n"
    "      <arg type='s' name='bcc' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='message' direction='out'/>\n"
    "    </method>\n"
    "    <method name='SaveDraft'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='to' direction='in'/>\n"
    "      <arg type='s' name='subject' direction='in'/>\n"
    "      <arg type='s' name='body' direction='in'/>\n"
    "      <arg type='as' name='attachment_paths' direction='in'/>\n"
    "      <arg type='s' name='in_reply_to' direction='in'/>\n"
    "      <arg type='s' name='references' direction='in'/>\n"
    "      <arg type='s' name='cc' direction='in'/>\n"
    "      <arg type='s' name='bcc' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='folder' direction='out'/>\n"
    "      <arg type='s' name='draft_uid' direction='out'/>\n"
    "    </method>\n"
    "    <method name='OpenComposer'>\n"
    "      <arg type='s' name='account_uid' direction='in'/>\n"
    "      <arg type='s' name='to' direction='in'/>\n"
    "      <arg type='s' name='subject' direction='in'/>\n"
    "      <arg type='s' name='body' direction='in'/>\n"
    "      <arg type='as' name='attachment_paths' direction='in'/>\n"
    "      <arg type='s' name='in_reply_to' direction='in'/>\n"
    "      <arg type='s' name='references' direction='in'/>\n"
    "      <arg type='s' name='cc' direction='in'/>\n"
    "      <arg type='s' name='bcc' direction='in'/>\n"
    "      <arg type='b' name='success' direction='out'/>\n"
    "      <arg type='s' name='message' direction='out'/>\n"
    "    </method>\n"
    "  </interface>\n"
    "</node>";

/* PHASE 1.2 CASE-INSENSITIVE FOLDER RESOLUTION */
static CamelFolder *
resolve_store_folder_sync (CamelStore *store, const gchar *folder_name, GError **error)
{
    const gchar *effective_name = folder_name && *folder_name ? folder_name : "Inbox";
    CamelFolder *folder = NULL;
    GError *local_err = NULL;

    folder = camel_store_get_folder_sync (store, effective_name, 0, NULL, &local_err);
    if (folder) {
        return folder;
    }

    CamelFolderInfo *fi = camel_store_get_folder_info_sync (store, NULL, CAMEL_STORE_FOLDER_INFO_RECURSIVE | CAMEL_STORE_FOLDER_INFO_FAST, NULL, NULL);
    if (!fi) {
        g_propagate_error (error, local_err);
        return NULL;
    }

    gchar *effective_name_folded = g_utf8_casefold (effective_name, -1);
    gchar *matched_name = NULL;

    GPtrArray *stack = g_ptr_array_new ();
    if (fi) g_ptr_array_add (stack, fi);

    while (stack->len > 0) {
        CamelFolderInfo *curr = g_ptr_array_remove_index (stack, stack->len - 1);
        while (curr) {
            if (curr->full_name) {
                gchar *curr_folded = g_utf8_casefold (curr->full_name, -1);
                if (g_strcmp0 (curr_folded, effective_name_folded) == 0) {
                    matched_name = g_strdup (curr->full_name);
                }
                g_free (curr_folded);
                if (matched_name) break;
            }
            if (curr->child) {
                g_ptr_array_add (stack, curr->child);
            }
            curr = curr->next;
        }
        if (matched_name) break;
    }

    g_ptr_array_free (stack, TRUE);
    g_free (effective_name_folded);
    camel_folder_info_free (fi);

    if (matched_name) {
        g_clear_error (&local_err);
        folder = camel_store_get_folder_sync (store, matched_name, 0, NULL, error);
        g_free (matched_name);
        return folder;
    }

    g_propagate_error (error, local_err);
    return NULL;
}

/* SHARED HELPERS */
static gboolean
header_value_is_safe (const gchar *value)
{
    return value == NULL || (strchr (value, '\r') == NULL && strchr (value, '\n') == NULL);
}

static ESource *
find_account_extension_source (ESourceRegistry *registry, ESource *account_source, const gchar *extension_name)
{
    if (e_source_has_extension (account_source, extension_name)) {
        return g_object_ref (account_source);
    }
    const gchar *parent_uid = e_source_get_parent (account_source);
    if (parent_uid) {
        ESource *parent_source = e_source_registry_ref_source (registry, parent_uid);
        if (parent_source) {
            if (e_source_has_extension (parent_source, extension_name)) {
                return parent_source; /* already reffed */
            }
            g_object_unref (parent_source);

            GList *sources = e_source_registry_list_sources (registry, extension_name);
            for (GList *l = sources; l != NULL; l = l->next) {
                ESource *s = E_SOURCE (l->data);
                if (g_strcmp0 (e_source_get_parent (s), parent_uid) == 0) {
                    ESource *ret = g_object_ref (s);
                    g_list_free_full (sources, g_object_unref);
                    return ret;
                }
            }
            g_list_free_full (sources, g_object_unref);
        }
    }
    return NULL;
}

static gboolean
resolve_identity_details (ESourceRegistry *registry, ESource *account_source, gchar **out_identity_uid, gchar **out_from_name, gchar **out_from_address)
{
    ESource *identity_source = find_account_extension_source (registry, account_source, E_SOURCE_EXTENSION_MAIL_IDENTITY);
    if (!identity_source) return FALSE;

    ESourceMailIdentity *identity = e_source_get_extension (identity_source, E_SOURCE_EXTENSION_MAIL_IDENTITY);
    if (out_identity_uid) *out_identity_uid = g_strdup (e_source_get_uid (identity_source));
    if (out_from_name) *out_from_name = g_strdup (e_source_mail_identity_get_name (identity));
    if (out_from_address) *out_from_address = g_strdup (e_source_mail_identity_get_address (identity));

    g_object_unref (identity_source);
    return TRUE;
}

static CamelFolder *
resolve_special_folder_sync (EMailSession *session, ESource *account_source, const gchar *configured_uri, CamelFolderInfoFlags target_type_flag, const gchar *fallback_name, EMailLocalFolder local_fallback)
{
    CamelFolder *folder = NULL;

    if (configured_uri && *configured_uri) {
        folder = e_mail_session_uri_to_folder_sync (session, configured_uri, 0, NULL, NULL);
        if (folder) return folder;
    }

    CamelService *store_svc = camel_session_ref_service (CAMEL_SESSION (session), e_source_get_uid (account_source));
    if (store_svc && CAMEL_IS_STORE (store_svc)) {
        CamelFolderInfo *fi = camel_store_get_folder_info_sync (CAMEL_STORE (store_svc), NULL, CAMEL_STORE_FOLDER_INFO_RECURSIVE | CAMEL_STORE_FOLDER_INFO_FAST, NULL, NULL);
        if (fi) {
            gchar *matched_name = NULL;
            GPtrArray *stack = g_ptr_array_new ();
            g_ptr_array_add (stack, fi);

            while (stack->len > 0) {
                CamelFolderInfo *curr = g_ptr_array_remove_index (stack, stack->len - 1);
                while (curr) {
                    if ((curr->flags & CAMEL_FOLDER_TYPE_MASK) == target_type_flag) {
                        matched_name = g_strdup (curr->full_name);
                        break;
                    }
                    if (curr->child) {
                        g_ptr_array_add (stack, curr->child);
                    }
                    curr = curr->next;
                }
                if (matched_name) break;
            }

            g_ptr_array_free (stack, TRUE);
            camel_folder_info_free (fi);

            if (matched_name) {
                folder = resolve_store_folder_sync (CAMEL_STORE (store_svc), matched_name, NULL);
                g_free (matched_name);
            }
        }
        if (!folder) {
            folder = resolve_store_folder_sync (CAMEL_STORE (store_svc), fallback_name, NULL);
        }
    }
    if (store_svc) g_object_unref (store_svc);

    if (!folder) {
        folder = e_mail_session_get_local_folder (session, local_fallback);
        if (folder) g_object_ref (folder);
    }

    return folder;
}

static void
add_recipients_from_string (CamelInternetAddress *addr_obj, const gchar *input_str)
{
    gchar **tokens;

    if (!addr_obj || !input_str || !*input_str)
        return;

    tokens = g_strsplit_set (input_str, ",;", -1);
    for (gint i = 0; tokens && tokens[i]; i++) {
        gchar *trimmed = g_strstrip (tokens[i]);
        if (*trimmed) {
            if (camel_address_decode (CAMEL_ADDRESS (addr_obj), trimmed) < 0) {
                camel_internet_address_add (addr_obj, NULL, trimmed);
            }
        }
    }
    g_strfreev (tokens);
}

static gboolean
read_bounded_regular_file (const gchar *path,
                           const gchar *basename,
                           guint64 max_bytes,
                           GByteArray **out_bytes,
                           GError **error)
{
    struct stat st;
    int fd = open (path, O_RDONLY | O_CLOEXEC);
    GByteArray *buf;
    guint8 chunk[65536];

    if (fd < 0) {
        g_set_error (
            error,
            G_IO_ERROR,
            G_IO_ERROR_INVALID_ARGUMENT,
            "Attachment '%s' is not a readable regular file.",
            basename);
        return FALSE;
    }

    if (fstat (fd, &st) != 0 || !S_ISREG (st.st_mode)) {
        close (fd);
        g_set_error (
            error,
            G_IO_ERROR,
            G_IO_ERROR_INVALID_ARGUMENT,
            "Attachment '%s' is not a readable regular file.",
            basename);
        return FALSE;
    }

    if (st.st_size < 0 || (guint64) st.st_size > max_bytes) {
        close (fd);
        g_set_error_literal (
            error,
            G_IO_ERROR,
            G_IO_ERROR_INVALID_ARGUMENT,
            "Attachments exceed the 20 MiB total size limit.");
        return FALSE;
    }

    buf = g_byte_array_sized_new ((guint) st.st_size);
    for (;;) {
        ssize_t n = read (fd, chunk, sizeof (chunk));
        if (n == 0)
            break;
        if (n < 0) {
            if (errno == EINTR)
                continue;
            g_byte_array_unref (buf);
            close (fd);
            g_set_error (
                error,
                G_IO_ERROR,
                G_IO_ERROR_FAILED,
                "Could not read attachment '%s'.",
                basename);
            return FALSE;
        }
        if ((guint64) buf->len + (guint64) n > max_bytes) {
            g_byte_array_unref (buf);
            close (fd);
            g_set_error_literal (
                error,
                G_IO_ERROR,
                G_IO_ERROR_INVALID_ARGUMENT,
                "Attachments exceed the 20 MiB total size limit.");
            return FALSE;
        }
        g_byte_array_append (buf, chunk, (guint) n);
    }

    close (fd);
    *out_bytes = buf;
    return TRUE;
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

    multipart = camel_multipart_new ();
    camel_data_wrapper_set_mime_type (CAMEL_DATA_WRAPPER (multipart), "multipart/mixed");
    camel_multipart_set_boundary (multipart, NULL);

    part = camel_mime_part_new ();
    camel_mime_part_set_content (part, body, strlen (body), "text/plain; charset=utf-8");
    camel_multipart_add_part (multipart, part);
    g_object_unref (part);

    for (guint index = 0; index < attachment_count; index++) {
        GByteArray *file_bytes = NULL;
        gchar *basename = g_path_get_basename (attachment_paths[index]);
        gchar *content_type;
        gchar *mime_type;
        gboolean uncertain = FALSE;

        if (!read_bounded_regular_file (
                attachment_paths[index],
                basename,
                MAX_ATTACHMENT_TOTAL_BYTES - total_bytes,
                &file_bytes,
                error)) {
            g_free (basename);
            g_object_unref (multipart);
            return FALSE;
        }

        total_bytes += (guint64) file_bytes->len;

        content_type = g_content_type_guess (
            basename,
            file_bytes->data,
            MIN ((gsize) file_bytes->len, (gsize) 512),
            &uncertain);
        mime_type = content_type ? g_content_type_get_mime_type (content_type) : NULL;
        if (!mime_type)
            mime_type = g_strdup ("application/octet-stream");

        part = camel_mime_part_new ();
        camel_mime_part_set_content (
            part, (const gchar *) file_bytes->data, (gint) file_bytes->len, mime_type);
        camel_mime_part_set_filename (part, basename);
        camel_mime_part_set_disposition (part, "attachment");
        camel_mime_part_set_encoding (part, CAMEL_TRANSFER_ENCODING_BASE64);
        camel_multipart_add_part (multipart, part);

        g_object_unref (part);
        g_free (mime_type);
        g_free (content_type);
        g_free (basename);
        g_byte_array_unref (file_bytes);
    }

    camel_medium_set_content (CAMEL_MEDIUM (message), CAMEL_DATA_WRAPPER (multipart));
    g_object_unref (multipart);
    return TRUE;
}

static CamelMimeMessage *
build_mime_message (const gchar *subject_str,
                    const gchar *body_str,
                    gchar **attachment_paths,
                    const gchar *from_name,
                    const gchar *from_address,
                    const gchar *to_str,
                    const gchar *cc_str,
                    const gchar *bcc_str,
                    const gchar *in_reply_to,
                    const gchar *references,
                    GError **error)
{
    CamelMimeMessage *message = camel_mime_message_new ();
    camel_mime_message_set_date (message, CAMEL_MESSAGE_DATE_CURRENT, 0);
    camel_mime_message_set_subject (message, subject_str);

    if (!set_message_content (message, body_str, attachment_paths, error)) {
        g_object_unref (message);
        return NULL;
    }

    if (in_reply_to && *in_reply_to)
        camel_medium_set_header (CAMEL_MEDIUM (message), "In-Reply-To", in_reply_to);
    if (references && *references)
        camel_medium_set_header (CAMEL_MEDIUM (message), "References", references);

    if (from_address) {
        CamelInternetAddress *from_addr = camel_internet_address_new ();
        camel_internet_address_add (from_addr, from_name, from_address);
        camel_mime_message_set_from (message, from_addr);
        g_object_unref (from_addr);
    }

    CamelInternetAddress *to_addr = camel_internet_address_new ();
    add_recipients_from_string (to_addr, to_str);
    camel_mime_message_set_recipients (message, CAMEL_RECIPIENT_TYPE_TO, to_addr);
    g_object_unref (to_addr);

    if (cc_str && *cc_str) {
        CamelInternetAddress *cc_addr = camel_internet_address_new ();
        add_recipients_from_string (cc_addr, cc_str);
        camel_mime_message_set_recipients (message, CAMEL_RECIPIENT_TYPE_CC, cc_addr);
        g_object_unref (cc_addr);
    }

    if (bcc_str && *bcc_str) {
        CamelInternetAddress *bcc_addr = camel_internet_address_new ();
        add_recipients_from_string (bcc_addr, bcc_str);
        camel_mime_message_set_recipients (message, CAMEL_RECIPIENT_TYPE_BCC, bcc_addr);
        g_object_unref (bcc_addr);
    }

    return message;
}

/* D-BUS METHODS */

static gboolean
acquire_store_and_folder_or_fail (const gchar *account_uid,
                                  const gchar *folder_name,
                                  const gchar *folder_err_prefix,
                                  GDBusMethodInvocation *invocation,
                                  CamelService **out_service,
                                  CamelFolder **out_folder)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailSession *session;
    CamelService *service;
    CamelFolder *folder_obj;
    GError *error = NULL;

    if (!shell) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return FALSE;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, "Mail backend not found"));
        return FALSE;
    }

    session = e_mail_backend_get_session (E_MAIL_BACKEND (shell_backend));
    service = camel_session_ref_service (CAMEL_SESSION (session), account_uid);
    if (!service || !CAMEL_IS_STORE (service)) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, "Account not found or is not a store"));
        if (service)
            g_object_unref (service);
        return FALSE;
    }

    folder_obj = resolve_store_folder_sync (CAMEL_STORE (service), folder_name, &error);
    if (!folder_obj) {
        gchar *msg = g_strdup_printf (
            "%s: %s", folder_err_prefix, error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg));
        g_free (msg);
        g_clear_error (&error);
        g_object_unref (service);
        return FALSE;
    }

    *out_service = service;
    *out_folder = folder_obj;
    return TRUE;
}

static void
handle_move_message (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *message_uid, *source_folder, *dest_folder;
    CamelService *service = NULL;
    CamelFolder *src_folder_obj = NULL;
    CamelFolder *dst_folder_obj = NULL;
    GPtrArray *uids;
    GError *error = NULL;
    gboolean success;

    g_variant_get (parameters, "(&s&s&s&s)", &account_uid, &message_uid, &source_folder, &dest_folder);
    if (!acquire_store_and_folder_or_fail (
            account_uid, source_folder, "Source folder not found", invocation, &service, &src_folder_obj))
        return;

    dst_folder_obj = resolve_store_folder_sync (CAMEL_STORE (service), dest_folder, &error);
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
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service = NULL;
    CamelFolder *folder_obj = NULL;

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);
    if (!acquire_store_and_folder_or_fail (
            account_uid, folder_name, "Folder not found", invocation, &service, &folder_obj))
        return;

    camel_folder_set_message_flags (folder_obj, message_uid, CAMEL_MESSAGE_DELETED | CAMEL_MESSAGE_SEEN, CAMEL_MESSAGE_DELETED | CAMEL_MESSAGE_SEEN);
    camel_folder_synchronize_sync (folder_obj, FALSE, NULL, NULL);

    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Message deleted successfully"));

    g_object_unref (folder_obj);
    g_object_unref (service);
}

static void
handle_mark_as_read (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *message_uid, *folder_name;
    gboolean read_flag;
    CamelService *service = NULL;
    CamelFolder *folder_obj = NULL;

    g_variant_get (parameters, "(&s&s&sb)", &account_uid, &message_uid, &folder_name, &read_flag);
    if (!acquire_store_and_folder_or_fail (
            account_uid, folder_name, "Folder not found", invocation, &service, &folder_obj))
        return;

    camel_folder_set_message_flags (folder_obj, message_uid, CAMEL_MESSAGE_SEEN, read_flag ? CAMEL_MESSAGE_SEEN : 0);
    camel_folder_synchronize_sync (folder_obj, FALSE, NULL, NULL);

    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, read_flag ? "Message marked as read" : "Message marked as unread"));

    g_object_unref (folder_obj);
    g_object_unref (service);
}


static void
handle_get_message (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service = NULL;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    CamelDataWrapper *dw = NULL;
    CamelStream *stream = NULL;
    GByteArray *byte_array = NULL;
    GError *error = NULL;

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);
    if (!acquire_store_and_folder_or_fail (
            account_uid, folder_name, "Folder not found", invocation, &service, &folder_obj))
        return;

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

static gboolean
list_attachments_cb (CamelMimeMessage *msg, CamelMimePart *part, CamelMimePart *container, gpointer user_data)
{
    (void)msg;
    (void)container;
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
    return TRUE;
}

static void
handle_list_attachments (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *message_uid, *folder_name;
    CamelService *service = NULL;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    g_variant_get (parameters, "(&s&s&s)", &account_uid, &message_uid, &folder_name);
    if (!acquire_store_and_folder_or_fail (
            account_uid, folder_name, "Folder not found", invocation, &service, &folder_obj))
        return;

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

static gboolean
save_attachment_cb (CamelMimeMessage *msg, CamelMimePart *part, CamelMimePart *container, gpointer user_data)
{
    (void)msg;
    (void)container;
    SaveAttachmentData *data = user_data;
    const gchar *filename;

    if (data->found || data->error) return FALSE;

    filename = camel_mime_part_get_filename (part);
    if (filename && g_strcmp0 (filename, data->target_name) == 0) {
        CamelDataWrapper *dw = camel_medium_get_content (CAMEL_MEDIUM (part));
        CamelStream *stream;

        if (!dw) {
            data->error = g_error_new_literal (G_IO_ERROR, G_IO_ERROR_FAILED, "Attachment has no content");
            return FALSE;
        }

        stream = camel_stream_fs_new_with_name (data->dest_path, O_CREAT | O_WRONLY | O_TRUNC, 0666, &data->error);
        if (stream) {
            camel_data_wrapper_decode_to_stream_sync (dw, stream, NULL, &data->error);
            g_object_unref (stream);
            if (!data->error)
                data->found = TRUE;
        }
    }
    return TRUE;
}

static void
handle_save_attachment (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *message_uid, *folder_name, *attachment_name, *dest_path;
    CamelService *service = NULL;
    CamelFolder *folder_obj = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    g_variant_get (parameters, "(&s&s&s&s&s)", &account_uid, &message_uid, &folder_name, &attachment_name, &dest_path);
    if (!acquire_store_and_folder_or_fail (
            account_uid, folder_name, "Folder not found", invocation, &service, &folder_obj))
        return;

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
send_mail (const gchar *account_uid,
           const gchar *to_str,
           const gchar *subject_str,
           const gchar *body_str,
           gchar **attachment_paths,
           const gchar *in_reply_to,
           const gchar *references,
           const gchar *cc_str,
           const gchar *bcc_str,
           GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    ESourceRegistry *registry;
    ESource *source = NULL;
    ESource *submission_source = NULL;
    const gchar *transport_uid = NULL;
    gchar *from_name = NULL;
    gchar *from_address = NULL;
    CamelService *service = NULL;
    CamelTransport *transport = NULL;
    CamelMimeMessage *message = NULL;
    CamelInternetAddress *all_recipients = NULL;
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

    if (!header_value_is_safe (subject_str) ||
        !header_value_is_safe (to_str) ||
        !header_value_is_safe (cc_str) ||
        !header_value_is_safe (bcc_str) ||
        !header_value_is_safe (in_reply_to) ||
        !header_value_is_safe (references)) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, "Headers contain invalid characters"));
        return;
    }

    source = e_source_registry_ref_source (registry, account_uid);
    if (!source) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account source not found in registry"));
        return;
    }

    submission_source = find_account_extension_source (registry, source, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
    if (submission_source) {
        ESourceMailSubmission *submission = e_source_get_extension (submission_source, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
        transport_uid = e_source_mail_submission_get_transport_uid (submission);
    }

    if (!transport_uid) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Could not resolve transport (submission) UID for account"));
        if (submission_source) g_object_unref (submission_source);
        g_object_unref (source);
        return;
    }

    if (!resolve_identity_details (registry, source, NULL, &from_name, &from_address) || !from_address) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Could not resolve sender from-address for account"));
        g_free (from_name);
        g_free (from_address);
        if (submission_source) g_object_unref (submission_source);
        g_object_unref (source);
        return;
    }

    service = camel_session_ref_service (CAMEL_SESSION (session), transport_uid);
    if (!service || !CAMEL_IS_TRANSPORT (service)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Transport service not found or invalid"));
        if (service) g_object_unref (service);
        g_free (from_name);
        g_free (from_address);
        if (submission_source) g_object_unref (submission_source);
        g_object_unref (source);
        return;
    }
    transport = CAMEL_TRANSPORT (service);

    message = build_mime_message (subject_str, body_str, attachment_paths, from_name, from_address, to_str, cc_str, bcc_str, in_reply_to, references, &error);
    if (!message) {
        gchar *message_error = g_strdup_printf (
            "Failed to build message: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(bs)", FALSE, message_error));
        g_free (message_error);
        g_clear_error (&error);
        g_object_unref (service);
        g_free (from_name);
        g_free (from_address);
        if (submission_source) g_object_unref (submission_source);
        g_object_unref (source);
        return;
    }

    all_recipients = camel_internet_address_new ();
    if (1) {
        CamelInternetAddress *to_addr = camel_internet_address_new ();
        add_recipients_from_string (to_addr, to_str);
        camel_address_cat (CAMEL_ADDRESS (all_recipients), CAMEL_ADDRESS (to_addr));
        g_object_unref (to_addr);

        if (cc_str && *cc_str) {
            CamelInternetAddress *cc_addr = camel_internet_address_new ();
            add_recipients_from_string (cc_addr, cc_str);
            camel_address_cat (CAMEL_ADDRESS (all_recipients), CAMEL_ADDRESS (cc_addr));
            g_object_unref (cc_addr);
        }

        if (bcc_str && *bcc_str) {
            CamelInternetAddress *bcc_addr = camel_internet_address_new ();
            add_recipients_from_string (bcc_addr, bcc_str);
            camel_address_cat (CAMEL_ADDRESS (all_recipients), CAMEL_ADDRESS (bcc_addr));
            g_object_unref (bcc_addr);
        }
    }

    if (!camel_service_connect_sync (service, NULL, &error)) {
        gchar *msg_err = g_strdup_printf ("Failed to connect to transport service: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg_err));
        g_free (msg_err);
        g_clear_error (&error);
    } else {
        gboolean out_sent_message_saved = FALSE;
        CamelInternetAddress *from_addr = camel_internet_address_new ();
        camel_internet_address_add (from_addr, from_name, from_address);

        success = camel_transport_send_to_sync (transport, message, CAMEL_ADDRESS (from_addr), CAMEL_ADDRESS (all_recipients), &out_sent_message_saved, NULL, &error);
        if (success) {
            if (!out_sent_message_saved) {
                ESourceMailSubmission *submission = e_source_get_extension (submission_source, E_SOURCE_EXTENSION_MAIL_SUBMISSION);
                gboolean use_sent_folder = submission ? e_source_mail_submission_get_use_sent_folder (submission) : TRUE;

                if (use_sent_folder) {
                    const gchar *sent_folder_uri = submission ? e_source_mail_submission_get_sent_folder (submission) : NULL;
                    CamelFolder *sent_folder = resolve_special_folder_sync (session, source, sent_folder_uri, CAMEL_FOLDER_TYPE_SENT, "Sent", E_MAIL_LOCAL_FOLDER_SENT);
                    if (sent_folder) {
                        CamelMessageInfo *info = camel_message_info_new (NULL);
                        camel_message_info_set_flags (info, CAMEL_MESSAGE_SEEN, CAMEL_MESSAGE_SEEN);
                        GError *sent_err = NULL;
                        if (!camel_folder_append_message_sync (sent_folder, message, info, NULL, NULL, &sent_err)) {
                            g_warning ("Could not save copy to Sent folder: %s", sent_err ? sent_err->message : "Unknown error");
                            g_clear_error (&sent_err);
                            g_dbus_method_invocation_return_value (
                                invocation,
                                g_variant_new ("(bs)", TRUE, "Email sent successfully (warning: could not save copy to Sent folder)"));
                        } else {
                            camel_folder_synchronize_sync (sent_folder, FALSE, NULL, NULL);
                            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Email sent successfully"));
                        }
                        g_clear_object (&info);
                        g_object_unref (sent_folder);
                    } else {
                        g_warning ("Sent folder not found for account");
                        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Email sent successfully (warning: could not save copy to Sent folder)"));
                    }
                } else {
                    g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Email sent successfully"));
                }
            } else {
                g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", TRUE, "Email sent successfully"));
            }
        } else {
            gchar *msg_err = g_strdup_printf ("Failed to send email: %s", error ? error->message : "Unknown error");
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg_err));
            g_free (msg_err);
            g_clear_error (&error);
        }
        g_object_unref (from_addr);
        camel_service_disconnect_sync (service, TRUE, NULL, NULL);
    }

    if (all_recipients) g_object_unref (all_recipients);
    g_object_unref (message);
    g_object_unref (service);
    g_free (from_name);
    g_free (from_address);
    if (submission_source) g_object_unref (submission_source);
    g_object_unref (source);
}

static void
handle_send_mail (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    const gchar *account_uid, *to_str, *subject_str, *body_str;

    g_variant_get (
        parameters,
        "(&s&s&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str);
    send_mail (
        account_uid, to_str, subject_str, body_str, NULL, "", "", "", "", invocation);
}

static void
handle_send_mail_with_attachments (GVariant *parameters,
                                   GDBusMethodInvocation *invocation)
{
    const gchar *account_uid = NULL, *to_str = NULL, *subject_str = NULL, *body_str = NULL;
    const gchar *in_reply_to = "", *references = "", *cc_str = "", *bcc_str = "";
    GVariant *attachment_paths_variant = NULL;
    gchar **attachment_paths = NULL;

    g_variant_get (
        parameters,
        "(&s&s&s&s@as&s&s&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str,
        &attachment_paths_variant,
        &in_reply_to,
        &references,
        &cc_str,
        &bcc_str);
    attachment_paths = g_variant_dup_strv (attachment_paths_variant, NULL);

    send_mail (
        account_uid,
        to_str,
        subject_str,
        body_str,
        attachment_paths,
        in_reply_to,
        references,
        cc_str,
        bcc_str,
        invocation);

    g_strfreev (attachment_paths);
    g_variant_unref (attachment_paths_variant);
}

static void
handle_save_draft (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    EShellBackend *shell_backend;
    EMailBackend *backend;
    EMailSession *session;
    ESourceRegistry *registry;
    ESource *source = NULL;

    const gchar *account_uid, *to_str, *subject_str, *body_str;
    const gchar *in_reply_to, *references, *cc_str, *bcc_str;
    GVariant *attachment_paths_variant = NULL;
    gchar **attachment_paths = NULL;

    gchar *from_name = NULL;
    gchar *from_address = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, "Shell not available", ""));
        return;
    }

    shell_backend = e_shell_get_backend_by_name (shell, "mail");
    if (!shell_backend) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, "Mail backend not found", ""));
        return;
    }

    backend = E_MAIL_BACKEND (shell_backend);
    session = e_mail_backend_get_session (backend);
    registry = e_shell_get_registry (shell);

    g_variant_get (
        parameters,
        "(&s&s&s&s@as&s&s&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str,
        &attachment_paths_variant,
        &in_reply_to,
        &references,
        &cc_str,
        &bcc_str);

    attachment_paths = g_variant_dup_strv (attachment_paths_variant, NULL);

    if (!header_value_is_safe (subject_str) ||
        !header_value_is_safe (to_str) ||
        !header_value_is_safe (cc_str) ||
        !header_value_is_safe (bcc_str) ||
        !header_value_is_safe (in_reply_to) ||
        !header_value_is_safe (references)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, "Headers contain invalid characters", ""));
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    source = e_source_registry_ref_source (registry, account_uid);
    if (!source) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, "Account not found", ""));
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    resolve_identity_details (registry, source, NULL, &from_name, &from_address);

    message = build_mime_message (subject_str, body_str, attachment_paths, from_name, from_address, to_str, cc_str, bcc_str, in_reply_to, references, &error);
    if (!message) {
        gchar *msg_err = g_strdup_printf ("Failed to build draft: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, msg_err, ""));
        g_free (msg_err);
        g_clear_error (&error);
        g_free (from_name);
        g_free (from_address);
        g_object_unref (source);
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    ESource *composition_source = find_account_extension_source (registry, source, E_SOURCE_EXTENSION_MAIL_COMPOSITION);
    const gchar *drafts_uri = NULL;
    if (composition_source) {
        ESourceMailComposition *comp = e_source_get_extension (composition_source, E_SOURCE_EXTENSION_MAIL_COMPOSITION);
        drafts_uri = e_source_mail_composition_get_drafts_folder (comp);
    }

    CamelFolder *drafts_folder = resolve_special_folder_sync (session, source, drafts_uri, CAMEL_FOLDER_TYPE_DRAFTS, "Drafts", E_MAIL_LOCAL_FOLDER_DRAFTS);
    if (!drafts_folder) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, "Could not resolve drafts folder", ""));
    } else {
        CamelMessageInfo *info = camel_message_info_new (NULL);
        camel_message_info_set_flags (info, CAMEL_MESSAGE_DRAFT | CAMEL_MESSAGE_SEEN, CAMEL_MESSAGE_DRAFT | CAMEL_MESSAGE_SEEN);
        gchar *appended_uid = NULL;

        if (camel_folder_append_message_sync (drafts_folder, message, info, &appended_uid, NULL, &error)) {
            camel_folder_synchronize_sync (drafts_folder, FALSE, NULL, NULL);
            const gchar *full_name = camel_folder_get_full_name (drafts_folder);
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", TRUE, full_name ? full_name : "", appended_uid ? appended_uid : ""));
        } else {
            gchar *msg_err = g_strdup_printf ("Failed to save draft: %s", error ? error->message : "Unknown error");
            g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bss)", FALSE, msg_err, ""));
            g_free (msg_err);
            g_clear_error (&error);
        }

        g_free (appended_uid);
        g_clear_object (&info);
        g_object_unref (drafts_folder);
    }

    g_object_unref (message);
    if (composition_source) g_object_unref (composition_source);
    g_free (from_name);
    g_free (from_address);
    g_object_unref (source);
    g_strfreev (attachment_paths);
    g_variant_unref (attachment_paths_variant);
}

typedef struct {
    GDBusMethodInvocation *invocation;
    EShell *shell;
    CamelMimeMessage *message;
    gchar *identity_uid;
    gchar *from_name;
    gchar *from_address;
    gchar *in_reply_to;
    gchar *references;
} OpenComposerContext;

static void
open_composer_context_free (OpenComposerContext *ctx)
{
    if (!ctx) return;
    g_clear_object (&ctx->invocation);
    g_clear_object (&ctx->shell);
    g_clear_object (&ctx->message);
    g_free (ctx->identity_uid);
    g_free (ctx->from_name);
    g_free (ctx->from_address);
    g_free (ctx->in_reply_to);
    g_free (ctx->references);
    g_free (ctx);
}

static void
on_composer_created_cb (GObject *source_object, GAsyncResult *result, gpointer user_data)
{
    (void)source_object;
    OpenComposerContext *ctx = user_data;
    GError *error = NULL;
    EMsgComposer *composer = e_msg_composer_new_finish (result, &error);

    if (!composer) {
        gchar *msg_err = g_strdup_printf ("Failed to create composer: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (g_steal_pointer (&ctx->invocation), g_variant_new ("(bs)", FALSE, msg_err));
        g_free (msg_err);
        g_clear_error (&error);
        open_composer_context_free (ctx);
        return;
    }

    e_msg_composer_setup_with_message (composer, ctx->message, TRUE, ctx->identity_uid, ctx->from_name, ctx->from_address, NULL);

    if (ctx->in_reply_to && *ctx->in_reply_to) {
        e_msg_composer_set_header (composer, "In-Reply-To", ctx->in_reply_to);
        e_msg_composer_set_is_reply_or_forward (composer, TRUE);
    }
    if (ctx->references && *ctx->references) {
        e_msg_composer_set_header (composer, "References", ctx->references);
    }

    gtk_window_present (GTK_WINDOW (composer));
    g_dbus_method_invocation_return_value (g_steal_pointer (&ctx->invocation), g_variant_new ("(bs)", TRUE, "Composer window opened"));

    open_composer_context_free (ctx);
}

static gboolean
open_composer_invoke_cb (gpointer user_data)
{
    OpenComposerContext *ctx = user_data;
    e_msg_composer_new (ctx->shell, on_composer_created_cb, ctx);
    return G_SOURCE_REMOVE;
}

static void
handle_open_composer (GVariant *parameters, GDBusMethodInvocation *invocation)
{
    EShell *shell = e_shell_get_default ();
    ESourceRegistry *registry;
    ESource *source = NULL;

    const gchar *account_uid, *to_str, *subject_str, *body_str;
    const gchar *in_reply_to, *references, *cc_str, *bcc_str;
    GVariant *attachment_paths_variant = NULL;
    gchar **attachment_paths = NULL;

    gchar *identity_uid = NULL;
    gchar *from_name = NULL;
    gchar *from_address = NULL;
    CamelMimeMessage *message = NULL;
    GError *error = NULL;

    if (!shell) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Shell not available"));
        return;
    }

    registry = e_shell_get_registry (shell);

    g_variant_get (
        parameters,
        "(&s&s&s&s@as&s&s&s&s)",
        &account_uid,
        &to_str,
        &subject_str,
        &body_str,
        &attachment_paths_variant,
        &in_reply_to,
        &references,
        &cc_str,
        &bcc_str);

    attachment_paths = g_variant_dup_strv (attachment_paths_variant, NULL);

    if (!header_value_is_safe (subject_str) ||
        !header_value_is_safe (to_str) ||
        !header_value_is_safe (cc_str) ||
        !header_value_is_safe (bcc_str) ||
        !header_value_is_safe (in_reply_to) ||
        !header_value_is_safe (references)) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Headers contain invalid characters"));
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    source = e_source_registry_ref_source (registry, account_uid);
    if (!source) {
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, "Account not found"));
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    resolve_identity_details (registry, source, &identity_uid, &from_name, &from_address);

    message = build_mime_message (subject_str, body_str, attachment_paths, from_name, from_address, to_str, cc_str, bcc_str, in_reply_to, references, &error);
    if (!message) {
        gchar *msg_err = g_strdup_printf ("Failed to build message: %s", error ? error->message : "Unknown error");
        g_dbus_method_invocation_return_value (invocation, g_variant_new ("(bs)", FALSE, msg_err));
        g_free (msg_err);
        g_clear_error (&error);
        g_free (identity_uid);
        g_free (from_name);
        g_free (from_address);
        g_object_unref (source);
        g_strfreev (attachment_paths);
        g_variant_unref (attachment_paths_variant);
        return;
    }

    OpenComposerContext *ctx = g_new0 (OpenComposerContext, 1);
    ctx->invocation = invocation;
    ctx->shell = g_object_ref (shell);
    ctx->message = g_object_ref (message);
    ctx->identity_uid = g_strdup (identity_uid);
    ctx->from_name = g_strdup (from_name);
    ctx->from_address = g_strdup (from_address);
    ctx->in_reply_to = g_strdup (in_reply_to);
    ctx->references = g_strdup (references);

    g_main_context_invoke (NULL, open_composer_invoke_cb, ctx);

    g_object_unref (message);
    g_free (identity_uid);
    g_free (from_name);
    g_free (from_address);
    g_object_unref (source);
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
    (void)connection;
    (void)sender;
    (void)object_path;
    (void)interface_name;
    (void)user_data;
    if (g_strcmp0 (method_name, "GetVersion") == 0) {
        g_dbus_method_invocation_return_value (
            invocation, g_variant_new ("(ss)", BRIDGE_GIT_COMMIT, BRIDGE_BUILD_DATE));
    } else if (g_strcmp0 (method_name, "MoveMessage") == 0) {
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
    } else if (g_strcmp0 (method_name, "SaveDraft") == 0) {
        handle_save_draft (parameters, invocation);
    } else if (g_strcmp0 (method_name, "OpenComposer") == 0) {
        handle_open_composer (parameters, invocation);
    } else {
        g_dbus_method_invocation_return_error (
            invocation,
            G_DBUS_ERROR,
            G_DBUS_ERROR_UNKNOWN_METHOD,
            "Unknown method: %s",
            method_name ? method_name : "(null)");
    }
}

static const GDBusInterfaceVTable vtable = {
    handle_method_call, NULL, NULL, {0}
};

G_MODULE_EXPORT gboolean
e_plugin_ui_init (gpointer ui_manager, gpointer user_data)
{
    (void)ui_manager;
    (void)user_data;
    const gchar *prgname = g_get_prgname ();
    GError *error = NULL;

    if (g_strcmp0 (prgname, "org.gnome.Evolution") != 0 && g_strcmp0 (prgname, "evolution") != 0)
        return TRUE;

    g_print ("CUSTOM INSTRUMENTATION PLUGIN LOADING in %s (PID %d), commit %s, built %s\n",
             prgname, (int)getpid(), BRIDGE_GIT_COMMIT, BRIDGE_BUILD_DATE);

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

    return TRUE;
}
