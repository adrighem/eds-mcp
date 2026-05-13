project('evolution-mail-process', 'c',
  version: '0.1.0',
  meson_version: '>= 0.50.0'
)

glib_dep = dependency('glib-2.0')
gio_dep = dependency('gio-2.0')
eds_dep = dependency('libedataserver-1.2')
camel_dep = dependency('camel-1.2')
ebook_dep = dependency('libebook-1.2')
ecal_dep = dependency('libecal-2.0')
evo_mail_dep = dependency('evolution-mail-3.0')
evo_shell_dep = dependency('evolution-shell-3.0')
email_engine_dep = dependency('libemail-engine')

shared_module('my-evolution-extension',
  'evolution-mail-process.c',
  dependencies: [glib_dep, gio_dep, eds_dep, camel_dep, ebook_dep, ecal_dep, evo_mail_dep, evo_shell_dep, email_engine_dep],
  name_prefix: 'lib',
  install: true,
  install_dir: '/home/vincent/.local/share/evolution/modules'
)
