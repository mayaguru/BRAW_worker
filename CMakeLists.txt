cmake_minimum_required(VERSION 3.21)

project(BrawConverter LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BRAW_ENABLE_SDK "Enable integration with the Blackmagic RAW SDK" ON)

set(BRAW_SDK_ROOT "" CACHE PATH "Blackmagic RAW SDK root directory")

if (NOT BRAW_SDK_ROOT)
    set(_braw_default "${CMAKE_SOURCE_DIR}/third_party/BlackmagicRAW")
    if (WIN32)
        set(_braw_installed "C:/Program Files (x86)/Blackmagic Design/Blackmagic RAW/SDK")
        file(TO_CMAKE_PATH "${_braw_installed}" _braw_installed)
        if (EXISTS "${_braw_installed}")
            set(_braw_default "${_braw_installed}")
        endif()
    endif()
    set(BRAW_SDK_ROOT "${_braw_default}" CACHE PATH "Blackmagic RAW SDK root directory" FORCE)
endif()

set(BRAW_SDK_FOUND OFF)
if (BRAW_ENABLE_SDK)
    set(BRAW_SDK_INCLUDE_DIR "${BRAW_SDK_ROOT}/include")
    set(BRAW_SDK_LIBRARY "")
    if (WIN32)
        set(_braw_lib_dir "${BRAW_SDK_ROOT}/Win/x64/Release")
        find_library(BRAW_SDK_LIBRARY
            NAMES BlackmagicRawAPI
            PATHS "${_braw_lib_dir}"
            NO_DEFAULT_PATH)
    else()
        find_library(BRAW_SDK_LIBRARY NAMES BlackmagicRawAPI
            PATHS "${BRAW_SDK_ROOT}/lib" "${BRAW_SDK_ROOT}/lib64")
    endif()

    if (EXISTS "${BRAW_SDK_INCLUDE_DIR}/BlackmagicRawAPI.h" AND BRAW_SDK_LIBRARY)
        set(BRAW_SDK_FOUND ON)
        message(STATUS "Blackmagic RAW SDK: ${BRAW_SDK_ROOT}")
    else()
        set(BRAW_ENABLE_SDK OFF CACHE BOOL "" FORCE)
        message(WARNING "Blackmagic RAW SDK를 찾지 못했습니다. BRAW 디코딩이 비활성화됩니다.")
    endif()
endif()

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

add_subdirectory(src/core)
add_subdirectory(src/export)
add_subdirectory(src/app)
add_subdirectory(src/ui)
