find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(braw_viewer
    main.cpp
    main_window.cpp
)

target_include_directories(braw_viewer
    PRIVATE
        ${CMAKE_SOURCE_DIR}/src
)

target_link_libraries(braw_viewer
    PRIVATE
        Qt6::Widgets
        braw_core
        braw_export
)
