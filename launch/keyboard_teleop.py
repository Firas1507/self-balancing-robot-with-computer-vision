#!/usr/bin/env python3
"""
Simple keyboard teleop for the balancing robot.

Publishes a target forward/backward velocity to /cmd_vel_teleop.
This is intentionally a SEPARATE topic from /cmd_vel -- the LQR
balance controller already publishes its own output to /cmd_vel,
so this node does not write there. Instead, lqr_controller_fixed.py
subscribes to /cmd_vel_teleop and folds the requested velocity into
its own balance law as a target, rather than overwriting or fighting
the balance correction.

Controls:
  w / Up arrow    : increase forward target speed
  s / Down arrow  : increase backward target speed
  space / x       : stop (target speed -> 0 immediately)
  q               : quit

Speed ramps smoothly toward the held key's target rather than jumping,
and decays back to 0 automatically when no key is held -- so letting go
naturally returns to "just balance in place" without a separate command.
"""

import sys
import termios
import tty
import select

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class KeyboardTeleop(Node):
    def __init__(self):
        super().__init__('keyboard_teleop')

        self.declare_parameter('max_speed', 1.0)       # m/s, must not exceed
                                                         # lqr_controller's
                                                         # teleop_max_speed
        self.declare_parameter('accel', 1.5)            # m/s^2 ramp rate
        self.declare_parameter('publish_rate_hz', 20.0)

        self.max_speed = self.get_parameter('max_speed').value
        self.accel = self.get_parameter('accel').value
        rate_hz = self.get_parameter('publish_rate_hz').value

        self.pub = self.create_publisher(Twist, '/cmd_vel_teleop', 10)

        self.target_speed = 0.0   # what the held key wants
        self.current_speed = 0.0  # ramps toward target_speed

        self.settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

        period = 1.0 / rate_hz
        self.timer = self.create_timer(period, self.on_timer)
        self.dt = period

        self.get_logger().info(
            "Keyboard teleop ready. w/Up = forward, s/Down = backward, "
            "space/x = stop, q = quit. Click/focus this terminal window."
        )

    def read_key(self):
        """Non-blocking single-key read, including arrow-key escape codes."""
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch == '\x1b':  # escape sequence, e.g. arrow keys
                ch2 = sys.stdin.read(1)
                ch3 = sys.stdin.read(1)
                if ch2 == '[':
                    if ch3 == 'A':
                        return 'UP'
                    if ch3 == 'B':
                        return 'DOWN'
                return None
            return ch
        return None

    def on_timer(self):
        key = self.read_key()

        if key in ('w', 'W', 'UP'):
            self.target_speed = self.max_speed
        elif key in ('s', 'S', 'DOWN'):
            self.target_speed = -self.max_speed
        elif key in (' ', 'x', 'X'):
            self.target_speed = 0.0
            self.current_speed = 0.0
        elif key in ('q', 'Q'):
            self.get_logger().info("Quit requested.")
            self.shutdown_and_exit()
            return
        elif key is None:
            # No key pressed this tick: decay target back toward 0 so
            # releasing the key naturally returns to "just balance".
            self.target_speed = 0.0

        # Ramp current_speed toward target_speed at self.accel (m/s^2)
        max_step = self.accel * self.dt
        if self.current_speed < self.target_speed:
            self.current_speed = min(self.current_speed + max_step, self.target_speed)
        elif self.current_speed > self.target_speed:
            self.current_speed = max(self.current_speed - max_step, self.target_speed)

        msg = Twist()
        msg.linear.x = self.current_speed
        self.pub.publish(msg)

    def shutdown_and_exit(self):
        stop = Twist()
        self.pub.publish(stop)
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
        self.destroy_node()
        rclpy.shutdown()
        sys.exit(0)

    def restore_terminal(self):
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
        except Exception:
            pass


def main(args=None):
    rclpy.init(args=args)
    node = KeyboardTeleop()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            stop = Twist()
            node.pub.publish(stop)
        except Exception:
            pass
        node.restore_terminal()
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
