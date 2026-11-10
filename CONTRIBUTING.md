# Contributing

Thanks for helping map where depth cameras lie about glass.

## Quick ways to help
- **Report a sensor**: open an issue with the camera model and a short bag (< 50 MB) where glass is missed or
  wrongly flagged. Please include the `sensor_profile` and any parameter overrides.
- Pick a [`good first issue`](docs/good_first_issues.md).

## Dev setup
Any OS: open the repo in the devcontainer (`.devcontainer/`) or build `docker/Dockerfile` (ROS 2 Jazzy).
```bash
colcon build --packages-select limit_case_ros2 && colcon test --packages-select limit_case_ros2 && colcon test-result --verbose
```
Humble must also build. When APIs differ between distros, guard with `#if` / `__has_include`, do not drop Humble.

## Rules
- Algorithm code lives in the ROS-free core (`glass_filter`, `priority_flood`): no `rclcpp` or `cv_bridge`
  includes there. The node and CLI stay thin.
- C++17, no PCL. Core must stay under 10 ms at 640x480 with `downsample: 2`.
- Add a gtest for every behavior change (synthetic scenes are fine and preferred).
- README numbers must come from `results/*.csv` produced by `scripts/eval_glassbench.py`. Never invent metrics.
- Tune on ClearGrasp D435 **val** only; report on D435 **test** and D415.
- Never commit TransCG data or images derived from it (CC BY-NC-SA).
- Small commits, one logical change each. Format with `ament_clang_format` / `ament_cpplint` (CI lints).
