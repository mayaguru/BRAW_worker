add_library(braw_export STATIC
    image_writer.cpp
    exr_writer.cpp
)

target_include_directories(braw_export
    PUBLIC
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_SOURCE_DIR}/src
)

target_link_libraries(braw_export PUBLIC braw_core)

if (OPENEXR_FOUND)
    target_compile_definitions(braw_export PUBLIC OPENEXR_AVAILABLE=1)
    target_include_directories(braw_export PUBLIC ${OPENEXR_INCLUDE_DIR})
    target_link_libraries(braw_export PUBLIC ${OPENEXR_LIBS})
else()
    target_compile_definitions(braw_export PUBLIC OPENEXR_AVAILABLE=0)
endif()

if (OCIO_FOUND)
    target_compile_definitions(braw_export PUBLIC OCIO_AVAILABLE=1)
    target_include_directories(braw_export PUBLIC ${OCIO_INCLUDE_DIR})
    target_link_libraries(braw_export PUBLIC ${OCIO_LIBS})
else()
    target_compile_definitions(braw_export PUBLIC OCIO_AVAILABLE=0)
endif()
