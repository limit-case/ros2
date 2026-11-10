# Dev/CI image. `docker build --target base .` for the devcontainer; default target builds and tests.
FROM ros:jazzy AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-cv-bridge ros-jazzy-image-transport ros-jazzy-message-filters \
    ros-jazzy-diagnostic-updater ros-jazzy-depth-image-proc ros-jazzy-rviz2 \
    ros-jazzy-ament-lint-auto ros-jazzy-ament-cmake-gtest ros-jazzy-launch-testing-ament-cmake \
    ros-jazzy-launch-testing-ros ros-jazzy-ament-cmake-clang-format ros-jazzy-ament-cmake-cpplint \
    libopencv-dev python3-colcon-common-extensions python3-numpy \
  && rm -rf /var/lib/apt/lists/*

FROM base AS build
WORKDIR /ws
COPY . src/limit_case_ros2
RUN . /opt/ros/jazzy/setup.sh && colcon build --packages-select limit_case_ros2 --event-handlers console_cohesion+
RUN . /opt/ros/jazzy/setup.sh && . install/setup.sh \
  && colcon test --packages-select limit_case_ros2 --event-handlers console_direct+ \
  ; colcon test-result --verbose | tee /ws/test_result.txt
