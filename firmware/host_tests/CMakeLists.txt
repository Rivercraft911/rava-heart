cmake_minimum_required(VERSION 3.16)
project(rava_heart_host_tests LANGUAGES CXX)

option(HEART_ENABLE_SANITIZERS "Enable AddressSanitizer and UBSan" OFF)

add_executable(heart_core_tests test_core.cpp)
target_compile_features(heart_core_tests PRIVATE cxx_std_20)
target_include_directories(heart_core_tests PRIVATE ../main)
target_compile_options(heart_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(HEART_ENABLE_SANITIZERS)
  target_compile_options(
    heart_core_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(heart_core_tests PRIVATE -fsanitize=address,undefined)
endif()
