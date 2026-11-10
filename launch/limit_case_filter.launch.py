"""Run the glass filter on a live depth camera (defaults match RealSense aligned depth)."""
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, TextSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile


def generate_launch_description():
    share = get_package_share_directory('limit_case_ros2')
    profile = LaunchConfiguration('sensor_profile')
    cfg = PathJoinSubstitution([share, 'config', [profile, TextSubstitution(text='.yaml')]])

    args = [
        DeclareLaunchArgument('sensor_profile', default_value='default',
                              description='config/<name>.yaml: default, realsense_d435, '
                                          'realsense_d415, realsense_l515'),
        DeclareLaunchArgument(
            'depth_topic', default_value='/camera/aligned_depth_to_color/image_raw'),
        DeclareLaunchArgument(
            'info_topic', default_value='/camera/aligned_depth_to_color/camera_info'),
        DeclareLaunchArgument('color_topic', default_value='/camera/color/image_raw'),
    ]
    node = Node(
        package='limit_case_ros2', executable='glass_filter_node', name='glass_filter',
        output='screen',
        parameters=[ParameterFile(cfg, allow_substs=True),
                    {'sensor_profile': profile}],
        remappings=[('depth/image', LaunchConfiguration('depth_topic')),
                    ('depth/camera_info', LaunchConfiguration('info_topic')),
                    ('color/image', LaunchConfiguration('color_topic'))],
    )
    return LaunchDescription(args + [node])
