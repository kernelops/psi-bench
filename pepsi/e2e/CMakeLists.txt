cmake_minimum_required(VERSION 3.22)
project(pepsi_e2e LANGUAGES CXX)

# End-to-end PEPSI driver: real input files, separate client/server processes over TCP.
# Standalone project. It reuses the SEAL download/configuration and the crypto parameter
# table (Params in utils.cpp) of ../src without modifying anything there.
#
#   cmake -S e2e -B build-e2e && cmake --build build-e2e --target pepsi_e2e

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../src upstream EXCLUDE_FROM_ALL)

find_package(OpenMP REQUIRED COMPONENTS CXX)

add_executable(pepsi_e2e pepsi_e2e.cpp ${CMAKE_CURRENT_SOURCE_DIR}/../src/utils.cpp)
target_include_directories(pepsi_e2e PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../src)
target_link_libraries(pepsi_e2e PRIVATE seal OpenMP::OpenMP_CXX)
