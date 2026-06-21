#!/usr/bin/env python3
"""
LQR balance controller.
"""

import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist


def quaternion_to_rpy(x, y, z, w):
    """Full roll-pitch-yaw extraction."""
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return roll, pitch, yaw


class LQRController(Node):
    def __init__(self):
        super().__init__('lqr_controller')

        # LQR Gains
        self.declare_parameter('k_x', -1.00)
        self.declare_parameter('k_xdot', -2.743)
        self.declare_parameter('k_theta', -58.491)
        self.declare_parameter('k_thetadot', -6.061)
        # BUG FIX: was -1.0. publish_control() already computes
        # u = -(k_x*x + k_xdot*x_dot + k_theta*theta + k_thetadot*theta_dot),
        # i.e. u = -(K . state), which is the correct LQR control law for
        # the K gains above (derived via solve_continuous_are earlier in
        # this project). Multiplying that by control_sign=-1.0 flipped it
        # back to +(K . state) -- the wrong sign, same failure pattern as
        # the gyro double-flip found in the PID controller. Restored to
        # +1.0 so the correct law is applied untouched.
        self.declare_parameter('control_sign', 1.0)
        self.declare_parameter('scale', 1.0)
        self.declare_parameter('max_linear_speed', 2.5)
        # BUG FIX: added a max_tilt emergency cutoff (matches the one
        # already in balance_controller.py, which this controller was
        # missing entirely). Root cause of "drives forward, flips, then
        # keeps driving forward": quaternion_to_rpy()'s pitch uses asin(),
        # which is mathematically bounded to [-90, +90] degrees no matter
        # the real tilt -- past 90 degrees of REAL rotation, the reported
        # angle folds back TOWARD zero instead of continuing to grow
        # (e.g. a true 180deg flip reports as 0deg, "perfectly balanced").
        # So once the robot tips past ~90 degrees, theta lies to the
        # controller and it keeps publishing confident-looking commands.
        # Rather than trying to mathematically unwrap pitch past +-90
        # (which needs roll/yaw info too and adds real complexity), this
        # adds the same simple safeguard the PID controller already uses:
        # once |theta| exceeds max_tilt, stop publishing driving commands
        # entirely. This keeps the fix small and consistent with the rest
        # of the project instead of introducing new math.
        self.declare_parameter('max_tilt_deg', 20.0)
        # Light low-pass filter on theta_dot (gyro). Without this, the raw
        # angular_velocity.y was noisy/jittery between samples (e.g. swings
        # like -173.6deg/s -> +72.1deg/s while theta itself barely moved),
        # and k_thetadot=-6.061 was turning that noise directly into speed
        # commands -- consistent with the frequent +-2.5 clamp saturation
        # and rapid sign flips seen once the robot was actually balancing.
        # Same filtering approach as balance_controller.py's alpha_rate,
        # just applied here too since this controller previously had none.
        self.declare_parameter('rate_filter_alpha', 0.2)
        # Forward/backward teleop support.
        # IMPORTANT: this is added INSIDE the LQR law (biasing the x_dot
        # error term), not added to the final output speed. The LQR's
        # k_xdot*x_dot term always drives x_dot back toward 0 -- it has no
        # other notion of "desired" velocity. If a bias were added AFTER
        # computing u, the controller would immediately see the resulting
        # real-world speed increase and compute a correction to cancel it
        # straight back out, fighting the teleop input continuously.
        # Biasing the error itself (x_dot - v_target) makes the LQR drive
        # toward v_target instead of toward 0, while theta/theta_dot
        # balancing keeps working exactly as before.
        # Note: the k_x*x (position) term is NOT compensated here, so a
        # long sustained hold on one direction will still feel a growing
        # "pull back toward spawn" from that term -- fine for short nudges/
        # taps (the normal WASD use case), but worth knowing if you want
        # to drive far in one direction for a long time.
        self.declare_parameter('teleop_max_speed', 1.0)
        self.declare_parameter('teleop_timeout_sec', 0.5)
        # BUG FIX: removed pitch_offset_deg entirely.
        # This parameter tried to cancel a ~73 degree spawn tilt by
        # subtracting it from the raw IMU pitch, but (a) the sign was
        # backwards (pitch_offset_deg=-73.0 made theta = pitch + 73deg
        # instead of pitch - 73deg, doubling the error instead of
        # canceling it), and (b) a 73 degree spawn tilt means the robot
        # is spawning already nearly lying on its side -- that's a real
        # spawn-pose problem (initial orientation / -z height in the
        # launch/SDF), not something a sensor offset in this controller
        # should be compensating for. Fix the spawn pose so the robot
        # actually starts near 0 degrees, then this controller can use
        # the raw IMU pitch directly, same as balance_controller.py does.

        self.k_x = self.get_parameter('k_x').value
        self.k_xdot = self.get_parameter('k_xdot').value
        self.k_theta = self.get_parameter('k_theta').value
        self.k_thetadot = self.get_parameter('k_thetadot').value
        self.control_sign = self.get_parameter('control_sign').value
        self.scale = self.get_parameter('scale').value
        self.max_speed = self.get_parameter('max_linear_speed').value
        self.max_tilt = math.radians(self.get_parameter('max_tilt_deg').value)
        self.rate_filter_alpha = self.get_parameter('rate_filter_alpha').value
        self.teleop_max_speed = self.get_parameter('teleop_max_speed').value
        self.teleop_timeout_sec = self.get_parameter('teleop_timeout_sec').value
        self.emergency_stop = False
        self.theta_dot_filtered = 0.0
        self.v_target = 0.0
        self.last_teleop_time = None

        self.x = 0.0
        self.x_dot = 0.0
        self.theta = 0.0
        self.theta_dot = 0.0
        self.start_x = None
        self.prev_speed = 0.0
        self.max_accel = 0.5

        self.odom_sub = self.create_subscription(Odometry, '/odom', self.odom_callback, 50)
        self.imu_sub = self.create_subscription(Imu, '/imu', self.imu_callback, 50)
        # Separate topic from /cmd_vel on purpose: /cmd_vel is THIS
        # controller's own output. If teleop also published there, both
        # publishers would race on the same topic with no actual blending
        # -- whichever publishes last/most often would just win. Teleop
        # publishes a target velocity here instead, which gets folded into
        # the LQR law itself (see publish_control).
        self.teleop_sub = self.create_subscription(Twist, '/cmd_vel_teleop', self.teleop_callback, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self.get_logger().warn(
            f'LQR: K=[{self.k_x:.2f}, {self.k_xdot:.2f}, '
            f'{self.k_theta:.2f}, {self.k_thetadot:.2f}], '
            f'control_sign={self.control_sign}'
        )

    def odom_callback(self, msg: Odometry):
        current_x = msg.pose.pose.position.x
        if self.start_x is None:
            self.start_x = current_x
        self.x = current_x - self.start_x
        self.x_dot = msg.twist.twist.linear.x

    def teleop_callback(self, msg: Twist):
        self.v_target = max(-self.teleop_max_speed,
                             min(self.teleop_max_speed, msg.linear.x))
        self.last_teleop_time = self.get_clock().now()

    def imu_callback(self, msg: Imu):
        q = msg.orientation
        roll, pitch, yaw = quaternion_to_rpy(q.x, q.y, q.z, q.w)

        # Raw IMU pitch, no offset. If the robot still doesn't spawn near
        # 0 degrees, fix the spawn pose (launch file / SDF initial
        # orientation), not this controller.
        self.theta = pitch

        # Low-pass filter the raw gyro rate before using it, so sensor
        # noise doesn't get amplified by k_thetadot into speed chatter.
        theta_dot_raw = msg.angular_velocity.y
        self.theta_dot_filtered = (
            self.rate_filter_alpha * theta_dot_raw +
            (1.0 - self.rate_filter_alpha) * self.theta_dot_filtered
        )
        self.theta_dot = self.theta_dot_filtered

        # Log once
        if self.start_x is not None and abs(self.x) < 0.01 and not hasattr(self, 'logged'):
            self.logged = True
            self.get_logger().warn(
                f"INIT: raw_pitch={math.degrees(pitch):.1f}°"
            )

        self.publish_control()

    def publish_control(self):
        # --- EMERGENCY STOP ---
        # Stops driving once tilt exceeds max_tilt, instead of trusting
        # theta past the point where asin() can represent it correctly.
        if abs(self.theta) > self.max_tilt:
            if not self.emergency_stop:
                self.get_logger().error(
                    f"EMERGENCY: tilt={math.degrees(self.theta):.1f}° "
                    f"exceeds max_tilt={math.degrees(self.max_tilt):.1f}° -- stopping"
                )
                self.emergency_stop = True
            self.cmd_pub.publish(Twist())
            self.prev_speed = 0.0
            return
        else:
            self.emergency_stop = False

        # Timeout: if teleop hasn't sent anything recently, fall back to
        # v_target=0 (pure balance, no drive) instead of coasting forever
        # on the last command -- protects against a closed teleop terminal
        # leaving the robot driving indefinitely.
        if self.last_teleop_time is not None:
            since_last = (self.get_clock().now() - self.last_teleop_time).nanoseconds / 1e9
            if since_last > self.teleop_timeout_sec:
                self.v_target = 0.0

        u = -(self.k_x * self.x +
              self.k_xdot * (self.x_dot - self.v_target) +
              self.k_theta * self.theta +
              self.k_thetadot * self.theta_dot)

        control = self.control_sign * u * self.scale

        speed = max(self.prev_speed - self.max_accel,
                    min(self.prev_speed + self.max_accel, control))
        speed = max(-self.max_speed, min(self.max_speed, speed))
        self.prev_speed = speed

        cmd = Twist()
        cmd.linear.x = speed
        self.cmd_pub.publish(cmd)

        self.get_logger().info(
            f"theta={math.degrees(self.theta):.2f}° "
            f"thetadot={math.degrees(self.theta_dot):.1f}°/s "
            f"v_target={self.v_target:.2f} "
            f"u={u:.2f} speed={speed:.2f}",
            throttle_duration_sec=0.1
        )


def main(args=None):
    rclpy.init(args=args)
    node = LQRController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        stop = Twist()
        node.cmd_pub.publish(stop)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
