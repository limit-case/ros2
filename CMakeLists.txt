cmake_minimum_required(VERSION 3.8)
project(limit_case_ros2)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)  # latency numbers must come from an optimized build
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(diagnostic_updater REQUIRED)
find_package(message_filters REQUIRED)
find_package(cv_bridge REQUIRED)

# ROS-free core (no rclcpp / cv_bridge here)
add_library(limit_case_core src/priority_flood.cpp src/glass_filter.cpp)
target_include_directories(limit_case_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

# Offline CLI (OpenCV only, no ROS)
add_executable(filter_cli src/filter_cli.cpp)
target_link_libraries(filter_cli limit_case_core ${OpenCV_LIBS})

# Composable node + standalone executable
add_library(glass_filter_component SHARED src/filter_node.cpp)
target_link_libraries(glass_filter_component limit_case_core)
target_include_directories(glass_filter_component PRIVATE ${OpenCV_INCLUDE_DIRS})
ament_target_dependencies(glass_filter_component
  rclcpp rclcpp_components sensor_msgs diagnostic_msgs diagnostic_updater message_filters cv_bridge)
rclcpp_components_register_node(glass_filter_component
  PLUGIN "limit_case_ros2::GlassFilterNode"
  EXECUTABLE glass_filter_node)

install(TARGETS limit_case_core EXPORT export_limit_case_core
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(TARGETS glass_filter_component
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(TARGETS filter_cli RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch rviz nav2 DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/eval_glassbench.py scripts/clearGrasp_to_bag.py
  DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
  ament_add_gtest(test_priority_flood test/test_priority_flood.cpp)
  target_link_libraries(test_priority_flood limit_case_core)
  ament_add_gtest(test_glass_filter test/test_glass_filter.cpp)
  target_link_libraries(test_glass_filter limit_case_core)

  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_launch.py)
endif()

ament_export_include_directories(include)
ament_export_targets(export_limit_case_core)
ament_package()
