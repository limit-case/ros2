^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Changelog for package limit_case_ros2
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

0.1.0 (2026-11-16)
------------------
* First public release: an honest depth-only baseline for silent depth failures on transparent objects.
* ``glass_filter_node`` (composable): Priority-Flood basin detection on the depth image; publishes the
  filtered depth, a mask and a ``suspected_obstacles`` point cloud; diagnostics with latency and flagged share.
* ROS-free core (``priority_flood``, ``glass_filter``) and ``filter_cli`` for offline evaluation.
* Sensor profiles: ``realsense_d435`` (tuned on ClearGrasp D435 val only), ``realsense_d415``,
  ``realsense_l515`` and ``default`` (untuned).
* Evaluation on ClearGrasp with the GlassBench measurement rules; every README number is in ``results/*.csv``.
* Demo bag launch file, the ground-truth error view (``gt:=true``) and an offscreen renderer for the
  ground-truth error clip (``tools/render_gt_clip.sh``).
* Nav2 costmap snippet.
* ROS 2 Jazzy and Humble.
* Contributors: Yajan
