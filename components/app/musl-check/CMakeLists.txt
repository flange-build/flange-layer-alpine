cmake_minimum_required(VERSION 3.16)
project(musl_check VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)

add_executable(musl-check src/main.cpp)
target_link_libraries(musl-check PRIVATE Threads::Threads ZLIB::ZLIB)
install(TARGETS musl-check RUNTIME DESTINATION bin)
