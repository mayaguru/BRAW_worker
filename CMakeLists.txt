cmake_minimum_required(VERSION 3.21)

project(BrawConverter LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# UTF-8 소스 파일 인코딩 강제 (MSVC)
if(MSVC)
    add_compile_options(/utf-8)
endif()

option(BRAW_ENABLE_SDK "Enable integration with the Blackmagic RAW SDK" ON)
option(OPENEXR_ENABLE "Enable OpenEXR export support" ON)

set(BRAW_SDK_ROOT "" CACHE PATH "Blackmagic RAW SDK root directory")
set(OPENEXR_ROOT "" CACHE PATH "OpenEXR install root directory")
set(OPENEXR_BIN_DIR "" CACHE PATH "OpenEXR runtime bin directory")

if (NOT BRAW_SDK_ROOT)
    set(_braw_default "${CMAKE_SOURCE_DIR}/third_party/BlackmagicRAW")
    if (WIN32)
        set(_braw_installed "C:/Program Files (x86)/Blackmagic Design/Blackmagic RAW/Blackmagic RAW SDK")
        file(TO_CMAKE_PATH "${_braw_installed}" _braw_installed)
        if (EXISTS "${_braw_installed}")
            set(_braw_default "${_braw_installed}")
        endif()
    endif()
    set(BRAW_SDK_ROOT "${_braw_default}" CACHE PATH "Blackmagic RAW SDK root directory" FORCE)
endif()

set(BRAW_SDK_FOUND OFF)
set(BRAW_SDK_INCLUDE_DIRS "")
set(BRAW_SDK_IDL "")
set(BRAW_SDK_LIBRARY_DIR "")

if (BRAW_ENABLE_SDK)
    if (WIN32)
        set(_braw_include_candidates
            "${BRAW_SDK_ROOT}/Win/Include"
            "${BRAW_SDK_ROOT}/include")
        set(_braw_idl_path "${BRAW_SDK_ROOT}/Win/Include/BlackmagicRawAPI.idl")
        set(_braw_library_dir "${BRAW_SDK_ROOT}/Win/Libraries")
    else()
        set(_braw_include_candidates
            "${BRAW_SDK_ROOT}/include"
            "${BRAW_SDK_ROOT}/Linux/Include")
        set(_braw_idl_path "${BRAW_SDK_ROOT}/include/BlackmagicRawAPI.idl")
        set(_braw_library_dir "${BRAW_SDK_ROOT}/lib")
    endif()

    foreach(_inc ${_braw_include_candidates})
        if (EXISTS "${_inc}")
            list(APPEND BRAW_SDK_INCLUDE_DIRS "${_inc}")
        endif()
    endforeach()

    if (EXISTS "${_braw_idl_path}")
        set(BRAW_SDK_IDL "${_braw_idl_path}")
    endif()

    if (EXISTS "${_braw_library_dir}")
        set(BRAW_SDK_LIBRARY_DIR "${_braw_library_dir}")
    endif()

    if (BRAW_SDK_INCLUDE_DIRS AND BRAW_SDK_IDL)
        set(BRAW_SDK_FOUND ON)
        message(STATUS "Blackmagic RAW SDK: ${BRAW_SDK_ROOT}")
    else()
        set(BRAW_ENABLE_SDK OFF CACHE BOOL "" FORCE)
        message(WARNING "Blackmagic RAW SDK를 찾지 못했습니다. BRAW 디코딩이 비활성화됩니다.")
    endif()
endif()

set(OPENEXR_FOUND OFF)
set(OPENEXR_INCLUDE_DIR "")
set(OPENEXR_LIBS "")
if (OPENEXR_ENABLE)
    # vcpkg toolchain을 사용하는 경우 find_package 우선 시도
    find_package(OpenEXR CONFIG QUIET)
    if (OpenEXR_FOUND)
        set(OPENEXR_FOUND ON)
        set(OPENEXR_LIBS OpenEXR::OpenEXR)
        get_target_property(OPENEXR_INCLUDE_DIR OpenEXR::OpenEXR INTERFACE_INCLUDE_DIRECTORIES)
        message(STATUS "OpenEXR found via find_package: ${OPENEXR_INCLUDE_DIR}")
    else()
        # 수동 검색 폴백
        list(APPEND _openexr_include_search
            "${OPENEXR_ROOT}/include"
            "${OPENEXR_ROOT}/Include"
            "${CMAKE_SOURCE_DIR}/third_party/OpenEXR/include"
            "C:/vcpkg/installed/x64-windows/include"
            "D:/vcpkg/installed/x64-windows/include")
        foreach(_inc ${_openexr_include_search})
            if (EXISTS "${_inc}/OpenEXR/ImfOutputFile.h")
                set(OPENEXR_INCLUDE_DIR "${_inc}")
                break()
            endif()
        endforeach()

        set(_openexr_lib_search_dirs
            "${OPENEXR_ROOT}/lib"
            "${OPENEXR_ROOT}/lib64"
            "${OPENEXR_ROOT}/Lib"
            "${CMAKE_SOURCE_DIR}/third_party/OpenEXR/lib"
            "C:/vcpkg/installed/x64-windows/lib"
            "D:/vcpkg/installed/x64-windows/lib")

        macro(_find_openexr_lib var)
            if (NOT ${var})
                find_library(${var}
                    NAMES ${ARGN}
                    PATHS ${_openexr_lib_search_dirs}
                    NO_DEFAULT_PATH)
            endif()
        endmacro()

        _find_openexr_lib(OPENEXR_LIB NAMES OpenEXR-3_3 OpenEXR-3_2 OpenEXR-3_1 OpenEXR)
        _find_openexr_lib(IMATH_LIB NAMES Imath-3_1 Imath)
        _find_openexr_lib(IEX_LIB NAMES Iex-3_1 Iex)
        _find_openexr_lib(ILMTHREAD_LIB NAMES IlmThread-3_1 IlmThread)

        if (OPENEXR_INCLUDE_DIR AND OPENEXR_LIB AND IMATH_LIB AND IEX_LIB AND ILMTHREAD_LIB)
            set(OPENEXR_FOUND ON)
            set(OPENEXR_LIBS ${OPENEXR_LIB} ${IMATH_LIB} ${ILMTHREAD_LIB} ${IEX_LIB})
            message(STATUS "OpenEXR found manually: ${OPENEXR_INCLUDE_DIR}")
        else()
            message(WARNING "OpenEXR 라이브러리를 찾을 수 없습니다. EXR 내보내기가 비활성화됩니다.")
        endif()
    endif()
endif()

add_subdirectory(src/core)
add_subdirectory(src/export)
add_subdirectory(src/app)

# Qt는 UI 타겟에만 필요
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)
add_subdirectory(src/ui)
