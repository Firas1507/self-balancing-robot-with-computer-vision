import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.conditions import LaunchConfigurationEquals


def generate_launch_description():

    pkg_robot_description = get_package_share_directory('robot_description')
    pkg_gazebo_ros = get_package_share_directory('gazebo_ros')

    xacro_file = os.path.join(pkg_robot_description, 'urdf', 'balancer_robot.xacro')
    world_file = os.path.join(pkg_robot_description, 'launch', 'balancer_world.world')
    pid_script = os.path.join(pkg_robot_description, 'launch', 'balance_controller.py')
    lqr_script = os.path.join(pkg_robot_description, 'launch', 'lqr_controller.py')

    controller_type = LaunchConfiguration('controller_type')

    robot_description_content = Command(f"xacro {xacro_file}")

    robot_description = ParameterValue(
        robot_description_content,
        value_type=str
    )

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_gazebo_ros, 'launch', 'gazebo.launch.py')
        ),
        launch_arguments={
            'world': world_file,
            'verbose': 'true',
        }.items()
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'use_sim_time': True,
        }]
    )

    static_map_to_odom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_map_to_odom',
        arguments=['0', '0', '0', '0', '0', '0', 'map', 'odom'],
        output='screen',
    )

    spawn_entity = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        output='screen',
        arguments=[
            '-topic', 'robot_description',
            '-entity', 'balancer_robot',
            '-z', '0.1',  # matches new wheel_radius (was 0.05 for old 0.05m wheel)
        ]
    )

    pid_controller = ExecuteProcess(
        cmd=['python3', pid_script],
        output='screen',
        condition=LaunchConfigurationEquals('controller_type', 'pid'),
        respawn=True,
        respawn_delay=1,
    )

    lqr_controller = ExecuteProcess(
        cmd=['python3', lqr_script],
        output='screen',
        condition=LaunchConfigurationEquals('controller_type', 'lqr'),
        respawn=True,
        respawn_delay=1,
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'controller_type',
            default_value='pid',
            description='pid, lqr or none'
        ),

        gazebo,
        robot_state_publisher,
        static_map_to_odom,
        spawn_entity,
        pid_controller,
        lqr_controller,
    ])
