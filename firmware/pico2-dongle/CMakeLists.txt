cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico2)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(pico2_dongle C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

add_executable(pico2_dongle
    main.c
    usb_descriptors.c
    msc_disk.c
)

target_include_directories(pico2_dongle PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
)

target_link_libraries(pico2_dongle
    pico_stdlib
    tinyusb_device
    tinyusb_board
)

pico_set_binary_type(pico2_dongle copy_to_ram)

# Generate UF2 output
pico_add_extra_outputs(pico2_dongle)

# Debug via UART (USB is in device mode for MSC)
pico_enable_stdio_usb(pico2_dongle 0)
pico_enable_stdio_uart(pico2_dongle 1)
