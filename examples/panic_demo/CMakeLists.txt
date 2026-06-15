# ESP-IDF v5.3 最小工程骨架,build 出 panic_demo.elf 供 symbolize 验证
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(panic_demo)
