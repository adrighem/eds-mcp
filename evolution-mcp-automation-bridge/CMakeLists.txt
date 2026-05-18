cmake_minimum_required(VERSION 3.16)
project(evolution_custom_instrumentation C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(PkgConfig REQUIRED)

pkg_check_modules(EVO_SHELL REQUIRED evolution-shell-3.0)
pkg_check_modules(EVO_MAIL  REQUIRED evolution-mail-3.0)
pkg_check_modules(EVO_ENGINE REQUIRED libemail-engine)
pkg_check_modules(EDS        REQUIRED libedataserver-1.2)
pkg_check_modules(CAMEL      REQUIRED camel-1.2)
pkg_check_modules(EBOOK      REQUIRED libebook-1.2)
pkg_check_modules(ECAL       REQUIRED libecal-2.0)
pkg_check_modules(GLIB       REQUIRED glib-2.0 gobject-2.0 gmodule-2.0 gio-2.0 json-glib-1.0)

add_library(evolution-mcp-automation-bridge SHARED
  evolution-mail-process.c
)

target_include_directories(evolution-mcp-automation-bridge PRIVATE
  ${EVO_SHELL_INCLUDE_DIRS}
  ${EVO_MAIL_INCLUDE_DIRS}
  ${EVO_ENGINE_INCLUDE_DIRS}
  ${EDS_INCLUDE_DIRS}
  ${CAMEL_INCLUDE_DIRS}
  ${EBOOK_INCLUDE_DIRS}
  ${ECAL_INCLUDE_DIRS}
  ${GLIB_INCLUDE_DIRS}
)

target_link_directories(evolution-mcp-automation-bridge PRIVATE
  ${EVO_SHELL_LIBRARY_DIRS}
  ${EVO_MAIL_LIBRARY_DIRS}
  ${EVO_ENGINE_LIBRARY_DIRS}
  ${EDS_LIBRARY_DIRS}
  ${CAMEL_LIBRARY_DIRS}
  ${EBOOK_LIBRARY_DIRS}
  ${ECAL_LIBRARY_DIRS}
  ${GLIB_LIBRARY_DIRS}
)

target_compile_options(evolution-mcp-automation-bridge PRIVATE
  ${EVO_SHELL_CFLAGS_OTHER}
  ${EVO_MAIL_CFLAGS_OTHER}
  ${EVO_ENGINE_CFLAGS_OTHER}
  ${EDS_CFLAGS_OTHER}
  ${CAMEL_CFLAGS_OTHER}
  ${EBOOK_CFLAGS_OTHER}
  ${ECAL_CFLAGS_OTHER}
  ${GLIB_CFLAGS_OTHER}
)

target_link_libraries(evolution-mcp-automation-bridge
  ${EVO_SHELL_LIBRARIES}
  ${EVO_MAIL_LIBRARIES}
  ${EVO_ENGINE_LIBRARIES}
  ${EDS_LIBRARIES}
  ${CAMEL_LIBRARIES}
  ${EBOOK_LIBRARIES}
  ${ECAL_LIBRARIES}
  ${GLIB_LIBRARIES}
)

set_target_properties(evolution-mcp-automation-bridge PROPERTIES
  PREFIX ""
  OUTPUT_NAME "libevolution-mcp-automation-bridge"
)

# Detect Evolution plugin dir
execute_process(
  COMMAND sh -c "dpkg -L evolution | awk '/\\/evolution\\/plugins\\/.*\\.so$/ {print; exit}' | xargs dirname"
  OUTPUT_VARIABLE EVO_PLUGIN_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
)

if(NOT EVO_PLUGIN_DIR)
  set(EVO_PLUGIN_DIR "/usr/lib/evolution/plugins")
endif()

set(PLUGINDIR "${EVO_PLUGIN_DIR}")
set(SOEXT ".so")
configure_file(
  evolution-mcp-automation-bridge.eplug.in
  ${CMAKE_CURRENT_BINARY_DIR}/evolution-mcp-automation-bridge.eplug
  @ONLY
)

install(TARGETS evolution-mcp-automation-bridge LIBRARY DESTINATION ${EVO_PLUGIN_DIR})
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/evolution-mcp-automation-bridge.eplug DESTINATION ${EVO_PLUGIN_DIR})
