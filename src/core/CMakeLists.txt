add_library(braw_core STATIC
    braw_decoder.cpp
    frame_buffer.cpp
)

target_include_directories(braw_core
    PUBLIC
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_SOURCE_DIR}/third_party
)

if (BRAW_ENABLE_SDK AND BRAW_SDK_FOUND)
    target_compile_definitions(braw_core PUBLIC BRAW_SDK_AVAILABLE=1)
    target_include_directories(braw_core PUBLIC ${BRAW_SDK_INCLUDE_DIR})
    target_link_libraries(braw_core PUBLIC ${BRAW_SDK_LIBRARY})
else()
    target_compile_definitions(braw_core PUBLIC BRAW_SDK_AVAILABLE=0)
endif()
