add_library(braw_export STATIC
    image_writer.cpp
)

target_include_directories(braw_export
    PUBLIC
        ${CMAKE_CURRENT_LIST_DIR}
)
