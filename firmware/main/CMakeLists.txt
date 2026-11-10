idf_component_register(
  SRCS "app_main.cpp"
  INCLUDE_DIRS "."
  PRIV_REQUIRES
    esp_driver_gpio
    esp_driver_i2c
    esp_event
    esp_netif
    esp_timer
    esp_wifi
    nvs_flash
)

target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_20)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Wpedantic)
