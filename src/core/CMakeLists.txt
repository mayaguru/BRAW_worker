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
    foreach(_inc ${BRAW_SDK_INCLUDE_DIRS})
        target_include_directories(braw_core PUBLIC ${_inc})
    endforeach()

    if (WIN32)
        find_program(MIDL_EXECUTABLE midl)
        if (NOT MIDL_EXECUTABLE)
            message(FATAL_ERROR "midl.exe를 찾을 수 없습니다. Visual Studio C++ MIDL 도구를 설치하세요.")
        endif()

        set(BRAW_MIDL_OUTPUT_DIR "${CMAKE_BINARY_DIR}/generated/braw_sdk")
        file(MAKE_DIRECTORY "${BRAW_MIDL_OUTPUT_DIR}")
        set(BRAW_MIDL_HEADER "${BRAW_MIDL_OUTPUT_DIR}/BlackmagicRawAPI.h")
        set(BRAW_MIDL_I_FILE "${BRAW_MIDL_OUTPUT_DIR}/BlackmagicRawAPI_i.c")

        add_custom_command(
            OUTPUT "${BRAW_MIDL_HEADER}" "${BRAW_MIDL_I_FILE}"
            COMMAND ${MIDL_EXECUTABLE}
                    /nologo
                    /env x64
                    /tlb BlackmagicRawAPI.tlb
                    /h BlackmagicRawAPI.h
                    /iid BlackmagicRawAPI_i.c
                    /out "${BRAW_MIDL_OUTPUT_DIR}"
                    "${BRAW_SDK_IDL}"
            DEPENDS "${BRAW_SDK_IDL}"
            COMMENT "MIDL: Generating Blackmagic RAW COM interfaces"
        )

        add_custom_target(braw_midl DEPENDS "${BRAW_MIDL_HEADER}" "${BRAW_MIDL_I_FILE}")
        add_dependencies(braw_core braw_midl)
        set_source_files_properties("${BRAW_MIDL_I_FILE}" PROPERTIES GENERATED TRUE LANGUAGE C)
        target_sources(braw_core PRIVATE "${BRAW_MIDL_I_FILE}" "${BRAW_SDK_ROOT}/Win/Include/BlackmagicRawAPIDispatch.cpp")
        target_include_directories(braw_core BEFORE PUBLIC "${BRAW_MIDL_OUTPUT_DIR}")
        target_include_directories(braw_core PUBLIC "${BRAW_SDK_ROOT}/Win/Include")
        target_link_libraries(braw_core PUBLIC Ole32 OleAut32)

        if (BRAW_SDK_LIBRARY_DIR)
            file(TO_CMAKE_PATH "${BRAW_SDK_LIBRARY_DIR}" _braw_lib_dir_norm)
            target_compile_definitions(braw_core PUBLIC BRAW_SDK_LIBRARY_DIR=\"${_braw_lib_dir_norm}\")
        endif()
    endif()
else()
    target_compile_definitions(braw_core PUBLIC BRAW_SDK_AVAILABLE=0)
endif()
