#!/usr/bin/env python3

import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from geometry_msgs.msg import Twist


def quaternion_to_pitch(x, y, z, w):
    # Safe clamp for numerical stability
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    return math.asin(sinp)


class BalanceController(Node):
    def __init__(self):
        super().__init__('balance_controller')

        # ---------------- PARAMETERS ----------------
        self.declare_parameter('kp', 60.0)
        self.declare_parameter('ki', 0.3)
        self.declare_parameter('kd', 12.0)
        self.declare_parameter('max_speed', 4.0)
        self.declare_parameter('control_sign', 1.0)

        self.kp = self.get_parameter('kp').value
        self.ki = self.get_parameter('ki').value
        self.kd = self.get_parameter('kd').value
        self.max_speed = self.get_parameter('max_speed').value
        self.control_sign = self.get_parameter('control_sign').value

        # ---------------- STATE ----------------
        self.pitch = 0.0
        self.pitch_filtered = 0.0
        self.pitch_rate = 0.0

        self.alpha_pitch = 0.85
        self.alpha_rate = 0.6

        self.integral = 0.0
        self.integral_limit = 0.3

        self.last_pitch = None
        self.last_time = None

        # ---------------- SAFETY ----------------
        self.max_tilt = math.radians(25)

        # ---------------- DEBUG ----------------
        self.step = 0

        self.create_subscription(Imu, '/imu', self.imu_callback, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self.get_logger().warn("BALANCER STARTED (ROBUST MODE)")

    # =========================================================
    # IMU CALLBACK (HARDENED)
    # =========================================================
    def imu_callback(self, msg):
        try:
            now = self.get_clock().now()

            q = msg.orientation
            pitch_raw = quaternion_to_pitch(q.x, q.y, q.z, q.w)

            # -------- FIRST FRAME SAFE INIT --------
            if self.last_time is None:
                self.last_time = now
                self.last_pitch = pitch_raw
                self.pitch_filtered = pitch_raw
                return

            dt = (now - self.last_time).nanoseconds / 1e9
            self.last_time = now

            # -------- DT SAFETY FILTER --------
            if dt <= 0.0 or dt > 0.05:
                return  # ignore bad physics spikes

            # -------- FILTER PITCH --------
            self.pitch_filtered = (
                self.alpha_pitch * pitch_raw +
                (1.0 - self.alpha_pitch) * self.pitch_filtered
            )

            # -------- GYRO --------
            gyro_y = float(msg.angular_velocity.y)

            self.pitch_rate = (
                self.alpha_rate * gyro_y +
                (1.0 - self.alpha_rate) * self.pitch_rate
            )

            # -------- NUMERICAL RATE (SAFE) --------
            numerical_rate = (self.pitch_filtered - self.last_pitch) / dt
            self.last_pitch = self.pitch_filtered

            # -------- EMERGENCY STOP --------
            if abs(self.pitch_filtered) > self.max_tilt:
                self.cmd_pub.publish(Twist())
                self.integral = 0.0
                return

            # -------- INTEGRAL (ANTI WINDUP) --------
            self.integral += self.pitch_filtered * dt
            self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))

            # -------- PID --------
            P = self.kp * self.pitch_filtered
            I = self.ki * self.integral
            D = -self.kd * self.pitch_rate

            control = self.control_sign * (P + I + D)

            # -------- CLAMP OUTPUT --------
            speed = max(-self.max_speed, min(self.max_speed, control))

            # -------- PUBLISH --------
            cmd = Twist()
            cmd.linear.x = speed
            self.cmd_pub.publish(cmd)

            # -------- DEBUG (slow print) --------
            self.step += 1
            if self.step % 20 == 0:
                self.get_logger().info(
                    f"pitch={math.degrees(self.pitch_filtered):.2f} "
                    f"gyro={math.degrees(gyro_y):.1f} "
                    f"num={math.degrees(numerical_rate):.1f} "
                    f"P={P:.1f} I={I:.2f} D={D:.1f} "
                    f"spd={speed:.2f}"
                )

        except Exception as e:
            # THIS FIXES YOUR CRASH
            self.get_logger().error(f"IMU CALLBACK ERROR: {e}")
            return


# =========================================================
# MAIN
# =========================================================
def main(args=None):
    rclpy.init(args=args)
    node = BalanceController()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cmd_pub.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
