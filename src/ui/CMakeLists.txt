find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(braw_viewer
    viewer_main.cpp
    viewer_window.cpp
    timeline_slider.cpp
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

# Blackmagic RAW SDK DLL 복사
if(WIN32 AND BRAW_SDK_FOUND)
    add_custom_command(TARGET braw_viewer POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${BRAW_SDK_LIBRARY_DIR}/BlackmagicRawAPI.dll"
            "$<TARGET_FILE_DIR:braw_viewer>"
        COMMENT "Copying Blackmagic RAW SDK DLL to output directory"
    )
endif()

# Qt 배포용 windeployqt 실행 (선택사항)
if(WIN32)
    get_target_property(_qt_qmake_location Qt6::qmake IMPORTED_LOCATION)
    get_filename_component(_qt_bin_dir "${_qt_qmake_location}" DIRECTORY)
    find_program(WINDEPLOYQT_EXECUTABLE windeployqt HINTS "${_qt_bin_dir}")

    if(WINDEPLOYQT_EXECUTABLE)
        add_custom_command(TARGET braw_viewer POST_BUILD
            COMMAND "${WINDEPLOYQT_EXECUTABLE}"
                --no-compiler-runtime
                --no-system-d3d-compiler
                --no-opengl-sw
                "$<TARGET_FILE:braw_viewer>"
            COMMENT "Running windeployqt for Qt dependencies"
        )
    endif()
endif()
