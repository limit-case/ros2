# Good first issues (copy into GitHub issues at release)

1. **Add a sensor profile** (`config/<sensor>.yaml`) for another camera (Orbbec, ZED, OAK-D) with a sentence on how its depth fails on glass.
2. **Add a `tests` case**: opaque concave bowl scene in `test_glass_filter.cpp`; document what the current score does.
3. **Support `mono16` / other depth encodings** in the node, with a launch-test case.
4. **CLI: write a colorized overlay PNG** (`--overlay`) to make eval debugging easier.
5. **Eval script: per-scene breakdown table** in the markdown output (worst 5 scenes).
6. **Dynamic reconfigure test**: launch test that changes `confidence_threshold` at runtime and checks the output changes.
7. **Docs: Moveit2 octomap example** analogous to `nav2/costmap_snippet.yaml`.
8. **Performance**: benchmark gtest (disabled by default) printing core latency at 640x480 for `downsample` 1, 2, 4.
