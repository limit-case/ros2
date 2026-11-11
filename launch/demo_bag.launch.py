"""No hardware: play the demo bag, run the filter, show raw / filtered / suspected clouds in RViz.

  ros2 launch limit_case_ros2 demo_bag.launch.py bag:=/path/to/demo_bag
Cloud colours (rviz/demo.rviz): raw = grey, filtered = white, suspected obstacles = red.
Arguments: bag (required), rviz:=false for headless runs, loop:=false to play the bag once.

  ros2 launch limit_case_ros2 demo_bag.launch.py bag:=/path/to/demo_bag gt:=true
Ground-truth error view instead of the filter (rviz/demo_gt.rviz): the raw cloud coloured by
GlassBench bucket, red = wrong (more than 5% off ground truth), white = correct, grey = not
glass. Needs the sidecar made by `gt_error_cloud.py prepare`; gt_file defaults to
<bag>/gt_sidecar.npz.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode


def generate_launch_description():
    share = get_package_share_directory('limit_case_ros2')
    depth = '/camera/aligned_depth_to_color/image_raw'
    info = '/camera/aligned_depth_to_color/camera_info'

    bag = ExecuteProcess(
        cmd=['ros2', 'bag', 'play', LaunchConfiguration('bag'),
             '--loop'],
        output='screen', condition=IfCondition(PythonExpression(
            ["'", LaunchConfiguration('loop'), "' == 'true'"])))
    bag_once = ExecuteProcess(
        cmd=['ros2', 'bag', 'play', LaunchConfiguration('bag')], output='screen',
        condition=IfCondition(PythonExpression(
            ["'", LaunchConfiguration('loop'), "' != 'true'"])))

    # The bag only carries the optical frame. Add the usual ROS body frame (x forward, z up)
    # so RViz shows the scene upright.
    tf = Node(
        package='tf2_ros', executable='static_transform_publisher', output='log',
        arguments=['--yaw', '-1.5707963', '--pitch', '0', '--roll', '-1.5707963',
                   '--frame-id', 'camera_link', '--child-frame-id', 'camera_color_optical_frame'])

    gt = LaunchConfiguration('gt')
    gt_file = PythonExpression([
        "'", LaunchConfiguration('gt_file'), "' or '", LaunchConfiguration('bag'),
        "'.rstrip('/') + '/gt_sidecar.npz'"])
    gt_cloud = Node(
        package='limit_case_ros2', executable='gt_error_cloud.py', name='gt_error_cloud',
        output='screen', condition=IfCondition(gt),
        parameters=[{'gt_file': gt_file}], remappings=[('depth/image', depth)])

    filt = Node(
        package='limit_case_ros2', executable='glass_filter_node', name='glass_filter',
        output='screen', condition=UnlessCondition(gt),
        parameters=[os.path.join(share, 'config', 'realsense_d435.yaml')],
        remappings=[('depth/image', depth), ('depth/camera_info', info)])

    clouds = ComposableNodeContainer(
        name='demo_clouds', namespace='', package='rclcpp_components',
        executable='component_container', output='screen', condition=UnlessCondition(gt),
        composable_node_descriptions=[
            ComposableNode(
                package='depth_image_proc', plugin='depth_image_proc::PointCloudXyzNode',
                name='raw_xyz',
                remappings=[('image_rect', depth), ('camera_info', info),
                            ('points', '/demo/raw_points')]),
            ComposableNode(
                package='depth_image_proc', plugin='depth_image_proc::PointCloudXyzNode',
                name='filtered_xyz',
                # image_transport looks for camera_info next to the image topic; point it at
                # the real one (the filter only republishes the image).
                remappings=[('image_rect', '/limit_case/depth/filtered'),
                            ('camera_info', info),
                            ('/limit_case/depth/camera_info', info),
                            ('points', '/demo/filtered_points')]),
        ])

    rviz_config = PythonExpression([
        "'", os.path.join(share, 'rviz', 'demo_gt.rviz'), "' if '", gt, "' == 'true' else '",
        os.path.join(share, 'rviz', 'demo.rviz'), "'"])
    rviz = Node(package='rviz2', executable='rviz2', output='screen',
                arguments=['-d', rviz_config],
                condition=IfCondition(LaunchConfiguration('rviz')))

    return LaunchDescription([
        DeclareLaunchArgument('bag', description='path to the demo rosbag2 (mcap) directory'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('loop', default_value='true'),
        DeclareLaunchArgument('gt', default_value='false',
                              description='ground-truth error view instead of the filter'),
        DeclareLaunchArgument('gt_file', default_value='',
                              description='sidecar .npz (default: <bag>/gt_sidecar.npz)'),
        bag, bag_once, tf, gt_cloud, filt, clouds, rviz])
