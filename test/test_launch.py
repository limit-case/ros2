"""Smoke test: launch the node, publish one synthetic frame, expect all outputs within 2 s."""
import time
import unittest

import launch
import launch_ros.actions
import launch_testing.actions
import numpy as np
import pytest
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image, PointCloud2

W, H = 160, 120


@pytest.mark.launch_test
def generate_test_description():
    node = launch_ros.actions.Node(
        package='limit_case_ros2', executable='glass_filter_node', name='glass_filter',
        parameters=[{'min_region_area_px': 100}],
        remappings=[('depth/image', '/t/depth'), ('depth/camera_info', '/t/info')])
    return launch.LaunchDescription([node, launch_testing.actions.ReadyToTest()]), {}


def scene_mm():
    d = np.full((H, W), 1500, np.uint16)
    d[30:90, 50:110] = 1000
    d[45:75, 65:95] = 1900
    return d


class TestOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node('glass_test')

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def test_all_outputs_arrive(self):
        got = {}
        q = QoSProfile(depth=5, reliability=ReliabilityPolicy.RELIABLE)
        for name, typ in (('/limit_case/depth/filtered', Image), ('/limit_case/mask', Image),
                          ('/limit_case/suspected_obstacles', PointCloud2)):
            self.node.create_subscription(typ, name, lambda m, n=name: got.__setitem__(n, m), q)
        depth_pub = self.node.create_publisher(Image, '/t/depth', 5)
        info_pub = self.node.create_publisher(CameraInfo, '/t/info', 5)

        info = CameraInfo()
        info.width, info.height = W, H
        info.k = [200.0, 0.0, 80.0, 0.0, 200.0, 60.0, 0.0, 0.0, 1.0]
        img = Image()
        img.header.frame_id = 'cam'
        img.header.stamp.sec = 42
        img.height, img.width, img.encoding, img.step = H, W, '16UC1', W * 2
        img.data = scene_mm().tobytes()

        deadline = time.time() + 2.0
        while time.time() < deadline and len(got) < 3:
            info_pub.publish(info)
            depth_pub.publish(img)
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertEqual(len(got), 3, f'only got {sorted(got)}')
        mask = np.frombuffer(got['/limit_case/mask'].data, np.uint8).reshape(H, W)
        self.assertGreater(int((mask[45:75, 65:95] > 0).sum()), 600)
        self.assertEqual(got['/limit_case/depth/filtered'].header.frame_id, 'cam')
        self.assertEqual(got['/limit_case/depth/filtered'].header.stamp.sec, 42)
