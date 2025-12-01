add_executable(braw_cli
    cli_decode.cpp
)

target_include_directories(braw_cli PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(braw_cli PRIVATE braw_core braw_export)

# Blackmagic RAW SDK DLL 복사
if(WIN32 AND BRAW_SDK_FOUND)
    add_custom_command(TARGET braw_cli POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${BRAW_SDK_LIBRARY_DIR}/BlackmagicRawAPI.dll"
            "$<TARGET_FILE_DIR:braw_cli>"
        COMMENT "Copying Blackmagic RAW SDK DLL to output directory"
    )
endif()
