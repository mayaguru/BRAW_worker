add_executable(braw_cli
    cli_decode.cpp
)

target_include_directories(braw_cli PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(braw_cli PRIVATE braw_core braw_export)
