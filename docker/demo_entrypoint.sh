#!/bin/bash
# Virtual X display + VNC + noVNC, then the demo launch file. Browse to http://localhost:6080/vnc.html
set -e
. /opt/ros/"$ROS_DISTRO"/setup.bash
. /ws/install/setup.bash

if [ ! -f "$BAG/metadata.yaml" ]; then
  echo "No rosbag2 at $BAG (metadata.yaml missing). Mount it: -v \"\$PWD/demo_bag:/bag:ro\"" >&2
  exit 1
fi

Xvfb :1 -screen 0 "$SCREEN" -ac +extension GLX +render -noreset &
sleep 1
openbox &
x11vnc -display :1 -forever -shared -nopw -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 &
sleep 1
echo "Open http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
exec ros2 launch limit_case_ros2 demo_bag.launch.py bag:="$BAG" "$@"
